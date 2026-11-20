"""Workflow 域模型（E4-T12…T17 / T21）。

Workflow 状态、Node 状态与 Phase 状态只能由 Workflow Engine 修改。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

DEFINITION_DRAFT = "DRAFT"
DEFINITION_ACTIVE = "ACTIVE"
DEFINITION_DEPRECATED = "DEPRECATED"
DEFINITION_STATUSES = frozenset({DEFINITION_DRAFT, DEFINITION_ACTIVE, DEFINITION_DEPRECATED})

INSTANCE_CREATED = "CREATED"
INSTANCE_READY = "READY"
INSTANCE_RUNNING = "RUNNING"
INSTANCE_PAUSING = "PAUSING"
INSTANCE_PAUSED = "PAUSED"
INSTANCE_RESUMING = "RESUMING"
INSTANCE_WAITING_APPROVAL = "WAITING_APPROVAL"
INSTANCE_WAITING_USER = "WAITING_USER"
INSTANCE_BLOCKED = "BLOCKED"
INSTANCE_FAILED = "FAILED"
INSTANCE_CANCELLED = "CANCELLED"
INSTANCE_COMPLETED = "COMPLETED"

INSTANCE_TRANSITIONS: dict[str, frozenset[str]] = {
    INSTANCE_CREATED: frozenset({INSTANCE_READY, INSTANCE_CANCELLED}),
    INSTANCE_READY: frozenset({INSTANCE_RUNNING, INSTANCE_CANCELLED, INSTANCE_BLOCKED}),
    INSTANCE_RUNNING: frozenset(
        {
            INSTANCE_PAUSING,
            INSTANCE_WAITING_APPROVAL,
            INSTANCE_WAITING_USER,
            INSTANCE_BLOCKED,
            INSTANCE_FAILED,
            INSTANCE_COMPLETED,
            INSTANCE_CANCELLED,
        }
    ),
    INSTANCE_PAUSING: frozenset({INSTANCE_PAUSED, INSTANCE_FAILED, INSTANCE_CANCELLED}),
    INSTANCE_PAUSED: frozenset({INSTANCE_RESUMING, INSTANCE_CANCELLED}),
    INSTANCE_RESUMING: frozenset({INSTANCE_RUNNING, INSTANCE_FAILED, INSTANCE_CANCELLED}),
    INSTANCE_WAITING_APPROVAL: frozenset(
        {INSTANCE_RUNNING, INSTANCE_BLOCKED, INSTANCE_FAILED, INSTANCE_CANCELLED}
    ),
    INSTANCE_WAITING_USER: frozenset({INSTANCE_RUNNING, INSTANCE_CANCELLED}),
    INSTANCE_BLOCKED: frozenset({INSTANCE_READY, INSTANCE_RUNNING, INSTANCE_CANCELLED}),
    INSTANCE_FAILED: frozenset({INSTANCE_READY, INSTANCE_CANCELLED}),
    INSTANCE_COMPLETED: frozenset(),
    INSTANCE_CANCELLED: frozenset(),
}

NODE_PENDING = "PENDING"
NODE_READY = "READY"
NODE_RUNNING = "RUNNING"
NODE_SUCCEEDED = "SUCCEEDED"
NODE_FAILED = "FAILED"
NODE_SKIPPED = "SKIPPED"
NODE_CANCELLED = "CANCELLED"
NODE_STATUSES = frozenset(
    {
        NODE_PENDING,
        NODE_READY,
        NODE_RUNNING,
        NODE_SUCCEEDED,
        NODE_FAILED,
        NODE_SKIPPED,
        NODE_CANCELLED,
    }
)

PHASE_PENDING = "PENDING"
PHASE_READY = "READY"
PHASE_IN_PROGRESS = "IN_PROGRESS"
PHASE_REVIEW_PENDING = "REVIEW_PENDING"
PHASE_ACCEPTED = "ACCEPTED"
PHASE_NEEDS_REVISION = "NEEDS_REVISION"
PHASE_STATUSES = frozenset(
    {
        PHASE_PENDING,
        PHASE_READY,
        PHASE_IN_PROGRESS,
        PHASE_REVIEW_PENDING,
        PHASE_ACCEPTED,
        PHASE_NEEDS_REVISION,
    }
)

REVIEW_DRAFT = "DRAFT"
REVIEW_SUBMITTED = "SUBMITTED"
REVIEW_ACCEPTED = "ACCEPTED"
REVIEW_NEEDS_REVISION = "NEEDS_REVISION"
REVIEW_STATUSES = frozenset(
    {REVIEW_DRAFT, REVIEW_SUBMITTED, REVIEW_ACCEPTED, REVIEW_NEEDS_REVISION}
)

NODE_TYPE_TASK = "TASK"
NODE_TYPE_AI_EXECUTION = "AI_EXECUTION"
NODE_TYPE_TOOL_OPERATION = "TOOL_OPERATION"
NODE_TYPE_APPROVAL = "APPROVAL"
NODE_TYPE_USER_CONFIRMATION = "USER_CONFIRMATION"
NODE_TYPE_VERIFICATION = "VERIFICATION"
NODE_TYPE_PARALLEL = "PARALLEL"
NODE_TYPE_SUB_WORKFLOW = "SUB_WORKFLOW"
NODE_TYPES = frozenset(
    {
        NODE_TYPE_TASK,
        NODE_TYPE_AI_EXECUTION,
        NODE_TYPE_TOOL_OPERATION,
        NODE_TYPE_APPROVAL,
        NODE_TYPE_USER_CONFIRMATION,
        NODE_TYPE_VERIFICATION,
        NODE_TYPE_PARALLEL,
        NODE_TYPE_SUB_WORKFLOW,
    }
)


class WorkflowDefinitionModel(Base):
    __tablename__ = "workflow_definitions"

    definition_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowDefinitionVersionModel(Base):
    __tablename__ = "workflow_definition_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    definition_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_definitions.definition_id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("definition_id", "version", name="uq_workflow_version"),)


class WorkflowNodeDefinitionModel(Base):
    __tablename__ = "workflow_node_definitions"

    node_definition_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_definition_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    )
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_node_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    dependency_keys: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (UniqueConstraint("version_id", "node_key", name="uq_node_definition_key"),)


class WorkflowInstanceModel(Base):
    __tablename__ = "workflow_instances"

    instance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    definition_id: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_phase_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_workflow_instances_project", "project_id", "status"),)


class WorkflowNodeInstanceModel(Base):
    __tablename__ = "workflow_node_instances"

    node_instance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
    )
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    phase_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        UniqueConstraint("workflow_instance_id", "node_key", name="uq_node_instance_key"),
    )


class WorkflowPhaseModel(Base):
    __tablename__ = "workflow_phases"

    phase_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    entry_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("workflow_instance_id", "phase_key", name="uq_workflow_phase_key"),
    )


class WorkflowPhaseReviewModel(Base):
    __tablename__ = "workflow_phase_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workflow_phases.phase_id", ondelete="CASCADE"), nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    deliverables: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
