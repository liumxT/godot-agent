"""Agent Execution Loop（E6-T07）。

执行顺序：校验绑定 → 初始化 → 认领 RUNNING → 创建 Execution → 装配 Context →
调用 Model Gateway → 解析 Action → 执行 Action → 记录事件 → 决定下一步。

边界：

- 只通过 Model Gateway 与 Tool System 工作，不直接操作项目文件或厂商 SDK；
- 模型返回 UNKNOWN 时进入 UNKNOWN，不自动重试；
- 需要审批（R3+）或用户输入时停在 WAITING_*，不继续执行；
- 预算由定义快照限制：调用前预留、完成后结算，超限按 Budget Profile 处理；
- 每轮结束写 Checkpoint，暂停/审批等待/终止时也写 Checkpoint，便于恢复。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from core.errors import (
    AgentBudgetExceeded,
    AgentStateInvalid,
    AppError,
    ModelCallFailed,
    ModelRequestUnknown,
)
from core.security.tokens import utcnow
from modules.agent_runtime.budget import BudgetManager, BudgetTracker
from modules.agent_runtime.checkpoint import CheckpointService
from modules.agent_runtime.context_binding import AgentContextBindingService
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.execution import AgentExecutionService, ExecutionView
from modules.agent_runtime.instance import AgentInstanceService, ConfigSnapshotView, InstanceView
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.model_binding import AgentModelBindingService
from modules.agent_runtime.models import (
    ACTION_ANALYZE,
    ACTION_COMPLETE_EXECUTION,
    ACTION_CREATE_PLAN,
    ACTION_EXECUTE_TOOL,
    ACTION_FAIL_EXECUTION,
    ACTION_REPORT_PROGRESS,
    ACTION_REQUEST_APPROVAL,
    ACTION_REQUEST_USER_INPUT,
    ACTION_UPDATE_PLAN,
    BUDGET_EXCEED_PAUSE,
    BUDGET_EXCEED_STOP,
    BUDGET_EXCEED_WAITING_INPUT,
    EVENT_APPROVAL_REQUESTED,
    EVENT_BUDGET_EXCEEDED,
    EVENT_MODEL_REQUEST_COMPLETED,
    EVENT_MODEL_REQUEST_STARTED,
    EVENT_TOOL_REQUEST_COMPLETED,
    EVENT_TOOL_REQUEST_STARTED,
    EXECUTION_PAUSED,
    EXECUTION_STOPPED,
    INSTANCE_CREATED,
    INSTANCE_PAUSED,
    INSTANCE_PAUSING,
    INSTANCE_READY,
    INSTANCE_RUNNING,
    INSTANCE_STOPPING,
    INSTANCE_TERMINAL_STATUSES,
    INSTANCE_WAITING_APPROVAL,
    INSTANCE_WAITING_INPUT,
    STEP_READY,
)
from modules.agent_runtime.planning import PlanningService
from modules.agent_runtime.response_parser import AgentAction, AgentResponseParser
from modules.agent_runtime.tool_binding import AgentToolBindingService
from modules.model_gateway.models import REQUEST_SUCCEEDED, REQUEST_UNKNOWN
from modules.tool.execution import (
    EXECUTION_SUCCEEDED,
    EXECUTION_UNKNOWN,
)

__all__ = ["AgentExecutionLoop", "LoopResult"]

_LOOP_COMPLETED = "COMPLETED"
_LOOP_FAILED = "FAILED"
_LOOP_PAUSED = "PAUSED"
_LOOP_STOPPED = "STOPPED"
_LOOP_WAITING_APPROVAL = "WAITING_APPROVAL"
_LOOP_WAITING_INPUT = "WAITING_INPUT"
_LOOP_UNKNOWN = "UNKNOWN"

_DEFAULT_LIMITS = {
    "max_iterations": 30,
    "max_model_calls": 40,
    "max_tool_calls": 60,
}
_INTERRUPTED_STATUSES = frozenset({INSTANCE_PAUSING, INSTANCE_PAUSED, INSTANCE_STOPPING})


@dataclass(frozen=True, slots=True)
class LoopResult:
    instance_id: str
    execution_id: str
    status: str
    iterations: int
    reason: str | None = None


class AgentExecutionLoop:
    def __init__(
        self,
        *,
        instances: AgentInstanceService,
        lifecycle: AgentLifecycleService,
        executions: AgentExecutionService,
        events: AgentEventService,
        planning: PlanningService,
        context: AgentContextBindingService,
        models: AgentModelBindingService,
        tools: AgentToolBindingService,
        budget: BudgetManager,
        checkpoints: CheckpointService,
        parser: AgentResponseParser | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._instances = instances
        self._lifecycle = lifecycle
        self._executions = executions
        self._events = events
        self._planning = planning
        self._context = context
        self._models = models
        self._tools = tools
        self._budget = budget
        self._checkpoints = checkpoints
        self._parser = parser or AgentResponseParser()
        self._clock = clock

    async def run(
        self,
        instance_id: str,
        *,
        max_iterations: int | None = None,
        approval_id: str | None = None,
    ) -> LoopResult:
        instance = await self._instances.get(instance_id)
        if instance.status in INSTANCE_TERMINAL_STATUSES:
            latest = await self._executions.latest_for_instance(instance_id)
            return LoopResult(
                instance_id=instance_id,
                execution_id=latest.execution_id if latest is not None else "",
                status=instance.status,
                iterations=0,
                reason=instance.termination_reason,
            )
        if instance.status == INSTANCE_CREATED:
            instance = await self._lifecycle.initialize(instance_id)
        if instance.status == INSTANCE_READY:
            instance = await self._lifecycle.start(instance_id)
        if instance.status != INSTANCE_RUNNING:
            raise AgentStateInvalid(
                "当前状态不能执行 Agent",
                details={"instance_id": instance_id, "status": instance.status},
            )

        snapshot = await self._instances.get_snapshot(instance_id)
        execution = await self._executions.start_execution(instance)
        try:
            bundle = await self._context.build(instance, snapshot)
            bound = await self._models.resolve(
                snapshot, context_size=bundle.token_estimate
            )
            tool_definitions = await self._tools.definitions(snapshot)
        except AppError as exc:
            return await self._fail(instance, execution, exc.code, 0)

        limits = {**_DEFAULT_LIMITS, **dict(snapshot.budget)}
        if max_iterations is not None:
            limits["max_iterations"] = max_iterations
        tracker = await self._budget.load(execution.execution_id, limits)
        started_at = execution.started_at or self._clock()

        iterations = 0
        pending_approval = approval_id
        while True:
            current = await self._instances.get(instance_id)
            if current.status in _INTERRUPTED_STATUSES:
                return LoopResult(
                    instance_id,
                    execution.execution_id,
                    current.status,
                    iterations,
                    "INSTANCE_INTERRUPTED",
                )
            try:
                iteration_slot = tracker.reserve("iterations")
                model_slot = tracker.reserve("model_calls")
            except AgentBudgetExceeded as exc:
                return await self._budget_exceeded(
                    instance, execution, tracker, exc.details, iterations
                )
            tracker.settle(iteration_slot)
            tracker.settle(model_slot)
            iterations += 1
            try:
                tracker.check_elapsed((self._clock() - started_at).total_seconds())
            except AgentBudgetExceeded as exc:
                return await self._budget_exceeded(
                    instance, execution, tracker, exc.details, iterations
                )
            await self._budget.persist(execution.execution_id, tracker)

            await self._events.append(
                instance_id,
                EVENT_MODEL_REQUEST_STARTED,
                payload={"model_id": bound.model_id, "iteration": iterations},
                execution_id=execution.execution_id,
            )
            try:
                response = await self._models.generate(
                    instance=instance,
                    snapshot=snapshot,
                    bound=bound,
                    bundle=bundle,
                    tools=tool_definitions,
                )
            except ModelRequestUnknown:
                await self._events.append(
                    instance_id,
                    EVENT_MODEL_REQUEST_COMPLETED,
                    payload={"status": REQUEST_UNKNOWN, "iteration": iterations},
                    execution_id=execution.execution_id,
                )
                return await self._unknown(
                    instance, execution, "MODEL_REQUEST_UNKNOWN", iterations
                )
            except ModelCallFailed as exc:
                await self._events.append(
                    instance_id,
                    EVENT_MODEL_REQUEST_COMPLETED,
                    payload={"status": "FAILED", "iteration": iterations},
                    execution_id=execution.execution_id,
                )
                return await self._fail(instance, execution, exc.code, iterations)
            except AppError as exc:
                await self._events.append(
                    instance_id,
                    EVENT_MODEL_REQUEST_COMPLETED,
                    payload={"status": "FAILED", "iteration": iterations},
                    execution_id=execution.execution_id,
                )
                return await self._fail(instance, execution, exc.code, iterations)

            await self._events.append(
                instance_id,
                EVENT_MODEL_REQUEST_COMPLETED,
                payload={
                    "status": response.status,
                    "model_request_id": response.request_id,
                    "finish_reason": response.finish_reason,
                    "iteration": iterations,
                },
                execution_id=execution.execution_id,
            )
            if response.usage is not None:
                if response.usage.input_tokens:
                    tracker.record("input_tokens", response.usage.input_tokens)
                if response.usage.output_tokens:
                    tracker.record("output_tokens", response.usage.output_tokens)
                await self._budget.persist(execution.execution_id, tracker)
                exceeded = tracker.exceeded()
                if exceeded is not None:
                    return await self._budget_exceeded(
                        instance, execution, tracker, exceeded, iterations
                    )
            if response.status == REQUEST_UNKNOWN:
                return await self._unknown(
                    instance, execution, "MODEL_REQUEST_UNKNOWN", iterations
                )
            if response.status != REQUEST_SUCCEEDED:
                return await self._fail(
                    instance, execution, f"MODEL_{response.status}", iterations
                )

            try:
                action = self._parser.parse(response)
            except AppError as exc:
                return await self._fail(instance, execution, exc.code, iterations)

            pending_approval, outcome = await self._dispatch(
                instance,
                snapshot,
                execution,
                action,
                iterations,
                tracker,
                pending_approval,
            )
            await self._budget.persist(execution.execution_id, tracker)
            if outcome is not None:
                return outcome
            await self._checkpoint(
                instance.instance_id, execution.execution_id, "ITERATION_COMPLETED"
            )

    # ---- Action 分派 ----

    async def _dispatch(
        self,
        instance: InstanceView,
        snapshot: ConfigSnapshotView,
        execution: ExecutionView,
        action: AgentAction,
        iterations: int,
        tracker: BudgetTracker,
        pending_approval: str | None,
    ) -> tuple[str | None, LoopResult | None]:
        kind = action.action_type
        if kind == ACTION_EXECUTE_TOOL:
            outcome = await self._execute_tool(
                instance,
                snapshot,
                execution,
                action,
                iterations,
                tracker,
                pending_approval,
            )
            return None, outcome
        if kind in {ACTION_CREATE_PLAN, ACTION_UPDATE_PLAN}:
            try:
                supersedes = None
                if kind == ACTION_UPDATE_PLAN:
                    active = await self._planning.active_plan(execution.execution_id)
                    supersedes = active.plan_id if active is not None else None
                await self._planning.create_plan(
                    instance_id=instance.instance_id,
                    execution_id=execution.execution_id,
                    objective=action.payload["objective"],
                    steps=action.payload["steps"],
                    supersedes_plan_id=supersedes,
                )
            except AppError as exc:
                return pending_approval, await self._fail(
                    instance, execution, exc.code, iterations
                )
            return pending_approval, None
        if kind == ACTION_COMPLETE_EXECUTION:
            return pending_approval, await self._complete(
                instance, execution, action, iterations
            )
        if kind == ACTION_FAIL_EXECUTION:
            return pending_approval, await self._fail(
                instance, execution, str(action.payload["reason"]), iterations
            )
        if kind == ACTION_REQUEST_APPROVAL:
            await self._events.append(
                instance.instance_id,
                EVENT_APPROVAL_REQUESTED,
                payload={"reason": action.payload.get("reason"), "source": "AGENT"},
                execution_id=execution.execution_id,
            )
            await self._wait_for_approval(instance, execution, pending_action=None)
            return pending_approval, LoopResult(
                instance.instance_id,
                execution.execution_id,
                _LOOP_WAITING_APPROVAL,
                iterations,
                "AGENT_REQUESTED_APPROVAL",
            )
        if kind == ACTION_REQUEST_USER_INPUT:
            await self._wait_for_input(instance, execution)
            return pending_approval, LoopResult(
                instance.instance_id,
                execution.execution_id,
                _LOOP_WAITING_INPUT,
                iterations,
                "AGENT_REQUESTED_USER_INPUT",
            )
        if kind in {ACTION_ANALYZE, ACTION_REPORT_PROGRESS}:
            return pending_approval, None
        return pending_approval, await self._fail(
            instance, execution, "UNSUPPORTED_ACTION", iterations
        )

    async def _execute_tool(
        self,
        instance: InstanceView,
        snapshot: ConfigSnapshotView,
        execution: ExecutionView,
        action: AgentAction,
        iterations: int,
        tracker: BudgetTracker,
        pending_approval: str | None,
    ) -> LoopResult | None:
        try:
            tool = await self._tools.resolve(snapshot, str(action.payload["tool"]))
        except AppError as exc:
            return await self._fail(instance, execution, exc.code, iterations)

        tool_input = dict(action.payload.get("input", {}))
        resource_scope = tuple(action.payload.get("resource_scope", ()))

        assessment = self._tools.assess(tool)
        if assessment.approval_required and not pending_approval:
            await self._events.append(
                instance.instance_id,
                EVENT_APPROVAL_REQUESTED,
                payload={
                    "tool_id": tool.tool_id,
                    "risk_level": assessment.level,
                    "reason": "RISK_APPROVAL_REQUIRED",
                },
                execution_id=execution.execution_id,
            )
            await self._wait_for_approval(
                instance,
                execution,
                pending_action={
                    "tool_id": tool.tool_id,
                    "tool_name": tool.name,
                    "tool_version": getattr(tool, "version", None),
                    "input": tool_input,
                    "resource_scope": list(resource_scope),
                },
            )
            return LoopResult(
                instance.instance_id,
                execution.execution_id,
                _LOOP_WAITING_APPROVAL,
                iterations,
                "APPROVAL_REQUIRED",
            )

        try:
            tool_slot = tracker.reserve("tool_calls")
        except AgentBudgetExceeded as exc:
            return await self._budget_exceeded(
                instance, execution, tracker, exc.details, iterations
            )
        tracker.settle(tool_slot)
        await self._budget.persist(execution.execution_id, tracker)

        step = None
        plan = await self._planning.active_plan(execution.execution_id)
        if plan is not None:
            step = await self._planning.next_runnable_step(plan.plan_id)
            if step is not None and step.status == STEP_READY:
                step = await self._planning.start_step(step.step_id)

        await self._events.append(
            instance.instance_id,
            EVENT_TOOL_REQUEST_STARTED,
            payload={"tool_id": tool.tool_id, "tool_name": tool.name},
            execution_id=execution.execution_id,
        )
        approval_id = pending_approval or action.payload.get("approval_id")
        try:
            result = await self._tools.execute(
                instance=instance,
                snapshot=snapshot,
                tool=tool,
                tool_input=tool_input,
                resource_scope=resource_scope,
                approval_id=approval_id,
                idempotency_key=f"{execution.execution_id}:{iterations}",
            )
        except AppError as exc:
            await self._events.append(
                instance.instance_id,
                EVENT_TOOL_REQUEST_COMPLETED,
                payload={"tool_id": tool.tool_id, "status": "REJECTED", "error": exc.code},
                execution_id=execution.execution_id,
            )
            if step is not None:
                await self._planning.fail_step(step.step_id, reason=exc.code)
            return await self._fail(instance, execution, exc.code, iterations)

        await self._events.append(
            instance.instance_id,
            EVENT_TOOL_REQUEST_COMPLETED,
            payload={
                "tool_id": tool.tool_id,
                "status": result.status,
                "tool_execution_id": result.execution_id,
                "reused": result.reused,
            },
            execution_id=execution.execution_id,
        )

        if result.status == EXECUTION_UNKNOWN:
            if step is not None:
                await self._planning.fail_step(step.step_id, reason="TOOL_EXECUTION_UNKNOWN")
            return await self._unknown(
                instance, execution, "TOOL_EXECUTION_UNKNOWN", iterations
            )
        if result.status != EXECUTION_SUCCEEDED:
            if step is not None:
                await self._planning.fail_step(
                    step.step_id, reason=f"TOOL_{result.status}"
                )
            return await self._fail(instance, execution, f"TOOL_{result.status}", iterations)
        if step is not None:
            await self._planning.complete_step(
                step.step_id,
                output_reference=result.execution_id,
                tool_execution_id=result.execution_id,
            )
        return None

    async def _complete(
        self,
        instance: InstanceView,
        execution: ExecutionView,
        action: AgentAction,
        iterations: int,
    ) -> LoopResult:
        blocking = await self._planning.blocking_steps(execution.execution_id)
        plan = await self._planning.active_plan(execution.execution_id)
        if blocking:
            return await self._fail(instance, execution, "INCOMPLETE_PLAN", iterations)
        if plan is not None:
            try:
                await self._planning.complete_plan(plan.plan_id)
            except AppError as exc:
                return await self._fail(instance, execution, exc.code, iterations)
        reason = action.payload.get("summary") or "AGENT_COMPLETED"
        await self._executions.complete(execution.execution_id, reason=reason)
        completed = await self._lifecycle.complete(instance.instance_id, reason=reason)
        await self._checkpoint(instance.instance_id, execution.execution_id, "COMPLETED")
        return LoopResult(
            completed.instance_id,
            execution.execution_id,
            _LOOP_COMPLETED,
            iterations,
            reason,
        )

    # ---- 状态收尾 ----

    async def _wait_for_approval(
        self,
        instance: InstanceView,
        execution: ExecutionView,
        *,
        pending_action: dict | None,
    ) -> None:
        await self._executions.wait_for_approval(execution.execution_id)
        await self._lifecycle.transition(
            instance.instance_id, INSTANCE_WAITING_APPROVAL
        )
        await self._checkpoint(
            instance.instance_id,
            execution.execution_id,
            "WAITING_APPROVAL",
            pending_action=pending_action,
        )

    async def _wait_for_input(
        self, instance: InstanceView, execution: ExecutionView
    ) -> None:
        await self._executions.wait_for_input(execution.execution_id)
        await self._lifecycle.transition(instance.instance_id, INSTANCE_WAITING_INPUT)
        await self._checkpoint(instance.instance_id, execution.execution_id, "WAITING_INPUT")

    async def _fail(
        self,
        instance: InstanceView,
        execution: ExecutionView,
        reason: str,
        iterations: int,
    ) -> LoopResult:
        await self._safe(self._executions.fail(execution.execution_id, reason=reason))
        await self._safe(self._lifecycle.fail(instance.instance_id, reason=reason))
        await self._checkpoint(instance.instance_id, execution.execution_id, "FAILED")
        return LoopResult(
            instance.instance_id, execution.execution_id, _LOOP_FAILED, iterations, reason
        )

    async def _unknown(
        self,
        instance: InstanceView,
        execution: ExecutionView,
        reason: str,
        iterations: int,
    ) -> LoopResult:
        await self._safe(self._executions.mark_unknown(execution.execution_id, reason=reason))
        await self._safe(self._lifecycle.mark_unknown(instance.instance_id, reason=reason))
        await self._checkpoint(instance.instance_id, execution.execution_id, "UNKNOWN")
        return LoopResult(
            instance.instance_id,
            execution.execution_id,
            _LOOP_UNKNOWN,
            iterations,
            reason,
        )

    async def _budget_exceeded(
        self,
        instance: InstanceView,
        execution: ExecutionView,
        tracker: BudgetTracker,
        detail: dict | None,
        iterations: int,
    ) -> LoopResult:
        await self._budget.persist(execution.execution_id, tracker)
        await self._events.append(
            instance.instance_id,
            EVENT_BUDGET_EXCEEDED,
            payload={
                "detail": detail,
                "policy": tracker.on_exceed,
                "iteration": iterations,
            },
            execution_id=execution.execution_id,
        )
        if tracker.on_exceed == BUDGET_EXCEED_PAUSE:
            await self._checkpoint(
                instance.instance_id, execution.execution_id, "BUDGET_EXCEEDED"
            )
            await self._safe(
                self._executions.transition(
                    execution.execution_id, EXECUTION_PAUSED, reason="BUDGET_EXCEEDED"
                )
            )
            await self._safe(self._lifecycle.pause(instance.instance_id))
            return LoopResult(
                instance.instance_id,
                execution.execution_id,
                _LOOP_PAUSED,
                iterations,
                "BUDGET_EXCEEDED",
            )
        if tracker.on_exceed == BUDGET_EXCEED_WAITING_INPUT:
            await self._checkpoint(
                instance.instance_id, execution.execution_id, "BUDGET_EXCEEDED"
            )
            await self._safe(self._executions.wait_for_input(execution.execution_id))
            await self._safe(
                self._lifecycle.transition(instance.instance_id, INSTANCE_WAITING_INPUT)
            )
            return LoopResult(
                instance.instance_id,
                execution.execution_id,
                _LOOP_WAITING_INPUT,
                iterations,
                "BUDGET_EXCEEDED",
            )
        if tracker.on_exceed == BUDGET_EXCEED_STOP:
            await self._safe(
                self._planning.abandon_plan(
                    execution.execution_id, reason="BUDGET_EXCEEDED"
                )
            )
            await self._checkpoint(
                instance.instance_id, execution.execution_id, "BUDGET_EXCEEDED"
            )
            await self._safe(
                self._executions.transition(
                    execution.execution_id, EXECUTION_STOPPED, reason="BUDGET_EXCEEDED"
                )
            )
            await self._safe(self._lifecycle.stop(instance.instance_id, reason="BUDGET_EXCEEDED"))
            return LoopResult(
                instance.instance_id,
                execution.execution_id,
                _LOOP_STOPPED,
                iterations,
                "BUDGET_EXCEEDED",
            )
        return await self._fail(instance, execution, "BUDGET_EXCEEDED", iterations)

    async def _checkpoint(
        self,
        instance_id: str,
        execution_id: str,
        trigger: str,
        *,
        pending_action: dict | None = None,
    ) -> None:
        try:
            await self._checkpoints.create(
                instance_id=instance_id,
                execution_id=execution_id,
                trigger=trigger,
                pending_action=pending_action,
            )
        except AppError:
            # Checkpoint 失败不能掩盖主流程结果；恢复阶段会按 UNKNOWN 处理。
            pass

    async def _safe(self, action: Awaitable[object]) -> None:
        try:
            await action
        except AppError:
            pass
