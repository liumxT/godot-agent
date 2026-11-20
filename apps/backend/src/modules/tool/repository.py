"""工具定义仓储（E5-T17）。"""

from __future__ import annotations

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository, Page
from modules.tool.models import ToolDefinitionModel


class ToolDefinitionRepository(BaseRepository[ToolDefinitionModel]):
    model = ToolDefinitionModel

    async def latest_version(self, name: str) -> int:
        value = await self.session.scalar(
            select(func.max(ToolDefinitionModel.version)).where(
                ToolDefinitionModel.name == name
            )
        )
        return int(value or 0)

    async def get_by_name_version(self, name: str, version: int) -> ToolDefinitionModel | None:
        return await self.session.scalar(
            select(ToolDefinitionModel).where(
                ToolDefinitionModel.name == name,
                ToolDefinitionModel.version == version,
            )
        )

    async def list_definitions(
        self,
        *,
        category: str | None,
        enabled: bool | None,
        limit: int,
        offset: int,
    ) -> Page[ToolDefinitionModel]:
        filters = []
        if category is not None:
            filters.append(ToolDefinitionModel.category == category)
        if enabled is not None:
            filters.append(ToolDefinitionModel.enabled == enabled)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    def _order_columns(self):
        return (ToolDefinitionModel.name.asc(), ToolDefinitionModel.version.desc())
