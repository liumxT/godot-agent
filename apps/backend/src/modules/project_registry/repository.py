"""Project 域仓储（E4-T01…T04）。"""

from __future__ import annotations

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository, Page
from modules.project_registry.models import (
    ProjectConfigurationModel,
    ProjectConfigurationVersionModel,
    ProjectIdentityModel,
    ProjectMembershipModel,
    ProjectRecordModel,
)


class ProjectRecordRepository(BaseRepository[ProjectRecordModel]):
    model = ProjectRecordModel

    async def get_by_root(self, project_root: str) -> ProjectRecordModel | None:
        return await self.session.scalar(
            select(ProjectRecordModel).where(ProjectRecordModel.project_root == project_root)
        )

    async def list_page(
        self, *, status: str | None, limit: int, offset: int
    ) -> Page[ProjectRecordModel]:
        filters = [ProjectRecordModel.status == status] if status else []
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def count_by_status(self, status: str) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(ProjectRecordModel)
            .where(ProjectRecordModel.status == status)
        )
        return int(value or 0)


class ProjectIdentityRepository(BaseRepository[ProjectIdentityModel]):
    model = ProjectIdentityModel


class ProjectConfigurationRepository(BaseRepository[ProjectConfigurationModel]):
    model = ProjectConfigurationModel


class ProjectConfigurationVersionRepository(BaseRepository[ProjectConfigurationVersionModel]):
    model = ProjectConfigurationVersionModel

    async def latest_version(self, project_id: str) -> int:
        value = await self.session.scalar(
            select(func.max(ProjectConfigurationVersionModel.version_no)).where(
                ProjectConfigurationVersionModel.project_id == project_id
            )
        )
        return int(value or 0)

    async def list_by_project(self, project_id: str) -> list[ProjectConfigurationVersionModel]:
        rows = await self.session.scalars(
            select(ProjectConfigurationVersionModel)
            .where(ProjectConfigurationVersionModel.project_id == project_id)
            .order_by(ProjectConfigurationVersionModel.version_no)
        )
        return list(rows.all())


class ProjectMembershipRepository(BaseRepository[ProjectMembershipModel]):
    model = ProjectMembershipModel

    async def list_by_project(self, project_id: str) -> list[ProjectMembershipModel]:
        rows = await self.session.scalars(
            select(ProjectMembershipModel).where(ProjectMembershipModel.project_id == project_id)
        )
        return list(rows.all())
