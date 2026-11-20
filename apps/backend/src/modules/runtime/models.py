"""Runtime 实例实体（E3-T16）。

Runtime 是独立通道，不与 Editor 状态混用；本表只记录实例生命周期。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

RUNTIME_RUNNING = "RUNNING"
RUNTIME_STOPPED = "STOPPED"
RUNTIME_CRASHED = "CRASHED"
RUNTIME_ENDED = "ENDED"


class RuntimeInstanceModel(Base):
    __tablename__ = "e3_runtime_instances"

    runtime_instance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("e3_projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    editor_session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("e3_editor_sessions.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    godot_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    build_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_e3_runtime_instances_project_status", "project_id", "status"),
        Index("ix_e3_runtime_instances_status", "status"),
    )
