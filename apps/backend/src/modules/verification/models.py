"""Verification & QA 领域模型（E9-T01 / T02 / T03）。

状态所有权（冻结规则）：

- VerificationCampaign / VerificationPlan / VerificationRun / VerificationResult
  由 Verification System 唯一拥有；
- Task 由 Task System 拥有，Workflow / Phase / Node 由 Workflow Engine 拥有，
  ChangeSet 由 ChangeSet Manager 拥有，Approval 由 Approval System 拥有；
- 本模块只保存上述对象的引用，绝不直接修改其状态；
- ``UNKNOWN`` 与 ``FAILED`` 必须分离，``SKIPPED`` 不得计为 ``PASSED``；
- 未执行结果不得计入通过率；
- 证据必须可追溯（来源 + 内容哈希），失效证据不能作为通过依据。
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
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

# ---- Campaign 状态 ----

CAMPAIGN_DRAFT = "DRAFT"
CAMPAIGN_PLANNING = "PLANNING"
CAMPAIGN_READY = "READY"
CAMPAIGN_RUNNING = "RUNNING"
CAMPAIGN_COMPLETED = "COMPLETED"
CAMPAIGN_FAILED = "FAILED"
CAMPAIGN_CANCELLED = "CANCELLED"
CAMPAIGN_STATUSES = frozenset(
    {
        CAMPAIGN_DRAFT,
        CAMPAIGN_PLANNING,
        CAMPAIGN_READY,
        CAMPAIGN_RUNNING,
        CAMPAIGN_COMPLETED,
        CAMPAIGN_FAILED,
        CAMPAIGN_CANCELLED,
    }
)
CAMPAIGN_TRANSITIONS: dict[str, frozenset[str]] = {
    CAMPAIGN_DRAFT: frozenset({CAMPAIGN_PLANNING, CAMPAIGN_CANCELLED}),
    CAMPAIGN_PLANNING: frozenset({CAMPAIGN_READY, CAMPAIGN_FAILED, CAMPAIGN_CANCELLED}),
    CAMPAIGN_READY: frozenset({CAMPAIGN_RUNNING, CAMPAIGN_CANCELLED}),
    CAMPAIGN_RUNNING: frozenset({CAMPAIGN_COMPLETED, CAMPAIGN_FAILED, CAMPAIGN_CANCELLED}),
    CAMPAIGN_COMPLETED: frozenset(),
    CAMPAIGN_FAILED: frozenset({CAMPAIGN_PLANNING, CAMPAIGN_CANCELLED}),
    CAMPAIGN_CANCELLED: frozenset(),
}

CAMPAIGN_TYPE_TASK = "TASK"
CAMPAIGN_TYPE_PHASE = "PHASE"
CAMPAIGN_TYPE_WORKFLOW = "WORKFLOW"
CAMPAIGN_TYPE_REGRESSION = "REGRESSION"
CAMPAIGN_TYPE_ASSET = "ASSET"
CAMPAIGN_TYPE_MANUAL = "MANUAL"
CAMPAIGN_TYPES = frozenset(
    {
        CAMPAIGN_TYPE_TASK,
        CAMPAIGN_TYPE_PHASE,
        CAMPAIGN_TYPE_WORKFLOW,
        CAMPAIGN_TYPE_REGRESSION,
        CAMPAIGN_TYPE_ASSET,
        CAMPAIGN_TYPE_MANUAL,
    }
)

# ---- Plan 状态 ----

PLAN_DRAFT = "DRAFT"
PLAN_READY = "READY"
PLAN_ACTIVE = "ACTIVE"
PLAN_COMPLETED = "COMPLETED"
PLAN_CANCELLED = "CANCELLED"
PLAN_STATUSES = frozenset({PLAN_DRAFT, PLAN_READY, PLAN_ACTIVE, PLAN_COMPLETED, PLAN_CANCELLED})
PLAN_TRANSITIONS: dict[str, frozenset[str]] = {
    PLAN_DRAFT: frozenset({PLAN_READY, PLAN_CANCELLED}),
    PLAN_READY: frozenset({PLAN_ACTIVE, PLAN_CANCELLED}),
    PLAN_ACTIVE: frozenset({PLAN_COMPLETED, PLAN_CANCELLED}),
    PLAN_COMPLETED: frozenset(),
    PLAN_CANCELLED: frozenset(),
}

# ---- 六层验证体系 ----

LAYER_STATIC = "STATIC"
LAYER_STRUCTURE = "STRUCTURE"
LAYER_RESOURCE = "RESOURCE"
LAYER_RUNTIME = "RUNTIME"
LAYER_FUNCTIONAL = "FUNCTIONAL"
LAYER_VISUAL = "VISUAL"
LAYER_PERFORMANCE = "PERFORMANCE"
VERIFICATION_LAYERS = (
    LAYER_STATIC,
    LAYER_STRUCTURE,
    LAYER_RESOURCE,
    LAYER_RUNTIME,
    LAYER_FUNCTIONAL,
    LAYER_VISUAL,
    LAYER_PERFORMANCE,
)

# ---- Run 执行状态 ----

RUN_QUEUED = "QUEUED"
RUN_RUNNING = "RUNNING"
RUN_COMPLETED = "COMPLETED"
RUN_FAILED = "FAILED"
RUN_UNKNOWN = "UNKNOWN"
RUN_SKIPPED = "SKIPPED"
RUN_CANCELLED = "CANCELLED"
RUN_STATUSES = frozenset(
    {
        RUN_QUEUED,
        RUN_RUNNING,
        RUN_COMPLETED,
        RUN_FAILED,
        RUN_UNKNOWN,
        RUN_SKIPPED,
        RUN_CANCELLED,
    }
)
RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    RUN_QUEUED: frozenset({RUN_RUNNING, RUN_FAILED, RUN_UNKNOWN, RUN_SKIPPED, RUN_CANCELLED}),
    RUN_RUNNING: frozenset(
        {RUN_COMPLETED, RUN_FAILED, RUN_UNKNOWN, RUN_SKIPPED, RUN_CANCELLED}
    ),
    RUN_COMPLETED: frozenset(),
    RUN_FAILED: frozenset(),
    RUN_UNKNOWN: frozenset({RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED}),
    RUN_SKIPPED: frozenset(),
    RUN_CANCELLED: frozenset(),
}

# ---- Result 状态 ----

RESULT_PASSED = "PASSED"
RESULT_FAILED = "FAILED"
RESULT_UNKNOWN = "UNKNOWN"
RESULT_SKIPPED = "SKIPPED"
RESULT_NOT_RUN = "NOT_RUN"
RESULT_WAIVED = "WAIVED"
RESULT_SUPERSEDED = "SUPERSEDED"
RESULT_STATUSES = frozenset(
    {
        RESULT_PASSED,
        RESULT_FAILED,
        RESULT_UNKNOWN,
        RESULT_SKIPPED,
        RESULT_NOT_RUN,
        RESULT_WAIVED,
        RESULT_SUPERSEDED,
    }
)
# 只有 UNKNOWN / NOT_RUN 允许在补测后转为已执行结果；
# 已产生的通过或失败结果只能被新结果取代（SUPERSEDED），禁止原地改写；
# 豁免（WAIVED）是 owner 的独立判定，不等于 PASSED。
RESULT_TRANSITIONS: dict[str, frozenset[str]] = {
    RESULT_PASSED: frozenset({RESULT_SUPERSEDED}),
    RESULT_FAILED: frozenset({RESULT_SUPERSEDED, RESULT_WAIVED}),
    RESULT_UNKNOWN: frozenset(
        {
            RESULT_PASSED,
            RESULT_FAILED,
            RESULT_SKIPPED,
            RESULT_NOT_RUN,
            RESULT_WAIVED,
            RESULT_SUPERSEDED,
        }
    ),
    RESULT_SKIPPED: frozenset({RESULT_SUPERSEDED, RESULT_WAIVED}),
    RESULT_NOT_RUN: frozenset(
        {
            RESULT_PASSED,
            RESULT_FAILED,
            RESULT_SKIPPED,
            RESULT_UNKNOWN,
            RESULT_WAIVED,
            RESULT_SUPERSEDED,
        }
    ),
    RESULT_WAIVED: frozenset({RESULT_SUPERSEDED}),
    RESULT_SUPERSEDED: frozenset(),
}
EXECUTED_RESULT_STATUSES = frozenset({RESULT_PASSED, RESULT_FAILED})
NON_PASSING_RESULT_STATUSES = frozenset(
    {
        RESULT_FAILED,
        RESULT_UNKNOWN,
        RESULT_SKIPPED,
        RESULT_NOT_RUN,
        RESULT_WAIVED,
    }
)

# ---- Evidence ----

EVIDENCE_VALID = "VALID"
EVIDENCE_STALE = "STALE"
EVIDENCE_REVOKED = "REVOKED"
EVIDENCE_EXPIRED = "EXPIRED"
EVIDENCE_VALIDITY_STATUSES = frozenset(
    {EVIDENCE_VALID, EVIDENCE_STALE, EVIDENCE_REVOKED, EVIDENCE_EXPIRED}
)
EVIDENCE_TRANSITIONS: dict[str, frozenset[str]] = {
    EVIDENCE_VALID: frozenset({EVIDENCE_STALE, EVIDENCE_REVOKED, EVIDENCE_EXPIRED}),
    EVIDENCE_STALE: frozenset({EVIDENCE_VALID, EVIDENCE_REVOKED, EVIDENCE_EXPIRED}),
    EVIDENCE_REVOKED: frozenset(),
    EVIDENCE_EXPIRED: frozenset({EVIDENCE_STALE, EVIDENCE_REVOKED}),
}

EVIDENCE_TYPE_LOG = "LOG"
EVIDENCE_TYPE_SCREENSHOT = "SCREENSHOT"
EVIDENCE_TYPE_TEST_REPORT = "TEST_REPORT"
EVIDENCE_TYPE_RUNTIME_TRACE = "RUNTIME_TRACE"
EVIDENCE_TYPE_DEBUGGER_LOG = "DEBUGGER_LOG"
EVIDENCE_TYPE_PERFORMANCE_SAMPLE = "PERFORMANCE_SAMPLE"
EVIDENCE_TYPE_VIDEO = "VIDEO"
EVIDENCE_TYPE_STRUCTURE_SNAPSHOT = "STRUCTURE_SNAPSHOT"
EVIDENCE_TYPE_DIFF = "DIFF"
EVIDENCE_TYPE_MANUAL_NOTE = "MANUAL_NOTE"
EVIDENCE_TYPES = frozenset(
    {
        EVIDENCE_TYPE_LOG,
        EVIDENCE_TYPE_SCREENSHOT,
        EVIDENCE_TYPE_TEST_REPORT,
        EVIDENCE_TYPE_RUNTIME_TRACE,
        EVIDENCE_TYPE_DEBUGGER_LOG,
        EVIDENCE_TYPE_PERFORMANCE_SAMPLE,
        EVIDENCE_TYPE_VIDEO,
        EVIDENCE_TYPE_STRUCTURE_SNAPSHOT,
        EVIDENCE_TYPE_DIFF,
        EVIDENCE_TYPE_MANUAL_NOTE,
    }
)

SOURCE_TYPE_GODOT_RUNTIME = "GODOT_RUNTIME"
SOURCE_TYPE_GODOT_EDITOR = "GODOT_EDITOR"
SOURCE_TYPE_TEST_RUNNER = "TEST_RUNNER"
SOURCE_TYPE_AGENT = "AGENT"
SOURCE_TYPE_USER = "USER"
SOURCE_TYPE_IMPORT = "IMPORT"
SOURCE_TYPE_CI = "CI"
EVIDENCE_SOURCE_TYPES = frozenset(
    {
        SOURCE_TYPE_GODOT_RUNTIME,
        SOURCE_TYPE_GODOT_EDITOR,
        SOURCE_TYPE_TEST_RUNNER,
        SOURCE_TYPE_AGENT,
        SOURCE_TYPE_USER,
        SOURCE_TYPE_IMPORT,
        SOURCE_TYPE_CI,
    }
)

# ---- Test Case ----

TEST_TYPE_STATIC = "STATIC"
TEST_TYPE_STRUCTURAL = "STRUCTURAL"
TEST_TYPE_RESOURCE = "RESOURCE"
TEST_TYPE_RUNTIME = "RUNTIME"
TEST_TYPE_FUNCTIONAL = "FUNCTIONAL"
TEST_TYPE_VISUAL = "VISUAL"
TEST_TYPE_PERFORMANCE = "PERFORMANCE"
TEST_TYPE_DEBUGGER = "DEBUGGER"
TEST_TYPE_REGRESSION = "REGRESSION"
TEST_TYPES = frozenset(
    {
        TEST_TYPE_STATIC,
        TEST_TYPE_STRUCTURAL,
        TEST_TYPE_RESOURCE,
        TEST_TYPE_RUNTIME,
        TEST_TYPE_FUNCTIONAL,
        TEST_TYPE_VISUAL,
        TEST_TYPE_PERFORMANCE,
        TEST_TYPE_DEBUGGER,
        TEST_TYPE_REGRESSION,
    }
)

AUTOMATION_MANUAL = "MANUAL"
AUTOMATION_SEMI = "SEMI_AUTOMATED"
AUTOMATION_AUTOMATED = "AUTOMATED"
AUTOMATION_LEVELS = frozenset({AUTOMATION_MANUAL, AUTOMATION_SEMI, AUTOMATION_AUTOMATED})

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_CRITICAL = "CRITICAL"
RISK_LEVELS = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL})

TEST_CASE_DRAFT = "DRAFT"
TEST_CASE_ACTIVE = "ACTIVE"
TEST_CASE_ARCHIVED = "ARCHIVED"
TEST_CASE_STATUSES = frozenset({TEST_CASE_DRAFT, TEST_CASE_ACTIVE, TEST_CASE_ARCHIVED})
TEST_CASE_TRANSITIONS: dict[str, frozenset[str]] = {
    TEST_CASE_DRAFT: frozenset({TEST_CASE_ACTIVE, TEST_CASE_ARCHIVED}),
    TEST_CASE_ACTIVE: frozenset({TEST_CASE_ARCHIVED}),
    TEST_CASE_ARCHIVED: frozenset(),
}

# ---- Acceptance Criteria ----

CRITERION_FUNCTIONAL = "FUNCTIONAL"
CRITERION_STRUCTURAL = "STRUCTURAL"
CRITERION_RUNTIME = "RUNTIME"
CRITERION_VISUAL = "VISUAL"
CRITERION_PERFORMANCE = "PERFORMANCE"
CRITERION_SECURITY = "SECURITY"
CRITERION_TYPES = frozenset(
    {
        CRITERION_FUNCTIONAL,
        CRITERION_STRUCTURAL,
        CRITERION_RUNTIME,
        CRITERION_VISUAL,
        CRITERION_PERFORMANCE,
        CRITERION_SECURITY,
    }
)

CRITERION_ACTIVE = "ACTIVE"
CRITERION_SUPERSEDED = "SUPERSEDED"
CRITERION_RETIRED = "RETIRED"
CRITERION_STATUSES = frozenset({CRITERION_ACTIVE, CRITERION_SUPERSEDED, CRITERION_RETIRED})
CRITERION_TRANSITIONS: dict[str, frozenset[str]] = {
    CRITERION_ACTIVE: frozenset({CRITERION_SUPERSEDED, CRITERION_RETIRED}),
    CRITERION_SUPERSEDED: frozenset({CRITERION_RETIRED}),
    CRITERION_RETIRED: frozenset(),
}

# ---- Requirement → Test 追踪 ----

COVERAGE_DIRECT = "DIRECT"
COVERAGE_INDIRECT = "INDIRECT"
COVERAGE_PARTIAL = "PARTIAL"
COVERAGE_NEGATIVE = "NEGATIVE"
COVERAGE_TYPES = frozenset({COVERAGE_DIRECT, COVERAGE_INDIRECT, COVERAGE_PARTIAL, COVERAGE_NEGATIVE})

METHOD_STATIC_ANALYSIS = "STATIC_ANALYSIS"
METHOD_STRUCTURE_INSPECTION = "STRUCTURE_INSPECTION"
METHOD_RESOURCE_VALIDATION = "RESOURCE_VALIDATION"
METHOD_RUNTIME_TEST = "RUNTIME_TEST"
METHOD_FUNCTIONAL_TEST = "FUNCTIONAL_TEST"
METHOD_VISUAL_CHECK = "VISUAL_CHECK"
METHOD_PERFORMANCE_TEST = "PERFORMANCE_TEST"
VERIFICATION_METHODS = frozenset(
    {
        METHOD_STATIC_ANALYSIS,
        METHOD_STRUCTURE_INSPECTION,
        METHOD_RESOURCE_VALIDATION,
        METHOD_RUNTIME_TEST,
        METHOD_FUNCTIONAL_TEST,
        METHOD_VISUAL_CHECK,
        METHOD_PERFORMANCE_TEST,
    }
)

# ---- Runtime 测试环境（E9-T08） ----

RUNTIME_ENV_READY = "READY"
RUNTIME_ENV_BUSY = "BUSY"
RUNTIME_ENV_STOPPED = "STOPPED"
RUNTIME_ENV_FAILED = "FAILED"
RUNTIME_ENV_UNKNOWN = "UNKNOWN"
RUNTIME_ENVIRONMENT_STATUSES = frozenset(
    {RUNTIME_ENV_READY, RUNTIME_ENV_BUSY, RUNTIME_ENV_STOPPED, RUNTIME_ENV_FAILED, RUNTIME_ENV_UNKNOWN}
)

RUNTIME_NOT_STARTED = "NOT_STARTED"
RUNTIME_STARTING = "STARTING"
RUNTIME_RUNNING = "RUNNING"
RUNTIME_COMPLETED = "COMPLETED"
RUNTIME_FAILED = "FAILED"
RUNTIME_TIMEOUT = "TIMEOUT"
RUNTIME_CRASHED = "CRASHED"
RUNTIME_UNKNOWN = "UNKNOWN"
RUNTIME_EXECUTION_STATUSES = frozenset(
    {
        RUNTIME_NOT_STARTED,
        RUNTIME_STARTING,
        RUNTIME_RUNNING,
        RUNTIME_COMPLETED,
        RUNTIME_FAILED,
        RUNTIME_TIMEOUT,
        RUNTIME_CRASHED,
        RUNTIME_UNKNOWN,
    }
)
RUNTIME_TERMINAL_STATUSES = frozenset(
    {RUNTIME_COMPLETED, RUNTIME_FAILED, RUNTIME_TIMEOUT, RUNTIME_CRASHED, RUNTIME_UNKNOWN}
)

# ---- 功能测试框架（E9-T09） ----

FUNCTIONAL_KIND_UNIT = "UNIT"
FUNCTIONAL_KIND_INTEGRATION = "INTEGRATION"
FUNCTIONAL_KIND_GAMEPLAY = "GAMEPLAY"
FUNCTIONAL_KIND_END_TO_END = "END_TO_END"
FUNCTIONAL_TEST_KINDS = frozenset(
    {
        FUNCTIONAL_KIND_UNIT,
        FUNCTIONAL_KIND_INTEGRATION,
        FUNCTIONAL_KIND_GAMEPLAY,
        FUNCTIONAL_KIND_END_TO_END,
    }
)

FUNCTIONAL_PASSED = "PASSED"
FUNCTIONAL_FAILED = "FAILED"
FUNCTIONAL_SKIPPED = "SKIPPED"
FUNCTIONAL_BLOCKED = "BLOCKED"
FUNCTIONAL_TIMEOUT = "TIMEOUT"
FUNCTIONAL_UNKNOWN = "UNKNOWN"
FUNCTIONAL_INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
FUNCTIONAL_STATUSES = frozenset(
    {
        FUNCTIONAL_PASSED,
        FUNCTIONAL_FAILED,
        FUNCTIONAL_SKIPPED,
        FUNCTIONAL_BLOCKED,
        FUNCTIONAL_TIMEOUT,
        FUNCTIONAL_UNKNOWN,
        FUNCTIONAL_INFRASTRUCTURE_ERROR,
    }
)
# 功能测试状态到正式验证结果的保守映射：
# SKIPPED 不得计为 PASSED；BLOCKED 视为未执行；超时/基础设施故障归为 UNKNOWN。
FUNCTIONAL_TO_RESULT_STATUS: dict[str, str] = {
    FUNCTIONAL_PASSED: RESULT_PASSED,
    FUNCTIONAL_FAILED: RESULT_FAILED,
    FUNCTIONAL_SKIPPED: RESULT_SKIPPED,
    FUNCTIONAL_BLOCKED: RESULT_NOT_RUN,
    FUNCTIONAL_TIMEOUT: RESULT_UNKNOWN,
    FUNCTIONAL_UNKNOWN: RESULT_UNKNOWN,
    FUNCTIONAL_INFRASTRUCTURE_ERROR: RESULT_UNKNOWN,
}

# ---- Debugger 错误验证（E9-T10） ----

SEVERITY_FATAL = "FATAL"
SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"
DEBUGGER_SEVERITIES = frozenset({SEVERITY_FATAL, SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO})

ERROR_CATEGORY_PARSER = "PARSER_ERROR"
ERROR_CATEGORY_SCRIPT = "SCRIPT_ERROR"
ERROR_CATEGORY_RUNTIME = "RUNTIME_ERROR"
ERROR_CATEGORY_INVALID_CALL = "INVALID_CALL"
ERROR_CATEGORY_INVALID_ACCESS = "INVALID_ACCESS"
ERROR_CATEGORY_NULL_REFERENCE = "NULL_REFERENCE"
ERROR_CATEGORY_RESOURCE_LOAD = "RESOURCE_LOAD_ERROR"
ERROR_CATEGORY_NODE_NOT_FOUND = "NODE_NOT_FOUND"
ERROR_CATEGORY_SIGNAL = "SIGNAL_ERROR"
ERROR_CATEGORY_PHYSICS = "PHYSICS_ERROR"
ERROR_CATEGORY_ENGINE_CRASH = "ENGINE_CRASH"
ERROR_CATEGORY_WARNING = "WARNING"
ERROR_CATEGORY_INFO = "INFO"
DEBUGGER_ERROR_CATEGORIES = frozenset(
    {
        ERROR_CATEGORY_PARSER,
        ERROR_CATEGORY_SCRIPT,
        ERROR_CATEGORY_RUNTIME,
        ERROR_CATEGORY_INVALID_CALL,
        ERROR_CATEGORY_INVALID_ACCESS,
        ERROR_CATEGORY_NULL_REFERENCE,
        ERROR_CATEGORY_RESOURCE_LOAD,
        ERROR_CATEGORY_NODE_NOT_FOUND,
        ERROR_CATEGORY_SIGNAL,
        ERROR_CATEGORY_PHYSICS,
        ERROR_CATEGORY_ENGINE_CRASH,
        ERROR_CATEGORY_WARNING,
        ERROR_CATEGORY_INFO,
    }
)

ERROR_STATUS_OPEN = "OPEN"
ERROR_STATUS_RESOLVED = "RESOLVED"
ERROR_STATUS_IGNORED = "IGNORED"
DEBUGGER_ERROR_STATUSES = frozenset(
    {ERROR_STATUS_OPEN, ERROR_STATUS_RESOLVED, ERROR_STATUS_IGNORED}
)

# ---- Defect Management（E9-T14） ----

DEFECT_BLOCKER = "BLOCKER"
DEFECT_CRITICAL = "CRITICAL"
DEFECT_MAJOR = "MAJOR"
DEFECT_MINOR = "MINOR"
DEFECT_TRIVIAL = "TRIVIAL"
DEFECT_SEVERITIES = frozenset(
    {DEFECT_BLOCKER, DEFECT_CRITICAL, DEFECT_MAJOR, DEFECT_MINOR, DEFECT_TRIVIAL}
)

DEFECT_P0 = "P0"
DEFECT_P1 = "P1"
DEFECT_P2 = "P2"
DEFECT_P3 = "P3"
DEFECT_PRIORITIES = frozenset({DEFECT_P0, DEFECT_P1, DEFECT_P2, DEFECT_P3})

DEFECT_CATEGORY_GAMEPLAY = "GAMEPLAY_LOGIC"
DEFECT_CATEGORY_SCRIPT = "GDSCRIPT"
DEFECT_CATEGORY_UI = "UI"
DEFECT_CATEGORY_SCENE = "SCENE_STRUCTURE"
DEFECT_CATEGORY_TILEMAP = "TILEMAP"
DEFECT_CATEGORY_RESOURCE = "RESOURCE_IMPORT"
DEFECT_CATEGORY_INTEGRATION = "GODOT_INTEGRATION"
DEFECT_CATEGORY_ASSET = "ASSET_QUALITY"
DEFECT_CATEGORY_ANIMATION = "ANIMATION"
DEFECT_CATEGORY_PERFORMANCE = "PERFORMANCE"
DEFECT_CATEGORY_TEST = "TEST_AUTOMATION"
DEFECT_CATEGORY_SECURITY = "SECURITY"
DEFECT_CATEGORY_OTHER = "OTHER"
DEFECT_CATEGORIES = frozenset(
    {
        DEFECT_CATEGORY_GAMEPLAY,
        DEFECT_CATEGORY_SCRIPT,
        DEFECT_CATEGORY_UI,
        DEFECT_CATEGORY_SCENE,
        DEFECT_CATEGORY_TILEMAP,
        DEFECT_CATEGORY_RESOURCE,
        DEFECT_CATEGORY_INTEGRATION,
        DEFECT_CATEGORY_ASSET,
        DEFECT_CATEGORY_ANIMATION,
        DEFECT_CATEGORY_PERFORMANCE,
        DEFECT_CATEGORY_TEST,
        DEFECT_CATEGORY_SECURITY,
        DEFECT_CATEGORY_OTHER,
    }
)

DEFECT_OPEN = "OPEN"
DEFECT_TRIAGED = "TRIAGED"
DEFECT_ASSIGNED = "ASSIGNED"
DEFECT_IN_PROGRESS = "IN_PROGRESS"
DEFECT_FIX_SUBMITTED = "FIX_SUBMITTED"
DEFECT_VERIFYING = "VERIFYING"
DEFECT_RESOLVED = "RESOLVED"
DEFECT_REOPENED = "REOPENED"
DEFECT_REJECTED = "REJECTED"
DEFECT_STATUSES = frozenset(
    {
        DEFECT_OPEN,
        DEFECT_TRIAGED,
        DEFECT_ASSIGNED,
        DEFECT_IN_PROGRESS,
        DEFECT_FIX_SUBMITTED,
        DEFECT_VERIFYING,
        DEFECT_RESOLVED,
        DEFECT_REOPENED,
        DEFECT_REJECTED,
    }
)
DEFECT_TRANSITIONS: dict[str, frozenset[str]] = {
    DEFECT_OPEN: frozenset({DEFECT_TRIAGED, DEFECT_REJECTED}),
    DEFECT_TRIAGED: frozenset({DEFECT_ASSIGNED, DEFECT_REJECTED}),
    DEFECT_ASSIGNED: frozenset({DEFECT_IN_PROGRESS, DEFECT_TRIAGED}),
    DEFECT_IN_PROGRESS: frozenset({DEFECT_FIX_SUBMITTED}),
    DEFECT_FIX_SUBMITTED: frozenset({DEFECT_VERIFYING}),
    DEFECT_VERIFYING: frozenset({DEFECT_RESOLVED, DEFECT_REOPENED, DEFECT_REJECTED}),
    DEFECT_RESOLVED: frozenset({DEFECT_REOPENED}),
    DEFECT_REOPENED: frozenset({DEFECT_ASSIGNED, DEFECT_TRIAGED}),
    DEFECT_REJECTED: frozenset(),
}
DEFECT_ACTIVE_STATUSES = frozenset(
    {
        DEFECT_OPEN,
        DEFECT_TRIAGED,
        DEFECT_ASSIGNED,
        DEFECT_IN_PROGRESS,
        DEFECT_FIX_SUBMITTED,
        DEFECT_VERIFYING,
        DEFECT_REOPENED,
    }
)

# ---- Regression（E9-T15） ----

REGRESSION_TARGETED = "TARGETED"
REGRESSION_DEPENDENCY = "DEPENDENCY"
REGRESSION_FULL = "FULL"
REGRESSION_SECURITY = "SECURITY"
REGRESSION_STRATEGIES = frozenset(
    {REGRESSION_TARGETED, REGRESSION_DEPENDENCY, REGRESSION_FULL, REGRESSION_SECURITY}
)

REGRESSION_RISK_LOW = "LOW"
REGRESSION_RISK_MEDIUM = "MEDIUM"
REGRESSION_RISK_HIGH = "HIGH"
REGRESSION_RISK_CRITICAL = "CRITICAL"
REGRESSION_RISK_LEVELS = frozenset(
    {
        REGRESSION_RISK_LOW,
        REGRESSION_RISK_MEDIUM,
        REGRESSION_RISK_HIGH,
        REGRESSION_RISK_CRITICAL,
    }
)


def transitions_for(kind: str) -> dict[str, frozenset[str]]:
    """按领域类型返回状态迁移表。"""

    table = {
        "campaign": CAMPAIGN_TRANSITIONS,
        "plan": PLAN_TRANSITIONS,
        "run": RUN_TRANSITIONS,
        "result": RESULT_TRANSITIONS,
        "evidence": EVIDENCE_TRANSITIONS,
        "test_case": TEST_CASE_TRANSITIONS,
        "criterion": CRITERION_TRANSITIONS,
        "defect": DEFECT_TRANSITIONS,
    }.get(kind)
    if table is None:
        raise ValueError(f"未知状态机类型: {kind}")
    return table


class VerificationCampaignModel(Base):
    __tablename__ = "verification_campaigns"

    campaign_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phase_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=CAMPAIGN_DRAFT)
    verification_policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_verification_campaigns_project_status", "project_id", "status"),
        Index("ix_verification_campaigns_task", "task_id"),
        Index("ix_verification_campaigns_phase", "phase_id"),
    )


class VerificationPlanModel(Base):
    __tablename__ = "verification_plans"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("verification_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    test_suite_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    verification_layers_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    environment_profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_platforms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    acceptance_policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=PLAN_DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_verification_plans_campaign", "campaign_id", "status"),)


class VerificationTestCaseModel(Base):
    __tablename__ = "verification_test_cases"

    test_case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_type: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_method: Mapped[str] = mapped_column(String(64), nullable=False)
    preconditions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    setup_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    expected_result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cleanup_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    evidence_requirements_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default=RISK_MEDIUM)
    automation_level: Mapped[str] = mapped_column(
        String(24), nullable=False, default=AUTOMATION_MANUAL
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=TEST_CASE_ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_verification_test_case_name"),
        Index("ix_verification_test_cases_project_type", "project_id", "test_type"),
    )


class VerificationCriterionModel(Base):
    """E9 可判定验收标准注册中心。

    E4 的 ``acceptance_criteria`` 保存需求基线；本表补充 E9 需要的判定类型、
    判定方法、阈值、必需证据与版本，二者通过 ``requirement_id`` 关联。
    """

    __tablename__ = "verification_criteria"

    criterion_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("requirements.requirement_id", ondelete="CASCADE"),
        nullable=False,
    )
    criterion_type: Mapped[str] = mapped_column(String(24), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    verification_method: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    threshold_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    required_evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default=RISK_MEDIUM)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=CRITERION_ACTIVE)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_verification_criteria_project", "project_id", "status"),
        Index("ix_verification_criteria_requirement", "requirement_id"),
    )


class VerificationTestLinkModel(Base):
    __tablename__ = "verification_test_links"

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("requirements.requirement_id", ondelete="CASCADE"),
        nullable=False,
    )
    criterion_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_criteria.criterion_id", ondelete="CASCADE"),
        nullable=True,
    )
    test_case_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("verification_test_cases.test_case_id", ondelete="CASCADE"),
        nullable=False,
    )
    coverage_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=COVERAGE_DIRECT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "requirement_id", "test_case_id", name="uq_verification_test_link"
        ),
        Index("ix_verification_test_links_requirement", "requirement_id"),
    )


class VerificationRunModel(Base):
    __tablename__ = "verification_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("verification_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_plans.plan_id", ondelete="SET NULL"),
        nullable=True,
    )
    test_suite_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    test_case_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_test_cases.test_case_id", ondelete="SET NULL"),
        nullable=True,
    )
    environment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(24), nullable=False, default=RUN_QUEUED)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_verification_runs_campaign_status", "campaign_id", "execution_status"),
        Index("ix_verification_runs_test_case", "test_case_id"),
    )


class VerificationResultModel(Base):
    __tablename__ = "verification_results"

    result_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("verification_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    requirement_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("requirements.requirement_id", ondelete="SET NULL"), nullable=True
    )
    criterion_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_criteria.criterion_id", ondelete="SET NULL"),
        nullable=True,
    )
    test_case_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_test_cases.test_case_id", ondelete="SET NULL"),
        nullable=True,
    )
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_verification_results_campaign", "campaign_id", "result_status"),
        Index("ix_verification_results_requirement", "requirement_id"),
        Index("ix_verification_results_run", "run_id"),
    )


class VerificationEvidenceModel(Base):
    __tablename__ = "verification_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validity_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EVIDENCE_VALID
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_verification_evidence_project_type", "project_id", "evidence_type"),
        Index("ix_verification_evidence_run", "verification_run_id"),
        Index("ix_verification_evidence_hash", "content_hash"),
    )


class VerificationRuntimeEnvironmentModel(Base):
    """运行时测试环境记录（E9-T08）。

    每次运行都必须有独立的环境记录，用于区分“功能失败”与“环境故障”。
    """

    __tablename__ = "verification_runtime_environments"

    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    project_revision: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    godot_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    display_resolution: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    renderer: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    runtime_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    test_configuration_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=RUNTIME_ENV_READY
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_verification_runtime_environments_project_status",
            "project_id",
            "status",
        ),
        Index(
            "ix_verification_runtime_environments_instance",
            "runtime_instance_id",
        ),
    )


class VerificationDebuggerErrorModel(Base):
    """Debugger 错误结构化记录（E9-T10）。

    同一 ``fingerprint`` 在同一项目内聚合，用 ``is_baseline`` 区分历史问题与
    本轮新增问题；归因只记录 ChangeSet 引用，不修改 ChangeSet 状态。
    """

    __tablename__ = "verification_debugger_errors"

    error_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    scene: Mapped[str | None] = mapped_column(String(256), nullable=True)
    node: Mapped[str | None] = mapped_column(String(256), nullable=True)
    script: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    godot_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ERROR_STATUS_OPEN)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "project_id", "fingerprint", name="uq_verification_debugger_error_fingerprint"
        ),
        Index(
            "ix_verification_debugger_errors_project_status", "project_id", "status"
        ),
        Index(
            "ix_verification_debugger_errors_project_severity", "project_id", "severity"
        ),
        Index("ix_verification_debugger_errors_run", "run_id"),
    )


class VerificationDefectModel(Base):
    """标准缺陷记录（E9-T14）。

    Severity 表示影响程度，Priority 表示处理优先级，两者独立保存。
    """

    __tablename__ = "verification_defects"

    defect_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("requirements.requirement_id", ondelete="SET NULL"),
        nullable=True,
    )
    source_result_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_results.result_id", ondelete="SET NULL"),
        nullable=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[str] = mapped_column(String(4), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reproduction_steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    expected_result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actual_result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    assigned_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DEFECT_OPEN)
    related_changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_verification_defects_project_status", "project_id", "status"),
        Index("ix_verification_defects_project_severity", "project_id", "severity"),
        Index("ix_verification_defects_requirement", "requirement_id"),
        Index("ix_verification_defects_changeset", "related_changeset_id"),
    )


class VerificationRegressionPlanModel(Base):
    """变更影响分析与回归计划（E9-T15）。"""

    __tablename__ = "verification_regression_plans"

    regression_plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    affected_requirements_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    affected_test_cases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    affected_scenes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    affected_scripts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    affected_resources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    dependents_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    historical_defects_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    coverage_gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_checks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_verification_regression_plans_project", "project_id", "created_at"),
        Index("ix_verification_regression_plans_changeset", "changeset_id"),
    )


# ---- Quality Gate 层级与状态（E9-T16） ----

GATE_REQUIREMENT_COMPLETENESS = "GATE-1_REQUIREMENT_COMPLETENESS"
GATE_STATIC = "GATE-2_STATIC_VALIDATION"
GATE_STRUCTURAL = "GATE-3_STRUCTURAL_VALIDATION"
GATE_RUNTIME = "GATE-4_RUNTIME_VALIDATION"
GATE_FUNCTIONAL = "GATE-5_FUNCTIONAL_VALIDATION"
GATE_EVIDENCE = "GATE-6_EVIDENCE_COMPLETENESS"
GATE_DEFECT = "GATE-7_DEFECT_STATUS"
GATE_REGRESSION = "GATE-8_REGRESSION_VALIDATION"
GATE_LICENSE = "GATE-9_LICENSE_ASSET_VALIDATION"
GATE_SECURITY = "GATE-10_SECURITY_VALIDATION"
QUALITY_GATES = (
    GATE_REQUIREMENT_COMPLETENESS,
    GATE_STATIC,
    GATE_STRUCTURAL,
    GATE_RUNTIME,
    GATE_FUNCTIONAL,
    GATE_EVIDENCE,
    GATE_DEFECT,
    GATE_REGRESSION,
    GATE_LICENSE,
    GATE_SECURITY,
)

GATE_NOT_REQUIRED = "NOT_REQUIRED"
GATE_PENDING = "PENDING"
GATE_RUNNING = "RUNNING"
GATE_PASSED = "PASSED"
GATE_FAILED = "FAILED"
GATE_BLOCKED = "BLOCKED"
GATE_UNKNOWN = "UNKNOWN"
GATE_WAIVED = "WAIVED"
GATE_STATUSES = frozenset(
    {
        GATE_NOT_REQUIRED,
        GATE_PENDING,
        GATE_RUNNING,
        GATE_PASSED,
        GATE_FAILED,
        GATE_BLOCKED,
        GATE_UNKNOWN,
        GATE_WAIVED,
    }
)
GATE_TRANSITIONS: dict[str, frozenset[str]] = {
    GATE_NOT_REQUIRED: frozenset({GATE_PENDING, GATE_WAIVED}),
    GATE_PENDING: frozenset({GATE_RUNNING, GATE_WAIVED}),
    GATE_RUNNING: frozenset({GATE_PASSED, GATE_FAILED, GATE_BLOCKED, GATE_UNKNOWN}),
    GATE_PASSED: frozenset(),
    GATE_FAILED: frozenset({GATE_PENDING, GATE_WAIVED}),
    GATE_BLOCKED: frozenset({GATE_PENDING, GATE_WAIVED}),
    GATE_UNKNOWN: frozenset({GATE_PENDING, GATE_WAIVED}),
    GATE_WAIVED: frozenset({GATE_PENDING}),
}

# 部分执行既不能算 PASSED，也不等同于 FAILED。
GATE_OVERALL_PARTIAL = "PARTIAL"
GATE_OVERALL_STATUSES = frozenset(
    {GATE_PASSED, GATE_FAILED, GATE_BLOCKED, GATE_UNKNOWN, GATE_OVERALL_PARTIAL}
)

# ---- Phase Review 状态（E9-T17） ----

PHASE_REVIEW_DRAFT = "DRAFT"
PHASE_REVIEW_SUBMITTED = "SUBMITTED"
PHASE_REVIEW_UNDER_REVIEW = "UNDER_REVIEW"
PHASE_REVIEW_ACCEPTED = "ACCEPTED"
PHASE_REVIEW_REJECTED = "REJECTED"
PHASE_REVIEW_REVISION_REQUIRED = "REVISION_REQUIRED"
PHASE_REVIEW_STATUSES = frozenset(
    {
        PHASE_REVIEW_DRAFT,
        PHASE_REVIEW_SUBMITTED,
        PHASE_REVIEW_UNDER_REVIEW,
        PHASE_REVIEW_ACCEPTED,
        PHASE_REVIEW_REJECTED,
        PHASE_REVIEW_REVISION_REQUIRED,
    }
)
PHASE_REVIEW_TRANSITIONS: dict[str, frozenset[str]] = {
    PHASE_REVIEW_DRAFT: frozenset({PHASE_REVIEW_SUBMITTED}),
    PHASE_REVIEW_SUBMITTED: frozenset(
        {PHASE_REVIEW_UNDER_REVIEW, PHASE_REVIEW_REVISION_REQUIRED}
    ),
    PHASE_REVIEW_UNDER_REVIEW: frozenset(
        {
            PHASE_REVIEW_ACCEPTED,
            PHASE_REVIEW_REJECTED,
            PHASE_REVIEW_REVISION_REQUIRED,
        }
    ),
    PHASE_REVIEW_ACCEPTED: frozenset(),
    PHASE_REVIEW_REJECTED: frozenset(),
    PHASE_REVIEW_REVISION_REQUIRED: frozenset({PHASE_REVIEW_SUBMITTED}),
}

PHASE_REVIEW_DECISION_ACCEPT = "ACCEPT"
PHASE_REVIEW_DECISION_REJECT = "REJECT"
PHASE_REVIEW_DECISION_REQUEST_REVISION = "REQUEST_REVISION"
PHASE_REVIEW_DECISIONS = frozenset(
    {
        PHASE_REVIEW_DECISION_ACCEPT,
        PHASE_REVIEW_DECISION_REJECT,
        PHASE_REVIEW_DECISION_REQUEST_REVISION,
    }
)
PHASE_REVIEW_DECISION_STATUS: dict[str, str] = {
    PHASE_REVIEW_DECISION_ACCEPT: PHASE_REVIEW_ACCEPTED,
    PHASE_REVIEW_DECISION_REJECT: PHASE_REVIEW_REJECTED,
    PHASE_REVIEW_DECISION_REQUEST_REVISION: PHASE_REVIEW_REVISION_REQUIRED,
}


class QualityGatePolicyModel(Base):
    """项目级质量门禁策略（E9-T16）。"""

    __tablename__ = "quality_gate_policies"

    gate_policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    campaign_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    required_gates_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    waivers_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_quality_gate_policies_project", "project_id", "created_at"),
    )


class QualityGateResultModel(Base):
    """单次门禁评估结果，逐门禁保存以保证可追踪。"""

    __tablename__ = "quality_gate_results"

    gate_result_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("verification_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    )
    gate_policy_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("quality_gate_policies.gate_policy_id", ondelete="SET NULL"),
        nullable=True,
    )
    gate_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_quality_gate_results_campaign", "campaign_id", "evaluated_at"),
        Index("ix_quality_gate_results_project", "project_id", "evaluated_at"),
    )


class QualityGateWaiverModel(Base):
    """门禁豁免：必须由授权者给出原因、风险、范围与有效期。"""

    __tablename__ = "quality_gate_waivers"

    waiver_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    gate_result_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("quality_gate_results.gate_result_id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_name: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_by: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_statement: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(256), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_quality_gate_waivers_gate_result", "gate_result_id"),
        Index("ix_quality_gate_waivers_campaign_gate", "campaign_id", "gate_name"),
    )


class PhaseReviewModel(Base):
    """Phase Review 报告与用户验收状态（E9-T17）。

    只保存 Workflow Phase 引用，不修改 Workflow / Phase 状态；
    Verification PASSED 不会自动导致 ACCEPTED。
    """

    __tablename__ = "phase_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    phase_id: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("verification_campaigns.campaign_id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PHASE_REVIEW_DRAFT
    )
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_phase_reviews_project_phase", "project_id", "workflow_id", "phase_id"),
        Index("ix_phase_reviews_campaign", "campaign_id"),
    )


class PhaseReviewDecisionModel(Base):
    """Phase Review 验收决策，只追加不覆盖。"""

    __tablename__ = "phase_review_decisions"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("phase_reviews.review_id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_phase_review_decisions_review", "review_id", "decided_at"),
    )
