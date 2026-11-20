"""E3 临时项目身份实体（T14 前置）。

E4 引入正式 Registry 时按同名字段迁移，``project_id`` 保持兼容。
服务端不信任客户端提交的路径：落库前重新 realpath 并重算指纹。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base


class ProjectModel(Base):
    __tablename__ = "e3_projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_root: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    project_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    project_name: Mapped[str] = mapped_column(String(256), nullable=False)
    godot_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_e3_projects_fingerprint", "project_fingerprint"),)
