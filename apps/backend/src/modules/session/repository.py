"""Session 仓储（E2-T05）。

只接收会话、不创建引擎、不提交事务；事务边界由 Service 控制。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, or_, select, update

from infrastructure.database.repository import BaseRepository
from modules.session.models import (
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_EXPIRED,
    SESSION_STATUS_REVOKED,
    SessionModel,
)


class SessionRepository(BaseRepository[SessionModel]):
    model = SessionModel

    async def get_by_hash(self, token_hash: str) -> SessionModel | None:
        return await self.session.scalar(
            select(SessionModel).where(SessionModel.token_hash == token_hash)
        )

    async def expire_due(self, now: datetime) -> int:
        """把已超过 expires_at 的 ACTIVE Session 标记为 EXPIRED。"""

        result = await self.session.execute(
            update(SessionModel)
            .where(
                SessionModel.status == SESSION_STATUS_ACTIVE,
                SessionModel.expires_at <= now,
            )
            .values(status=SESSION_STATUS_EXPIRED)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)

    async def delete_older_than(self, before: datetime) -> int:
        """清理过期或撤销超过保留期的 Session。"""

        result = await self.session.execute(
            delete(SessionModel)
            .where(
                SessionModel.status.in_((SESSION_STATUS_EXPIRED, SESSION_STATUS_REVOKED)),
                or_(
                    SessionModel.expires_at < before,
                    SessionModel.revoked_at < before,
                ),
            )
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)
