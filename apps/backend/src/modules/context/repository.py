"""Context 域仓储（E5-T16）。"""

from __future__ import annotations

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository, Page
from modules.context.models import ContextAssemblyModel


class ContextAssemblyRepository(BaseRepository[ContextAssemblyModel]):
    model = ContextAssemblyModel

    async def latest_version(self, project_id: str) -> int:
        value = await self.session.scalar(
            select(func.max(ContextAssemblyModel.context_version)).where(
                ContextAssemblyModel.project_id == project_id
            )
        )
        return int(value or 0)

    async def list_for_project(
        self, project_id: str, *, limit: int, offset: int
    ) -> Page[ContextAssemblyModel]:
        return await self.paginate(
            limit=limit,
            offset=offset,
            filters=[ContextAssemblyModel.project_id == project_id],
        )
