"""Session 租约与项目级 Fencing 实体（E3-T08）。

租约状态：``ACTIVE → RENEWING → ACTIVE``，任一有效状态可转 ``EXPIRED`` / ``REVOKED``。
Fencing Token 按项目单调分配，旧连接不能覆盖新租约。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

LEASE_STATUS_ACTIVE = "ACTIVE"
LEASE_STATUS_RENEWING = "RENEWING"
LEASE_STATUS_EXPIRED = "EXPIRED"
LEASE_STATUS_REVOKED = "REVOKED"

LEASE_TRANSITIONS: dict[str, frozenset[str]] = {
    LEASE_STATUS_ACTIVE: frozenset(
        {LEASE_STATUS_RENEWING, LEASE_STATUS_EXPIRED, LEASE_STATUS_REVOKED}
    ),
    LEASE_STATUS_RENEWING: frozenset(
        {LEASE_STATUS_ACTIVE, LEASE_STATUS_EXPIRED, LEASE_STATUS_REVOKED}
    ),
    LEASE_STATUS_EXPIRED: frozenset(),
    LEASE_STATUS_REVOKED: frozenset(),
}


class LeaseModel(Base):
    __tablename__ = "e3_session_leases"

    lease_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e3_editor_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e3_projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_e3_session_leases_session_status", "session_id", "status"),
        Index("ix_e3_session_leases_project_status", "project_id", "status"),
    )


class ProjectFencingModel(Base):
    __tablename__ = "e3_project_fencing"

    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e3_projects.project_id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_token: Mapped[int] = mapped_column(Integer, nullable=False)
