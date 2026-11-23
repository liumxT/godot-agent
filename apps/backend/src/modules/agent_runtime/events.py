"""Agent Runtime 只追加事件日志（E6-T13 基础）。

事件是运行时可审计性的基础：模型调用、工具调用、状态迁移、暂停/恢复/取消、
检查点与错误都必须写入。事件不保存模型隐藏推理、密钥或完整文件内容。

``sequence_number`` 在 Instance 内单调递增，唯一约束兜底并发写入。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationFailed
from core.security.tokens import isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.models import AGENT_EVENT_TYPES, AgentEventModel
from modules.agent_runtime.repository import AgentEventRepository


@dataclass(frozen=True, slots=True)
class AgentEventView:
    event_id: str
    agent_instance_id: str
    execution_id: str | None
    sequence_number: int
    event_type: str
    payload: dict[str, Any]
    correlation_id: str | None
    created_at: datetime


def _view(entity: AgentEventModel) -> AgentEventView:
    return AgentEventView(
        event_id=entity.event_id,
        agent_instance_id=entity.agent_instance_id,
        execution_id=entity.execution_id,
        sequence_number=entity.sequence_number,
        event_type=entity.event_type,
        payload=json.loads(entity.event_payload),
        correlation_id=entity.correlation_id,
        created_at=entity.created_at,
    )


def format_event(view: AgentEventView) -> dict[str, Any]:
    return {
        "event_id": view.event_id,
        "agent_instance_id": view.agent_instance_id,
        "execution_id": view.execution_id,
        "sequence_number": view.sequence_number,
        "event_type": view.event_type,
        "payload": view.payload,
        "correlation_id": view.correlation_id,
        "created_at": isoformat(view.created_at),
    }


class AgentEventService:
    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def append_in_session(
        self,
        session: AsyncSession,
        *,
        instance_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        execution_id: str | None = None,
        correlation_id: str | None = None,
        now: datetime | None = None,
    ) -> AgentEventView:
        if event_type not in AGENT_EVENT_TYPES:
            raise ValidationFailed(
                "未知的 Agent 事件类型", details={"event_type": event_type}
            )
        resolved_now = now or self._clock()
        repository = AgentEventRepository(session)
        sequence = await repository.next_sequence(instance_id)
        entity = AgentEventModel(
            event_id="agev_" + uuid4().hex[:12],
            agent_instance_id=instance_id,
            execution_id=execution_id,
            sequence_number=sequence,
            event_type=event_type,
            event_payload=json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True),
            correlation_id=correlation_id,
            created_at=resolved_now,
        )
        await repository.add(entity)
        return _view(entity)

    async def append(
        self,
        instance_id: str,
        event_type: str,
        *,
        payload: Mapping[str, Any] | None = None,
        execution_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AgentEventView:
        async with self._database.session() as session, transaction(session):
            view = await self.append_in_session(
                session,
                instance_id=instance_id,
                event_type=event_type,
                payload=payload,
                execution_id=execution_id,
                correlation_id=correlation_id,
            )
            await session.flush()
            return view

    async def last_sequence(self, instance_id: str) -> int:
        """返回该 Instance 已持久化的最大事件序号（无事件时为 0）。"""

        async with self._database.session() as session:
            return await AgentEventRepository(session).next_sequence(instance_id) - 1

    async def list_after(
        self, instance_id: str, *, after_sequence: int = 0, limit: int = 200
    ) -> list[AgentEventView]:
        async with self._database.session() as session:
            rows = await AgentEventRepository(session).list_after(
                instance_id, after_sequence=after_sequence, limit=limit
            )
        return [_view(row) for row in rows]
