"""Client 领域实体（E2-T06 / T04）。

数据库只保存客户端元数据、凭证状态与 Token 摘要；
客户端 Secret 与 Token 明文分别存放在 keyring 与响应中。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

CLIENT_STATUS_ACTIVE = "active"
CLIENT_STATUS_REVOKED = "revoked"

CREDENTIAL_TYPE_CLIENT_SECRET = "client_secret"
CREDENTIAL_STATUS_ACTIVE = "active"
CREDENTIAL_STATUS_REVOKED = "revoked"


class ClientModel(Base):
    __tablename__ = "e2_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_type: Mapped[str] = mapped_column(String(32), nullable=False)
    client_name: Mapped[str] = mapped_column(String(128), nullable=False)
    client_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    godot_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=CLIENT_STATUS_ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_e2_clients_status", "status"),)


class ClientCredentialModel(Base):
    __tablename__ = "e2_client_credentials"

    credential_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e2_clients.client_id", ondelete="CASCADE"),
        nullable=False,
    )
    credential_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_e2_client_credentials_client_id", "client_id"),)


class AccessTokenModel(Base):
    __tablename__ = "e2_access_tokens"

    token_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e2_clients.client_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_e2_access_tokens_client_id", "client_id"),)
