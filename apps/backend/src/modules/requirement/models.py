"""Requirement Tracking 模型（E4-T18）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

REQUIREMENT_DRAFT = "DRAFT"
REQUIREMENT_ACTIVE = "ACTIVE"
REQUIREMENT_IMPLEMENTED = "IMPLEMENTED"
REQUIREMENT_VERIFIED = "VERIFIED"
REQUIREMENT_REJECTED = "REJECTED"
REQUIREMENT_DEFERRED = "DEFERRED"
REQUIREMENT_STATUSES = frozenset(
    {
        REQUIREMENT_DRAFT,
        REQUIREMENT_ACTIVE,
        REQUIREMENT_IMPLEMENTED,
        REQUIREMENT_VERIFIED,
        REQUIREMENT_REJECTED,
        REQUIREMENT_DEFERRED,
    }
)

CATEGORY_FUNCTIONAL = "FUNCTIONAL"
CATEGORY_NON_FUNCTIONAL = "NON_FUNCTIONAL"
CATEGORY_CONSTRAINT = "CONSTRAINT"
CATEGORY_ASSET = "ASSET"
REQUIREMENT_CATEGORIES = frozenset(
    {CATEGORY_FUNCTIONAL, CATEGORY_NON_FUNCTIONAL, CATEGORY_CONSTRAINT, CATEGORY_ASSET}
)

CRITERION_PENDING = "PENDING"
CRITERION_MET = "MET"
CRITERION_NOT_MET = "NOT_MET"
CRITERION_WAIVED = "WAIVED"
CRITERION_STATUSES = frozenset(
    {CRITERION_PENDING, CRITERION_MET, CRITERION_NOT_MET, CRITERION_WAIVED}
)


class RequirementModel(Base):
    __tablename__ = "requirements"

    requirement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    requirement_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "requirement_key", name="uq_requirement_key"),)


class AcceptanceCriterionModel(Base):
    __tablename__ = "acceptance_criteria"

    criterion_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("requirements.requirement_id", ondelete="CASCADE"), nullable=False
    )
    criterion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    verification_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    required_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (UniqueConstraint("requirement_id", "criterion_key", name="uq_criterion_key"),)


class RequirementTraceModel(Base):
    __tablename__ = "requirement_traces"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("requirements.requirement_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phase_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_result_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
