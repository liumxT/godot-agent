"""Agent Execution 记录（E6-T07）。

一次 Instance 可以有多次 Execution（恢复会开新 Execution，不复用旧的）。
Execution 状态由本模块拥有；Task / Attempt 状态仍由 Task System 拥有。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import AgentStateInvalid, NotFoundError, VersionConflict
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.instance import InstanceView
from modules.agent_runtime.models import (
    EVENT_EXECUTION_STARTED,
    EXECUTION_COMPLETED,
    EXECUTION_CREATED,
    EXECUTION_FAILED,
    EXECUTION_RUNNING,
    EXECUTION_STOPPED,
    EXECUTION_TRANSITIONS,
    EXECUTION_UNKNOWN,
    EXECUTION_WAITING_APPROVAL,
    EXECUTION_WAITING_INPUT,
    AgentExecutionModel,
)
from modules.agent_runtime.repository import AgentExecutionRepository

_TERMINAL = frozenset({EXECUTION_COMPLETED, EXECUTION_FAILED, EXECUTION_STOPPED})


@dataclass(frozen=True, slots=True)
class ExecutionView:
    execution_id: str
    agent_instance_id: str
    task_id: str | None
    attempt_id: str | None
    execution_number: int
    status: str
    last_checkpoint_id: str | None
    termination_reason: str | None
    budget_usage: dict[str, Any]
    version: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


def _view(entity: AgentExecutionModel) -> ExecutionView:
    return ExecutionView(
        execution_id=entity.execution_id,
        agent_instance_id=entity.agent_instance_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        execution_number=entity.execution_number,
        status=entity.status,
        last_checkpoint_id=entity.last_checkpoint_id,
        termination_reason=entity.termination_reason,
        budget_usage=json.loads(entity.budget_usage_json or "{}"),
        version=entity.version,
        started_at=entity.started_at,
        ended_at=entity.ended_at,
        created_at=entity.created_at,
    )


class AgentExecutionService:
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

    async def get(self, execution_id: str) -> ExecutionView:
        async with self._database.session() as session:
            entity = await AgentExecutionRepository(session).get(execution_id)
        if entity is None:
            raise NotFoundError("Agent Execution 不存在", details={"execution_id": execution_id})
        return _view(entity)

    async def list_for_instance(self, instance_id: str) -> list[ExecutionView]:
        async with self._database.session() as session:
            rows = await AgentExecutionRepository(session).list_for_instance(instance_id)
        return [_view(row) for row in rows]

    async def latest_for_instance(self, instance_id: str) -> ExecutionView | None:
        async with self._database.session() as session:
            entity = await AgentExecutionRepository(session).latest(instance_id)
        return _view(entity) if entity is not None else None

    async def start_execution(self, instance: InstanceView) -> ExecutionView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentExecutionRepository(session)
            number = await repository.next_number(instance.instance_id)
            entity = AgentExecutionModel(
                execution_id="agex_" + uuid4().hex[:12],
                agent_instance_id=instance.instance_id,
                task_id=instance.task_id,
                attempt_id=instance.attempt_id,
                execution_number=number,
                status=EXECUTION_RUNNING,
                last_checkpoint_id=None,
                termination_reason=None,
                budget_usage_json="{}",
                version=1,
                started_at=now,
                ended_at=None,
                created_at=now,
            )
            await repository.add(entity)
            await self._events.append_in_session(
                session,
                instance_id=instance.instance_id,
                execution_id=entity.execution_id,
                event_type=EVENT_EXECUTION_STARTED,
                payload={"execution_number": number},
                now=now,
            )
            await session.flush()
            return _view(entity)

    async def transition(
        self,
        execution_id: str,
        target: str,
        *,
        reason: str | None = None,
    ) -> ExecutionView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentExecutionRepository(session)
            entity = await repository.get(execution_id)
            if entity is None:
                raise NotFoundError(
                    "Agent Execution 不存在", details={"execution_id": execution_id}
                )
            if entity.status == target:
                return _view(entity)
            if target not in EXECUTION_TRANSITIONS.get(entity.status, frozenset()):
                raise AgentStateInvalid(
                    "非法的 Agent Execution 状态迁移",
                    details={
                        "execution_id": execution_id,
                        "from_status": entity.status,
                        "to_status": target,
                    },
                )
            ended_at = now if target in _TERMINAL else None
            previous = entity.status
            rowcount = await repository.compare_and_set_status(
                execution_id,
                expected_version=entity.version,
                from_status=previous,
                to_status=target,
                now=now,
                ended_at=ended_at,
                termination_reason=reason,
            )
            if rowcount == 0:
                raise VersionConflict(
                    "Agent Execution 状态已被并发修改",
                    details={"execution_id": execution_id},
                )
            entity.status = target
            entity.version += 1
            if ended_at is not None:
                entity.ended_at = ended_at
            if reason is not None:
                entity.termination_reason = reason
            await session.flush()
            return _view(entity)

    async def complete(self, execution_id: str, *, reason: str | None = None) -> ExecutionView:
        return await self.transition(execution_id, EXECUTION_COMPLETED, reason=reason)

    async def fail(self, execution_id: str, *, reason: str | None = None) -> ExecutionView:
        return await self.transition(execution_id, EXECUTION_FAILED, reason=reason)

    async def wait_for_approval(self, execution_id: str) -> ExecutionView:
        return await self.transition(execution_id, EXECUTION_WAITING_APPROVAL)

    async def wait_for_input(self, execution_id: str) -> ExecutionView:
        return await self.transition(execution_id, EXECUTION_WAITING_INPUT)

    async def mark_unknown(self, execution_id: str, *, reason: str | None = None) -> ExecutionView:
        return await self.transition(execution_id, EXECUTION_UNKNOWN, reason=reason)


__all__ = [
    "EXECUTION_CREATED",
    "AgentExecutionService",
    "ExecutionView",
]
