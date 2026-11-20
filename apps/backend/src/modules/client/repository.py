"""Client / Credential / Access Token 仓储（E2-T06 / T04）。

只接收会话、不创建引擎、不提交事务；事务边界由 Service 控制。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, or_, select, update

from infrastructure.database.repository import BaseRepository
from modules.client.models import (
    AccessTokenModel,
    ClientCredentialModel,
    ClientModel,
)


class ClientRepository(BaseRepository[ClientModel]):
    model = ClientModel

    async def count(self) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(ClientModel)) or 0)

    async def list_clients(
        self, *, limit: int, offset: int, status: str | None = None
    ) -> list[ClientModel]:
        statement = select(ClientModel)
        if status is not None:
            statement = statement.where(ClientModel.status == status)
        statement = statement.order_by(ClientModel.created_at).limit(limit).offset(offset)
        return list(await self.session.scalars(statement))


class CredentialRepository(BaseRepository[ClientCredentialModel]):
    model = ClientCredentialModel

    async def list_for_client(self, client_id: str) -> list[ClientCredentialModel]:
        rows = await self.session.scalars(
            select(ClientCredentialModel)
            .where(ClientCredentialModel.client_id == client_id)
            .order_by(ClientCredentialModel.created_at)
        )
        return list(rows)

    async def revoke_active_for_client(self, client_id: str, revoked_at: datetime) -> int:
        result = await self.session.execute(
            update(ClientCredentialModel)
            .where(
                ClientCredentialModel.client_id == client_id,
                ClientCredentialModel.revoked_at.is_(None),
            )
            .values(status="revoked", revoked_at=revoked_at)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)


class AccessTokenRepository(BaseRepository[AccessTokenModel]):
    model = AccessTokenModel

    async def get_by_hash(self, token_hash: str) -> AccessTokenModel | None:
        return await self.session.scalar(
            select(AccessTokenModel).where(AccessTokenModel.token_hash == token_hash)
        )

    async def revoke_if_active(self, token_id: str, revoked_at: datetime) -> bool:
        """条件更新：只有未撤销且未过期时成功，避免并发轮换。"""

        result = await self.session.execute(
            update(AccessTokenModel)
            .where(
                AccessTokenModel.token_id == token_id,
                AccessTokenModel.revoked_at.is_(None),
                AccessTokenModel.expires_at > revoked_at,
            )
            .values(revoked_at=revoked_at)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)

    async def revoke_for_client(self, client_id: str, revoked_at: datetime) -> int:
        result = await self.session.execute(
            update(AccessTokenModel)
            .where(
                AccessTokenModel.client_id == client_id,
                AccessTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)

    async def delete_older_than(self, before: datetime) -> int:
        result = await self.session.execute(
            delete(AccessTokenModel)
            .where(
                or_(
                    AccessTokenModel.expires_at < before,
                    AccessTokenModel.revoked_at < before,
                )
            )
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)
