"""Recovery Coordinator（E6-T15）。

进程重启或执行中断后，本模块负责把非终止 Instance 收敛到一个可继续的状态：

- ``READY`` / ``CREATED`` 交给 Scheduler，不在这里启动；
- ``PAUSED`` / ``UNKNOWN`` 保持现状，等待显式 Resume 或人工处理；
- ``RUNNING`` / ``WAITING_*`` / ``PAUSING`` / ``RESUMING`` 才需要判定：
  最后一朵 Checkpoint 必须存在、事件序号有效、Execution 对应一致，且 Task 仍有效；
  校验通过则暂停为 ``PAUSED``（写 RECOVERY 事件与 Checkpoint），否则标记 ``UNKNOWN``。

恢复过程只读校验，不重放动作：UNKNOWN 状态下禁止自动重复执行可能产生副作用的操作。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.errors import AppError
from infrastructure.database.service import DatabaseService
from modules.agent_runtime.checkpoint import CheckpointService
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.execution import AgentExecutionService
from modules.agent_runtime.instance import AgentInstanceService, InstanceView
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.models import (
    EVENT_RECOVERY_COMPLETED,
    EVENT_RECOVERY_STARTED,
    EXECUTION_PAUSED,
    EXECUTION_RUNNING,
    EXECUTION_UNKNOWN,
    EXECUTION_WAITING_APPROVAL,
    EXECUTION_WAITING_INPUT,
    INSTANCE_CREATED,
    INSTANCE_INITIALIZING,
    INSTANCE_PAUSED,
    INSTANCE_PAUSING,
    INSTANCE_READY,
    INSTANCE_RESUMING,
    INSTANCE_RUNNING,
    INSTANCE_STOPPING,
    INSTANCE_TERMINAL_STATUSES,
    INSTANCE_UNKNOWN,
    INSTANCE_WAITING_APPROVAL,
    INSTANCE_WAITING_INPUT,
    INSTANCE_WAITING_TOOL,
)
from modules.agent_runtime.repository import AgentInstanceRepository

__all__ = [
    "RECOVERY_PAUSED",
    "RECOVERY_SKIPPED",
    "RECOVERY_STOPPED",
    "RECOVERY_UNKNOWN",
    "RecoveryCoordinator",
    "RecoveryResult",
]

RECOVERY_SKIPPED = "SKIPPED"
RECOVERY_PAUSED = "PAUSED"
RECOVERY_UNKNOWN = "UNKNOWN"
RECOVERY_STOPPED = "STOPPED"

_ACTIVE_STATUSES = frozenset(
    {
        INSTANCE_RUNNING,
        INSTANCE_WAITING_TOOL,
        INSTANCE_WAITING_APPROVAL,
        INSTANCE_WAITING_INPUT,
        INSTANCE_PAUSING,
        INSTANCE_RESUMING,
    }
)
_EXECUTION_RESUMABLE = frozenset(
    {
        EXECUTION_RUNNING,
        EXECUTION_WAITING_APPROVAL,
        EXECUTION_WAITING_INPUT,
        EXECUTION_UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    instance_id: str
    previous_status: str
    status: str
    decision: str
    reasons: tuple[str, ...] = ()


class RecoveryCoordinator:
    def __init__(
        self,
        database: DatabaseService,
        *,
        instances: AgentInstanceService,
        lifecycle: AgentLifecycleService,
        executions: AgentExecutionService,
        events: AgentEventService,
        checkpoints: CheckpointService,
    ) -> None:
        self._database = database
        self._instances = instances
        self._lifecycle = lifecycle
        self._executions = executions
        self._events = events
        self._checkpoints = checkpoints

    async def recover_all(self, *, limit: int = 200) -> list[RecoveryResult]:
        async with self._database.session() as session:
            rows = await AgentInstanceRepository(session).list_non_terminal(limit=limit)
        results: list[RecoveryResult] = []
        for row in rows:
            try:
                results.append(await self.recover(row.instance_id))
            except AppError as exc:
                results.append(
                    RecoveryResult(
                        instance_id=row.instance_id,
                        previous_status=row.status,
                        status=row.status,
                        decision=RECOVERY_UNKNOWN,
                        reasons=(exc.code,),
                    )
                )
        return results

    async def recover(self, instance_id: str) -> RecoveryResult:
        instance = await self._instances.get(instance_id)
        if instance.status in INSTANCE_TERMINAL_STATUSES:
            return self._skip(instance, "TERMINAL")
        if instance.status == INSTANCE_UNKNOWN:
            return RecoveryResult(
                instance_id=instance.instance_id,
                previous_status=instance.status,
                status=instance.status,
                decision=RECOVERY_UNKNOWN,
                reasons=("INSTANCE_UNKNOWN",),
            )
        if instance.status in {INSTANCE_CREATED, INSTANCE_READY}:
            return self._skip(instance, "AWAIT_SCHEDULER")
        if instance.status == INSTANCE_PAUSED:
            return self._skip(instance, "PAUSED")
        if instance.status == INSTANCE_STOPPING:
            return await self._finish_stopping(instance)
        if instance.status == INSTANCE_INITIALIZING:
            return await self._mark_unknown(instance, ("INITIALIZATION_INCOMPLETE",))
        if instance.status not in _ACTIVE_STATUSES:
            return self._skip(instance, "NO_ACTION")

        execution = await self._executions.latest_for_instance(instance_id)
        checkpoint = await self._checkpoints.latest(instance_id)
        reasons: list[str] = []
        if checkpoint is None:
            reasons.append("CHECKPOINT_MISSING")
        if execution is None:
            reasons.append("EXECUTION_MISSING")
        if checkpoint is not None:
            last_sequence = await self._events.last_sequence(instance_id)
            if checkpoint.last_event_sequence > last_sequence:
                reasons.append("CHECKPOINT_OUT_OF_RANGE")
            if execution is not None and checkpoint.execution_id != execution.execution_id:
                reasons.append("CHECKPOINT_EXECUTION_MISMATCH")
        try:
            await self._instances.assert_task_binding(instance_id)
        except AppError:
            reasons.append("TASK_BINDING_INVALID")

        await self._events.append(
            instance_id,
            EVENT_RECOVERY_STARTED,
            payload={
                "checkpoint_id": checkpoint.checkpoint_id if checkpoint else None,
                "execution_id": execution.execution_id if execution else None,
                "reasons": reasons,
            },
            execution_id=execution.execution_id if execution else None,
        )

        if reasons:
            return await self._mark_unknown(instance, tuple(dict.fromkeys(reasons)))

        assert checkpoint is not None and execution is not None
        await self._checkpoints.create(
            instance_id=instance_id,
            execution_id=execution.execution_id,
            trigger="RECOVERY",
        )
        if execution.status in _EXECUTION_RESUMABLE:
            try:
                await self._executions.transition(
                    execution.execution_id, EXECUTION_PAUSED, reason="RECOVERED"
                )
            except AppError:
                pass
        if instance.status in {
            INSTANCE_RUNNING,
            INSTANCE_WAITING_TOOL,
            INSTANCE_WAITING_APPROVAL,
            INSTANCE_WAITING_INPUT,
        }:
            paused: InstanceView = await self._lifecycle.pause(instance_id)
        else:
            paused = await self._lifecycle.transition(instance_id, INSTANCE_PAUSED)
        await self._events.append(
            instance_id,
            EVENT_RECOVERY_COMPLETED,
            payload={
                "decision": RECOVERY_PAUSED,
                "checkpoint_id": checkpoint.checkpoint_id,
            },
            execution_id=execution.execution_id,
        )
        return RecoveryResult(
            instance_id=instance_id,
            previous_status=instance.status,
            status=paused.status,
            decision=RECOVERY_PAUSED,
        )

    async def _mark_unknown(
        self, instance: InstanceView, reasons: tuple[str, ...]
    ) -> RecoveryResult:
        execution = await self._executions.latest_for_instance(instance.instance_id)
        if execution is not None and execution.status in _EXECUTION_RESUMABLE:
            try:
                await self._executions.transition(
                    execution.execution_id, EXECUTION_UNKNOWN, reason=reasons[0]
                )
            except AppError:
                pass
        try:
            marked = await self._lifecycle.mark_unknown(instance.instance_id, reason=reasons[0])
        except AppError:
            marked = await self._instances.get(instance.instance_id)
        await self._events.append(
            instance.instance_id,
            EVENT_RECOVERY_COMPLETED,
            payload={"decision": RECOVERY_UNKNOWN, "reasons": list(reasons)},
            execution_id=execution.execution_id if execution else None,
        )
        return RecoveryResult(
            instance_id=instance.instance_id,
            previous_status=instance.status,
            status=marked.status,
            decision=RECOVERY_UNKNOWN,
            reasons=reasons,
        )

    async def _finish_stopping(self, instance: InstanceView) -> RecoveryResult:
        execution = await self._executions.latest_for_instance(instance.instance_id)
        await self._events.append(
            instance.instance_id,
            EVENT_RECOVERY_STARTED,
            payload={"reason": "INTERRUPTED_STOP"},
            execution_id=execution.execution_id if execution else None,
        )
        try:
            stopped = await self._lifecycle.stop(instance.instance_id, reason="RECOVERED_STOPPING")
        except AppError:
            stopped = await self._instances.get(instance.instance_id)
        await self._events.append(
            instance.instance_id,
            EVENT_RECOVERY_COMPLETED,
            payload={"decision": RECOVERY_STOPPED},
            execution_id=execution.execution_id if execution else None,
        )
        return RecoveryResult(
            instance_id=instance.instance_id,
            previous_status=instance.status,
            status=stopped.status,
            decision=RECOVERY_STOPPED,
        )

    @staticmethod
    def _skip(instance: InstanceView, reason: str) -> RecoveryResult:
        return RecoveryResult(
            instance_id=instance.instance_id,
            previous_status=instance.status,
            status=instance.status,
            decision=RECOVERY_SKIPPED,
            reasons=(reason,),
        )
