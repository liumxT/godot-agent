"""Project Access 实体（E2-T07）。

访问关系同时绑定 ``client_id`` 与 ``session_id``：Session 有效不代表拥有项目访问，
项目 ID 必须由服务端记录校验，客户端提交的 ID 一律视为不可信输入。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

ACCESS_LEVELS = frozenset({"owner", "editor", "viewer"})

ACCESS_STATUS_ACTIVE = "ACTIVE"
ACCESS_STATUS_REVOKED = "REVOKED"
ACCESS_STATUS_EXPIRED = "EXPIRED"


class ProjectAccessModel(Base):
    __tablename__ = "e2_project_access"

    access_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e2_clients.client_id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e2_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    access_level: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ACCESS_STATUS_ACTIVE)

    __table_args__ = (
        Index("ix_e2_project_access_client_project_status", "client_id", "project_id", "status"),
        Index("ix_e2_project_access_session_id", "session_id"),
    )
