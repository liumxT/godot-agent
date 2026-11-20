"""编辑器快照实体（E3-T11）。

只保存摘要，不包含资源内容；``payload`` 为通过契约校验的完整快照。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base


class SnapshotModel(Base):
    __tablename__ = "e3_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
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
    editor_instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(nullable=False)
    last_event_sequence: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "snapshot_version",
            name="uq_e3_snapshots_session_version",
        ),
        Index("ix_e3_snapshots_session_created", "session_id", "created_at"),
    )
