"""Project Access 仓储（E2-T07）。

只接收会话、不创建引擎、不提交事务；事务边界由 Service 控制。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from infrastructure.database.repository import BaseRepository
from modules.access.models import (
    ACCESS_STATUS_ACTIVE,
    ACCESS_STATUS_EXPIRED,
    ProjectAccessModel,
)


class ProjectAccessRepository(BaseRepository[ProjectAccessModel]):
    model = ProjectAccessModel

    async def get_active(
        self, *, project_id: str, session_id: str, now: datetime
    ) -> ProjectAccessModel | None:
        return await self.session.scalar(
            select(ProjectAccessModel).where(
                ProjectAccessModel.project_id == project_id,
                ProjectAccessModel.session_id == session_id,
                ProjectAccessModel.status == ACCESS_STATUS_ACTIVE,
                ProjectAccessModel.expires_at > now,
            )
        )

    async def get_active_owner(
        self, *, project_id: str, client_id: str, now: datetime
    ) -> ProjectAccessModel | None:
        return await self.session.scalar(
            select(ProjectAccessModel).where(
                ProjectAccessModel.project_id == project_id,
                ProjectAccessModel.client_id == client_id,
                ProjectAccessModel.access_level == "owner",
                ProjectAccessModel.status == ACCESS_STATUS_ACTIVE,
                ProjectAccessModel.expires_at > now,
            )
        )

    async def expire_due(self, now: datetime) -> int:
        result = await self.session.execute(
            update(ProjectAccessModel)
            .where(
                ProjectAccessModel.status == ACCESS_STATUS_ACTIVE,
                ProjectAccessModel.expires_at <= now,
            )
            .values(status=ACCESS_STATUS_EXPIRED)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)
