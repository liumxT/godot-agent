"""Inbox 仓储（E1-T10）。

以 ``(event_id, consumer_id)`` 为主键记录消费结果，保证重复投递时处理器不重复执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.errors import translate_db_error

_UPSERT = text(
    "INSERT INTO event_inbox (event_id, consumer_id, status, processed_at, last_error) "
    "VALUES (:event_id, :consumer_id, :status, "
    "CASE WHEN :status = 'processed' THEN CURRENT_TIMESTAMP ELSE NULL END, :last_error) "
    "ON CONFLICT(event_id, consumer_id) DO UPDATE SET "
    "status = excluded.status, "
    "processed_at = excluded.processed_at, "
    "last_error = excluded.last_error"
)


@dataclass(frozen=True, slots=True)
class InboxEntry:
    event_id: str
    consumer_id: str
    status: str
    received_at: datetime | str
    processed_at: datetime | str | None
    last_error: str | None


class InboxRepository:
    async def get(
        self, session: AsyncSession, event_id: str, consumer_id: str
    ) -> InboxEntry | None:
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT event_id, consumer_id, status, received_at, processed_at, "
                        "last_error FROM event_inbox "
                        "WHERE event_id = :event_id AND consumer_id = :consumer_id"
                    ),
                    {"event_id": event_id, "consumer_id": consumer_id},
                )
            ).first()
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc
        if row is None:
            return None
        return InboxEntry(
            event_id=row.event_id,
            consumer_id=row.consumer_id,
            status=row.status,
            received_at=row.received_at,
            processed_at=row.processed_at,
            last_error=row.last_error,
        )

    async def is_processed(self, session: AsyncSession, event_id: str, consumer_id: str) -> bool:
        entry = await self.get(session, event_id, consumer_id)
        return entry is not None and entry.status == "processed"

    async def mark_processed(self, session: AsyncSession, event_id: str, consumer_id: str) -> None:
        await self._upsert(session, event_id, consumer_id, "processed", None)

    async def mark_failed(
        self,
        session: AsyncSession,
        event_id: str,
        consumer_id: str,
        error: str,
    ) -> None:
        await self._upsert(session, event_id, consumer_id, "failed", error)

    async def counts(self, session: AsyncSession) -> dict[str, int]:
        try:
            rows = (
                await session.execute(
                    text("SELECT status, count(*) AS total FROM event_inbox GROUP BY status")
                )
            ).all()
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc
        return {row.status: int(row.total) for row in rows}

    async def _upsert(
        self,
        session: AsyncSession,
        event_id: str,
        consumer_id: str,
        status: str,
        error: str | None,
    ) -> None:
        try:
            await session.execute(
                _UPSERT,
                {
                    "event_id": event_id,
                    "consumer_id": consumer_id,
                    "status": status,
                    "last_error": error,
                },
            )
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc
