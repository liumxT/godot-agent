"""Agent Runtime 可观测性（E6-T16）。

提供运行指标与一次 Execution 的完整追踪视图：

- 指标：实例/执行数量、队列与执行耗时、迭代次数、模型调用、工具调用、Token、
  成本、失败率、UNKNOWN、恢复成功率、审批等待数量；
- 追踪：Task → Attempt → Instance → Execution → Plan/Step → Model/Tool → Event；
- 所有事件载荷在输出前做脱敏，禁止暴露 API Key、Token、密钥与隐藏推理内容。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from infrastructure.database.service import DatabaseService
from modules.agent_runtime.checkpoint import CheckpointService
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.execution import AgentExecutionService
from modules.agent_runtime.instance import AgentInstanceService
from modules.agent_runtime.models import (
    EVENT_APPROVAL_REQUESTED,
    EVENT_MODEL_REQUEST_STARTED,
    EVENT_RECOVERY_COMPLETED,
    EVENT_RECOVERY_STARTED,
    EVENT_TOOL_REQUEST_STARTED,
    EXECUTION_COMPLETED,
    EXECUTION_FAILED,
    EXECUTION_RUNNING,
    EXECUTION_STOPPED,
    INSTANCE_UNKNOWN,
    INSTANCE_WAITING_APPROVAL,
    AgentExecutionModel,
    AgentInstanceModel,
    AgentStepModel,
)
from modules.agent_runtime.planning import PlanningService

__all__ = ["AgentMetrics", "AgentObservabilityService", "log_context", "sanitize"]

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "password",
        "reasoning",
        "secret",
        "token",
        "chain_of_thought",
        "hidden_reasoning",
    }
)
_REDACTED = "[REDACTED]"
_TERMINAL_EXECUTIONS = frozenset({EXECUTION_COMPLETED, EXECUTION_FAILED, EXECUTION_STOPPED})


def sanitize(value: Any, *, depth: int = 0) -> Any:
    """递归脱敏事件载荷；超过 8 层直接折叠，避免异常结构放大。"""

    if depth > 8:
        return _REDACTED
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if str(key).lower() in _SENSITIVE_KEYS
                else sanitize(item, depth=depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item, depth=depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + "...[truncated]"
    return value


def log_context(
    *,
    instance_id: str | None = None,
    execution_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, str]:
    """统一日志维度；空值不输出。"""

    values = {
        "agent_instance_id": instance_id,
        "agent_execution_id": execution_id,
        "agent_plan_id": plan_id,
        "agent_step_id": step_id,
        "project_id": project_id,
    }
    return {key: value for key, value in values.items() if value}


@dataclass(frozen=True, slots=True)
class AgentMetrics:
    agent_instance_count: int
    instance_status_counts: dict[str, int]
    running_execution_count: int
    queue_waiting_seconds: float
    execution_duration_seconds: float
    average_iterations: float
    model_call_count: int
    tool_call_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_total: float
    retry_count: int
    failure_rate: float
    unknown_count: int
    recovery_started: int
    recovery_succeeded: int
    recovery_success_rate: float
    approval_waiting_count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _usage_value(usage: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


class AgentObservabilityService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        instances: AgentInstanceService,
        executions: AgentExecutionService,
        events: AgentEventService,
        planning: PlanningService,
        checkpoints: CheckpointService,
        tasks: Any | None = None,
        attempts: Any | None = None,
    ) -> None:
        self._database = database
        self._instances = instances
        self._executions = executions
        self._events = events
        self._planning = planning
        self._checkpoints = checkpoints
        self._tasks = tasks
        self._attempts = attempts

    async def metrics(self, *, project_id: str | None = None) -> AgentMetrics:
        async with self._database.session() as session:
            instance_rows = list(
                (await session.scalars(select(AgentInstanceModel))).all()
            )
            execution_rows = list(
                (await session.scalars(select(AgentExecutionModel))).all()
            )
            steps = list((await session.scalars(select(AgentStepModel))).all())
        if project_id is not None:
            instance_rows = [
                row for row in instance_rows if row.project_id == project_id
            ]
        instance_ids = {row.instance_id for row in instance_rows}
        execution_rows = [
            row
            for row in execution_rows
            if project_id is None or row.agent_instance_id in instance_ids
        ]

        status_counts = Counter(row.status for row in instance_rows)
        usage_list = [json.loads(row.budget_usage_json or "{}") for row in execution_rows]
        iterations = [_usage_value(usage, "iterations") for usage in usage_list]
        model_calls = int(sum(_usage_value(usage, "model_calls") for usage in usage_list))
        tool_calls = int(sum(_usage_value(usage, "tool_calls") for usage in usage_list))
        input_tokens = int(sum(_usage_value(usage, "input_tokens") for usage in usage_list))
        output_tokens = int(sum(_usage_value(usage, "output_tokens") for usage in usage_list))
        cost_total = sum(
            _usage_value(usage, "cost_usage", "cost_total") for usage in usage_list
        )

        terminal = [row for row in execution_rows if row.status in _TERMINAL_EXECUTIONS]
        failed = [row for row in terminal if row.status == EXECUTION_FAILED]
        failure_rate = (len(failed) / len(terminal)) if terminal else 0.0

        queue_waits = [
            max(
                (row.created_at - instance.started_at).total_seconds(), 0.0
            )
            for row in execution_rows
            for instance in instance_rows
            if row.agent_instance_id == instance.instance_id
            and instance.started_at is not None
        ]
        durations = [
            (row.completed_at - row.started_at).total_seconds()
            for row in execution_rows
            if row.status in _TERMINAL_EXECUTIONS
            and row.started_at is not None
            and row.completed_at is not None
        ]

        events = await self._events.list_all(limit=5000)
        execution_id_set = {row.execution_id for row in execution_rows}
        if project_id is not None:
            events = [
                event
                for event in events
                if event.agent_instance_id in instance_ids
                or event.execution_id in execution_id_set
            ]
        recovery_started = sum(
            1 for event in events if event.event_type == EVENT_RECOVERY_STARTED
        )
        recovery_succeeded = sum(
            1
            for event in events
            if event.event_type == EVENT_RECOVERY_COMPLETED
            and event.payload.get("decision") == "PAUSED"
        )
        recovery_rate = (
            recovery_succeeded / recovery_started if recovery_started else 0.0
        )

        retry_count = sum(row.retry_count for row in steps)

        return AgentMetrics(
            agent_instance_count=len(instance_rows),
            instance_status_counts=dict(status_counts),
            running_execution_count=sum(
                1 for row in execution_rows if row.status == EXECUTION_RUNNING
            ),
            queue_waiting_seconds=(
                sum(queue_waits) / len(queue_waits) if queue_waits else 0.0
            ),
            execution_duration_seconds=(
                sum(durations) / len(durations) if durations else 0.0
            ),
            average_iterations=(
                sum(iterations) / len(iterations) if iterations else 0.0
            ),
            model_call_count=model_calls,
            tool_call_count=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_total=cost_total,
            retry_count=retry_count,
            failure_rate=failure_rate,
            unknown_count=status_counts.get(INSTANCE_UNKNOWN, 0),
            recovery_started=recovery_started,
            recovery_succeeded=recovery_succeeded,
            recovery_success_rate=recovery_rate,
            approval_waiting_count=status_counts.get(INSTANCE_WAITING_APPROVAL, 0),
        )

    async def trace(self, execution_id: str) -> dict[str, Any]:
        execution = await self._executions.get(execution_id)
        instance = await self._instances.get(execution.agent_instance_id)
        plans = await self._planning.list_plans(execution_id)
        checkpoint = await self._checkpoints.latest(instance.instance_id)
        events = await self._events.list_for_execution(execution_id, limit=500)

        model_requests: list[dict[str, Any]] = []
        tool_executions: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        for event in events:
            if event.event_type == EVENT_MODEL_REQUEST_STARTED:
                model_requests.append(
                    {
                        "sequence": event.sequence_number,
                        "at": _iso(event.created_at),
                        "payload": sanitize(event.payload),
                    }
                )
            elif event.event_type == EVENT_TOOL_REQUEST_STARTED:
                tool_executions.append(
                    {
                        "sequence": event.sequence_number,
                        "at": _iso(event.created_at),
                        "payload": sanitize(event.payload),
                    }
                )
            elif event.event_type == EVENT_APPROVAL_REQUESTED:
                approvals.append(
                    {
                        "sequence": event.sequence_number,
                        "at": _iso(event.created_at),
                        "payload": sanitize(event.payload),
                    }
                )

        return {
            "context": log_context(
                instance_id=instance.instance_id,
                execution_id=execution.execution_id,
                project_id=instance.project_id,
            ),
            "task": await self._task_summary(instance.task_id),
            "attempt": await self._attempt_summary(instance.attempt_id),
            "instance": {
                "instance_id": instance.instance_id,
                "status": instance.status,
                "agent_definition_id": instance.agent_definition_id,
                "agent_version": instance.agent_version,
                "project_id": instance.project_id,
                "session_id": instance.session_id,
                "client_id": instance.client_id,
                "config_snapshot_id": instance.config_snapshot_id,
                "created_at": _iso(instance.created_at),
                "started_at": _iso(instance.started_at),
                "completed_at": _iso(instance.completed_at),
                "termination_reason": instance.termination_reason,
            },
            "execution": {
                "execution_id": execution.execution_id,
                "status": execution.status,
                "iteration_count": int(_usage_value(execution.budget_usage, "iterations")),
                "model_call_count": int(
                    _usage_value(execution.budget_usage, "model_calls")
                ),
                "tool_call_count": int(_usage_value(execution.budget_usage, "tool_calls")),
                "budget_usage": sanitize(execution.budget_usage),
                "termination_reason": execution.termination_reason,
                "started_at": _iso(execution.started_at),
                "completed_at": _iso(execution.ended_at),
            },
            "plans": [
                {
                    "plan_id": plan.plan_id,
                    "status": plan.status,
                    "plan_version": plan.plan_version,
                    "objective": plan.objective,
                    "steps": [
                        {
                            "step_id": step.step_id,
                            "step_number": step.step_number,
                            "step_type": step.step_type,
                            "description": step.description,
                            "status": step.status,
                            "retry_count": step.retry_count,
                            "tool_execution_id": step.tool_execution_id,
                        }
                        for step in plan.steps
                    ],
                }
                for plan in plans
            ],
            "checkpoint": (
                None
                if checkpoint is None
                else {
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "trigger": checkpoint.state.get("trigger"),
                    "last_event_sequence": checkpoint.last_event_sequence,
                    "created_at": _iso(checkpoint.created_at),
                }
            ),
            "model_requests": model_requests,
            "tool_executions": tool_executions,
            "approvals": approvals,
            "events": [
                {
                    "sequence": event.sequence_number,
                    "event_type": event.event_type,
                    "at": _iso(event.created_at),
                    "payload": sanitize(event.payload),
                }
                for event in events
            ],
        }

    async def _task_summary(self, task_id: str | None) -> dict[str, Any] | None:
        if task_id is None or self._tasks is None:
            return None
        try:
            task = await self._tasks.get(task_id)
        except Exception:  # noqa: BLE001 - 追踪视图不应因历史数据缺失而失败
            return {"task_id": task_id, "status": "MISSING"}
        return {
            "task_id": task.task_id,
            "title": getattr(task, "title", None),
            "status": getattr(task, "status", None),
            "project_id": getattr(task, "project_id", None),
        }

    async def _attempt_summary(self, attempt_id: str | None) -> dict[str, Any] | None:
        if attempt_id is None or self._attempts is None:
            return None
        try:
            attempt = await self._attempts.get(attempt_id)
        except Exception:  # noqa: BLE001 - 追踪视图不应因历史数据缺失而失败
            return {"attempt_id": attempt_id, "status": "MISSING"}
        return {
            "attempt_id": attempt.attempt_id,
            "status": getattr(attempt, "status", None),
            "task_id": getattr(attempt, "task_id", None),
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
