"""项目身份仓储（E3-T14 前置）。"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository
from modules.project.models import ProjectModel


class ProjectRepository(BaseRepository[ProjectModel]):
    model = ProjectModel

    async def get_by_root(self, project_root: str) -> ProjectModel | None:
        return await self.session.scalar(
            select(ProjectModel).where(ProjectModel.project_root == project_root)
        )

    async def get_by_fingerprint(self, fingerprint: str) -> ProjectModel | None:
        return await self.session.scalar(
            select(ProjectModel).where(ProjectModel.project_fingerprint == fingerprint).limit(1)
        )
