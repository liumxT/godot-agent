"""编辑器快照仓储（E3-T11）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select

from infrastructure.database.repository import BaseRepository
from modules.snapshot.models import SnapshotModel


class SnapshotRepository(BaseRepository[SnapshotModel]):
    model = SnapshotModel

    async def latest(self, session_id: str) -> SnapshotModel | None:
        return await self.session.scalar(
            select(SnapshotModel)
            .where(SnapshotModel.session_id == session_id)
            .order_by(SnapshotModel.created_at.desc())
            .limit(1)
        )

    async def max_version(self, session_id: str) -> int:
        value = await self.session.scalar(
            select(func.max(SnapshotModel.snapshot_version)).where(
                SnapshotModel.session_id == session_id
            )
        )
        return int(value or 0)

    async def list_beyond(self, session_id: str, keep: int) -> list[str]:
        result = await self.session.execute(
            select(SnapshotModel.snapshot_id)
            .where(SnapshotModel.session_id == session_id)
            .order_by(SnapshotModel.created_at.desc())
            .offset(keep)
        )
        return list(result.scalars().all())

    async def delete_ids(self, snapshot_ids: list[str]) -> int:
        if not snapshot_ids:
            return 0
        result = await self.session.execute(
            delete(SnapshotModel).where(SnapshotModel.snapshot_id.in_(snapshot_ids))
        )
        return int(result.rowcount or 0)

    async def delete_before(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            delete(SnapshotModel).where(SnapshotModel.created_at < cutoff)
        )
        return int(result.rowcount or 0)
