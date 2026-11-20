"""Project 域模型（E4-T01 / T04）。

E3 的 ``e3_projects`` 只承载 Editor 上报的项目身份；E4 新增业务项目表，
``project_id`` 与 ``e3_projects`` 保持一致，由 ``ProjectService`` 统一派生。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

PROJECT_INITIALIZING = "INITIALIZING"
PROJECT_ACTIVE = "ACTIVE"
PROJECT_SUSPENDED = "SUSPENDED"
PROJECT_ARCHIVED = "ARCHIVED"
PROJECT_CLOSED = "CLOSED"

PROJECT_STATUSES = frozenset(
    {PROJECT_INITIALIZING, PROJECT_ACTIVE, PROJECT_SUSPENDED, PROJECT_ARCHIVED, PROJECT_CLOSED}
)

PROJECT_TRANSITIONS: dict[str, frozenset[str]] = {
    PROJECT_INITIALIZING: frozenset({PROJECT_ACTIVE, PROJECT_CLOSED}),
    PROJECT_ACTIVE: frozenset({PROJECT_SUSPENDED, PROJECT_ARCHIVED, PROJECT_CLOSED}),
    PROJECT_SUSPENDED: frozenset({PROJECT_ACTIVE, PROJECT_ARCHIVED, PROJECT_CLOSED}),
    PROJECT_ARCHIVED: frozenset({PROJECT_ACTIVE, PROJECT_CLOSED}),
    PROJECT_CLOSED: frozenset({PROJECT_ACTIVE, PROJECT_ARCHIVED}),
}

PROJECT_TYPE_2D = "GODOT_2D"
PROJECT_TYPE_3D = "GODOT_3D"
PROJECT_TYPE_HYBRID = "GODOT_HYBRID"
PROJECT_TYPE_UNKNOWN = "GODOT_UNKNOWN"
PROJECT_TYPES = frozenset(
    {PROJECT_TYPE_2D, PROJECT_TYPE_3D, PROJECT_TYPE_HYBRID, PROJECT_TYPE_UNKNOWN}
)

MEMBER_OWNER = "owner"
MEMBER_EDITOR = "editor"
MEMBER_VIEWER = "viewer"
MEMBER_ROLES = frozenset({MEMBER_OWNER, MEMBER_EDITOR, MEMBER_VIEWER})

FINGERPRINT_ALGORITHM = "sha256-realpath"


class ProjectRecordModel(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_root: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    project_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    godot_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    configuration_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_projects_status", "status"),
        Index("ix_projects_fingerprint", "project_fingerprint"),
    )


class ProjectIdentityModel(Base):
    __tablename__ = "project_identities"

    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        primary_key=True,
    )
    fingerprint_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint_value: Mapped[str] = mapped_column(String(64), nullable=False)
    project_config_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectConfigurationModel(Base):
    __tablename__ = "project_configurations"

    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        primary_key=True,
    )
    default_game_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preferred_rendering_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_platforms: Mapped[str | None] = mapped_column(Text, nullable=True)
    godot_version_policy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_agent_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    coding_conventions: Mapped[str | None] = mapped_column(Text, nullable=True)
    naming_conventions: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectConfigurationVersionModel(Base):
    __tablename__ = "project_configuration_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "version_no", name="uq_config_version"),)


class ProjectMembershipModel(Base):
    __tablename__ = "project_memberships"

    membership_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "client_id", name="uq_project_member"),)
