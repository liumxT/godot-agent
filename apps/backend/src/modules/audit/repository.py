"""审计仓储（E2-T11）。

只接收会话、不创建引擎、不提交事务；审计写入不提供更新/删除方法。
"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository
from modules.audit.models import AuditEventModel


class AuditRepository(BaseRepository[AuditEventModel]):
    model = AuditEventModel

    async def recent(self, *, limit: int = 50) -> list[AuditEventModel]:
        rows = await self.session.scalars(
            select(AuditEventModel)
            .order_by(AuditEventModel.timestamp.desc(), AuditEventModel.audit_id.desc())
            .limit(limit)
        )
        return list(rows.all())

    async def for_action(self, action: str, *, limit: int = 50) -> list[AuditEventModel]:
        rows = await self.session.scalars(
            select(AuditEventModel)
            .where(AuditEventModel.action == action)
            .order_by(AuditEventModel.timestamp.desc(), AuditEventModel.audit_id.desc())
            .limit(limit)
        )
        return list(rows.all())

    async def for_client(self, client_id: str, *, limit: int = 50) -> list[AuditEventModel]:
        rows = await self.session.scalars(
            select(AuditEventModel)
            .where(AuditEventModel.client_id == client_id)
            .order_by(AuditEventModel.timestamp.desc(), AuditEventModel.audit_id.desc())
            .limit(limit)
        )
        return list(rows.all())
