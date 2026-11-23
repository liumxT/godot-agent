"""Multi-Agent 领域模型（E7-T01）。

状态所有权：

- Team / Assignment / Handoff / Collaboration / Conflict / Integration 只由
  ``multi_agent`` 模块修改；
- Task / Attempt 由 Task System 拥有，Workflow 由 Workflow Engine 拥有，
  Agent Instance / Execution 由 Agent Runtime 拥有，本模块只保存引用；
- Event、Message 采用追加式设计，不通过删除记录隐藏失败。

约束：

- Assignment 必须绑定 Team、Task 与 Attempt，且一个 Assignment 只有一个当前负责人；
- Team 状态不能替代 Task 状态；
- Capability 只表示能力，权限仍由 Permission System 判定。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base
from modules.tool.models import TOOL_RISK_LEVELS

# ---- 状态与枚举 ----

TEAM_CREATED = "CREATED"
TEAM_INITIALIZING = "INITIALIZING"
TEAM_READY = "READY"
TEAM_RUNNING = "RUNNING"
TEAM_WAITING = "WAITING"
TEAM_INTEGRATING = "INTEGRATING"
TEAM_VERIFYING = "VERIFYING"
TEAM_COMPLETED = "COMPLETED"
TEAM_FAILED = "FAILED"
TEAM_CANCELLED = "CANCELLED"
TEAM_UNKNOWN = "UNKNOWN"

TEAM_STATUSES = frozenset(
    {
        TEAM_CREATED,
        TEAM_INITIALIZING,
        TEAM_READY,
        TEAM_RUNNING,
        TEAM_WAITING,
        TEAM_INTEGRATING,
        TEAM_VERIFYING,
        TEAM_COMPLETED,
        TEAM_FAILED,
        TEAM_CANCELLED,
        TEAM_UNKNOWN,
    }
)
TEAM_TERMINAL_STATUSES = frozenset({TEAM_COMPLETED, TEAM_FAILED, TEAM_CANCELLED})
TEAM_TRANSITIONS: dict[str, frozenset[str]] = {
    TEAM_CREATED: frozenset({TEAM_INITIALIZING, TEAM_CANCELLED, TEAM_FAILED}),
    TEAM_INITIALIZING: frozenset({TEAM_READY, TEAM_FAILED, TEAM_CANCELLED}),
    TEAM_READY: frozenset({TEAM_RUNNING, TEAM_COMPLETED, TEAM_CANCELLED, TEAM_FAILED}),
    TEAM_RUNNING: frozenset(
        {TEAM_WAITING, TEAM_INTEGRATING, TEAM_FAILED, TEAM_CANCELLED, TEAM_UNKNOWN}
    ),
    TEAM_WAITING: frozenset({TEAM_RUNNING, TEAM_CANCELLED, TEAM_FAILED, TEAM_UNKNOWN}),
    TEAM_INTEGRATING: frozenset({TEAM_VERIFYING, TEAM_FAILED, TEAM_CANCELLED, TEAM_UNKNOWN}),
    TEAM_VERIFYING: frozenset({TEAM_COMPLETED, TEAM_FAILED, TEAM_CANCELLED, TEAM_UNKNOWN}),
    TEAM_COMPLETED: frozenset(),
    TEAM_FAILED: frozenset(),
    TEAM_CANCELLED: frozenset(),
    TEAM_UNKNOWN: frozenset({TEAM_FAILED, TEAM_CANCELLED, TEAM_READY}),
}

ASSIGNMENT_CREATED = "CREATED"
ASSIGNMENT_READY = "READY"
ASSIGNMENT_ASSIGNED = "ASSIGNED"
ASSIGNMENT_STARTING = "STARTING"
ASSIGNMENT_RUNNING = "RUNNING"
ASSIGNMENT_WAITING = "WAITING"
ASSIGNMENT_HANDOFF_PENDING = "HANDOFF_PENDING"
ASSIGNMENT_INTEGRATING = "INTEGRATING"
ASSIGNMENT_COMPLETED = "COMPLETED"
ASSIGNMENT_FAILED = "FAILED"
ASSIGNMENT_CANCELLED = "CANCELLED"
ASSIGNMENT_BLOCKED = "BLOCKED"
ASSIGNMENT_UNKNOWN = "UNKNOWN"

ASSIGNMENT_STATUSES = frozenset(
    {
        ASSIGNMENT_CREATED,
        ASSIGNMENT_READY,
        ASSIGNMENT_ASSIGNED,
        ASSIGNMENT_STARTING,
        ASSIGNMENT_RUNNING,
        ASSIGNMENT_WAITING,
        ASSIGNMENT_HANDOFF_PENDING,
        ASSIGNMENT_INTEGRATING,
        ASSIGNMENT_COMPLETED,
        ASSIGNMENT_FAILED,
        ASSIGNMENT_CANCELLED,
        ASSIGNMENT_BLOCKED,
        ASSIGNMENT_UNKNOWN,
    }
)
ASSIGNMENT_TERMINAL_STATUSES = frozenset(
    {ASSIGNMENT_COMPLETED, ASSIGNMENT_FAILED, ASSIGNMENT_CANCELLED}
)
ASSIGNMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    ASSIGNMENT_CREATED: frozenset(
        {ASSIGNMENT_READY, ASSIGNMENT_BLOCKED, ASSIGNMENT_CANCELLED, ASSIGNMENT_FAILED}
    ),
    ASSIGNMENT_READY: frozenset(
        {ASSIGNMENT_ASSIGNED, ASSIGNMENT_BLOCKED, ASSIGNMENT_CANCELLED, ASSIGNMENT_FAILED}
    ),
    ASSIGNMENT_ASSIGNED: frozenset(
        {ASSIGNMENT_STARTING, ASSIGNMENT_FAILED, ASSIGNMENT_CANCELLED}
    ),
    ASSIGNMENT_STARTING: frozenset(
        {ASSIGNMENT_RUNNING, ASSIGNMENT_FAILED, ASSIGNMENT_CANCELLED, ASSIGNMENT_UNKNOWN}
    ),
    ASSIGNMENT_RUNNING: frozenset(
        {
            ASSIGNMENT_WAITING,
            ASSIGNMENT_HANDOFF_PENDING,
            ASSIGNMENT_INTEGRATING,
            ASSIGNMENT_COMPLETED,
            ASSIGNMENT_FAILED,
            ASSIGNMENT_CANCELLED,
            ASSIGNMENT_UNKNOWN,
        }
    ),
    ASSIGNMENT_WAITING: frozenset(
        {ASSIGNMENT_RUNNING, ASSIGNMENT_FAILED, ASSIGNMENT_CANCELLED, ASSIGNMENT_UNKNOWN}
    ),
    ASSIGNMENT_HANDOFF_PENDING: frozenset(
        {ASSIGNMENT_COMPLETED, ASSIGNMENT_FAILED, ASSIGNMENT_CANCELLED}
    ),
    ASSIGNMENT_INTEGRATING: frozenset(
        {ASSIGNMENT_COMPLETED, ASSIGNMENT_FAILED, ASSIGNMENT_CANCELLED, ASSIGNMENT_UNKNOWN}
    ),
    ASSIGNMENT_COMPLETED: frozenset(),
    ASSIGNMENT_FAILED: frozenset(),
    ASSIGNMENT_CANCELLED: frozenset(),
    ASSIGNMENT_BLOCKED: frozenset(
        {ASSIGNMENT_READY, ASSIGNMENT_CANCELLED, ASSIGNMENT_FAILED}
    ),
    ASSIGNMENT_UNKNOWN: frozenset(
        {ASSIGNMENT_FAILED, ASSIGNMENT_CANCELLED, ASSIGNMENT_COMPLETED}
    ),
}

HANDOFF_REQUESTED = "REQUESTED"
HANDOFF_VALIDATING = "VALIDATING"
HANDOFF_APPROVED = "APPROVED"
HANDOFF_REJECTED = "REJECTED"
HANDOFF_EXECUTING = "EXECUTING"
HANDOFF_COMPLETED = "COMPLETED"
HANDOFF_FAILED = "FAILED"
HANDOFF_CANCELLED = "CANCELLED"

HANDOFF_STATUSES = frozenset(
    {
        HANDOFF_REQUESTED,
        HANDOFF_VALIDATING,
        HANDOFF_APPROVED,
        HANDOFF_REJECTED,
        HANDOFF_EXECUTING,
        HANDOFF_COMPLETED,
        HANDOFF_FAILED,
        HANDOFF_CANCELLED,
    }
)
HANDOFF_TERMINAL_STATUSES = frozenset({HANDOFF_COMPLETED, HANDOFF_REJECTED, HANDOFF_CANCELLED})

HANDOFF_TRANSITIONS: dict[str, frozenset[str]] = {
    HANDOFF_REQUESTED: frozenset({HANDOFF_VALIDATING, HANDOFF_REJECTED, HANDOFF_CANCELLED}),
    HANDOFF_VALIDATING: frozenset(
        {HANDOFF_APPROVED, HANDOFF_REJECTED, HANDOFF_FAILED, HANDOFF_CANCELLED}
    ),
    HANDOFF_APPROVED: frozenset({HANDOFF_EXECUTING, HANDOFF_FAILED, HANDOFF_CANCELLED}),
    HANDOFF_EXECUTING: frozenset({HANDOFF_COMPLETED, HANDOFF_FAILED}),
    HANDOFF_COMPLETED: frozenset(),
    HANDOFF_REJECTED: frozenset(),
    HANDOFF_FAILED: frozenset(),
    HANDOFF_CANCELLED: frozenset(),
}

HANDOFF_ROLE = "ROLE_HANDOFF"
HANDOFF_TASK = "TASK_HANDOFF"
HANDOFF_REVIEW = "REVIEW_HANDOFF"
HANDOFF_INTEGRATION = "INTEGRATION_HANDOFF"
HANDOFF_FAILURE = "FAILURE_HANDOFF"
HANDOFF_TYPES = frozenset(
    {HANDOFF_ROLE, HANDOFF_TASK, HANDOFF_REVIEW, HANDOFF_INTEGRATION, HANDOFF_FAILURE}
)

COLLABORATION_ACTIVE = "ACTIVE"
COLLABORATION_WAITING = "WAITING"
COLLABORATION_COMPLETED = "COMPLETED"
COLLABORATION_FAILED = "FAILED"
COLLABORATION_CANCELLED = "CANCELLED"
COLLABORATION_STATUSES = frozenset(
    {
        COLLABORATION_ACTIVE,
        COLLABORATION_WAITING,
        COLLABORATION_COMPLETED,
        COLLABORATION_FAILED,
        COLLABORATION_CANCELLED,
    }
)

MESSAGE_TASK_UPDATE = "TASK_UPDATE"
MESSAGE_PROGRESS_REPORT = "PROGRESS_REPORT"
MESSAGE_RESULT_SUBMISSION = "RESULT_SUBMISSION"
MESSAGE_HANDOFF_REQUEST = "HANDOFF_REQUEST"
MESSAGE_REVIEW_REQUEST = "REVIEW_REQUEST"
MESSAGE_REVIEW_RESULT = "REVIEW_RESULT"
MESSAGE_CONFLICT_REPORT = "CONFLICT_REPORT"
MESSAGE_BLOCKED_REPORT = "BLOCKED_REPORT"
MESSAGE_INTEGRATION_REQUEST = "INTEGRATION_REQUEST"
MESSAGE_TYPES = frozenset(
    {
        MESSAGE_TASK_UPDATE,
        MESSAGE_PROGRESS_REPORT,
        MESSAGE_RESULT_SUBMISSION,
        MESSAGE_HANDOFF_REQUEST,
        MESSAGE_REVIEW_REQUEST,
        MESSAGE_REVIEW_RESULT,
        MESSAGE_CONFLICT_REPORT,
        MESSAGE_BLOCKED_REPORT,
        MESSAGE_INTEGRATION_REQUEST,
    }
)

CONFLICT_DETECTED = "DETECTED"
CONFLICT_ANALYZING = "ANALYZING"
CONFLICT_RESOLVING = "RESOLVING"
CONFLICT_RESOLVED = "RESOLVED"
CONFLICT_ESCALATED = "ESCALATED"
CONFLICT_DISMISSED = "DISMISSED"
CONFLICT_STATUSES = frozenset(
    {
        CONFLICT_DETECTED,
        CONFLICT_ANALYZING,
        CONFLICT_RESOLVING,
        CONFLICT_RESOLVED,
        CONFLICT_ESCALATED,
        CONFLICT_DISMISSED,
    }
)

SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"
CONFLICT_SEVERITIES = frozenset({SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH})

INTEGRATION_PENDING = "PENDING"
INTEGRATION_PLANNING = "PLANNING"
INTEGRATION_READY = "READY"
INTEGRATION_APPLYING = "APPLYING"
INTEGRATION_VERIFYING = "VERIFYING"
INTEGRATION_COMPLETED = "COMPLETED"
INTEGRATION_FAILED = "FAILED"
INTEGRATION_STATUSES = frozenset(
    {
        INTEGRATION_PENDING,
        INTEGRATION_PLANNING,
        INTEGRATION_READY,
        INTEGRATION_APPLYING,
        INTEGRATION_VERIFYING,
        INTEGRATION_COMPLETED,
        INTEGRATION_FAILED,
    }
)
INTEGRATION_TRANSITIONS: dict[str, frozenset[str]] = {
    INTEGRATION_PENDING: frozenset({INTEGRATION_PLANNING, INTEGRATION_FAILED}),
    INTEGRATION_PLANNING: frozenset({INTEGRATION_READY, INTEGRATION_FAILED}),
    INTEGRATION_READY: frozenset({INTEGRATION_APPLYING, INTEGRATION_FAILED}),
    INTEGRATION_APPLYING: frozenset({INTEGRATION_VERIFYING, INTEGRATION_FAILED}),
    INTEGRATION_VERIFYING: frozenset({INTEGRATION_COMPLETED, INTEGRATION_FAILED}),
    INTEGRATION_COMPLETED: frozenset(),
    INTEGRATION_FAILED: frozenset(),
}

REVIEW_PENDING = "PENDING"
REVIEW_IN_PROGRESS = "IN_PROGRESS"
REVIEW_COMPLETED = "COMPLETED"
REVIEW_FAILED = "FAILED"
REVIEW_STATUSES = frozenset({REVIEW_PENDING, REVIEW_IN_PROGRESS, REVIEW_COMPLETED, REVIEW_FAILED})

CONTEXT_ACTIVE = "ACTIVE"
CONTEXT_SUPERSEDED = "SUPERSEDED"
CONTEXT_STATUSES = frozenset({CONTEXT_ACTIVE, CONTEXT_SUPERSEDED})

CONTEXT_SCOPE_GLOBAL = "GLOBAL"
CONTEXT_SCOPE_PROJECT = "PROJECT"
CONTEXT_SCOPE_TASK = "TASK"
CONTEXT_SCOPE_TEAM = "TEAM"
CONTEXT_SCOPE_ASSIGNMENT = "ASSIGNMENT"
CONTEXT_SCOPE_PRIVATE = "PRIVATE"
SHARED_CONTEXT_SCOPES = frozenset(
    {
        CONTEXT_SCOPE_GLOBAL,
        CONTEXT_SCOPE_PROJECT,
        CONTEXT_SCOPE_TASK,
        CONTEXT_SCOPE_TEAM,
        CONTEXT_SCOPE_ASSIGNMENT,
    }
)

CONTEXT_STALE_ACCEPT = "ACCEPT"
CONTEXT_STALE_REFRESH = "REFRESH"
CONTEXT_STALE_PAUSE = "PAUSE"
CONTEXT_STALE_REANALYZE = "REANALYZE"
CONTEXT_STALE_POLICIES = frozenset(
    {CONTEXT_STALE_ACCEPT, CONTEXT_STALE_REFRESH, CONTEXT_STALE_PAUSE, CONTEXT_STALE_REANALYZE}
)

RESOURCE_TYPE_PROJECT_FILE = "PROJECT_FILE"
RESOURCE_TYPE_SCENE = "SCENE"
RESOURCE_TYPE_SCRIPT = "SCRIPT"
RESOURCE_TYPE_RESOURCE = "RESOURCE"
RESOURCE_TYPE_PROJECT_SETTINGS = "PROJECT_SETTINGS"
RESOURCE_TYPE_INPUT_MAP = "INPUT_MAP"
RESOURCE_TYPE_ASSET = "ASSET"
RESOURCE_TYPE_TILESET = "TILESET"
RESOURCE_TYPE_ANIMATION = "ANIMATION"
RESOURCE_TYPE_SHARED_INTERFACE = "SHARED_INTERFACE"
RESOURCE_TYPE_DATABASE = "DATABASE_RESOURCE"
RESOURCE_TYPES = frozenset(
    {
        RESOURCE_TYPE_PROJECT_FILE,
        RESOURCE_TYPE_SCENE,
        RESOURCE_TYPE_SCRIPT,
        RESOURCE_TYPE_RESOURCE,
        RESOURCE_TYPE_PROJECT_SETTINGS,
        RESOURCE_TYPE_INPUT_MAP,
        RESOURCE_TYPE_ASSET,
        RESOURCE_TYPE_TILESET,
        RESOURCE_TYPE_ANIMATION,
        RESOURCE_TYPE_SHARED_INTERFACE,
        RESOURCE_TYPE_DATABASE,
    }
)

LOCK_MODE_READ = "READ"
LOCK_MODE_WRITE = "WRITE"
LOCK_MODES = frozenset({LOCK_MODE_READ, LOCK_MODE_WRITE})
LOCK_ACTIVE = "ACTIVE"
LOCK_RELEASED = "RELEASED"
LOCK_STATUSES = frozenset({LOCK_ACTIVE, LOCK_RELEASED})

CONFLICT_WRITE_WRITE = "WRITE_WRITE"
CONFLICT_READ_WRITE = "READ_WRITE"
CONFLICT_STALE_CONTEXT = "STALE_CONTEXT"
CONFLICT_SCHEMA = "SCHEMA_CONFLICT"
CONFLICT_INTERFACE = "INTERFACE_CONFLICT"
CONFLICT_CHANGESET = "CHANGESET_CONFLICT"
CONFLICT_RESOURCE_LOCK = "RESOURCE_LOCK_CONFLICT"
CONFLICT_TYPES = frozenset(
    {
        CONFLICT_WRITE_WRITE,
        CONFLICT_READ_WRITE,
        CONFLICT_STALE_CONTEXT,
        CONFLICT_SCHEMA,
        CONFLICT_INTERFACE,
        CONFLICT_CHANGESET,
        CONFLICT_RESOURCE_LOCK,
    }
)
CONFLICT_TRANSITIONS: dict[str, frozenset[str]] = {
    CONFLICT_DETECTED: frozenset(
        {CONFLICT_ANALYZING, CONFLICT_ESCALATED, CONFLICT_RESOLVED}
    ),
    CONFLICT_ANALYZING: frozenset(
        {CONFLICT_RESOLVING, CONFLICT_ESCALATED, CONFLICT_RESOLVED}
    ),
    CONFLICT_RESOLVING: frozenset({CONFLICT_RESOLVED, CONFLICT_ESCALATED}),
    CONFLICT_ESCALATED: frozenset({CONFLICT_RESOLVED}),
    CONFLICT_RESOLVED: frozenset(),
}

RESOLUTION_SEQUENTIAL = "SEQUENTIAL_EXECUTION"
RESOLUTION_REBASE = "REBASE"
RESOLUTION_MERGE_PROPOSAL = "MERGE_PROPOSAL"
RESOLUTION_REASSIGN = "REASSIGN"
RESOLUTION_USER_DECISION = "USER_DECISION"
RESOLUTION_STRATEGIES = frozenset(
    {
        RESOLUTION_SEQUENTIAL,
        RESOLUTION_REBASE,
        RESOLUTION_MERGE_PROPOSAL,
        RESOLUTION_REASSIGN,
        RESOLUTION_USER_DECISION,
    }
)

TEAM_MEMBER_LEAD = "LEAD"
TEAM_MEMBER_WORKER = "WORKER"
TEAM_MEMBER_REVIEWER = "REVIEWER"
TEAM_MEMBER_ROLES = frozenset({TEAM_MEMBER_LEAD, TEAM_MEMBER_WORKER, TEAM_MEMBER_REVIEWER})

CAPABILITY_CATEGORY_DESIGN = "GAME_DESIGN"
CAPABILITY_CATEGORY_PROGRAMMING = "PROGRAMMING"
CAPABILITY_CATEGORY_GODOT = "GODOT"
CAPABILITY_CATEGORY_ART = "ART"
CAPABILITY_CATEGORY_QA = "QUALITY"
CAPABILITY_CATEGORIES = frozenset(
    {
        CAPABILITY_CATEGORY_DESIGN,
        CAPABILITY_CATEGORY_PROGRAMMING,
        CAPABILITY_CATEGORY_GODOT,
        CAPABILITY_CATEGORY_ART,
        CAPABILITY_CATEGORY_QA,
    }
)

RISK_PROFILES = frozenset(TOOL_RISK_LEVELS)
DEFAULT_RISK_PROFILE = "R2"

AUTHORITY_ORCHESTRATOR = "ORCHESTRATOR"

# ---- 表 ----


class AgentCapabilityModel(Base):
    __tablename__ = "agent_capabilities"

    capability_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    input_contract: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_contract: Mapped[str | None] = mapped_column(String(128), nullable=True)
    required_tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_model_capabilities: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    dependencies: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_profile: Mapped[str] = mapped_column(String(4), nullable=False, default=DEFAULT_RISK_PROFILE)
    validation_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_agent_capabilities_category", "category", "enabled"),)


class AgentTeamModel(Base):
    __tablename__ = "agent_teams"

    team_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("task_attempts.attempt_id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    lead_agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=TEAM_CREATED)
    team_policy_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_teams_task_status", "task_id", "status"),
        Index("ix_agent_teams_project_status", "project_id", "status"),
    )


class AgentTeamMemberModel(Base):
    __tablename__ = "agent_team_members"

    member_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_assignments.assignment_id", ondelete="CASCADE"), nullable=False
    )
    agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=TEAM_MEMBER_WORKER)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("assignment_id", name="uq_agent_team_member_assignment"),
        Index("ix_agent_team_members_team", "team_id", "role"),
    )


class AgentAssignmentModel(Base):
    __tablename__ = "agent_assignments"

    assignment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    agent_definition_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_definitions.definition_id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_definition_version: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("task_attempts.attempt_id", ondelete="CASCADE"), nullable=False
    )
    parent_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_objective: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    dependencies: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_capabilities: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    permission_requirements: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    budget_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    estimated_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(4), nullable=False, default=DEFAULT_RISK_PROFILE)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=ASSIGNMENT_CREATED)
    assigned_by: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_assignments_team_status", "team_id", "status"),
        Index("ix_agent_assignments_task_status", "task_id", "status"),
        Index("ix_agent_assignments_instance", "agent_instance_id"),
    )


class AgentAssignmentDependencyModel(Base):
    __tablename__ = "agent_assignment_dependencies"

    dependency_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_assignments.assignment_id", ondelete="CASCADE"), nullable=False
    )
    depends_on_assignment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_assignments.assignment_id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "depends_on_assignment_id",
            name="uq_agent_assignment_dependency",
        ),
    )


class AgentHandoffModel(Base):
    __tablename__ = "agent_handoffs"

    handoff_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_assignment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_assignments.assignment_id", ondelete="CASCADE"), nullable=False
    )
    target_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_agent_definition_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_definitions.definition_id", ondelete="RESTRICT"),
        nullable=False,
    )
    handoff_type: Mapped[str] = mapped_column(String(32), nullable=False)
    handoff_payload_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    context_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=HANDOFF_REQUESTED)
    requested_by_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_agent_handoffs_source", "source_assignment_id", "status"),)


class AgentCollaborationModel(Base):
    __tablename__ = "agent_collaborations"

    collaboration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    participant_assignments: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    shared_context_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=COLLABORATION_ACTIVE)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_agent_collaborations_team", "team_id", "status"),)


class AgentMessageModel(Base):
    __tablename__ = "agent_messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    source_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("team_id", "sequence_number", name="uq_agent_message_sequence"),
        Index("ix_agent_messages_correlation", "correlation_id"),
        Index("ix_agent_messages_target", "target_assignment_id", "consumed_at"),
    )


class AgentConflictModel(Base):
    __tablename__ = "agent_conflicts"

    conflict_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    conflicting_assignments: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    conflict_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default=SEVERITY_MEDIUM)
    resolution_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CONFLICT_DETECTED
    )
    resolution_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_agent_conflicts_team", "team_id", "resolution_status"),)


class AgentResourceLockModel(Base):
    __tablename__ = "agent_resource_locks"

    lock_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_assignments.assignment_id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=LOCK_ACTIVE)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_resource_locks_resource", "resource_key", "status"),
        Index("ix_agent_resource_locks_assignment", "assignment_id", "status"),
        Index(
            "uq_agent_resource_locks_active_write",
            "resource_key",
            unique=True,
            sqlite_where=text("status = 'ACTIVE' AND mode = 'WRITE'"),
            postgresql_where=text("status = 'ACTIVE' AND mode = 'WRITE'"),
        ),
    )


class AgentIntegrationModel(Base):
    __tablename__ = "agent_integrations"

    integration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    source_assignment_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    integration_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integration_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=INTEGRATION_PENDING)
    verification_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_agent_integrations_team", "team_id", "status"),)


class AgentReviewModel(Base):
    __tablename__ = "agent_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    target_assignment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_assignments.assignment_id", ondelete="CASCADE"), nullable=False
    )
    reviewer_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=REVIEW_PENDING)
    findings: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default=SEVERITY_MEDIUM)
    evidence_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_agent_reviews_target", "target_assignment_id", "status"),)


class AgentTeamBudgetModel(Base):
    __tablename__ = "agent_team_budgets"

    budget_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    budget_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("team_id", name="uq_agent_team_budget_team"),)


class AgentSharedContextModel(Base):
    __tablename__ = "agent_shared_context"

    context_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_teams.team_id", ondelete="CASCADE"), nullable=False
    )
    context_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="TEAM")
    content_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=CONTEXT_ACTIVE)
    superseded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("team_id", "context_version", name="uq_agent_shared_context_version"),
        Index("ix_agent_shared_context_team", "team_id", "status"),
    )


__all__ = [
    "ASSIGNMENT_STATUSES",
    "ASSIGNMENT_TERMINAL_STATUSES",
    "ASSIGNMENT_TRANSITIONS",
    "AUTHORITY_ORCHESTRATOR",
    "CAPABILITY_CATEGORIES",
    "CAPABILITY_CATEGORY_ART",
    "CAPABILITY_CATEGORY_DESIGN",
    "CAPABILITY_CATEGORY_GODOT",
    "CAPABILITY_CATEGORY_PROGRAMMING",
    "CAPABILITY_CATEGORY_QA",
    "COLLABORATION_STATUSES",
    "CONFLICT_SEVERITIES",
    "CONFLICT_STATUSES",
    "CONFLICT_TRANSITIONS",
    "CONFLICT_TYPES",
    "CONTEXT_SCOPE_ASSIGNMENT",
    "CONTEXT_SCOPE_GLOBAL",
    "CONTEXT_SCOPE_PRIVATE",
    "CONTEXT_SCOPE_PROJECT",
    "CONTEXT_SCOPE_TASK",
    "CONTEXT_SCOPE_TEAM",
    "CONTEXT_STALE_ACCEPT",
    "CONTEXT_STALE_PAUSE",
    "CONTEXT_STALE_POLICIES",
    "CONTEXT_STALE_REANALYZE",
    "CONTEXT_STALE_REFRESH",
    "CONTEXT_STATUSES",
    "HANDOFF_STATUSES",
    "HANDOFF_TERMINAL_STATUSES",
    "HANDOFF_TRANSITIONS",
    "HANDOFF_TYPES",
    "INTEGRATION_STATUSES",
    "INTEGRATION_TRANSITIONS",
    "LOCK_MODES",
    "LOCK_STATUSES",
    "MESSAGE_TYPES",
    "RESOLUTION_STRATEGIES",
    "RESOURCE_TYPES",
    "REVIEW_STATUSES",
    "RISK_PROFILES",
    "SHARED_CONTEXT_SCOPES",
    "TEAM_MEMBER_ROLES",
    "TEAM_STATUSES",
    "TEAM_TERMINAL_STATUSES",
    "TEAM_TRANSITIONS",
    "AgentAssignmentDependencyModel",
    "AgentAssignmentModel",
    "AgentCapabilityModel",
    "AgentCollaborationModel",
    "AgentConflictModel",
    "AgentHandoffModel",
    "AgentIntegrationModel",
    "AgentMessageModel",
    "AgentResourceLockModel",
    "AgentReviewModel",
    "AgentSharedContextModel",
    "AgentTeamBudgetModel",
    "AgentTeamMemberModel",
    "AgentTeamModel",
]
