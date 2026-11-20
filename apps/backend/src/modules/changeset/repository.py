"""ChangeSet 域仓储（E4-T19）。"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository, Page
from modules.changeset.models import (
    ChangeManifestItemModel,
    ChangeSetModel,
    ChangeSetValidationResultModel,
    ChangeSetVersionModel,
)


class ChangeSetRepository(BaseRepository[ChangeSetModel]):
    model = ChangeSetModel

    async def list_page(
        self, *, project_id: str, status: str | None, limit: int, offset: int
    ) -> Page[ChangeSetModel]:
        filters = [ChangeSetModel.project_id == project_id]
        if status:
            filters.append(ChangeSetModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)


class ChangeSetVersionRepository(BaseRepository[ChangeSetVersionModel]):
    model = ChangeSetVersionModel

    async def list_by_changeset(self, changeset_id: str) -> list[ChangeSetVersionModel]:
        rows = await self.session.scalars(
            select(ChangeSetVersionModel)
            .where(ChangeSetVersionModel.changeset_id == changeset_id)
            .order_by(ChangeSetVersionModel.version_no)
        )
        return list(rows.all())


class ChangeManifestItemRepository(BaseRepository[ChangeManifestItemModel]):
    model = ChangeManifestItemModel

    async def list_by_changeset(self, changeset_id: str) -> list[ChangeManifestItemModel]:
        rows = await self.session.scalars(
            select(ChangeManifestItemModel)
            .where(ChangeManifestItemModel.changeset_id == changeset_id)
            .order_by(ChangeManifestItemModel.resource_path)
        )
        return list(rows.all())


class ChangeSetValidationRepository(BaseRepository[ChangeSetValidationResultModel]):
    model = ChangeSetValidationResultModel

    async def latest(self, changeset_id: str) -> ChangeSetValidationResultModel | None:
        return await self.session.scalar(
            select(ChangeSetValidationResultModel)
            .where(ChangeSetValidationResultModel.changeset_id == changeset_id)
            .order_by(ChangeSetValidationResultModel.validated_at.desc())
            .limit(1)
        )
