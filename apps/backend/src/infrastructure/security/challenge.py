"""认证挑战存储与一次性消费（E2-T03）。

挑战值本身不是凭证：即使数据库泄漏，缺少客户端 Secret 也无法生成 proof。
因此持久化原始 nonce 以便服务端重算 HMAC；``used_at`` 保证一次性。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

CHALLENGE_STATUS_ISSUED = "issued"
CHALLENGE_STATUS_USED = "used"


class AuthChallengeModel(Base):
    __tablename__ = "e2_auth_challenges"

    challenge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e2_clients.client_id", ondelete="CASCADE"),
        nullable=False,
    )
    challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_e2_auth_challenges_client_status", "client_id", "status"),)


class ChallengeStore:
    """挑战的创建、读取与原子标记已使用。"""

    async def create(
        self,
        session: AsyncSession,
        *,
        challenge_id: str,
        client_id: str,
        challenge: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> AuthChallengeModel:
        entity = AuthChallengeModel(
            challenge_id=challenge_id,
            client_id=client_id,
            challenge=challenge,
            status=CHALLENGE_STATUS_ISSUED,
            created_at=created_at,
            expires_at=expires_at,
            used_at=None,
        )
        session.add(entity)
        await session.flush()
        return entity

    async def get(self, session: AsyncSession, challenge_id: str) -> AuthChallengeModel | None:
        return await session.get(AuthChallengeModel, challenge_id)

    async def consume(self, session: AsyncSession, challenge_id: str, now: datetime) -> bool:
        """仅当未使用且未过期时成功；返回是否抢占成功（防重放）。"""

        result = await session.execute(
            update(AuthChallengeModel)
            .where(
                AuthChallengeModel.challenge_id == challenge_id,
                AuthChallengeModel.status == CHALLENGE_STATUS_ISSUED,
                AuthChallengeModel.used_at.is_(None),
                AuthChallengeModel.expires_at > now,
            )
            .values(status=CHALLENGE_STATUS_USED, used_at=now)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)

    async def delete_expired(self, session: AsyncSession, before: datetime) -> int:
        from sqlalchemy import delete

        result = await session.execute(
            delete(AuthChallengeModel)
            .where(AuthChallengeModel.expires_at < before)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)

    async def list_for_client(
        self, session: AsyncSession, client_id: str
    ) -> list[AuthChallengeModel]:
        rows = await session.scalars(
            select(AuthChallengeModel).where(AuthChallengeModel.client_id == client_id)
        )
        return list(rows)
