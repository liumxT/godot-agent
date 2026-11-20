"""Task 域模型（E4-T06 / T07 / T08 / T09 / T10 / T11）。

Task 表示用户要求完成的工作，Attempt 表示一次实际执行尝试；两者独立建模。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

TASK_CREATED = "CREATED"
TASK_READY = "READY"
TASK_QUEUED = "QUEUED"
TASK_RUNNING = "RUNNING"
TASK_PAUSING = "PAUSING"
TASK_PAUSED = "PAUSED"
TASK_RESUMING = "RESUMING"
TASK_WAITING_APPROVAL = "WAITING_APPROVAL"
TASK_WAITING_USER = "WAITING_USER"
TASK_BLOCKED = "BLOCKED"
TASK_FAILED = "FAILED"
TASK_CANCELLED = "CANCELLED"
TASK_REVIEW_PENDING = "REVIEW_PENDING"
TASK_COMPLETED = "COMPLETED"
TASK_REJECTED = "REJECTED"
TASK_NEEDS_REVISION = "NEEDS_REVISION"

TASK_STATUSES = frozenset(
    {
        TASK_CREATED,
        TASK_READY,
        TASK_QUEUED,
        TASK_RUNNING,
        TASK_PAUSING,
        TASK_PAUSED,
        TASK_RESUMING,
        TASK_WAITING_APPROVAL,
        TASK_WAITING_USER,
        TASK_BLOCKED,
        TASK_FAILED,
        TASK_CANCELLED,
        TASK_REVIEW_PENDING,
        TASK_COMPLETED,
        TASK_REJECTED,
        TASK_NEEDS_REVISION,
    }
)

TERMINAL_TASK_STATUSES = frozenset({TASK_COMPLETED, TASK_CANCELLED})

TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    TASK_CREATED: frozenset({TASK_READY, TASK_CANCELLED}),
    TASK_READY: frozenset({TASK_QUEUED, TASK_BLOCKED, TASK_CANCELLED}),
    TASK_QUEUED: frozenset({TASK_RUNNING, TASK_CANCELLED, TASK_BLOCKED}),
    TASK_RUNNING: frozenset(
        {
            TASK_PAUSING,
            TASK_WAITING_APPROVAL,
            TASK_WAITING_USER,
            TASK_BLOCKED,
            TASK_FAILED,
            TASK_REVIEW_PENDING,
            TASK_CANCELLED,
        }
    ),
    TASK_PAUSING: frozenset({TASK_PAUSED, TASK_CANCELLED, TASK_FAILED}),
    TASK_PAUSED: frozenset({TASK_RESUMING, TASK_CANCELLED}),
    TASK_RESUMING: frozenset({TASK_RUNNING, TASK_FAILED, TASK_CANCELLED}),
    TASK_WAITING_APPROVAL: frozenset({TASK_RUNNING, TASK_BLOCKED, TASK_FAILED, TASK_CANCELLED}),
    TASK_WAITING_USER: frozenset({TASK_RUNNING, TASK_CANCELLED}),
    TASK_BLOCKED: frozenset({TASK_READY, TASK_CANCELLED}),
    TASK_FAILED: frozenset({TASK_READY, TASK_CANCELLED}),
    TASK_REVIEW_PENDING: frozenset(
        {TASK_COMPLETED, TASK_NEEDS_REVISION, TASK_REJECTED, TASK_CANCELLED}
    ),
    TASK_NEEDS_REVISION: frozenset({TASK_READY, TASK_CANCELLED}),
    TASK_REJECTED: frozenset({TASK_NEEDS_REVISION, TASK_CANCELLED}),
    TASK_COMPLETED: frozenset(),
    TASK_CANCELLED: frozenset(),
}

TASK_TYPE_GAME_DEVELOPMENT = "GAME_DEVELOPMENT"
TASK_TYPE_BUG_FIX = "BUG_FIX"
TASK_TYPE_REFACTORING = "REFACTORING"
TASK_TYPE_ASSET_CREATION = "ASSET_CREATION"
TASK_TYPE_LEVEL_DESIGN = "LEVEL_DESIGN"
TASK_TYPE_UI_DEVELOPMENT = "UI_DEVELOPMENT"
TASK_TYPE_TESTING = "TESTING"
TASK_TYPE_OPTIMIZATION = "OPTIMIZATION"
TASK_TYPE_RESEARCH = "RESEARCH"
TASK_TYPE_GENERAL = "GENERAL"
TASK_TYPES = frozenset(
    {
        TASK_TYPE_GAME_DEVELOPMENT,
        TASK_TYPE_BUG_FIX,
        TASK_TYPE_REFACTORING,
        TASK_TYPE_ASSET_CREATION,
        TASK_TYPE_LEVEL_DESIGN,
        TASK_TYPE_UI_DEVELOPMENT,
        TASK_TYPE_TESTING,
        TASK_TYPE_OPTIMIZATION,
        TASK_TYPE_RESEARCH,
        TASK_TYPE_GENERAL,
    }
)

PRIORITY_LOW = "LOW"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_HIGH = "HIGH"
PRIORITY_CRITICAL = "CRITICAL"
PRIORITIES = frozenset({PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH, PRIORITY_CRITICAL})

ATTEMPT_CREATED = "CREATED"
ATTEMPT_STARTING = "STARTING"
ATTEMPT_RUNNING = "RUNNING"
ATTEMPT_SUCCEEDED = "SUCCEEDED"
ATTEMPT_FAILED = "FAILED"
ATTEMPT_CANCELLED = "CANCELLED"
ATTEMPT_INTERRUPTED = "INTERRUPTED"
ATTEMPT_UNKNOWN = "UNKNOWN"
ATTEMPT_STATUSES = frozenset(
    {
        ATTEMPT_CREATED,
        ATTEMPT_STARTING,
        ATTEMPT_RUNNING,
        ATTEMPT_SUCCEEDED,
        ATTEMPT_FAILED,
        ATTEMPT_CANCELLED,
        ATTEMPT_INTERRUPTED,
        ATTEMPT_UNKNOWN,
    }
)

ATTEMPT_TRANSITIONS: dict[str, frozenset[str]] = {
    ATTEMPT_CREATED: frozenset({ATTEMPT_STARTING, ATTEMPT_CANCELLED}),
    ATTEMPT_STARTING: frozenset({ATTEMPT_RUNNING, ATTEMPT_FAILED, ATTEMPT_CANCELLED}),
    ATTEMPT_RUNNING: frozenset(
        {
            ATTEMPT_SUCCEEDED,
            ATTEMPT_FAILED,
            ATTEMPT_CANCELLED,
            ATTEMPT_INTERRUPTED,
            ATTEMPT_UNKNOWN,
        }
    ),
    ATTEMPT_SUCCEEDED: frozenset(),
    ATTEMPT_FAILED: frozenset(),
    ATTEMPT_CANCELLED: frozenset(),
    ATTEMPT_INTERRUPTED: frozenset({ATTEMPT_UNKNOWN}),
    ATTEMPT_UNKNOWN: frozenset(),
}

DEPENDENCY_FINISH_TO_START = "FINISH_TO_START"
DEPENDENCY_START_TO_START = "START_TO_START"
DEPENDENCY_FINISH_TO_FINISH = "FINISH_TO_FINISH"
DEPENDENCY_BLOCKS = "BLOCKS"
DEPENDENCY_RELATED = "RELATED"
DEPENDENCY_TYPES = frozenset(
    {
        DEPENDENCY_FINISH_TO_START,
        DEPENDENCY_START_TO_START,
        DEPENDENCY_FINISH_TO_FINISH,
        DEPENDENCY_BLOCKS,
        DEPENDENCY_RELATED,
    }
)
DEPENDENCY_ACTIVE = "ACTIVE"
DEPENDENCY_RESOLVED = "RESOLVED"
DEPENDENCY_REMOVED = "REMOVED"

CHECKPOINT_EXECUTION_STARTED = "EXECUTION_STARTED"
CHECKPOINT_PHASE_COMPLETED = "PHASE_COMPLETED"
CHECKPOINT_WAITING_APPROVAL = "WAITING_APPROVAL"
CHECKPOINT_SAFE_PAUSE = "SAFE_PAUSE"
CHECKPOINT_RECOVERY_POINT = "RECOVERY_POINT"
CHECKPOINT_EXECUTION_INTERRUPTED = "EXECUTION_INTERRUPTED"
CHECKPOINT_TYPES = frozenset(
    {
        CHECKPOINT_EXECUTION_STARTED,
        CHECKPOINT_PHASE_COMPLETED,
        CHECKPOINT_WAITING_APPROVAL,
        CHECKPOINT_SAFE_PAUSE,
        CHECKPOINT_RECOVERY_POINT,
        CHECKPOINT_EXECUTION_INTERRUPTED,
    }
)

ACTOR_USER = "USER"
ACTOR_AGENT = "AGENT"
ACTOR_SYSTEM = "SYSTEM"
ACTOR_WORKFLOW = "WORKFLOW"
ACTOR_TYPES = frozenset({ACTOR_USER, ACTOR_AGENT, ACTOR_SYSTEM, ACTOR_WORKFLOW})


class TaskModel(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    parent_task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requirement_set_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_parent", "parent_task_id"),
    )


class TaskAttemptModel(Base):
    __tablename__ = "task_attempts"

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_usage: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_attempt_number"),
        Index("ix_task_attempts_task", "task_id", "status"),
    )


class TaskDependencyModel(Base):
    __tablename__ = "task_dependencies"

    dependency_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    target_task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    dependency_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_task_id", "target_task_id", name="uq_task_dependency"),
    )


class TaskCheckpointModel(Base):
    __tablename__ = "task_checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("task_attempts.attempt_id", ondelete="SET NULL"), nullable=True
    )
    checkpoint_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_state_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    changeset_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_checkpoint_sequence"),)


class TaskEventModel(Base):
    __tablename__ = "task_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_task_event_sequence"),
        Index("ix_task_events_task", "task_id", "sequence"),
    )
