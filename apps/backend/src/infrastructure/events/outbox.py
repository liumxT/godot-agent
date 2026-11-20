"""Outbox 仓储（E1-T10）。

业务事务内调用 ``add()`` 写入待发布事件；Repository 不提交，提交由事务边界负责。
派发器通过 ``fetch_dispatchable`` / ``mark_*`` 推进状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.events.model import Event
from infrastructure.database.errors import translate_db_error

_INSERT = text(
    "INSERT INTO event_outbox "
    "(event_id, event_type, event_version, payload, correlation_id, status) "
    "VALUES (:event_id, :event_type, :event_version, :payload, :correlation_id, 'pending')"
)

_SELECT_DISPATCHABLE = text(
    "SELECT id, event_id, event_type, event_version, payload, correlation_id, status, "
    "retry_count, last_error, created_at, published_at "
    "FROM event_outbox "
    "WHERE status IN ('pending', 'failed') AND retry_count < :max_retries "
    "ORDER BY id LIMIT :limit"
)


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: int
    event_id: str
    event_type: str
    event_version: int
    payload: str
    correlation_id: str | None
    status: str
    retry_count: int
    last_error: str | None
    created_at: datetime | str
    published_at: datetime | str | None

    def to_event(self) -> Event:
        return Event.from_storage(
            event_id=self.event_id,
            event_type=self.event_type,
            event_version=self.event_version,
            payload=self.payload,
            correlation_id=self.correlation_id,
            occurred_at=self.created_at,
        )


class OutboxRepository:
    async def add(self, session: AsyncSession, event: Event) -> None:
        try:
            await session.execute(
                _INSERT,
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "event_version": event.event_version,
                    "payload": event.payload_json,
                    "correlation_id": event.correlation_id,
                },
            )
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc

    async def fetch_dispatchable(
        self,
        session: AsyncSession,
        *,
        limit: int,
        max_retries: int,
    ) -> list[OutboxMessage]:
        try:
            rows = (
                await session.execute(
                    _SELECT_DISPATCHABLE, {"limit": limit, "max_retries": max_retries}
                )
            ).all()
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc
        return [
            OutboxMessage(
                id=row.id,
                event_id=row.event_id,
                event_type=row.event_type,
                event_version=row.event_version,
                payload=row.payload,
                correlation_id=row.correlation_id,
                status=row.status,
                retry_count=row.retry_count,
                last_error=row.last_error,
                created_at=row.created_at,
                published_at=row.published_at,
            )
            for row in rows
        ]

    async def mark_publishing(self, session: AsyncSession, message_id: int) -> None:
        await self._execute(
            session,
            "UPDATE event_outbox SET status = 'publishing' WHERE id = :id",
            {"id": message_id},
        )

    async def mark_published(self, session: AsyncSession, message_id: int) -> None:
        await self._execute(
            session,
            "UPDATE event_outbox SET status = 'published', published_at = CURRENT_TIMESTAMP "
            "WHERE id = :id",
            {"id": message_id},
        )

    async def mark_failed(self, session: AsyncSession, message_id: int, error: str) -> None:
        await self._execute(
            session,
            "UPDATE event_outbox SET status = 'failed', retry_count = retry_count + 1, "
            "last_error = :error WHERE id = :id",
            {"id": message_id, "error": error},
        )

    async def reset_publishing(self, session: AsyncSession) -> int:
        """进程中断后把 ``publishing`` 复位为 ``pending``（E1-FI-007）。"""

        try:
            result = await session.execute(
                text("UPDATE event_outbox SET status = 'pending' WHERE status = 'publishing'")
            )
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc
        return int(result.rowcount or 0)

    async def counts(self, session: AsyncSession) -> dict[str, int]:
        try:
            rows = (
                await session.execute(
                    text("SELECT status, count(*) AS total FROM event_outbox GROUP BY status")
                )
            ).all()
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc
        return {row.status: int(row.total) for row in rows}

    async def _execute(
        self, session: AsyncSession, statement: str, params: dict[str, object]
    ) -> None:
        try:
            await session.execute(text(statement), params)
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc
