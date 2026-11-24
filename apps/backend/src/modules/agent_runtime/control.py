"""Pause / Resume / Cancel / Stop（E6-T14）。

控制动作只操作 Agent Runtime 的状态与事件：

- Pause：先写 Checkpoint，再进入 PAUSED，等待恢复；
- Resume：重新校验 Task / Attempt / 会话 / 项目 / 模型 / 工具 / Context / 预算 /
  审批，任一失效都不允许恢复；UNKNOWN 必须走恢复检查；
- Cancel / Stop：未执行的 Step 跳过，可能已执行的 Step 保守标记 UNKNOWN；
  Agent 不回写 Task System，Task 状态由 Task System 自己负责。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.errors import (
    AgentRecoveryRequired,
    AgentStateInvalid,
    AppError,
)
from modules.access.service import ProjectAccessService
from modules.agent_runtime.budget import BudgetManager
from modules.agent_runtime.checkpoint import CheckpointService
from modules.agent_runtime.context_binding import AgentContextBindingService
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.execution import AgentExecutionService
from modules.agent_runtime.instance import AgentInstanceService, InstanceView
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.model_binding import AgentModelBindingService
from modules.agent_runtime.models import (
    EVENT_CANCEL_REQUESTED,
    EVENT_PAUSE_REQUESTED,
    EVENT_RESUME_REQUESTED,
    EXECUTION_PAUSED,
    EXECUTION_RUNNING,
    EXECUTION_STOPPED,
    EXECUTION_UNKNOWN,
    EXECUTION_WAITING_APPROVAL,
    EXECUTION_WAITING_INPUT,
    INSTANCE_PAUSED,
    INSTANCE_RUNNING,
    INSTANCE_TERMINAL_STATUSES,
    INSTANCE_UNKNOWN,
)
from modules.agent_runtime.planning import PlanningService
from modules.agent_runtime.tool_binding import AgentToolBindingService
from modules.tool.approval import ToolApprovalGate, ToolApprovalScope

__all__ = ["AgentControlService", "ResumeCheck"]

_ACTIVE_EXECUTION_STATUSES = frozenset(
    {
        EXECUTION_RUNNING,
        EXECUTION_WAITING_APPROVAL,
        EXECUTION_WAITING_INPUT,
        EXECUTION_PAUSED,
        EXECUTION_UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class ResumeCheck:
    ok: bool
    reasons: tuple[str, ...]


class AgentControlService:
    def __init__(
        self,
        *,
        instances: AgentInstanceService,
        lifecycle: AgentLifecycleService,
        executions: AgentExecutionService,
        events: AgentEventService,
        checkpoints: CheckpointService,
        planning: PlanningService,
        models: AgentModelBindingService,
        tools: AgentToolBindingService,
        contexts: AgentContextBindingService,
        budget: BudgetManager,
        access: ProjectAccessService,
        approvals: ToolApprovalGate | None = None,
    ) -> None:
        self._instances = instances
        self._lifecycle = lifecycle
        self._executions = executions
        self._events = events
        self._checkpoints = checkpoints
        self._planning = planning
        self._models = models
        self._tools = tools
        self._contexts = contexts
        self._budget = budget
        self._access = access
        self._approvals = approvals

    # ---- Pause ----

    async def pause(self, instance_id: str, *, reason: str | None = None) -> InstanceView:
        instance = await self._instances.get(instance_id)
        if instance.status in INSTANCE_TERMINAL_STATUSES:
            return instance
        if instance.status == INSTANCE_PAUSED:
            return instance
        execution = await self._executions.latest_for_instance(instance_id)
        await self._events.append(
            instance_id,
            EVENT_PAUSE_REQUESTED,
            payload={"reason": reason},
            execution_id=execution.execution_id if execution is not None else None,
        )
        if execution is not None and execution.status in {
            EXECUTION_RUNNING,
            EXECUTION_WAITING_APPROVAL,
            EXECUTION_WAITING_INPUT,
        }:
            pending = await self._pending_action(instance_id)
            await self._checkpoints.create(
                instance_id=instance_id,
                execution_id=execution.execution_id,
                trigger="PAUSE_REQUESTED",
                pending_action=pending,
            )
            await self._executions.transition(execution.execution_id, EXECUTION_PAUSED)
        return await self._lifecycle.pause(instance_id)

    # ---- Resume ----

    async def validate_resume(
        self, instance_id: str, *, approval_id: str | None = None
    ) -> ResumeCheck:
        instance = await self._instances.get(instance_id)
        if instance.status == INSTANCE_RUNNING:
            return ResumeCheck(ok=True, reasons=())
        if instance.status == INSTANCE_UNKNOWN:
            return ResumeCheck(ok=False, reasons=("INSTANCE_UNKNOWN",))
        if instance.status != INSTANCE_PAUSED:
            return ResumeCheck(ok=False, reasons=("INSTANCE_NOT_PAUSED",))

        reasons: list[str] = []
        snapshot = await self._instances.get_snapshot(instance_id)

        if not instance.session_id or not instance.client_id:
            reasons.append("SESSION_MISSING")
        else:
            try:
                await self._access.get_current(
                    project_id=instance.project_id,
                    session_id=instance.session_id,
                    client_id=instance.client_id,
                )
            except AppError:
                reasons.append("PROJECT_ACCESS_DENIED")

        try:
            await self._instances.assert_task_binding(instance_id)
        except AppError:
            reasons.append("TASK_BINDING_INVALID")

        try:
            await self._models.resolve(snapshot)
        except AppError:
            reasons.append("MODEL_UNAVAILABLE")

        try:
            await self._tools.whitelist_tools(snapshot)
        except AppError:
            reasons.append("TOOL_UNAVAILABLE")

        try:
            await self._contexts.build(instance, snapshot)
        except AppError:
            reasons.append("CONTEXT_INVALID")

        execution = await self._executions.latest_for_instance(instance_id)
        if execution is None:
            reasons.append("EXECUTION_MISSING")
        else:
            tracker = await self._budget.load(execution.execution_id, snapshot.budget)
            if tracker.exceeded() is not None:
                reasons.append("BUDGET_EXCEEDED")

        pending = await self._pending_action(instance_id)
        if pending is not None:
            if not approval_id:
                reasons.append("APPROVAL_REQUIRED")
            elif self._approvals is not None:
                scope = ToolApprovalScope(
                    project_id=instance.project_id,
                    tool_id=str(pending.get("tool_id", "")),
                    tool_version=pending.get("tool_version"),
                    input_payload=dict(pending.get("input") or {}),
                    resource_scope=tuple(pending.get("resource_scope") or ()),
                )
                try:
                    await self._approvals.ensure_approved(approval_id, scope)
                except AppError:
                    reasons.append("APPROVAL_INVALID")

        return ResumeCheck(ok=not reasons, reasons=tuple(dict.fromkeys(reasons)))

    async def resume(
        self, instance_id: str, *, approval_id: str | None = None, actor: str | None = None
    ) -> InstanceView:
        check = await self.validate_resume(instance_id, approval_id=approval_id)
        if not check.ok:
            raise AgentRecoveryRequired(
                "恢复条件不满足，已保持 PAUSED",
                details={"instance_id": instance_id, "reasons": list(check.reasons)},
            )
        instance = await self._instances.get(instance_id)
        if instance.status == INSTANCE_RUNNING:
            return instance
        execution = await self._executions.latest_for_instance(instance_id)
        await self._events.append(
            instance_id,
            EVENT_RESUME_REQUESTED,
            payload={"actor": actor, "approval_id": approval_id},
            execution_id=execution.execution_id if execution is not None else None,
        )
        view = await self._lifecycle.resume(instance_id)
        if execution is not None and execution.status == EXECUTION_PAUSED:
            await self._executions.transition(execution.execution_id, EXECUTION_RUNNING)
        return view

    # ---- Cancel / Stop ----

    async def cancel(
        self,
        instance_id: str,
        *,
        reason: str = "CANCEL_REQUESTED",
        actor: str | None = None,
    ) -> InstanceView:
        return await self._terminate(
            instance_id,
            reason=reason,
            actor=actor,
            request_event=EVENT_CANCEL_REQUESTED,
            trigger="CANCEL_REQUESTED",
        )

    async def stop(
        self,
        instance_id: str,
        *,
        reason: str = "STOP_REQUESTED",
        actor: str | None = None,
    ) -> InstanceView:
        return await self._terminate(
            instance_id,
            reason=reason,
            actor=actor,
            request_event=None,
            trigger="STOP_REQUESTED",
        )

    async def _terminate(
        self,
        instance_id: str,
        *,
        reason: str,
        actor: str | None,
        request_event: str | None,
        trigger: str,
    ) -> InstanceView:
        instance = await self._instances.get(instance_id)
        if instance.status in INSTANCE_TERMINAL_STATUSES:
            return instance
        execution = await self._executions.latest_for_instance(instance_id)
        execution_id = execution.execution_id if execution is not None else None
        if request_event is not None:
            await self._events.append(
                instance_id,
                request_event,
                payload={"reason": reason, "actor": actor},
                execution_id=execution_id,
            )
        if execution is not None and execution.status in _ACTIVE_EXECUTION_STATUSES:
            await self._planning.abandon_plan(execution.execution_id, reason=reason)
            await self._checkpoints.create(
                instance_id=instance_id,
                execution_id=execution.execution_id,
                trigger=trigger,
            )
            try:
                await self._executions.transition(
                    execution.execution_id, EXECUTION_STOPPED, reason=reason
                )
            except AgentStateInvalid:
                pass
        return await self._lifecycle.stop(instance_id, reason=reason)

    # ---- 内部 ----

    async def _pending_action(self, instance_id: str) -> dict[str, Any] | None:
        checkpoint = await self._checkpoints.latest(instance_id)
        if checkpoint is None:
            return None
        pending = checkpoint.state.get("pending_action")
        return dict(pending) if isinstance(pending, dict) else None
