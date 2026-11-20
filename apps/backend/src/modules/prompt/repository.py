"""Prompt 域仓储（E5-T15）。"""

from __future__ import annotations

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository, Page
from modules.prompt.models import (
    PROMPT_STATUS_ACTIVE,
    PromptDefinitionModel,
    PromptTestResultModel,
)


class PromptDefinitionRepository(BaseRepository[PromptDefinitionModel]):
    model = PromptDefinitionModel

    async def latest_version(self, name: str) -> int:
        value = await self.session.scalar(
            select(func.max(PromptDefinitionModel.version)).where(
                PromptDefinitionModel.name == name
            )
        )
        return int(value or 0)

    async def get_by_name_version(self, name: str, version: int) -> PromptDefinitionModel | None:
        return await self.session.scalar(
            select(PromptDefinitionModel).where(
                PromptDefinitionModel.name == name,
                PromptDefinitionModel.version == version,
            )
        )

    async def get_active(self, name: str) -> PromptDefinitionModel | None:
        return await self.session.scalar(
            select(PromptDefinitionModel).where(
                PromptDefinitionModel.name == name,
                PromptDefinitionModel.status == PROMPT_STATUS_ACTIVE,
            )
        )

    async def list_versions(
        self, name: str, *, limit: int, offset: int
    ) -> Page[PromptDefinitionModel]:
        return await self.paginate(
            limit=limit, offset=offset, filters=[PromptDefinitionModel.name == name]
        )

    def _order_columns(self):
        return (PromptDefinitionModel.version.desc(),)


class PromptTestResultRepository(BaseRepository[PromptTestResultModel]):
    model = PromptTestResultModel

    async def list_for_prompt(
        self, prompt_id: str, *, limit: int, offset: int
    ) -> Page[PromptTestResultModel]:
        return await self.paginate(
            limit=limit, offset=offset, filters=[PromptTestResultModel.prompt_id == prompt_id]
        )
