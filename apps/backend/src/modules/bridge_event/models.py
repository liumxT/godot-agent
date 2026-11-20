"""Bridge 事件实体（E3-T10）。

事件契约见 ``packages/contracts/events/event.schema.json``；
``sequence`` 与 ``event_version`` 放在 ``payload`` 内，不新增顶层字段。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

DIRECTION_PLUGIN_TO_BACKEND = "plugin_to_backend"
DIRECTION_BACKEND_TO_PLUGIN = "backend_to_plugin"

PERSISTENCE_PERSISTENT = "PERSISTENT"
PERSISTENCE_EPHEMERAL = "EPHEMERAL"


class BridgeEventModel(Base):
    __tablename__ = "e3_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
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
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_e3_events_session_sequence", "session_id", "sequence"),
        Index("ix_e3_events_created_at", "created_at"),
    )
