"""E9 验证与质量请求模型（T18 / T19）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.project_workflow import StrictModel

CAMPAIGN_TYPE_LITERAL = Literal["TASK", "PHASE", "WORKFLOW", "REGRESSION", "ASSET", "MANUAL"]
CAMPAIGN_STATUS_LITERAL = Literal[
    "DRAFT", "PLANNING", "READY", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"
]
PLAN_STATUS_LITERAL = Literal["DRAFT", "READY", "ACTIVE", "COMPLETED", "CANCELLED"]
VERIFICATION_LAYER_LITERAL = Literal[
    "STATIC",
    "STRUCTURE",
    "RESOURCE",
    "RUNTIME",
    "FUNCTIONAL",
    "VISUAL",
    "PERFORMANCE",
]
TEST_TYPE_LITERAL = Literal[
    "STATIC",
    "STRUCTURAL",
    "RESOURCE",
    "RUNTIME",
    "FUNCTIONAL",
    "VISUAL",
    "PERFORMANCE",
    "DEBUGGER",
    "REGRESSION",
]
AUTOMATION_LEVEL_LITERAL = Literal["MANUAL", "SEMI_AUTOMATED", "AUTOMATED"]
RISK_LEVEL_LITERAL = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
CRITERION_TYPE_LITERAL = Literal[
    "FUNCTIONAL", "STRUCTURAL", "RUNTIME", "VISUAL", "PERFORMANCE", "SECURITY"
]
VERIFICATION_METHOD_LITERAL = Literal[
    "STATIC_ANALYSIS",
    "STRUCTURE_INSPECTION",
    "RESOURCE_VALIDATION",
    "RUNTIME_TEST",
    "FUNCTIONAL_TEST",
    "VISUAL_CHECK",
    "PERFORMANCE_TEST",
]
COVERAGE_TYPE_LITERAL = Literal["DIRECT", "INDIRECT", "PARTIAL", "NEGATIVE"]
EVIDENCE_TYPE_LITERAL = Literal[
    "LOG",
    "SCREENSHOT",
    "TEST_REPORT",
    "RUNTIME_TRACE",
    "DEBUGGER_LOG",
    "PERFORMANCE_SAMPLE",
    "VIDEO",
    "STRUCTURE_SNAPSHOT",
    "DIFF",
    "MANUAL_NOTE",
]
EVIDENCE_SOURCE_LITERAL = Literal[
    "GODOT_RUNTIME", "GODOT_EDITOR", "TEST_RUNNER", "AGENT", "USER", "IMPORT", "CI"
]
EVIDENCE_VALIDITY_LITERAL = Literal["VALID", "STALE", "REVOKED", "EXPIRED"]
RUN_STATUS_LITERAL = Literal[
    "QUEUED", "RUNNING", "COMPLETED", "FAILED", "UNKNOWN", "SKIPPED", "CANCELLED"
]
RESULT_STATUS_LITERAL = Literal[
    "PASSED", "FAILED", "UNKNOWN", "SKIPPED", "NOT_RUN", "WAIVED", "SUPERSEDED"
]
CONFIDENCE_LITERAL = Literal["HIGH", "MEDIUM", "LOW"]


class PlanProposalRequest(StrictModel):
    requirement_ids: list[str] = Field(min_length=1, max_length=500)
    target_platforms: list[str] = Field(default_factory=list, max_length=16)
    environment_profile: str | None = Field(default=None, max_length=128)
    acceptance_policy: dict[str, Any] = Field(default_factory=dict)


class PrepareVerificationRequest(PlanProposalRequest):
    campaign_type: CAMPAIGN_TYPE_LITERAL
    workflow_id: str | None = Field(default=None, max_length=64)
    phase_id: str | None = Field(default=None, max_length=64)
    task_id: str | None = Field(default=None, max_length=64)
    changeset_id: str | None = Field(default=None, max_length=64)
    allow_gaps: bool = False


class CampaignCreateRequest(StrictModel):
    campaign_type: CAMPAIGN_TYPE_LITERAL
    workflow_id: str | None = Field(default=None, max_length=64)
    phase_id: str | None = Field(default=None, max_length=64)
    task_id: str | None = Field(default=None, max_length=64)
    changeset_id: str | None = Field(default=None, max_length=64)
    verification_policy_id: str | None = Field(default=None, max_length=64)


class CampaignTransitionRequest(StrictModel):
    status: CAMPAIGN_STATUS_LITERAL


class PlanCreateRequest(StrictModel):
    requirement_ids: list[str] = Field(default_factory=list, max_length=500)
    test_suite_ids: list[str] = Field(default_factory=list, max_length=200)
    verification_layers: list[VERIFICATION_LAYER_LITERAL] = Field(default_factory=list)
    environment_profile: str | None = Field(default=None, max_length=128)
    target_platforms: list[str] = Field(default_factory=list, max_length=16)
    acceptance_policy: dict[str, Any] = Field(default_factory=dict)


class PlanTransitionRequest(StrictModel):
    status: PLAN_STATUS_LITERAL


class TestCaseCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=256)
    test_type: TEST_TYPE_LITERAL
    execution_method: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    preconditions: list[str] = Field(default_factory=list, max_length=64)
    setup: list[str] = Field(default_factory=list, max_length=64)
    steps: list[str] = Field(default_factory=list, max_length=128)
    expected_result: str = Field(default="", max_length=4000)
    cleanup: list[str] = Field(default_factory=list, max_length=64)
    timeout_seconds: int = Field(default=300, gt=0, le=86400)
    evidence_requirements: list[str] = Field(default_factory=list, max_length=32)
    risk_level: RISK_LEVEL_LITERAL = "MEDIUM"
    automation_level: AUTOMATION_LEVEL_LITERAL = "MANUAL"


class CriterionCreateRequest(StrictModel):
    requirement_id: str = Field(min_length=1, max_length=64)
    criterion_type: CRITERION_TYPE_LITERAL
    statement: str = Field(min_length=1, max_length=4000)
    verification_method: VERIFICATION_METHOD_LITERAL
    expected: dict[str, Any] = Field(default_factory=dict)
    threshold: dict[str, Any] = Field(default_factory=dict)
    required_evidence: list[str] = Field(default_factory=list, max_length=32)
    priority: RISK_LEVEL_LITERAL = "MEDIUM"


class TestLinkCreateRequest(StrictModel):
    requirement_id: str = Field(min_length=1, max_length=64)
    test_case_id: str = Field(min_length=1, max_length=64)
    criterion_id: str | None = Field(default=None, max_length=64)
    coverage_type: COVERAGE_TYPE_LITERAL = "DIRECT"


class EvidenceCreateRequest(StrictModel):
    evidence_type: EVIDENCE_TYPE_LITERAL
    source_type: EVIDENCE_SOURCE_LITERAL
    source_reference: str = Field(min_length=1, max_length=1024)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str | None = Field(default=None, max_length=64)
    captured_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceInvalidateRequest(StrictModel):
    status: EVIDENCE_VALIDITY_LITERAL = "STALE"


class RunStartRequest(StrictModel):
    plan_id: str | None = Field(default=None, max_length=64)
    test_suite_id: str | None = Field(default=None, max_length=64)
    test_case_id: str | None = Field(default=None, max_length=64)
    environment_id: str | None = Field(default=None, max_length=64)


class RunCompleteRequest(StrictModel):
    execution_status: RUN_STATUS_LITERAL
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    failure_reason: str | None = Field(default=None, max_length=4000)


class ResultCreateRequest(StrictModel):
    result_status: RESULT_STATUS_LITERAL
    run_id: str | None = Field(default=None, max_length=64)
    requirement_id: str | None = Field(default=None, max_length=64)
    criterion_id: str | None = Field(default=None, max_length=64)
    test_case_id: str | None = Field(default=None, max_length=64)
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    failure_reason: str | None = Field(default=None, max_length=4000)
    confidence_level: CONFIDENCE_LITERAL | None = None


class ResultWaiveRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=4000)


class RequirementInvalidateRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=4000)


RUNTIME_ENV_STATUS_LITERAL = Literal["READY", "BUSY", "STOPPED", "FAILED", "UNKNOWN"]
DEBUGGER_SEVERITY_LITERAL = Literal["FATAL", "ERROR", "WARNING", "INFO"]
DEBUGGER_ERROR_CATEGORY_LITERAL = Literal[
    "PARSER_ERROR",
    "SCRIPT_ERROR",
    "RUNTIME_ERROR",
    "INVALID_CALL",
    "INVALID_ACCESS",
    "NULL_REFERENCE",
    "RESOURCE_LOAD_ERROR",
    "NODE_NOT_FOUND",
    "SIGNAL_ERROR",
    "PHYSICS_ERROR",
    "ENGINE_CRASH",
    "WARNING",
    "INFO",
]
DEBUGGER_ERROR_STATUS_LITERAL = Literal["OPEN", "RESOLVED", "IGNORED"]


class RuntimeEnvironmentCreateRequest(StrictModel):
    project_revision: str = Field(default="", max_length=128)
    godot_version: str = Field(default="", max_length=32)
    platform: str = Field(default="", max_length=32)
    display_resolution: str = Field(default="", max_length=32)
    renderer: str = Field(default="", max_length=32)
    runtime_instance_id: str | None = Field(default=None, max_length=128)
    test_configuration: dict[str, Any] = Field(default_factory=dict)
    status: RUNTIME_ENV_STATUS_LITERAL = "READY"


class RuntimeEnvironmentUpdateRequest(StrictModel):
    status: RUNTIME_ENV_STATUS_LITERAL | None = None
    runtime_instance_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _require_change(self) -> RuntimeEnvironmentUpdateRequest:
        if self.status is None and self.runtime_instance_id is None:
            raise ValueError("至少需要提供 status 或 runtime_instance_id")
        return self


class DebuggerErrorItemRequest(StrictModel):
    category: DEBUGGER_ERROR_CATEGORY_LITERAL
    severity: DEBUGGER_SEVERITY_LITERAL
    message: str = Field(min_length=1, max_length=8000)
    source: str = Field(default="", max_length=64)
    scene: str | None = Field(default=None, max_length=256)
    node: str | None = Field(default=None, max_length=256)
    script: str | None = Field(default=None, max_length=512)
    stack_trace: str | None = Field(default=None, max_length=32000)
    runtime_instance_id: str | None = Field(default=None, max_length=128)
    godot_version: str | None = Field(default=None, max_length=32)
    project_revision: str | None = Field(default=None, max_length=128)
    changeset_id: str | None = Field(default=None, max_length=64)


class DebuggerErrorIngestRequest(StrictModel):
    errors: list[DebuggerErrorItemRequest] = Field(min_length=1, max_length=500)
    run_id: str | None = Field(default=None, max_length=64)
    project_revision: str | None = Field(default=None, max_length=128)
    baseline: bool = False


class DebuggerErrorResolveRequest(StrictModel):
    status: DEBUGGER_ERROR_STATUS_LITERAL = "RESOLVED"
    note: str | None = Field(default=None, max_length=4000)


class DebuggerGateRequest(StrictModel):
    block_new_fatal: bool = True
    block_new_error: bool = True
    require_approval_for_new_error: bool = False
    block_new_warning: bool = False
    warn_on_new_warning: bool = True


class EvidenceStaleRequest(StrictModel):
    project_revision: str = Field(min_length=1, max_length=128)


# ---- 缺陷与回归（T14 / T15） ----

DEFECT_SEVERITY_LITERAL = Literal["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "TRIVIAL"]
DEFECT_PRIORITY_LITERAL = Literal["P0", "P1", "P2", "P3"]
DEFECT_CATEGORY_LITERAL = Literal[
    "GAMEPLAY_LOGIC",
    "GDSCRIPT",
    "UI",
    "SCENE_STRUCTURE",
    "TILEMAP",
    "RESOURCE_IMPORT",
    "GODOT_INTEGRATION",
    "ASSET_QUALITY",
    "ANIMATION",
    "PERFORMANCE",
    "TEST_AUTOMATION",
    "SECURITY",
    "OTHER",
]
DEFECT_STATUS_LITERAL = Literal[
    "OPEN",
    "TRIAGED",
    "ASSIGNED",
    "IN_PROGRESS",
    "FIX_SUBMITTED",
    "VERIFYING",
    "RESOLVED",
    "REOPENED",
    "REJECTED",
]
REGRESSION_STRATEGY_LITERAL = Literal["TARGETED", "DEPENDENCY", "FULL", "SECURITY"]


class DefectCreateRequest(StrictModel):
    severity: DEFECT_SEVERITY_LITERAL
    category: DEFECT_CATEGORY_LITERAL
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=8000)
    priority: DEFECT_PRIORITY_LITERAL | None = None
    requirement_id: str | None = Field(default=None, max_length=64)
    source_result_id: str | None = Field(default=None, max_length=64)
    reproduction_steps: list[str] = Field(default_factory=list, max_length=100)
    expected_result: str = Field(default="", max_length=8000)
    actual_result: str = Field(default="", max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    assigned_agent_id: str | None = Field(default=None, max_length=64)
    related_changeset_id: str | None = Field(default=None, max_length=64)


class DefectTransitionRequest(StrictModel):
    status: DEFECT_STATUS_LITERAL
    assigned_agent_id: str | None = Field(default=None, max_length=64)
    resolution_reference: str | None = Field(default=None, max_length=256)
    note: str | None = Field(default=None, max_length=4000)


class ChangedFileRequest(StrictModel):
    resource_path: str = Field(min_length=1, max_length=512)
    operation_type: str = Field(default="MODIFY", max_length=32)
    risk_level: RISK_LEVEL_LITERAL = "MEDIUM"


class ImpactAnalysisRequest(StrictModel):
    changeset_id: str | None = Field(default=None, max_length=64)
    changed_files: list[ChangedFileRequest] = Field(default_factory=list, max_length=500)
    force_full: bool = False
    security_requested: bool = False

    @model_validator(mode="after")
    def _require_input(self) -> ImpactAnalysisRequest:
        if self.changeset_id is None and not self.changed_files:
            raise ValueError("至少需要提供 changeset_id 或 changed_files")
        return self


# ---- 质量门禁与 Phase Review（T16 / T17） ----

QUALITY_GATE_LITERAL = Literal[
    "GATE-1_REQUIREMENT_COMPLETENESS",
    "GATE-2_STATIC_VALIDATION",
    "GATE-3_STRUCTURAL_VALIDATION",
    "GATE-4_RUNTIME_VALIDATION",
    "GATE-5_FUNCTIONAL_VALIDATION",
    "GATE-6_EVIDENCE_COMPLETENESS",
    "GATE-7_DEFECT_STATUS",
    "GATE-8_REGRESSION_VALIDATION",
    "GATE-9_LICENSE_ASSET_VALIDATION",
    "GATE-10_SECURITY_VALIDATION",
]
PHASE_REVIEW_DECISION_LITERAL = Literal["ACCEPT", "REJECT", "REQUEST_REVISION"]
PHASE_REVIEW_STATUS_LITERAL = Literal[
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "ACCEPTED",
    "REJECTED",
    "REVISION_REQUIRED",
]


class GatePolicyCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    gates: list[QUALITY_GATE_LITERAL] = Field(default_factory=list, max_length=10)
    campaign_type: CAMPAIGN_TYPE_LITERAL | None = None
    risk_level: RISK_LEVEL_LITERAL | None = None
    waivers_allowed: bool = False
    created_by: str | None = Field(default=None, max_length=64)


class GateEvaluateRequest(StrictModel):
    campaign_id: str = Field(min_length=1, max_length=64)
    policy_id: str | None = Field(default=None, max_length=64)
    risk_level: RISK_LEVEL_LITERAL | None = None


class GateWaiverRequest(StrictModel):
    authorized_by: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=4000)
    risk_statement: str = Field(min_length=1, max_length=4000)
    scope: str = Field(min_length=1, max_length=256)
    expires_at: datetime


class PhaseReviewCreateRequest(StrictModel):
    workflow_id: str = Field(min_length=1, max_length=64)
    phase_id: str = Field(min_length=1, max_length=64)
    campaign_id: str | None = Field(default=None, max_length=64)
    goals: list[str] = Field(default_factory=list, max_length=100)
    completed: list[str] = Field(default_factory=list, max_length=200)
    incomplete: list[str] = Field(default_factory=list, max_length=200)
    user_confirmations: list[str] = Field(default_factory=list, max_length=100)


class PhaseReviewSubmitRequest(StrictModel):
    submitted_by: str | None = Field(default=None, max_length=64)


class PhaseReviewDecisionRequest(StrictModel):
    decision: PHASE_REVIEW_DECISION_LITERAL
    actor_id: str = Field(min_length=1, max_length=64)
    comment: str = Field(default="", max_length=4000)


# ---- Agent 集成与验证预算（T19） ----


class AgentRunRequest(StrictModel):
    """Agent 请求执行；预算上限由策略决定，Agent 不能自行放宽。"""

    risk_level: RISK_LEVEL_LITERAL = "MEDIUM"
    plan_id: str | None = Field(default=None, max_length=64)
    test_suite_id: str | None = Field(default=None, max_length=64)
    test_case_id: str | None = Field(default=None, max_length=64)
    environment_id: str | None = Field(default=None, max_length=64)
