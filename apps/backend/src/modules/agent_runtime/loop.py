"""Agent Execution Loop（E6-T07）。

执行顺序：校验绑定 → 初始化 → 认领 RUNNING → 创建 Execution → 装配 Context →
调用 Model Gateway → 解析 Action → 执行 Action → 记录事件 → 决定下一步。

边界：

- 只通过 Model Gateway 与 Tool System 工作，不直接操作项目文件或厂商 SDK；
- 模型返回 UNKNOWN 时进入 UNKNOWN，不自动重试；
- 需要审批（R3+）或用户输入时停在 WAITING_*，不继续执行；
- 预算由定义快照限制，超出预算失败关闭（完整 Budget Manager 在 M4）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from core.errors import AgentStateInvalid, AppError, ModelCallFailed, ModelRequestUnknown
from core.security.tokens import utcnow
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
    EVENT_APPROVAL_REQUESTED,
    EVENT_BUDGET_EXCEEDED,
    EVENT_MODEL_REQUEST_COMPLETED,
    EVENT_MODEL_REQUEST_STARTED,
    EVENT_TOOL_REQUEST_COMPLETED,
    EVENT_TOOL_REQUEST_STARTED,
    INSTANCE_CREATED,
    INSTANCE_READY,
    INSTANCE_RUNNING,
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
_LOOP_WAITING_APPROVAL = "WAITING_APPROVAL"
_LOOP_WAITING_INPUT = "WAITING_INPUT"
_LOOP_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class LoopResult:
    instance_id: str
    execution_id: str
    status: str
    iterations: int
    reason: str | None = None


def _limit(budget: dict, key: str, default: int) -> int:
    value = budget.get(key)
    if value is None:
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


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
        self._parser = parser or AgentResponseParser()
        self._clock = clock

    async def run(
        self, instance_id: str, *, max_iterations: int | None = None
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

        budget = snapshot.budget
        iteration_limit = (
            max_iterations
            if max_iterations is not None
            else _limit(budget, "max_iterations", 30)
        )
        model_call_limit = _limit(budget, "max_model_calls", 40)
        tool_call_limit = _limit(budget, "max_tool_calls", 60)

        iterations = 0
        model_calls = 0
        tool_calls = 0
        while True:
            iterations += 1
            if iterations > iteration_limit:
                return await self._budget_failed(
                    instance, execution, "MAX_ITERATIONS", iterations
                )
            if model_calls >= model_call_limit:
                return await self._budget_failed(
                    instance, execution, "MAX_MODEL_CALLS", iterations
                )
            model_calls += 1

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

            outcome, used = await self._dispatch(
                instance,
                snapshot,
                execution,
                action,
                iterations,
                tool_calls,
                tool_call_limit,
            )
            tool_calls += used
            if outcome is not None:
                return outcome

    # ---- Action 分派 ----

    async def _dispatch(
        self,
        instance: InstanceView,
        snapshot: ConfigSnapshotView,
        execution: ExecutionView,
        action: AgentAction,
        iterations: int,
        tool_calls: int,
        tool_call_limit: int,
    ) -> tuple[LoopResult | None, int]:
        kind = action.action_type
        if kind == ACTION_EXECUTE_TOOL:
            return await self._execute_tool(
                instance,
                snapshot,
                execution,
                action,
                iterations,
                tool_calls,
                tool_call_limit,
            )
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
                return await self._fail(instance, execution, exc.code, iterations), 0
            return None, 0
        if kind == ACTION_COMPLETE_EXECUTION:
            return await self._complete(instance, execution, action, iterations), 0
        if kind == ACTION_FAIL_EXECUTION:
            return (
                await self._fail(
                    instance, execution, str(action.payload["reason"]), iterations
                ),
                0,
            )
        if kind == ACTION_REQUEST_APPROVAL:
            await self._events.append(
                instance.instance_id,
                EVENT_APPROVAL_REQUESTED,
                payload={"reason": action.payload.get("reason"), "source": "AGENT"},
                execution_id=execution.execution_id,
            )
            await self._wait_for_approval(instance, execution)
            return (
                LoopResult(
                    instance.instance_id,
                    execution.execution_id,
                    _LOOP_WAITING_APPROVAL,
                    iterations,
                    "AGENT_REQUESTED_APPROVAL",
                ),
                0,
            )
        if kind == ACTION_REQUEST_USER_INPUT:
            await self._wait_for_input(instance, execution)
            return (
                LoopResult(
                    instance.instance_id,
                    execution.execution_id,
                    _LOOP_WAITING_INPUT,
                    iterations,
                    "AGENT_REQUESTED_USER_INPUT",
                ),
                0,
            )
        if kind in {ACTION_ANALYZE, ACTION_REPORT_PROGRESS}:
            return None, 0
        return await self._fail(instance, execution, "UNSUPPORTED_ACTION", iterations), 0

    async def _execute_tool(
        self,
        instance: InstanceView,
        snapshot: ConfigSnapshotView,
        execution: ExecutionView,
        action: AgentAction,
        iterations: int,
        tool_calls: int,
        tool_call_limit: int,
    ) -> tuple[LoopResult | None, int]:
        try:
            tool = await self._tools.resolve(snapshot, str(action.payload["tool"]))
        except AppError as exc:
            return await self._fail(instance, execution, exc.code, iterations), 0

        assessment = self._tools.assess(tool)
        if assessment.approval_required:
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
            await self._wait_for_approval(instance, execution)
            return (
                LoopResult(
                    instance.instance_id,
                    execution.execution_id,
                    _LOOP_WAITING_APPROVAL,
                    iterations,
                    "APPROVAL_REQUIRED",
                ),
                0,
            )

        if tool_calls >= tool_call_limit:
            return (
                await self._budget_failed(
                    instance, execution, "MAX_TOOL_CALLS", iterations
                ),
                0,
            )

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
        try:
            result = await self._tools.execute(
                instance=instance,
                snapshot=snapshot,
                tool=tool,
                tool_input=dict(action.payload.get("input", {})),
                resource_scope=tuple(action.payload.get("resource_scope", ())),
                approval_id=action.payload.get("approval_id"),
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
            return await self._fail(instance, execution, exc.code, iterations), 1

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
            return (
                await self._unknown(
                    instance, execution, "TOOL_EXECUTION_UNKNOWN", iterations
                ),
                1,
            )
        if result.status != EXECUTION_SUCCEEDED:
            if step is not None:
                await self._planning.fail_step(
                    step.step_id, reason=f"TOOL_{result.status}"
                )
            return (
                await self._fail(instance, execution, f"TOOL_{result.status}", iterations),
                1,
            )
        if step is not None:
            await self._planning.complete_step(
                step.step_id,
                output_reference=result.execution_id,
                tool_execution_id=result.execution_id,
            )
        return None, 1

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
        return LoopResult(
            completed.instance_id,
            execution.execution_id,
            _LOOP_COMPLETED,
            iterations,
            reason,
        )

    # ---- 状态收尾 ----

    async def _wait_for_approval(
        self, instance: InstanceView, execution: ExecutionView
    ) -> None:
        await self._executions.wait_for_approval(execution.execution_id)
        await self._lifecycle.transition(
            instance.instance_id, INSTANCE_WAITING_APPROVAL
        )

    async def _wait_for_input(
        self, instance: InstanceView, execution: ExecutionView
    ) -> None:
        await self._executions.wait_for_input(execution.execution_id)
        await self._lifecycle.transition(instance.instance_id, INSTANCE_WAITING_INPUT)

    async def _fail(
        self,
        instance: InstanceView,
        execution: ExecutionView,
        reason: str,
        iterations: int,
    ) -> LoopResult:
        async def _safe(action) -> None:
            try:
                await action
            except AgentStateInvalid:
                pass

        await _safe(self._executions.fail(execution.execution_id, reason=reason))
        await _safe(self._lifecycle.fail(instance.instance_id, reason=reason))
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
        async def _safe(action) -> None:
            try:
                await action
            except AgentStateInvalid:
                pass

        await _safe(self._executions.mark_unknown(execution.execution_id, reason=reason))
        await _safe(self._lifecycle.mark_unknown(instance.instance_id, reason=reason))
        return LoopResult(
            instance.instance_id,
            execution.execution_id,
            _LOOP_UNKNOWN,
            iterations,
            reason,
        )

    async def _budget_failed(
        self,
        instance: InstanceView,
        execution: ExecutionView,
        detail: str,
        iterations: int,
    ) -> LoopResult:
        await self._events.append(
            instance.instance_id,
            EVENT_BUDGET_EXCEEDED,
            payload={"detail": detail, "iteration": iterations},
            execution_id=execution.execution_id,
        )
        return await self._fail(instance, execution, "BUDGET_EXCEEDED", iterations)
