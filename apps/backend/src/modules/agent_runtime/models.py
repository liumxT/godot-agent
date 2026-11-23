"""Agent Runtime 领域模型（E6-T01）。

状态所有权：``Agent Instance`` / ``Agent Execution`` / ``Step`` 只由本模块修改；
Task、Attempt、Workflow、Tool Execution、Approval、Verification 的状态分别由
各自模块拥有，本模块只保存引用。

约束：

- Definition 发布后不可原地修改，版本表只追加；
- Event 表只追加，``sequence_number`` 在 Instance 内单调递增；
- Checkpoint 必须引用明确的 Execution 与最后确认的事件序号；
- 不保存任何模型隐藏推理或 API Key。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base
from modules.context.models import CONTEXT_PROFILE_DEFAULT, CONTEXT_PROFILES
from modules.tool.models import (
    RISK_HIGH,
    RISK_LOW_WRITE,
    RISK_NORMAL_WRITE,
    RISK_READ_ONLY,
    TOOL_RISK_LEVELS,
)

# ---- Agent Definition ----

DEFINITION_DRAFT = "DRAFT"
DEFINITION_ACTIVE = "ACTIVE"
DEFINITION_DEPRECATED = "DEPRECATED"
DEFINITION_DISABLED = "DISABLED"
DEFINITION_STATUSES = frozenset(
    {DEFINITION_DRAFT, DEFINITION_ACTIVE, DEFINITION_DEPRECATED, DEFINITION_DISABLED}
)

AGENT_CAPABILITIES = frozenset(
    {
        "task_analysis",
        "planning",
        "tool_execution",
        "result_summary",
        "verification",
        "approval_request",
        "user_interaction",
        "recovery",
    }
)

MODEL_POLICY_DEFAULT = "default_agent_policy"
PERMISSION_CEILINGS = frozenset(TOOL_RISK_LEVELS)

BUDGET_KEYS = frozenset(
    {
        "max_iterations",
        "max_model_calls",
        "max_tool_calls",
        "max_execution_seconds",
        "max_input_tokens",
        "max_output_tokens",
        "max_cost",
        "max_retries",
        "max_context_tokens",
    }
)
BUDGET_DEFAULT = {
    "max_iterations": 30,
    "max_model_calls": 40,
    "max_tool_calls": 60,
    "max_execution_seconds": 1800,
    "max_retries": 3,
}

# ---- Agent Instance ----

INSTANCE_CREATED = "CREATED"
INSTANCE_INITIALIZING = "INITIALIZING"
INSTANCE_READY = "READY"
INSTANCE_RUNNING = "RUNNING"
INSTANCE_WAITING_TOOL = "WAITING_TOOL"
INSTANCE_WAITING_APPROVAL = "WAITING_APPROVAL"
INSTANCE_WAITING_INPUT = "WAITING_INPUT"
INSTANCE_PAUSING = "PAUSING"
INSTANCE_PAUSED = "PAUSED"
INSTANCE_RESUMING = "RESUMING"
INSTANCE_STOPPING = "STOPPING"
INSTANCE_STOPPED = "STOPPED"
INSTANCE_COMPLETED = "COMPLETED"
INSTANCE_FAILED = "FAILED"
INSTANCE_UNKNOWN = "UNKNOWN"

INSTANCE_STATUSES = frozenset(
    {
        INSTANCE_CREATED,
        INSTANCE_INITIALIZING,
        INSTANCE_READY,
        INSTANCE_RUNNING,
        INSTANCE_WAITING_TOOL,
        INSTANCE_WAITING_APPROVAL,
        INSTANCE_WAITING_INPUT,
        INSTANCE_PAUSING,
        INSTANCE_PAUSED,
        INSTANCE_RESUMING,
        INSTANCE_STOPPING,
        INSTANCE_STOPPED,
        INSTANCE_COMPLETED,
        INSTANCE_FAILED,
        INSTANCE_UNKNOWN,
    }
)
INSTANCE_TERMINAL_STATUSES = frozenset(
    {INSTANCE_STOPPED, INSTANCE_COMPLETED, INSTANCE_FAILED}
)
# UNKNOWN 不能直接回到 RUNNING，必须先经过恢复检查（RESUMING）。
INSTANCE_TRANSITIONS: dict[str, frozenset[str]] = {
    INSTANCE_CREATED: frozenset({INSTANCE_INITIALIZING, INSTANCE_FAILED, INSTANCE_STOPPED}),
    INSTANCE_INITIALIZING: frozenset({INSTANCE_READY, INSTANCE_FAILED, INSTANCE_STOPPING}),
    INSTANCE_READY: frozenset({INSTANCE_RUNNING, INSTANCE_STOPPING, INSTANCE_FAILED}),
    INSTANCE_RUNNING: frozenset(
        {
            INSTANCE_WAITING_TOOL,
            INSTANCE_WAITING_APPROVAL,
            INSTANCE_WAITING_INPUT,
            INSTANCE_PAUSING,
            INSTANCE_STOPPING,
            INSTANCE_COMPLETED,
            INSTANCE_FAILED,
            INSTANCE_UNKNOWN,
        }
    ),
    INSTANCE_WAITING_TOOL: frozenset(
        {INSTANCE_RUNNING, INSTANCE_PAUSING, INSTANCE_STOPPING, INSTANCE_FAILED, INSTANCE_UNKNOWN}
    ),
    INSTANCE_WAITING_APPROVAL: frozenset(
        {INSTANCE_RUNNING, INSTANCE_PAUSING, INSTANCE_STOPPING, INSTANCE_FAILED, INSTANCE_UNKNOWN}
    ),
    INSTANCE_WAITING_INPUT: frozenset(
        {INSTANCE_RUNNING, INSTANCE_PAUSING, INSTANCE_STOPPING, INSTANCE_FAILED, INSTANCE_UNKNOWN}
    ),
    INSTANCE_PAUSING: frozenset({INSTANCE_PAUSED, INSTANCE_FAILED, INSTANCE_UNKNOWN}),
    INSTANCE_PAUSED: frozenset({INSTANCE_RESUMING, INSTANCE_STOPPING}),
    INSTANCE_RESUMING: frozenset(
        {INSTANCE_RUNNING, INSTANCE_PAUSED, INSTANCE_FAILED, INSTANCE_UNKNOWN}
    ),
    INSTANCE_STOPPING: frozenset({INSTANCE_STOPPED, INSTANCE_UNKNOWN}),
    INSTANCE_STOPPED: frozenset(),
    INSTANCE_COMPLETED: frozenset(),
    INSTANCE_FAILED: frozenset(),
    INSTANCE_UNKNOWN: frozenset(
        {INSTANCE_RESUMING, INSTANCE_PAUSED, INSTANCE_STOPPING, INSTANCE_FAILED, INSTANCE_COMPLETED}
    ),
}

# ---- Agent Execution ----

EXECUTION_CREATED = "CREATED"
EXECUTION_RUNNING = "RUNNING"
EXECUTION_WAITING_APPROVAL = "WAITING_APPROVAL"
EXECUTION_WAITING_INPUT = "WAITING_INPUT"
EXECUTION_PAUSED = "PAUSED"
EXECUTION_STOPPED = "STOPPED"
EXECUTION_COMPLETED = "COMPLETED"
EXECUTION_FAILED = "FAILED"
EXECUTION_UNKNOWN = "UNKNOWN"

EXECUTION_STATUSES = frozenset(
    {
        EXECUTION_CREATED,
        EXECUTION_RUNNING,
        EXECUTION_WAITING_APPROVAL,
        EXECUTION_WAITING_INPUT,
        EXECUTION_PAUSED,
        EXECUTION_STOPPED,
        EXECUTION_COMPLETED,
        EXECUTION_FAILED,
        EXECUTION_UNKNOWN,
    }
)
EXECUTION_TRANSITIONS: dict[str, frozenset[str]] = {
    EXECUTION_CREATED: frozenset({EXECUTION_RUNNING, EXECUTION_FAILED, EXECUTION_STOPPED}),
    EXECUTION_RUNNING: frozenset(
        {
            EXECUTION_WAITING_APPROVAL,
            EXECUTION_WAITING_INPUT,
            EXECUTION_PAUSED,
            EXECUTION_COMPLETED,
            EXECUTION_FAILED,
            EXECUTION_STOPPED,
            EXECUTION_UNKNOWN,
        }
    ),
    EXECUTION_WAITING_APPROVAL: frozenset(
        {EXECUTION_RUNNING, EXECUTION_PAUSED, EXECUTION_FAILED, EXECUTION_STOPPED, EXECUTION_UNKNOWN}
    ),
    EXECUTION_WAITING_INPUT: frozenset(
        {EXECUTION_RUNNING, EXECUTION_PAUSED, EXECUTION_FAILED, EXECUTION_STOPPED, EXECUTION_UNKNOWN}
    ),
    EXECUTION_PAUSED: frozenset({EXECUTION_RUNNING, EXECUTION_STOPPED}),
    EXECUTION_STOPPED: frozenset(),
    EXECUTION_COMPLETED: frozenset(),
    EXECUTION_FAILED: frozenset(),
    EXECUTION_UNKNOWN: frozenset(
        {EXECUTION_PAUSED, EXECUTION_STOPPED, EXECUTION_COMPLETED, EXECUTION_FAILED}
    ),
}

# ---- Plan / Step ----

PLAN_DRAFT = "DRAFT"
PLAN_ACTIVE = "ACTIVE"
PLAN_SUPERSEDED = "SUPERSEDED"
PLAN_COMPLETED = "COMPLETED"
PLAN_ABANDONED = "ABANDONED"
PLAN_STATUSES = frozenset({PLAN_DRAFT, PLAN_ACTIVE, PLAN_SUPERSEDED, PLAN_COMPLETED, PLAN_ABANDONED})

STEP_PENDING = "PENDING"
STEP_READY = "READY"
STEP_RUNNING = "RUNNING"
STEP_WAITING_TOOL = "WAITING_TOOL"
STEP_WAITING_APPROVAL = "WAITING_APPROVAL"
STEP_COMPLETED = "COMPLETED"
STEP_FAILED = "FAILED"
STEP_SKIPPED = "SKIPPED"
STEP_BLOCKED = "BLOCKED"
STEP_UNKNOWN = "UNKNOWN"
STEP_STATUSES = frozenset(
    {
        STEP_PENDING,
        STEP_READY,
        STEP_RUNNING,
        STEP_WAITING_TOOL,
        STEP_WAITING_APPROVAL,
        STEP_COMPLETED,
        STEP_FAILED,
        STEP_SKIPPED,
        STEP_BLOCKED,
        STEP_UNKNOWN,
    }
)
STEP_TERMINAL_STATUSES = frozenset({STEP_COMPLETED, STEP_FAILED, STEP_SKIPPED})
STEP_TRANSITIONS: dict[str, frozenset[str]] = {
    STEP_PENDING: frozenset({STEP_READY, STEP_SKIPPED, STEP_BLOCKED}),
    STEP_READY: frozenset(
        {STEP_RUNNING, STEP_WAITING_APPROVAL, STEP_SKIPPED, STEP_BLOCKED, STEP_FAILED}
    ),
    STEP_RUNNING: frozenset({STEP_WAITING_TOOL, STEP_COMPLETED, STEP_FAILED, STEP_UNKNOWN}),
    STEP_WAITING_TOOL: frozenset(
        {STEP_RUNNING, STEP_COMPLETED, STEP_FAILED, STEP_UNKNOWN, STEP_WAITING_APPROVAL}
    ),
    STEP_WAITING_APPROVAL: frozenset(
        {STEP_RUNNING, STEP_COMPLETED, STEP_FAILED, STEP_SKIPPED}
    ),
    STEP_COMPLETED: frozenset(),
    STEP_FAILED: frozenset(),
    STEP_SKIPPED: frozenset(),
    STEP_BLOCKED: frozenset({STEP_READY, STEP_FAILED}),
    STEP_UNKNOWN: frozenset({STEP_FAILED, STEP_COMPLETED}),
}

STEP_TYPE_ANALYSIS = "ANALYSIS"
STEP_TYPE_PLANNING = "PLANNING"
STEP_TYPE_TOOL_EXECUTION = "TOOL_EXECUTION"
STEP_TYPE_VERIFICATION = "VERIFICATION"
STEP_TYPE_APPROVAL = "APPROVAL"
STEP_TYPE_USER_INPUT = "USER_INPUT"
STEP_TYPE_REPORT = "REPORT"
STEP_TYPE_COMPLETION = "COMPLETION"
STEP_TYPES = frozenset(
    {
        STEP_TYPE_ANALYSIS,
        STEP_TYPE_PLANNING,
        STEP_TYPE_TOOL_EXECUTION,
        STEP_TYPE_VERIFICATION,
        STEP_TYPE_APPROVAL,
        STEP_TYPE_USER_INPUT,
        STEP_TYPE_REPORT,
        STEP_TYPE_COMPLETION,
    }
)

# ---- Agent Action（模型结构化响应）----

ACTION_ANALYZE = "ANALYZE"
ACTION_CREATE_PLAN = "CREATE_PLAN"
ACTION_UPDATE_PLAN = "UPDATE_PLAN"
ACTION_EXECUTE_TOOL = "EXECUTE_TOOL"
ACTION_REQUEST_APPROVAL = "REQUEST_APPROVAL"
ACTION_REQUEST_USER_INPUT = "REQUEST_USER_INPUT"
ACTION_REPORT_PROGRESS = "REPORT_PROGRESS"
ACTION_COMPLETE_EXECUTION = "COMPLETE_EXECUTION"
ACTION_FAIL_EXECUTION = "FAIL_EXECUTION"
AGENT_ACTION_TYPES = frozenset(
    {
        ACTION_ANALYZE,
        ACTION_CREATE_PLAN,
        ACTION_UPDATE_PLAN,
        ACTION_EXECUTE_TOOL,
        ACTION_REQUEST_APPROVAL,
        ACTION_REQUEST_USER_INPUT,
        ACTION_REPORT_PROGRESS,
        ACTION_COMPLETE_EXECUTION,
        ACTION_FAIL_EXECUTION,
    }
)

# ---- Agent Event ----

EVENT_INSTANCE_CREATED = "INSTANCE_CREATED"
EVENT_INSTANCE_INITIALIZED = "INSTANCE_INITIALIZED"
EVENT_EXECUTION_STARTED = "EXECUTION_STARTED"
EVENT_PLAN_CREATED = "PLAN_CREATED"
EVENT_PLAN_UPDATED = "PLAN_UPDATED"
EVENT_STEP_CREATED = "STEP_CREATED"
EVENT_STEP_STARTED = "STEP_STARTED"
EVENT_STEP_COMPLETED = "STEP_COMPLETED"
EVENT_STEP_FAILED = "STEP_FAILED"
EVENT_MODEL_REQUEST_STARTED = "MODEL_REQUEST_STARTED"
EVENT_MODEL_REQUEST_COMPLETED = "MODEL_REQUEST_COMPLETED"
EVENT_TOOL_REQUEST_STARTED = "TOOL_REQUEST_STARTED"
EVENT_TOOL_REQUEST_COMPLETED = "TOOL_REQUEST_COMPLETED"
EVENT_APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
EVENT_APPROVAL_GRANTED = "APPROVAL_GRANTED"
EVENT_APPROVAL_REJECTED = "APPROVAL_REJECTED"
EVENT_PAUSE_REQUESTED = "PAUSE_REQUESTED"
EVENT_PAUSED = "PAUSED"
EVENT_RESUME_REQUESTED = "RESUME_REQUESTED"
EVENT_RESUMED = "RESUMED"
EVENT_CANCEL_REQUESTED = "CANCEL_REQUESTED"
EVENT_STOPPED = "STOPPED"
EVENT_CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
EVENT_RECOVERY_STARTED = "RECOVERY_STARTED"
EVENT_RECOVERY_COMPLETED = "RECOVERY_COMPLETED"
EVENT_EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
EVENT_EXECUTION_FAILED = "EXECUTION_FAILED"
EVENT_EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
EVENT_BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
AGENT_EVENT_TYPES = frozenset(
    {
        EVENT_INSTANCE_CREATED,
        EVENT_INSTANCE_INITIALIZED,
        EVENT_EXECUTION_STARTED,
        EVENT_PLAN_CREATED,
        EVENT_PLAN_UPDATED,
        EVENT_STEP_CREATED,
        EVENT_STEP_STARTED,
        EVENT_STEP_COMPLETED,
        EVENT_STEP_FAILED,
        EVENT_MODEL_REQUEST_STARTED,
        EVENT_MODEL_REQUEST_COMPLETED,
        EVENT_TOOL_REQUEST_STARTED,
        EVENT_TOOL_REQUEST_COMPLETED,
        EVENT_APPROVAL_REQUESTED,
        EVENT_APPROVAL_GRANTED,
        EVENT_APPROVAL_REJECTED,
        EVENT_PAUSE_REQUESTED,
        EVENT_PAUSED,
        EVENT_RESUME_REQUESTED,
        EVENT_RESUMED,
        EVENT_CANCEL_REQUESTED,
        EVENT_STOPPED,
        EVENT_CHECKPOINT_CREATED,
        EVENT_RECOVERY_STARTED,
        EVENT_RECOVERY_COMPLETED,
        EVENT_EXECUTION_COMPLETED,
        EVENT_EXECUTION_FAILED,
        EVENT_EXECUTION_UNKNOWN,
        EVENT_BUDGET_EXCEEDED,
    }
)

# ---- 表 ----

DEFAULT_PERMISSION_CEILING = RISK_NORMAL_WRITE
READ_ONLY_CEILING = RISK_READ_ONLY
LOW_WRITE_CEILING = RISK_LOW_WRITE
HIGH_CEILING = RISK_HIGH


class AgentDefinitionModel(Base):
    __tablename__ = "agent_definitions"

    definition_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="GENERAL")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DEFINITION_DRAFT)
    current_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    supported_capabilities: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    model_policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_profile_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default=CONTEXT_PROFILE_DEFAULT
    )
    context_profile_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    tool_whitelist: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    permission_ceiling: Mapped[str] = mapped_column(
        String(4), nullable=False, default=DEFAULT_PERMISSION_CEILING
    )
    budget_profile_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    budget_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_agent_definitions_status", "status"),)


class AgentDefinitionVersionModel(Base):
    __tablename__ = "agent_definition_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_definition_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_definitions.definition_id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    compatibility_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_definition_id", "version", name="uq_agent_definition_version"),
        Index("ix_agent_definition_versions_def", "agent_definition_id", "published_at"),
    )


class AgentConfigSnapshotModel(Base):
    __tablename__ = "agent_config_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_definition_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_definitions.definition_id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    context_profile_version: Mapped[str] = mapped_column(String(32), nullable=False)
    tool_whitelist: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    permission_ceiling: Mapped[str] = mapped_column(String(4), nullable=False)
    budget_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    runtime_policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentInstanceModel(Base):
    __tablename__ = "agent_instances"

    instance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_definition_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_definitions.definition_id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=True
    )
    attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("task_attempts.attempt_id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=INSTANCE_CREATED)
    config_snapshot_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_config_snapshots.snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    termination_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_instances_project_status", "project_id", "status"),
        Index("ix_agent_instances_attempt", "attempt_id"),
    )


class AgentExecutionModel(Base):
    __tablename__ = "agent_executions"

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=EXECUTION_CREATED)
    last_checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    termination_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("agent_instance_id", "execution_number", name="uq_agent_execution_number"),
        Index("ix_agent_executions_instance_status", "agent_instance_id", "status"),
    )


class AgentPlanModel(Base):
    __tablename__ = "agent_plans"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PLAN_DRAFT)
    supersedes_plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("execution_id", "plan_version", name="uq_agent_plan_version"),
        Index("ix_agent_plans_execution", "execution_id", "status"),
    )


class AgentStepModel(Base):
    __tablename__ = "agent_steps"

    step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_plans.plan_id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=STEP_PENDING)
    dependencies: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    input_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("plan_id", "step_number", name="uq_agent_step_number"),
        Index("ix_agent_steps_execution_status", "execution_id", "status"),
    )


class AgentCheckpointModel(Base):
    __tablename__ = "agent_checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_completed_step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    budget_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    context_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_agent_checkpoints_instance", "agent_instance_id", "checkpoint_version"),
        Index("ix_agent_checkpoints_execution", "execution_id"),
    )


class AgentEventModel(Base):
    __tablename__ = "agent_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    event_payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("agent_instance_id", "sequence_number", name="uq_agent_event_sequence"),
        Index("ix_agent_events_instance", "agent_instance_id", "sequence_number"),
        Index("ix_agent_events_execution", "execution_id", "sequence_number"),
    )


__all__ = [
    "AGENT_ACTION_TYPES",
    "AGENT_CAPABILITIES",
    "AGENT_EVENT_TYPES",
    "BUDGET_DEFAULT",
    "BUDGET_KEYS",
    "CONTEXT_PROFILES",
    "CONTEXT_PROFILE_DEFAULT",
    "DEFINITION_ACTIVE",
    "DEFINITION_DISABLED",
    "DEFINITION_DRAFT",
    "DEFINITION_STATUSES",
    "EXECUTION_STATUSES",
    "EXECUTION_TRANSITIONS",
    "INSTANCE_STATUSES",
    "INSTANCE_TERMINAL_STATUSES",
    "INSTANCE_TRANSITIONS",
    "MODEL_POLICY_DEFAULT",
    "PERMISSION_CEILINGS",
    "PLAN_STATUSES",
    "STEP_STATUSES",
    "STEP_TERMINAL_STATUSES",
    "STEP_TYPES",
    "AgentCheckpointModel",
    "AgentConfigSnapshotModel",
    "AgentDefinitionModel",
    "AgentDefinitionVersionModel",
    "AgentEventModel",
    "AgentExecutionModel",
    "AgentInstanceModel",
    "AgentPlanModel",
    "AgentStepModel",
]
