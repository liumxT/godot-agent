"""Runtime 实例仓储（E3-T16）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update

from infrastructure.database.repository import BaseRepository
from modules.runtime.models import RUNTIME_ENDED, RUNTIME_RUNNING, RuntimeInstanceModel


class RuntimeInstanceRepository(BaseRepository[RuntimeInstanceModel]):
    model = RuntimeInstanceModel

    async def list_by_project(self, project_id: str) -> list[RuntimeInstanceModel]:
        result = await self.session.execute(
            select(RuntimeInstanceModel)
            .where(RuntimeInstanceModel.project_id == project_id)
            .order_by(RuntimeInstanceModel.started_at.desc())
        )
        return list(result.scalars().all())

    async def count_active(self) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(RuntimeInstanceModel)
            .where(RuntimeInstanceModel.status == RUNTIME_RUNNING)
        )
        return int(value or 0)

    async def expire_stale(self, cutoff: datetime, now: datetime) -> int:
        """心跳超时的 RUNNING 实例统一收尾为 ENDED。"""

        result = await self.session.execute(
            update(RuntimeInstanceModel)
            .where(
                RuntimeInstanceModel.status == RUNTIME_RUNNING,
                RuntimeInstanceModel.last_seen_at < cutoff,
            )
            .values(status=RUNTIME_ENDED, ended_at=now)
        )
        return int(result.rowcount or 0)
