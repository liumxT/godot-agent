"""Editor Session 绑定仓储（E3-T07）。"""

from __future__ import annotations

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository
from modules.editor_session.models import EditorSessionModel


class EditorSessionRepository(BaseRepository[EditorSessionModel]):
    model = EditorSessionModel

    async def list_by_project(self, project_id: str) -> list[EditorSessionModel]:
        result = await self.session.execute(
            select(EditorSessionModel)
            .where(EditorSessionModel.project_id == project_id)
            .order_by(EditorSessionModel.connected_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_statuses(self, statuses: list[str]) -> list[EditorSessionModel]:
        """按绑定状态列出连接，用于 ``/bridge/sessions`` 诊断。"""

        result = await self.session.execute(
            select(EditorSessionModel)
            .where(EditorSessionModel.binding_status.in_(statuses))
            .order_by(EditorSessionModel.project_id, EditorSessionModel.connected_at.desc())
        )
        return list(result.scalars().all())

    async def count_by_status(self, status: str) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(EditorSessionModel)
            .where(EditorSessionModel.binding_status == status)
        )
        return int(value or 0)
