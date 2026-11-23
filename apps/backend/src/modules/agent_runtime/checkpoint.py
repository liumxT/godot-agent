"""Checkpoint（E6-T13）。

Checkpoint 记录可恢复的最小状态：Instance / Execution 状态、Plan 与 Step 进度、
当前动作、预算用量与最后确认的事件序号。Checkpoint 不保存模型隐藏推理、
密钥或完整文件内容。

Checkpoint 与事件写入在同一事务内，并回填 Execution.last_checkpoint_id。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import NotFoundError
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.models import (
    EVENT_CHECKPOINT_CREATED,
    STEP_COMPLETED,
    STEP_RUNNING,
    STEP_WAITING_APPROVAL,
    STEP_WAITING_TOOL,
    AgentCheckpointModel,
)
from modules.agent_runtime.repository import (
    AgentCheckpointRepository,
    AgentEventRepository,
    AgentExecutionRepository,
    AgentInstanceRepository,
    AgentPlanRepository,
    AgentStepRepository,
)

__all__ = ["CheckpointService", "CheckpointView"]


@dataclass(frozen=True, slots=True)
class CheckpointView:
    checkpoint_id: str
    agent_instance_id: str
    execution_id: str
    plan_id: str | None
    last_completed_step_id: str | None
    current_step_id: str | None
    state: dict[str, Any]
    budget: dict[str, Any]
    context_snapshot_id: str | None
    last_event_sequence: int
    checkpoint_version: int
    created_at: datetime


def _view(entity: AgentCheckpointModel) -> CheckpointView:
    return CheckpointView(
        checkpoint_id=entity.checkpoint_id,
        agent_instance_id=entity.agent_instance_id,
        execution_id=entity.execution_id,
        plan_id=entity.plan_id,
        last_completed_step_id=entity.last_completed_step_id,
        current_step_id=entity.current_step_id,
        state=json.loads(entity.state_snapshot or "{}"),
        budget=json.loads(entity.budget_snapshot or "{}"),
        context_snapshot_id=entity.context_snapshot_id,
        last_event_sequence=entity.last_event_sequence,
        checkpoint_version=entity.checkpoint_version,
        created_at=entity.created_at,
    )


class CheckpointService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        events: AgentEventService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._events = events
        self._clock = clock

    async def get(self, checkpoint_id: str) -> CheckpointView:
        async with self._database.session() as session:
            entity = await AgentCheckpointRepository(session).get(checkpoint_id)
        if entity is None:
            raise NotFoundError(
                "Agent Checkpoint 不存在", details={"checkpoint_id": checkpoint_id}
            )
        return _view(entity)

    async def latest(self, instance_id: str) -> CheckpointView | None:
        async with self._database.session() as session:
            entity = await AgentCheckpointRepository(session).latest(instance_id)
        return _view(entity) if entity is not None else None

    async def create(
        self,
        *,
        instance_id: str,
        execution_id: str,
        trigger: str,
        context_id: str | None = None,
        pending_action: Mapping[str, Any] | None = None,
    ) -> CheckpointView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            instance = await AgentInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError(
                    "Agent Instance 不存在", details={"instance_id": instance_id}
                )
            execution = await AgentExecutionRepository(session).get(execution_id)
            if execution is None:
                raise NotFoundError(
                    "Agent Execution 不存在", details={"execution_id": execution_id}
                )
            plan = await AgentPlanRepository(session).get_active_for_execution(execution_id)
            steps = await AgentStepRepository(session).list_by_execution(execution_id)
            if plan is not None:
                steps = [item for item in steps if item.plan_id == plan.plan_id]
            current = next(
                (
                    item
                    for item in steps
                    if item.status
                    in {STEP_RUNNING, STEP_WAITING_TOOL, STEP_WAITING_APPROVAL}
                ),
                None,
            )
            completed = [
                item.step_id for item in steps if item.status == STEP_COMPLETED
            ]
            pending = [
                item.step_id
                for item in steps
                if item.status
                not in {STEP_COMPLETED, "FAILED", "SKIPPED"}
            ]
            state = {
                "instance_status": instance.status,
                "execution_status": execution.status,
                "task_id": instance.task_id,
                "attempt_id": instance.attempt_id,
                "project_id": instance.project_id,
                "session_id": instance.session_id,
                "client_id": instance.client_id,
                "plan_id": plan.plan_id if plan is not None else None,
                "plan_status": plan.status if plan is not None else None,
                "completed_steps": completed,
                "pending_steps": pending,
                "current_step_id": current.step_id if current is not None else None,
                "pending_action": dict(pending_action) if pending_action else None,
                "trigger": trigger,
            }
            last_event_sequence = (
                await AgentEventRepository(session).next_sequence(instance_id) - 1
            )
            entity = AgentCheckpointModel(
                checkpoint_id="agck_" + uuid4().hex[:12],
                agent_instance_id=instance_id,
                execution_id=execution_id,
                plan_id=plan.plan_id if plan is not None else None,
                last_completed_step_id=completed[-1] if completed else None,
                current_step_id=current.step_id if current is not None else None,
                state_snapshot=json.dumps(state, ensure_ascii=False, sort_keys=True),
                budget_snapshot=execution.budget_usage_json or "{}",
                context_snapshot_id=context_id,
                last_event_sequence=last_event_sequence,
                checkpoint_version=await AgentCheckpointRepository(
                    session
                ).next_version(instance_id),
                created_at=now,
            )
            await AgentCheckpointRepository(session).add(entity)
            execution.last_checkpoint_id = entity.checkpoint_id
            await self._events.append_in_session(
                session,
                instance_id=instance_id,
                execution_id=execution_id,
                event_type=EVENT_CHECKPOINT_CREATED,
                payload={
                    "checkpoint_id": entity.checkpoint_id,
                    "checkpoint_version": entity.checkpoint_version,
                    "trigger": trigger,
                    "last_event_sequence": last_event_sequence,
                },
                now=now,
            )
            await session.flush()
            return _view(entity)
