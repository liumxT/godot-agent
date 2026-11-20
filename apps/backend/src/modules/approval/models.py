"""Approval 域模型（E4-T20）。状态权威属于 Approval System。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

APPROVAL_PENDING = "PENDING"
APPROVAL_APPROVED = "APPROVED"
APPROVAL_REJECTED = "REJECTED"
APPROVAL_EXPIRED = "EXPIRED"
APPROVAL_CANCELLED = "CANCELLED"
APPROVAL_STATUSES = frozenset(
    {APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED, APPROVAL_EXPIRED, APPROVAL_CANCELLED}
)

APPROVAL_TYPE_CHANGESET_APPLY = "CHANGESET_APPLY"
APPROVAL_TYPE_RESOURCE_MUTATION = "RESOURCE_MUTATION"
APPROVAL_TYPE_PROJECT_CONFIGURATION = "PROJECT_CONFIGURATION"
APPROVAL_TYPE_USER_ACCEPTANCE = "USER_ACCEPTANCE"
APPROVAL_TYPE_HIGH_RISK_OPERATION = "HIGH_RISK_OPERATION"
APPROVAL_TYPES = frozenset(
    {
        APPROVAL_TYPE_CHANGESET_APPLY,
        APPROVAL_TYPE_RESOURCE_MUTATION,
        APPROVAL_TYPE_PROJECT_CONFIGURATION,
        APPROVAL_TYPE_USER_ACCEPTANCE,
        APPROVAL_TYPE_HIGH_RISK_OPERATION,
    }
)

TARGET_CHANGESET = "CHANGESET"
TARGET_CHANGESET_HASH = "CHANGESET_HASH"
TARGET_WORKFLOW_PHASE = "WORKFLOW_PHASE"
TARGET_PROJECT_CONFIGURATION = "PROJECT_CONFIGURATION"
TARGET_RESOURCE_SCOPE = "RESOURCE_SCOPE"
TARGET_TOOL_REQUEST = "TOOL_REQUEST"
TARGET_TYPES = frozenset(
    {
        TARGET_CHANGESET,
        TARGET_CHANGESET_HASH,
        TARGET_WORKFLOW_PHASE,
        TARGET_PROJECT_CONFIGURATION,
        TARGET_RESOURCE_SCOPE,
        TARGET_TOOL_REQUEST,
    }
)

DECISION_APPROVE = "APPROVE"
DECISION_REJECT = "REJECT"
DECISION_CANCEL = "CANCEL"
DECISIONS = frozenset({DECISION_APPROVE, DECISION_REJECT, DECISION_CANCEL})


class ApprovalModel(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_approvals_project", "project_id", "status"),
        Index("ix_approvals_target", "target_type", "target_id"),
    )


class ApprovalDecisionModel(Base):
    __tablename__ = "approval_decisions"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    approval_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("approvals.approval_id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalAuditEventModel(Base):
    __tablename__ = "approval_audit_events"

    audit_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    approval_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("approvals.approval_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
