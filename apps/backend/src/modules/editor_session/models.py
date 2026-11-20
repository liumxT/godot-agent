"""Editor Session 绑定实体（E3-T07）。

Session 状态的权威仍是 ``e2_sessions``；本表只记录 Editor 维度的连接绑定，
E3.md 中的 SUSPENDED 落在 ``binding_status``，不伪造 Session 状态。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

BINDING_CONNECTED = "CONNECTED"
BINDING_DISCONNECTED = "DISCONNECTED"
BINDING_RECOVERING = "RECOVERING"
BINDING_CLOSED = "CLOSED"

BINDING_TRANSITIONS: dict[str, frozenset[str]] = {
    BINDING_CONNECTED: frozenset({BINDING_DISCONNECTED, BINDING_RECOVERING, BINDING_CLOSED}),
    BINDING_DISCONNECTED: frozenset({BINDING_CONNECTED, BINDING_RECOVERING, BINDING_CLOSED}),
    BINDING_RECOVERING: frozenset({BINDING_CONNECTED, BINDING_CLOSED}),
    BINDING_CLOSED: frozenset(),
}

TRANSPORT_WEBSOCKET = "websocket"


class EditorSessionModel(Base):
    __tablename__ = "e3_editor_sessions"

    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e2_sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    editor_instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e3_projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    godot_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plugin_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transport: Mapped[str] = mapped_column(String(16), nullable=False)
    binding_status: Mapped[str] = mapped_column(String(16), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_e3_editor_sessions_project_status", "project_id", "binding_status"),
        Index("ix_e3_editor_sessions_editor_instance", "editor_instance_id"),
    )
