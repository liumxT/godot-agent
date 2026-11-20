"""Bridge 事件仓储（E3-T10）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, update

from infrastructure.database.repository import BaseRepository
from modules.bridge_event.models import BridgeEventModel


class BridgeEventRepository(BaseRepository[BridgeEventModel]):
    model = BridgeEventModel

    async def max_sequence(self, session_id: str, direction: str) -> int:
        value = await self.session.scalar(
            select(func.max(BridgeEventModel.sequence)).where(
                BridgeEventModel.session_id == session_id,
                BridgeEventModel.direction == direction,
            )
        )
        return int(value or 0)

    async def min_sequence(self, session_id: str, direction: str) -> int | None:
        value = await self.session.scalar(
            select(func.min(BridgeEventModel.sequence)).where(
                BridgeEventModel.session_id == session_id,
                BridgeEventModel.direction == direction,
            )
        )
        return int(value) if value is not None else None

    async def list_since(
        self,
        session_id: str,
        direction: str,
        after_sequence: int,
        limit: int,
    ) -> list[BridgeEventModel]:
        result = await self.session.execute(
            select(BridgeEventModel)
            .where(
                BridgeEventModel.session_id == session_id,
                BridgeEventModel.direction == direction,
                BridgeEventModel.sequence > after_sequence,
            )
            .order_by(BridgeEventModel.sequence.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_acked(
        self,
        session_id: str,
        direction: str,
        event_ids: list[str],
        last_sequence: int | None,
        now: datetime,
    ) -> int:
        conditions = []
        if event_ids:
            conditions.append(BridgeEventModel.event_id.in_(event_ids))
        if last_sequence is not None:
            conditions.append(BridgeEventModel.sequence <= last_sequence)
        if not conditions:
            return 0
        statement = (
            update(BridgeEventModel)
            .where(
                BridgeEventModel.session_id == session_id,
                BridgeEventModel.direction == direction,
                BridgeEventModel.acked_at.is_(None),
            )
            .values(acked_at=now)
            .execution_options(synchronize_session=False)
        )
        for condition in conditions:
            statement = statement.where(condition)
        result = await self.session.execute(statement)
        return int(result.rowcount or 0)

    async def count_unacked(self, session_id: str | None, direction: str) -> int:
        statement = (
            select(func.count())
            .select_from(BridgeEventModel)
            .where(
                BridgeEventModel.direction == direction,
                BridgeEventModel.acked_at.is_(None),
            )
        )
        if session_id is not None:
            statement = statement.where(BridgeEventModel.session_id == session_id)
        value = await self.session.scalar(statement)
        return int(value or 0)

    async def delete_before(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            delete(BridgeEventModel).where(BridgeEventModel.created_at < cutoff)
        )
        return int(result.rowcount or 0)
