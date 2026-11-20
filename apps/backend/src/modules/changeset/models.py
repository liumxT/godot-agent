"""ChangeSet 域模型（E4-T19）。状态权威属于 ChangeSet Manager。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

CHANGESET_DRAFT = "DRAFT"
CHANGESET_VALIDATING = "VALIDATING"
CHANGESET_READY = "READY_FOR_APPROVAL"
CHANGESET_APPROVED = "APPROVED"
CHANGESET_APPLYING = "APPLYING"
CHANGESET_APPLIED = "APPLIED"
CHANGESET_FAILED = "FAILED"
CHANGESET_UNKNOWN = "UNKNOWN"
CHANGESET_REJECTED = "REJECTED"
CHANGESET_CANCELLED = "CANCELLED"
CHANGESET_SUPERSEDED = "SUPERSEDED"
CHANGESET_STATUSES = frozenset(
    {
        CHANGESET_DRAFT,
        CHANGESET_VALIDATING,
        CHANGESET_READY,
        CHANGESET_APPROVED,
        CHANGESET_APPLYING,
        CHANGESET_APPLIED,
        CHANGESET_FAILED,
        CHANGESET_UNKNOWN,
        CHANGESET_REJECTED,
        CHANGESET_CANCELLED,
        CHANGESET_SUPERSEDED,
    }
)

OPERATION_CREATE = "CREATE"
OPERATION_UPDATE = "UPDATE"
OPERATION_DELETE = "DELETE"
OPERATION_MOVE = "MOVE"
OPERATION_COPY = "COPY"
OPERATION_TYPES = frozenset(
    {OPERATION_CREATE, OPERATION_UPDATE, OPERATION_DELETE, OPERATION_MOVE, OPERATION_COPY}
)

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_CRITICAL = "CRITICAL"
RISK_LEVELS = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL})

VALIDATION_VALID = "VALID"
VALIDATION_INVALID = "INVALID"
VALIDATION_PENDING = "PENDING"
VALIDATION_SKIPPED = "SKIPPED"


class ChangeSetModel(Base):
    __tablename__ = "change_sets"

    changeset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_change_sets_project", "project_id", "status"),)


class ChangeSetVersionModel(Base):
    __tablename__ = "change_set_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    changeset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("change_sets.changeset_id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("changeset_id", "version_no", name="uq_changeset_version"),)


class ChangeManifestItemModel(Base):
    __tablename__ = "change_manifest_items"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    changeset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("change_sets.changeset_id", ondelete="CASCADE"), nullable=False
    )
    resource_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    old_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (Index("ix_change_manifest_changeset", "changeset_id"),)


class ChangeSetValidationResultModel(Base):
    __tablename__ = "change_set_validation_results"

    result_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    changeset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("change_sets.changeset_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
