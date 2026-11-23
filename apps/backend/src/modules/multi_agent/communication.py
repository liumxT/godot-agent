"""Agent 间受控消息通信（E7-T12）。

所有消息必须绑定 Team 与明确的发送者/接收者；消息不直接触发操作，只作为
可审计的通知与请求载体。消费按 ``message_id`` 幂等，不接受非接收方消费。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from core.errors import AgentMessageInvalid, NotFoundError
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.multi_agent.models import (
    ASSIGNMENT_CANCELLED,
    ASSIGNMENT_FAILED,
    MESSAGE_TYPES,
    AgentMessageModel,
)
from modules.multi_agent.repository import (
    AgentAssignmentRepository,
    AgentMessageRepository,
    AgentTeamRepository,
)

_TERMINAL_SENDER_STATUSES = frozenset({ASSIGNMENT_CANCELLED, ASSIGNMENT_FAILED})


@dataclass(frozen=True, slots=True)
class MessageView:
    message_id: str
    team_id: str
    source_assignment_id: str
    target_assignment_id: str
    message_type: str
    payload_reference: str
    correlation_id: str | None
    sequence_number: int
    consumed_at: datetime | None
    created_at: datetime


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _message_view(entity: AgentMessageModel) -> MessageView:
    return MessageView(
        message_id=entity.message_id,
        team_id=entity.team_id,
        source_assignment_id=entity.source_assignment_id or "",
        target_assignment_id=entity.target_assignment_id or "",
        message_type=entity.message_type,
        payload_reference=entity.payload_reference,
        correlation_id=entity.correlation_id,
        sequence_number=entity.sequence_number,
        consumed_at=ensure_utc(entity.consumed_at) if entity.consumed_at else None,
        created_at=ensure_utc(entity.created_at),
    )


class MessageService:
    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def send(
        self,
        *,
        team_id: str,
        source_assignment_id: str,
        target_assignment_id: str,
        message_type: str,
        payload_reference: str,
        correlation_id: str | None = None,
    ) -> MessageView:
        if message_type not in MESSAGE_TYPES:
            raise AgentMessageInvalid(
                "消息类型非法",
                details={"reasons": ["UNKNOWN_MESSAGE_TYPE"], "message_type": message_type},
            )
        if not source_assignment_id or not target_assignment_id:
            raise AgentMessageInvalid(
                "消息必须具有明确的发送者与接收者",
                details={"reasons": ["ENDPOINT_REQUIRED"]},
            )
        if not (payload_reference or "").strip():
            raise AgentMessageInvalid(
                "消息必须引用 payload", details={"reasons": ["PAYLOAD_REQUIRED"]}
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            assignments = AgentAssignmentRepository(session)
            source = await assignments.get(source_assignment_id)
            if source is None or source.team_id != team_id:
                raise AgentMessageInvalid(
                    "发送者不属于该 Team",
                    details={"reasons": ["UNKNOWN_SOURCE"], "assignment_id": source_assignment_id},
                )
            if source.status in _TERMINAL_SENDER_STATUSES:
                raise AgentMessageInvalid(
                    "已结束的 Assignment 不能发送消息",
                    details={"reasons": ["SOURCE_TERMINAL"], "status": source.status},
                )
            target = await assignments.get(target_assignment_id)
            if target is None or target.team_id != team_id:
                raise AgentMessageInvalid(
                    "接收者不属于该 Team",
                    details={"reasons": ["UNKNOWN_TARGET"], "assignment_id": target_assignment_id},
                )
            repository = AgentMessageRepository(session)
            entity = AgentMessageModel(
                message_id=_new_id("msg_"),
                team_id=team_id,
                source_assignment_id=source_assignment_id,
                target_assignment_id=target_assignment_id,
                message_type=message_type,
                payload_reference=payload_reference,
                correlation_id=correlation_id,
                sequence_number=await repository.next_sequence(team_id),
                consumed_at=None,
                created_at=now,
            )
            await repository.add(entity)
            return _message_view(entity)

    async def get(self, message_id: str) -> MessageView:
        async with self._database.session() as session:
            entity = await AgentMessageRepository(session).get(message_id)
        if entity is None:
            raise NotFoundError("Agent 消息不存在", details={"message_id": message_id})
        return _message_view(entity)

    async def list_for_team(self, team_id: str, *, limit: int = 200) -> list[MessageView]:
        async with self._database.session() as session:
            rows = await AgentMessageRepository(session).list_for_team(team_id, limit=limit)
        return [_message_view(row) for row in rows]

    async def list_for_assignment(
        self, assignment_id: str, *, unread_only: bool = False
    ) -> list[MessageView]:
        async with self._database.session() as session:
            rows = await AgentMessageRepository(session).list_for_target(
                assignment_id, unread_only=unread_only
            )
        return [_message_view(row) for row in rows]

    async def consume(self, message_id: str, *, consumer_assignment_id: str) -> MessageView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentMessageRepository(session)
            entity = await repository.get(message_id)
            if entity is None:
                raise NotFoundError("Agent 消息不存在", details={"message_id": message_id})
            if entity.target_assignment_id != consumer_assignment_id:
                raise AgentMessageInvalid(
                    "消息只能由接收者消费",
                    details={
                        "reasons": ["CONSUMER_MISMATCH"],
                        "target_assignment_id": entity.target_assignment_id,
                    },
                )
            if entity.consumed_at is None:
                entity.consumed_at = now
                await session.flush()
            return _message_view(entity)


__all__ = ["MessageService", "MessageView"]
