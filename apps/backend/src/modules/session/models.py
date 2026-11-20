"""Session 领域实体（E2-T05）。

数据库只保存 Session Token 的 SHA-256 摘要；明文仅在创建/续期响应中出现。
状态机：``CREATED → ACTIVE → (EXPIRED | REVOKED | CLOSED)``。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

SESSION_STATUS_CREATED = "CREATED"
SESSION_STATUS_ACTIVE = "ACTIVE"
SESSION_STATUS_EXPIRED = "EXPIRED"
SESSION_STATUS_REVOKED = "REVOKED"
SESSION_STATUS_CLOSED = "CLOSED"

SESSION_TRANSITIONS: dict[str, frozenset[str]] = {
    SESSION_STATUS_CREATED: frozenset({SESSION_STATUS_ACTIVE}),
    SESSION_STATUS_ACTIVE: frozenset(
        {SESSION_STATUS_EXPIRED, SESSION_STATUS_REVOKED, SESSION_STATUS_CLOSED}
    ),
    SESSION_STATUS_EXPIRED: frozenset(),
    SESSION_STATUS_REVOKED: frozenset(),
    SESSION_STATUS_CLOSED: frozenset(),
}


class SessionModel(Base):
    __tablename__ = "e2_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e2_clients.client_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SESSION_STATUS_ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_e2_sessions_client_id", "client_id"),
        Index("ix_e2_sessions_status", "status"),
    )
