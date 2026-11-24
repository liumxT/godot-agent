"""Verification 服务（E9-T01 / T02 / T03）。

职责边界：

- 本服务拥有 Campaign / Plan / Run / Result / Evidence 状态，拥有验收标准与
  需求-测试追踪关系；
- 不修改 Task、Workflow、ChangeSet、Approval 状态，只保存引用；
- 通过必须有有效证据；失败必须给出原因；UNKNOWN 与 FAILED 分离；
- 未执行（NOT_RUN）与跳过（SKIPPED）不计入通过率。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    AgentBudgetExceeded,
    NotFoundError,
    ValidationFailed,
    VerificationEvidenceInvalid,
    VerificationEvidenceStale,
    VerificationPlanInvalid,
    VerificationRequirementUntraceable,
    VerificationResultInvalid,
    VerificationStateInvalid,
    VersionConflict,
)
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.verification.agent_policy import (
    AGENT_ACTION_REQUEST_RUN,
    AGENT_ACTION_REQUEST_VERIFICATION,
    AGENT_ALLOWED_ACTIONS,
    AGENT_FORBIDDEN_ACTIONS,
    BUDGET_REGRESSIONS,
    BUDGET_RETRIES,
    BUDGET_RUNTIME_SECONDS,
    BUDGET_SCREENSHOTS,
    BUDGET_TEST_RUNS,
    BUDGET_VIDEOS,
    DEFAULT_BUDGET_BY_RISK,
    VERIFICATION_BUDGET_DIMENSIONS,
    VerificationBudgetLimits,
    budget_limits_for,
    budget_statuses,
    ensure_agent_action_allowed,
    exhausted_dimensions,
)
from modules.verification.debugger import (
    DebuggerErrorInput,
    DebuggerGateDecision,
    DebuggerGatePolicy,
    build_snapshot,
    evaluate_gate,
    fingerprint_error,
)
from modules.verification.defect import (
    default_priority,
    recommend_agent,
)
from modules.verification.defect import (
    defect_summary as summarize_defects,
)
from modules.verification.evidence import (
    evidence_context_problems,
    verify_file_reference,
)
from modules.verification.impact import (
    ChangedFile,
    DefectRef,
    LinkRef,
    TestCaseRef,
    build_regression_plan,
    coerce_changed_file,
    is_security_sensitive,
    scan_reverse_dependencies,
)
from modules.verification.impact import (
    RegressionPlan as ImpactPlan,
)
from modules.verification.models import (
    AUTOMATION_LEVELS,
    CAMPAIGN_DRAFT,
    CAMPAIGN_PLANNING,
    CAMPAIGN_READY,
    CAMPAIGN_RUNNING,
    CAMPAIGN_STATUSES,
    CAMPAIGN_TRANSITIONS,
    CAMPAIGN_TYPE_ASSET,
    CAMPAIGN_TYPES,
    COVERAGE_TYPES,
    CRITERION_ACTIVE,
    CRITERION_TYPES,
    DEBUGGER_ERROR_CATEGORIES,
    DEBUGGER_ERROR_STATUSES,
    DEBUGGER_SEVERITIES,
    DEFECT_ACTIVE_STATUSES,
    DEFECT_ASSIGNED,
    DEFECT_BLOCKER,
    DEFECT_CATEGORIES,
    DEFECT_CRITICAL,
    DEFECT_OPEN,
    DEFECT_PRIORITIES,
    DEFECT_RESOLVED,
    DEFECT_SEVERITIES,
    DEFECT_STATUSES,
    DEFECT_TRANSITIONS,
    ERROR_STATUS_IGNORED,
    ERROR_STATUS_OPEN,
    ERROR_STATUS_RESOLVED,
    EVIDENCE_SOURCE_TYPES,
    EVIDENCE_TRANSITIONS,
    EVIDENCE_TYPE_SCREENSHOT,
    EVIDENCE_TYPE_VIDEO,
    EVIDENCE_TYPES,
    EVIDENCE_VALID,
    EVIDENCE_VALIDITY_STATUSES,
    EXECUTED_RESULT_STATUSES,
    GATE_DEFECT,
    GATE_EVIDENCE,
    GATE_FAILED,
    GATE_FUNCTIONAL,
    GATE_LICENSE,
    GATE_NOT_REQUIRED,
    GATE_PASSED,
    GATE_PENDING,
    GATE_REGRESSION,
    GATE_REQUIREMENT_COMPLETENESS,
    GATE_RUNTIME,
    GATE_SECURITY,
    GATE_STATIC,
    GATE_STRUCTURAL,
    GATE_TRANSITIONS,
    GATE_UNKNOWN,
    GATE_WAIVED,
    PHASE_REVIEW_DECISION_STATUS,
    PHASE_REVIEW_DECISIONS,
    PHASE_REVIEW_DRAFT,
    PHASE_REVIEW_STATUSES,
    PHASE_REVIEW_SUBMITTED,
    PHASE_REVIEW_TRANSITIONS,
    PHASE_REVIEW_UNDER_REVIEW,
    PLAN_READY,
    PLAN_STATUSES,
    PLAN_TRANSITIONS,
    QUALITY_GATES,
    REGRESSION_STRATEGIES,
    RESULT_FAILED,
    RESULT_NOT_RUN,
    RESULT_PASSED,
    RESULT_SKIPPED,
    RESULT_STATUSES,
    RESULT_TRANSITIONS,
    RESULT_UNKNOWN,
    RESULT_WAIVED,
    RISK_LEVELS,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_STATUSES,
    RUN_TRANSITIONS,
    RUN_UNKNOWN,
    RUNTIME_ENV_READY,
    RUNTIME_ENVIRONMENT_STATUSES,
    TEST_CASE_ACTIVE,
    TEST_CASE_STATUSES,
    TEST_TYPES,
    VERIFICATION_LAYERS,
    VERIFICATION_METHODS,
    PhaseReviewDecisionModel,
    PhaseReviewModel,
    QualityGatePolicyModel,
    QualityGateResultModel,
    QualityGateWaiverModel,
    VerificationCampaignModel,
    VerificationCriterionModel,
    VerificationDebuggerErrorModel,
    VerificationDefectModel,
    VerificationEvidenceModel,
    VerificationPlanModel,
    VerificationRegressionPlanModel,
    VerificationResultModel,
    VerificationRunModel,
    VerificationRuntimeEnvironmentModel,
    VerificationTestCaseModel,
    VerificationTestLinkModel,
)
from modules.verification.phase_review import (
    build_review_summary,
    recommendation_for,
)
from modules.verification.planner import (
    TEST_TYPE_TO_LAYER,
    PlanProposal,
    build_plan_proposal,
)
from modules.verification.quality_gate import (
    GateOutcome,
    GateWaiver,
    combine_outcomes,
    layer_gate,
    required_gates,
    waiver_problem,
)
from modules.verification.repository import (
    CampaignRepository,
    CriterionRepository,
    DebuggerErrorRepository,
    DefectRepository,
    EvidenceRepository,
    PhaseReviewDecisionRepository,
    PhaseReviewRepository,
    PlanRepository,
    QualityGatePolicyRepository,
    QualityGateResultRepository,
    QualityGateWaiverRepository,
    RegressionPlanRepository,
    ResultRepository,
    RunRepository,
    RuntimeEnvironmentRepository,
    TestCaseRepository,
    TestLinkRepository,
)

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CONFIDENCE_LEVELS = frozenset({"HIGH", "MEDIUM", "LOW"})
_REQUIREMENT_NOT_TESTABLE = frozenset({"REJECTED", "DEFERRED"})


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _ensure_transition(
    transitions: dict[str, frozenset[str]], current: str, target: str, subject: str
) -> None:
    allowed = transitions.get(current)
    if allowed is None or target not in allowed:
        raise VerificationStateInvalid(
            f"{subject} 状态迁移不被允许",
            details={"current": current, "target": target},
        )


@dataclass(frozen=True, slots=True)
class CampaignView:
    campaign_id: str
    project_id: str
    workflow_id: str | None
    phase_id: str | None
    task_id: str | None
    changeset_id: str | None
    campaign_type: str
    status: str
    verification_policy_id: str | None
    created_by: str | None
    version: int
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PlanView:
    plan_id: str
    campaign_id: str
    requirement_ids: tuple[str, ...]
    test_suite_ids: tuple[str, ...]
    verification_layers: tuple[str, ...]
    environment_profile: str | None
    target_platforms: tuple[str, ...]
    acceptance_policy: dict[str, Any]
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TestCaseView:
    test_case_id: str
    project_id: str
    name: str
    description: str | None
    test_type: str
    execution_method: str
    preconditions: tuple[str, ...]
    setup: tuple[str, ...]
    steps: tuple[str, ...]
    expected_result: str
    cleanup: tuple[str, ...]
    timeout_seconds: int
    evidence_requirements: tuple[str, ...]
    risk_level: str
    automation_level: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CriterionView:
    criterion_id: str
    project_id: str
    requirement_id: str
    criterion_type: str
    statement: str
    verification_method: str
    expected: dict[str, Any]
    threshold: dict[str, Any]
    required_evidence: tuple[str, ...]
    priority: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TestLinkView:
    link_id: str
    requirement_id: str
    criterion_id: str | None
    test_case_id: str
    coverage_type: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RunView:
    run_id: str
    campaign_id: str
    plan_id: str | None
    test_suite_id: str | None
    test_case_id: str | None
    environment_id: str | None
    execution_status: str
    started_at: datetime | None
    completed_at: datetime | None
    executor_id: str | None
    evidence_ids: tuple[str, ...]
    failure_reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ResultView:
    result_id: str
    campaign_id: str
    run_id: str | None
    requirement_id: str | None
    criterion_id: str | None
    test_case_id: str | None
    result_status: str
    evidence_ids: tuple[str, ...]
    failure_reason: str | None
    confidence_level: str | None
    verified_at: datetime | None
    superseded_by: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceView:
    evidence_id: str
    project_id: str
    evidence_type: str
    source_type: str
    source_reference: str
    content_hash: str
    verification_run_id: str | None
    captured_at: datetime
    validity_status: str
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeEnvironmentView:
    environment_id: str
    project_id: str
    project_revision: str
    godot_version: str
    platform: str
    display_resolution: str
    renderer: str
    runtime_instance_id: str | None
    test_configuration: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DebuggerErrorView:
    error_id: str
    project_id: str
    run_id: str | None
    fingerprint: str
    category: str
    severity: str
    message: str
    source: str
    scene: str | None
    node: str | None
    script: str | None
    stack_trace: str | None
    runtime_instance_id: str | None
    godot_version: str | None
    project_revision: str | None
    changeset_id: str | None
    occurrences: int
    is_baseline: bool
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DefectView:
    defect_id: str
    project_id: str
    requirement_id: str | None
    source_result_id: str | None
    severity: str
    priority: str
    category: str
    title: str
    description: str
    reproduction_steps: tuple[str, ...]
    expected_result: str
    actual_result: str
    evidence_ids: tuple[str, ...]
    assigned_agent_id: str | None
    status: str
    related_changeset_id: str | None
    resolution_reference: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RegressionPlanView:
    regression_plan_id: str
    project_id: str
    changeset_id: str | None
    strategy: str
    risk_level: str
    changed_files: tuple[str, ...]
    affected_requirements: tuple[str, ...]
    affected_test_cases: tuple[str, ...]
    affected_scenes: tuple[str, ...]
    affected_scripts: tuple[str, ...]
    affected_resources: tuple[str, ...]
    dependents: tuple[str, ...]
    historical_defects: tuple[str, ...]
    coverage_gaps: tuple[str, ...]
    required_checks: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GatePolicyView:
    gate_policy_id: str
    project_id: str
    name: str
    campaign_type: str | None
    risk_level: str | None
    required_gates: tuple[str, ...]
    waivers_allowed: bool
    created_by: str | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GateResultView:
    gate_result_id: str
    project_id: str
    campaign_id: str
    gate_policy_id: str | None
    gate_name: str
    status: str
    blocking: bool
    reason: str
    details: dict[str, Any]
    evaluated_at: datetime
    waiver: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class GateEvaluationView:
    project_id: str
    campaign_id: str
    gate_policy_id: str | None
    evaluated_at: datetime
    decision: dict[str, Any]
    gates: tuple[GateResultView, ...]


@dataclass(frozen=True, slots=True)
class PhaseReviewView:
    review_id: str
    project_id: str
    workflow_id: str
    phase_id: str
    campaign_id: str | None
    status: str
    summary: dict[str, Any]
    recommendation: str
    submitted_by: str | None
    submitted_at: datetime | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime
    decisions: tuple[dict[str, Any], ...]


def _campaign_view(entity: VerificationCampaignModel) -> CampaignView:
    return CampaignView(
        campaign_id=entity.campaign_id,
        project_id=entity.project_id,
        workflow_id=entity.workflow_id,
        phase_id=entity.phase_id,
        task_id=entity.task_id,
        changeset_id=entity.changeset_id,
        campaign_type=entity.campaign_type,
        status=entity.status,
        verification_policy_id=entity.verification_policy_id,
        created_by=entity.created_by,
        version=entity.version,
        created_at=entity.created_at,
        completed_at=entity.completed_at,
    )


def _plan_view(entity: VerificationPlanModel) -> PlanView:
    return PlanView(
        plan_id=entity.plan_id,
        campaign_id=entity.campaign_id,
        requirement_ids=tuple(str(item) for item in _load(entity.requirement_ids_json, [])),
        test_suite_ids=tuple(str(item) for item in _load(entity.test_suite_ids_json, [])),
        verification_layers=tuple(str(item) for item in _load(entity.verification_layers_json, [])),
        environment_profile=entity.environment_profile,
        target_platforms=tuple(str(item) for item in _load(entity.target_platforms_json, [])),
        acceptance_policy=_load(entity.acceptance_policy_json, {}),
        status=entity.status,
        created_at=entity.created_at,
    )


def _test_case_view(entity: VerificationTestCaseModel) -> TestCaseView:
    return TestCaseView(
        test_case_id=entity.test_case_id,
        project_id=entity.project_id,
        name=entity.name,
        description=entity.description,
        test_type=entity.test_type,
        execution_method=entity.execution_method,
        preconditions=tuple(str(item) for item in _load(entity.preconditions_json, [])),
        setup=tuple(str(item) for item in _load(entity.setup_json, [])),
        steps=tuple(str(item) for item in _load(entity.steps_json, [])),
        expected_result=entity.expected_result,
        cleanup=tuple(str(item) for item in _load(entity.cleanup_json, [])),
        timeout_seconds=entity.timeout_seconds,
        evidence_requirements=tuple(
            str(item) for item in _load(entity.evidence_requirements_json, [])
        ),
        risk_level=entity.risk_level,
        automation_level=entity.automation_level,
        status=entity.status,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _criterion_view(entity: VerificationCriterionModel) -> CriterionView:
    return CriterionView(
        criterion_id=entity.criterion_id,
        project_id=entity.project_id,
        requirement_id=entity.requirement_id,
        criterion_type=entity.criterion_type,
        statement=entity.statement,
        verification_method=entity.verification_method,
        expected=_load(entity.expected_json, {}),
        threshold=_load(entity.threshold_json, {}),
        required_evidence=tuple(str(item) for item in _load(entity.required_evidence_json, [])),
        priority=entity.priority,
        status=entity.status,
        version=entity.version,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _link_view(entity: VerificationTestLinkModel) -> TestLinkView:
    return TestLinkView(
        link_id=entity.link_id,
        requirement_id=entity.requirement_id,
        criterion_id=entity.criterion_id,
        test_case_id=entity.test_case_id,
        coverage_type=entity.coverage_type,
        created_at=entity.created_at,
    )


def _run_view(entity: VerificationRunModel) -> RunView:
    return RunView(
        run_id=entity.run_id,
        campaign_id=entity.campaign_id,
        plan_id=entity.plan_id,
        test_suite_id=entity.test_suite_id,
        test_case_id=entity.test_case_id,
        environment_id=entity.environment_id,
        execution_status=entity.execution_status,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        executor_id=entity.executor_id,
        evidence_ids=tuple(str(item) for item in _load(entity.evidence_ids_json, [])),
        failure_reason=entity.failure_reason,
        created_at=entity.created_at,
    )


def _result_view(entity: VerificationResultModel) -> ResultView:
    return ResultView(
        result_id=entity.result_id,
        campaign_id=entity.campaign_id,
        run_id=entity.run_id,
        requirement_id=entity.requirement_id,
        criterion_id=entity.criterion_id,
        test_case_id=entity.test_case_id,
        result_status=entity.result_status,
        evidence_ids=tuple(str(item) for item in _load(entity.evidence_ids_json, [])),
        failure_reason=entity.failure_reason,
        confidence_level=entity.confidence_level,
        verified_at=entity.verified_at,
        superseded_by=entity.superseded_by,
        created_at=entity.created_at,
    )


def _evidence_view(entity: VerificationEvidenceModel) -> EvidenceView:
    return EvidenceView(
        evidence_id=entity.evidence_id,
        project_id=entity.project_id,
        evidence_type=entity.evidence_type,
        source_type=entity.source_type,
        source_reference=entity.source_reference,
        content_hash=entity.content_hash,
        verification_run_id=entity.verification_run_id,
        captured_at=entity.captured_at,
        validity_status=entity.validity_status,
        metadata=_load(entity.metadata_json, {}),
        created_at=entity.created_at,
    )


def _runtime_environment_view(
    entity: VerificationRuntimeEnvironmentModel,
) -> RuntimeEnvironmentView:
    return RuntimeEnvironmentView(
        environment_id=entity.environment_id,
        project_id=entity.project_id,
        project_revision=entity.project_revision,
        godot_version=entity.godot_version,
        platform=entity.platform,
        display_resolution=entity.display_resolution,
        renderer=entity.renderer,
        runtime_instance_id=entity.runtime_instance_id,
        test_configuration=_load(entity.test_configuration_json, {}),
        status=entity.status,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _debugger_error_view(entity: VerificationDebuggerErrorModel) -> DebuggerErrorView:
    return DebuggerErrorView(
        error_id=entity.error_id,
        project_id=entity.project_id,
        run_id=entity.run_id,
        fingerprint=entity.fingerprint,
        category=entity.category,
        severity=entity.severity,
        message=entity.message,
        source=entity.source,
        scene=entity.scene,
        node=entity.node,
        script=entity.script,
        stack_trace=entity.stack_trace,
        runtime_instance_id=entity.runtime_instance_id,
        godot_version=entity.godot_version,
        project_revision=entity.project_revision,
        changeset_id=entity.changeset_id,
        occurrences=entity.occurrences,
        is_baseline=entity.is_baseline,
        status=entity.status,
        first_seen_at=entity.first_seen_at,
        last_seen_at=entity.last_seen_at,
        metadata=_load(entity.metadata_json, {}),
        created_at=entity.created_at,
    )


def _defect_view(entity: VerificationDefectModel) -> DefectView:
    return DefectView(
        defect_id=entity.defect_id,
        project_id=entity.project_id,
        requirement_id=entity.requirement_id,
        source_result_id=entity.source_result_id,
        severity=entity.severity,
        priority=entity.priority,
        category=entity.category,
        title=entity.title,
        description=entity.description,
        reproduction_steps=tuple(str(item) for item in _load(entity.reproduction_steps_json, [])),
        expected_result=entity.expected_result,
        actual_result=entity.actual_result,
        evidence_ids=tuple(str(item) for item in _load(entity.evidence_ids_json, [])),
        assigned_agent_id=entity.assigned_agent_id,
        status=entity.status,
        related_changeset_id=entity.related_changeset_id,
        resolution_reference=entity.resolution_reference,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _regression_plan_view(
    entity: VerificationRegressionPlanModel,
) -> RegressionPlanView:
    def _items(name: str) -> tuple[str, ...]:
        return tuple(str(item) for item in _load(getattr(entity, name), []))

    return RegressionPlanView(
        regression_plan_id=entity.regression_plan_id,
        project_id=entity.project_id,
        changeset_id=entity.changeset_id,
        strategy=entity.strategy,
        risk_level=entity.risk_level,
        changed_files=_items("changed_files_json"),
        affected_requirements=_items("affected_requirements_json"),
        affected_test_cases=_items("affected_test_cases_json"),
        affected_scenes=_items("affected_scenes_json"),
        affected_scripts=_items("affected_scripts_json"),
        affected_resources=_items("affected_resources_json"),
        dependents=_items("dependents_json"),
        historical_defects=_items("historical_defects_json"),
        coverage_gaps=_items("coverage_gaps_json"),
        required_checks=_items("required_checks_json"),
        created_at=entity.created_at,
    )


def _gate_policy_view(entity: QualityGatePolicyModel) -> GatePolicyView:
    return GatePolicyView(
        gate_policy_id=entity.gate_policy_id,
        project_id=entity.project_id,
        name=entity.name,
        campaign_type=entity.campaign_type,
        risk_level=entity.risk_level,
        required_gates=tuple(str(item) for item in _load(entity.required_gates_json, [])),
        waivers_allowed=entity.waivers_allowed,
        created_by=entity.created_by,
        version=entity.version,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _waiver_dict(entity: QualityGateWaiverModel) -> dict[str, Any]:
    return {
        "waiver_id": entity.waiver_id,
        "gate_result_id": entity.gate_result_id,
        "authorized_by": entity.authorized_by,
        "reason": entity.reason,
        "risk_statement": entity.risk_statement,
        "scope": entity.scope,
        "expires_at": entity.expires_at,
        "created_at": entity.created_at,
        "revoked_at": entity.revoked_at,
    }


def _gate_result_view(
    entity: QualityGateResultModel,
    waiver: QualityGateWaiverModel | None = None,
) -> GateResultView:
    return GateResultView(
        gate_result_id=entity.gate_result_id,
        project_id=entity.project_id,
        campaign_id=entity.campaign_id,
        gate_policy_id=entity.gate_policy_id,
        gate_name=entity.gate_name,
        status=entity.status,
        blocking=entity.blocking,
        reason=entity.reason,
        details=_load(entity.details_json, {}),
        evaluated_at=entity.evaluated_at,
        waiver=_waiver_dict(waiver) if waiver is not None else None,
    )


def _phase_review_view(
    entity: PhaseReviewModel,
    decisions: Sequence[PhaseReviewDecisionModel] = (),
) -> PhaseReviewView:
    return PhaseReviewView(
        review_id=entity.review_id,
        project_id=entity.project_id,
        workflow_id=entity.workflow_id,
        phase_id=entity.phase_id,
        campaign_id=entity.campaign_id,
        status=entity.status,
        summary=_load(entity.summary_json, {}),
        recommendation=entity.recommendation,
        submitted_by=entity.submitted_by,
        submitted_at=entity.submitted_at,
        decided_by=entity.decided_by,
        decided_at=entity.decided_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        decisions=tuple(
            {
                "decision_id": item.decision_id,
                "decision": item.decision,
                "actor_id": item.actor_id,
                "comment": item.comment,
                "decided_at": item.decided_at,
            }
            for item in decisions
        ),
    )


class VerificationService:
    """验证活动、执行、结果与证据的唯一入口。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        requirements: Any | None = None,
        projects: Any | None = None,
        changesets: Any | None = None,
    ) -> None:
        self._database = database
        self._requirements = requirements
        self._projects = projects
        self._changesets = changesets

    # ---- Campaign ----

    async def create_campaign(
        self,
        *,
        project_id: str,
        campaign_type: str,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        task_id: str | None = None,
        changeset_id: str | None = None,
        verification_policy_id: str | None = None,
        created_by: str | None = None,
    ) -> CampaignView:
        if not project_id:
            raise ValidationFailed("project_id 不能为空")
        if campaign_type not in CAMPAIGN_TYPES:
            raise ValidationFailed(
                "未知验证活动类型",
                details={"campaign_type": campaign_type, "allowed": sorted(CAMPAIGN_TYPES)},
            )
        now = utcnow()
        entity = VerificationCampaignModel(
            campaign_id=_new_id("vcp"),
            project_id=project_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            task_id=task_id,
            changeset_id=changeset_id,
            campaign_type=campaign_type,
            status=CAMPAIGN_DRAFT,
            verification_policy_id=verification_policy_id,
            created_by=created_by,
            version=1,
            created_at=now,
            completed_at=None,
        )
        async with self._database.session() as session, transaction(session):
            await CampaignRepository(session).add(entity)
        return _campaign_view(entity)

    async def get_campaign(self, campaign_id: str) -> CampaignView:
        async with self._database.session() as session:
            entity = await CampaignRepository(session).get(campaign_id)
        if entity is None:
            raise NotFoundError("验证活动不存在", details={"campaign_id": campaign_id})
        return _campaign_view(entity)

    async def list_campaigns(
        self,
        project_id: str,
        *,
        status: str | None = None,
        campaign_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in CAMPAIGN_STATUSES:
            raise ValidationFailed("未知验证活动状态", details={"status": status})
        async with self._database.session() as session:
            page = await CampaignRepository(session).list_page(
                project_id=project_id,
                status=status,
                campaign_type=campaign_type,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_campaign_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def transition_campaign(self, campaign_id: str, status: str) -> CampaignView:
        if status not in CAMPAIGN_STATUSES:
            raise ValidationFailed("未知验证活动状态", details={"status": status})
        async with self._database.session() as session, transaction(session):
            repository = CampaignRepository(session)
            entity = await repository.get(campaign_id)
            if entity is None:
                raise NotFoundError("验证活动不存在", details={"campaign_id": campaign_id})
            _ensure_transition(CAMPAIGN_TRANSITIONS, entity.status, status, "验证活动")
            completed_at = utcnow() if status in {"COMPLETED", "FAILED", "CANCELLED"} else None
            moved = await repository.transition(
                campaign_id,
                from_statuses=frozenset({entity.status}),
                to_status=status,
                expected_version=entity.version,
                now=utcnow(),
                completed_at=completed_at,
            )
            if not moved:
                raise VersionConflict("验证活动已被并发修改，请重新读取")
            updated = await repository.get(campaign_id)
        assert updated is not None
        return _campaign_view(updated)

    # ---- Plan ----

    async def create_plan(
        self,
        campaign_id: str,
        *,
        requirement_ids: tuple[str, ...] = (),
        test_suite_ids: tuple[str, ...] = (),
        verification_layers: tuple[str, ...] = (),
        environment_profile: str | None = None,
        target_platforms: tuple[str, ...] = (),
        acceptance_policy: dict[str, Any] | None = None,
    ) -> PlanView:
        layers = tuple(dict.fromkeys(verification_layers))
        if not layers:
            raise VerificationPlanInvalid("验证计划必须声明至少一个验证层次")
        unknown_layers = sorted(set(layers) - set(VERIFICATION_LAYERS))
        if unknown_layers:
            raise VerificationPlanInvalid(
                "存在未知验证层次",
                details={"layers": unknown_layers, "allowed": list(VERIFICATION_LAYERS)},
            )
        requirements = tuple(dict.fromkeys(requirement_ids))
        platforms = tuple(dict.fromkeys(target_platforms))
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            campaigns = CampaignRepository(session)
            campaign = await campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError("验证活动不存在", details={"campaign_id": campaign_id})
            if campaign.status not in {CAMPAIGN_DRAFT, CAMPAIGN_PLANNING, CAMPAIGN_READY}:
                raise VerificationStateInvalid(
                    "当前验证活动状态不能创建计划",
                    details={"status": campaign.status},
                )
            current = campaign
            for target in (CAMPAIGN_PLANNING, CAMPAIGN_READY):
                if current.status == target:
                    continue
                _ensure_transition(CAMPAIGN_TRANSITIONS, current.status, target, "验证活动")
                moved = await campaigns.transition(
                    campaign_id,
                    from_statuses=frozenset({current.status}),
                    to_status=target,
                    expected_version=current.version,
                    now=now,
                )
                if not moved:
                    raise VersionConflict("验证活动已被并发修改，请重新读取")
                current = await campaigns.get(campaign_id)
            entity = VerificationPlanModel(
                plan_id=_new_id("vpl"),
                campaign_id=campaign_id,
                requirement_ids_json=_dump(list(requirements)),
                test_suite_ids_json=_dump(list(test_suite_ids)),
                verification_layers_json=_dump(list(layers)),
                environment_profile=environment_profile,
                target_platforms_json=_dump(list(platforms)),
                acceptance_policy_json=_dump(acceptance_policy or {}),
                status=PLAN_READY,
                created_at=now,
            )
            await PlanRepository(session).add(entity)
        return _plan_view(entity)

    async def get_plan(self, plan_id: str) -> PlanView:
        async with self._database.session() as session:
            entity = await PlanRepository(session).get(plan_id)
        if entity is None:
            raise NotFoundError("验证计划不存在", details={"plan_id": plan_id})
        return _plan_view(entity)

    async def latest_plan(self, campaign_id: str) -> PlanView | None:
        async with self._database.session() as session:
            entity = await PlanRepository(session).get_for_campaign(campaign_id)
        return None if entity is None else _plan_view(entity)

    async def transition_plan(self, plan_id: str, status: str) -> PlanView:
        if status not in PLAN_STATUSES:
            raise ValidationFailed("未知验证计划状态", details={"status": status})
        async with self._database.session() as session, transaction(session):
            repository = PlanRepository(session)
            entity = await repository.get(plan_id)
            if entity is None:
                raise NotFoundError("验证计划不存在", details={"plan_id": plan_id})
            _ensure_transition(PLAN_TRANSITIONS, entity.status, status, "验证计划")
            moved = await repository.set_status(
                plan_id, from_statuses=frozenset({entity.status}), to_status=status
            )
            if not moved:
                raise VersionConflict("验证计划已被并发修改，请重新读取")
            updated = await repository.get(plan_id)
        assert updated is not None
        return _plan_view(updated)

    # ---- 验收标准与追踪 ----

    async def register_test_case(
        self,
        *,
        project_id: str,
        name: str,
        test_type: str,
        execution_method: str,
        description: str | None = None,
        preconditions: tuple[str, ...] = (),
        setup: tuple[str, ...] = (),
        steps: tuple[str, ...] = (),
        expected_result: str = "",
        cleanup: tuple[str, ...] = (),
        timeout_seconds: int = 300,
        evidence_requirements: tuple[str, ...] = (),
        risk_level: str = "MEDIUM",
        automation_level: str = "MANUAL",
        status: str = TEST_CASE_ACTIVE,
    ) -> TestCaseView:
        if test_type not in TEST_TYPES:
            raise ValidationFailed(
                "未知测试类型", details={"test_type": test_type, "allowed": sorted(TEST_TYPES)}
            )
        if risk_level not in RISK_LEVELS:
            raise ValidationFailed("未知风险级别", details={"risk_level": risk_level})
        if automation_level not in AUTOMATION_LEVELS:
            raise ValidationFailed("未知自动化级别", details={"automation_level": automation_level})
        if status not in TEST_CASE_STATUSES:
            raise ValidationFailed("未知测试用例状态", details={"status": status})
        if timeout_seconds <= 0:
            raise ValidationFailed("测试用例超时必须大于 0")
        if not name.strip():
            raise ValidationFailed("测试用例名称不能为空")
        if not execution_method.strip():
            raise ValidationFailed("测试用例必须声明执行方式")
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repository = TestCaseRepository(session)
            if await repository.get_by_name(project_id, name):
                raise VerificationStateInvalid(
                    "同名测试用例已存在", details={"project_id": project_id, "name": name}
                )
            entity = VerificationTestCaseModel(
                test_case_id=_new_id("vtc"),
                project_id=project_id,
                name=name,
                description=description,
                test_type=test_type,
                execution_method=execution_method,
                preconditions_json=_dump(list(preconditions)),
                setup_json=_dump(list(setup)),
                steps_json=_dump(list(steps)),
                expected_result=expected_result,
                cleanup_json=_dump(list(cleanup)),
                timeout_seconds=timeout_seconds,
                evidence_requirements_json=_dump(list(evidence_requirements)),
                risk_level=risk_level,
                automation_level=automation_level,
                status=status,
                created_at=now,
                updated_at=now,
            )
            await repository.add(entity)
        return _test_case_view(entity)

    async def list_test_cases(
        self,
        project_id: str,
        *,
        test_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await TestCaseRepository(session).list_page(
                project_id=project_id,
                test_type=test_type,
                status=status,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_test_case_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def get_test_case(self, test_case_id: str) -> TestCaseView:
        async with self._database.session() as session:
            entity = await TestCaseRepository(session).get(test_case_id)
        if entity is None:
            raise NotFoundError("测试用例不存在", details={"test_case_id": test_case_id})
        return _test_case_view(entity)

    async def propose_plan(
        self,
        project_id: str,
        requirement_ids: tuple[str, ...],
        *,
        target_platforms: tuple[str, ...] = (),
        environment_profile: str | None = None,
        acceptance_policy: dict[str, Any] | None = None,
    ) -> PlanProposal:
        """根据验收标准与追踪关系推导验证计划；不写库、不改变活动状态。"""

        criteria_by: dict[str, list[CriterionView]] = {}
        links_by: dict[str, list[TestLinkView]] = {}
        test_case_ids: list[str] = []
        async with self._database.session() as session:
            criteria_repository = CriterionRepository(session)
            link_repository = TestLinkRepository(session)
            for requirement_id in requirement_ids:
                criteria_by[requirement_id] = [
                    _criterion_view(item)
                    for item in await criteria_repository.list_for_requirement(requirement_id)
                ]
                links = [
                    _link_view(item)
                    for item in await link_repository.list_for_requirement(requirement_id)
                ]
                links_by[requirement_id] = links
                for link in links:
                    if link.test_case_id not in test_case_ids:
                        test_case_ids.append(link.test_case_id)
            rows = await TestCaseRepository(session).list_by_ids(test_case_ids)
        test_cases = {entity.test_case_id: _test_case_view(entity) for entity in rows}
        return build_plan_proposal(
            project_id=project_id,
            requirement_ids=requirement_ids,
            criteria_by_requirement=criteria_by,
            links_by_requirement=links_by,
            test_cases=test_cases,
            target_platforms=target_platforms,
            environment_profile=environment_profile,
            acceptance_policy=acceptance_policy,
        )

    async def register_criterion(
        self,
        *,
        project_id: str,
        requirement_id: str,
        criterion_type: str,
        statement: str,
        verification_method: str,
        expected: dict[str, Any] | None = None,
        threshold: dict[str, Any] | None = None,
        required_evidence: tuple[str, ...] = (),
        priority: str = "MEDIUM",
    ) -> CriterionView:
        if criterion_type not in CRITERION_TYPES:
            raise ValidationFailed(
                "未知验收标准类型",
                details={"criterion_type": criterion_type, "allowed": sorted(CRITERION_TYPES)},
            )
        if verification_method not in VERIFICATION_METHODS:
            raise ValidationFailed(
                "未知验证方法",
                details={
                    "verification_method": verification_method,
                    "allowed": sorted(VERIFICATION_METHODS),
                },
            )
        if priority not in RISK_LEVELS:
            raise ValidationFailed("未知优先级", details={"priority": priority})
        if not statement.strip():
            raise VerificationRequirementUntraceable("验收标准必须包含可判定的描述")
        if not requirement_id:
            raise VerificationRequirementUntraceable("验收标准必须关联正式需求")
        await self._ensure_requirement(requirement_id)
        now = utcnow()
        entity = VerificationCriterionModel(
            criterion_id=_new_id("vcr"),
            project_id=project_id,
            requirement_id=requirement_id,
            criterion_type=criterion_type,
            statement=statement,
            verification_method=verification_method,
            expected_json=_dump(expected or {}),
            threshold_json=_dump(threshold or {}),
            required_evidence_json=_dump(list(required_evidence)),
            priority=priority,
            status=CRITERION_ACTIVE,
            version=1,
            created_at=now,
            updated_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await CriterionRepository(session).add(entity)
        return _criterion_view(entity)

    async def list_criteria(
        self,
        project_id: str,
        *,
        status: str | None = None,
        criterion_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await CriterionRepository(session).list_page(
                project_id=project_id,
                status=status,
                criterion_type=criterion_type,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_criterion_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def link_test(
        self,
        *,
        requirement_id: str,
        test_case_id: str,
        criterion_id: str | None = None,
        coverage_type: str = "DIRECT",
    ) -> TestLinkView:
        if coverage_type not in COVERAGE_TYPES:
            raise ValidationFailed(
                "未知覆盖类型",
                details={"coverage_type": coverage_type, "allowed": sorted(COVERAGE_TYPES)},
            )
        await self._ensure_requirement(requirement_id)
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            test_cases = TestCaseRepository(session)
            test_case = await test_cases.get(test_case_id)
            if test_case is None:
                raise NotFoundError("测试用例不存在", details={"test_case_id": test_case_id})
            criteria = CriterionRepository(session)
            if criterion_id is not None:
                criterion = await criteria.get(criterion_id)
                if criterion is None:
                    raise NotFoundError("验收标准不存在", details={"criterion_id": criterion_id})
                if criterion.requirement_id != requirement_id:
                    raise VerificationRequirementUntraceable(
                        "验收标准不属于该需求",
                        details={
                            "criterion_id": criterion_id,
                            "requirement_id": requirement_id,
                        },
                    )
            links = TestLinkRepository(session)
            existing = await links.get_link(requirement_id, test_case_id)
            if existing is not None:
                return _link_view(existing)
            entity = VerificationTestLinkModel(
                link_id=_new_id("vtl"),
                requirement_id=requirement_id,
                criterion_id=criterion_id,
                test_case_id=test_case_id,
                coverage_type=coverage_type,
                created_at=now,
            )
            await links.add(entity)
        return _link_view(entity)

    async def list_links(self, requirement_id: str) -> list[TestLinkView]:
        async with self._database.session() as session:
            rows = await TestLinkRepository(session).list_for_requirement(requirement_id)
        return [_link_view(row) for row in rows]

    async def invalidate_requirement(self, requirement_id: str, *, reason: str) -> dict[str, int]:
        """需求变更后使旧验收标准与旧结果进入待复核状态。"""

        if not reason.strip():
            raise ValidationFailed("需求变更必须说明原因")
        async with self._database.session() as session, transaction(session):
            criteria = await CriterionRepository(session).supersede_active(requirement_id)
            results = await ResultRepository(session).supersede_for_requirement(requirement_id)
        return {"criteria_superseded": criteria, "results_superseded": results}

    # ---- Evidence ----

    async def record_evidence(
        self,
        *,
        project_id: str,
        evidence_type: str,
        source_type: str,
        source_reference: str,
        content_hash: str,
        run_id: str | None = None,
        captured_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceView:
        if evidence_type not in EVIDENCE_TYPES:
            raise VerificationEvidenceInvalid(
                "未知证据类型",
                details={"evidence_type": evidence_type, "allowed": sorted(EVIDENCE_TYPES)},
            )
        if source_type not in EVIDENCE_SOURCE_TYPES:
            raise VerificationEvidenceInvalid(
                "未知证据来源",
                details={"source_type": source_type, "allowed": sorted(EVIDENCE_SOURCE_TYPES)},
            )
        if not source_reference.strip():
            raise VerificationEvidenceInvalid("证据必须包含来源引用")
        if not _HASH_PATTERN.match(content_hash or ""):
            raise VerificationEvidenceInvalid(
                "证据内容哈希必须为 64 位小写十六进制", details={"content_hash": content_hash}
            )
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            if run_id is not None:
                run = await RunRepository(session).get(run_id)
                if run is None:
                    raise NotFoundError("验证执行不存在", details={"run_id": run_id})
            entity = VerificationEvidenceModel(
                evidence_id=_new_id("vev"),
                project_id=project_id,
                evidence_type=evidence_type,
                source_type=source_type,
                source_reference=source_reference,
                content_hash=content_hash,
                verification_run_id=run_id,
                captured_at=captured_at or now,
                validity_status=EVIDENCE_VALID,
                metadata_json=_dump(metadata or {}),
                created_at=now,
            )
            await EvidenceRepository(session).add(entity)
            if run_id is not None:
                runs = RunRepository(session)
                current = await runs.get(run_id)
                assert current is not None
                ids = list(_load(current.evidence_ids_json, []))
                ids.append(entity.evidence_id)
                await runs.set_evidence_ids(run_id, _dump(ids))
        return _evidence_view(entity)

    async def list_evidence(
        self,
        project_id: str,
        *,
        evidence_type: str | None = None,
        validity_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if validity_status is not None and validity_status not in EVIDENCE_VALIDITY_STATUSES:
            raise ValidationFailed("未知证据有效状态", details={"validity_status": validity_status})
        async with self._database.session() as session:
            page = await EvidenceRepository(session).list_page(
                project_id=project_id,
                evidence_type=evidence_type,
                validity_status=validity_status,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_evidence_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def get_evidence(self, evidence_id: str) -> EvidenceView:
        async with self._database.session() as session:
            entity = await EvidenceRepository(session).get(evidence_id)
        if entity is None:
            raise NotFoundError("证据不存在", details={"evidence_id": evidence_id})
        return _evidence_view(entity)

    async def invalidate_evidence(self, evidence_id: str, *, status: str = "STALE") -> EvidenceView:
        if status not in EVIDENCE_VALIDITY_STATUSES:
            raise ValidationFailed("未知证据有效状态", details={"status": status})
        async with self._database.session() as session, transaction(session):
            repository = EvidenceRepository(session)
            entity = await repository.get(evidence_id)
            if entity is None:
                raise NotFoundError("证据不存在", details={"evidence_id": evidence_id})
            _ensure_transition(EVIDENCE_TRANSITIONS, entity.validity_status, status, "证据")
            moved = await repository.transition(
                evidence_id,
                from_statuses=frozenset({entity.validity_status}),
                to_status=status,
            )
            if not moved:
                raise VersionConflict("证据已被并发修改，请重新读取")
            updated = await repository.get(evidence_id)
        assert updated is not None
        return _evidence_view(updated)

    async def evidence_summary(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            rows = await EvidenceRepository(session).list_all(project_id)
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for row in rows:
            by_type[row.evidence_type] = by_type.get(row.evidence_type, 0) + 1
            by_status[row.validity_status] = by_status.get(row.validity_status, 0) + 1
        return {
            "project_id": project_id,
            "total": len(rows),
            "by_type": by_type,
            "by_validity": by_status,
        }

    async def check_evidence_integrity(self, project_id: str) -> dict[str, Any]:
        """校验有效证据的上下文与文件 Hash；问题证据只报告不自动通过。"""

        async with self._database.session() as session:
            rows = await EvidenceRepository(session).list_all(project_id)
        problems: list[dict[str, str]] = []
        checked = 0
        for row in rows:
            if row.validity_status != EVIDENCE_VALID:
                continue
            checked += 1
            metadata = _load(row.metadata_json, {})
            for issue in evidence_context_problems(row.evidence_type, metadata):
                problems.append({"evidence_id": row.evidence_id, "problem": issue})
            for issue in verify_file_reference(row.source_reference, row.content_hash):
                problems.append({"evidence_id": row.evidence_id, "problem": issue})
        return {
            "project_id": project_id,
            "total": len(rows),
            "checked": checked,
            "valid": not problems,
            "problems": problems,
        }

    async def mark_stale_evidence(
        self, project_id: str, *, project_revision: str
    ) -> dict[str, Any]:
        """项目版本变化后，缺少当前版本上下文的证据标记为 STALE。"""

        if not project_revision.strip():
            raise ValidationFailed("project_revision 不能为空")
        stale = 0
        async with self._database.session() as session, transaction(session):
            repository = EvidenceRepository(session)
            for row in await repository.list_all(project_id):
                if row.validity_status != EVIDENCE_VALID:
                    continue
                metadata = _load(row.metadata_json, {})
                if metadata.get("project_revision") == project_revision:
                    continue
                _ensure_transition(EVIDENCE_TRANSITIONS, row.validity_status, "STALE", "证据")
                moved = await repository.transition(
                    row.evidence_id,
                    from_statuses=frozenset({EVIDENCE_VALID}),
                    to_status="STALE",
                )
                if moved:
                    stale += 1
        return {"project_id": project_id, "stale": stale}

    # ---- Run ----

    async def start_run(
        self,
        campaign_id: str,
        *,
        plan_id: str | None = None,
        test_suite_id: str | None = None,
        test_case_id: str | None = None,
        environment_id: str | None = None,
        executor_id: str | None = None,
    ) -> RunView:
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            campaigns = CampaignRepository(session)
            campaign = await campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError("验证活动不存在", details={"campaign_id": campaign_id})
            if campaign.status not in {CAMPAIGN_READY, CAMPAIGN_RUNNING}:
                raise VerificationStateInvalid(
                    "验证活动尚未就绪，不能执行",
                    details={"status": campaign.status},
                )
            if campaign.status == CAMPAIGN_READY:
                moved = await campaigns.transition(
                    campaign_id,
                    from_statuses=frozenset({CAMPAIGN_READY}),
                    to_status=CAMPAIGN_RUNNING,
                    expected_version=campaign.version,
                    now=now,
                )
                if not moved:
                    raise VersionConflict("验证活动已被并发修改，请重新读取")
            resolved_plan_id = plan_id
            if resolved_plan_id is None:
                plan = await PlanRepository(session).get_for_campaign(campaign_id)
                resolved_plan_id = None if plan is None else plan.plan_id
            entity = VerificationRunModel(
                run_id=_new_id("vrn"),
                campaign_id=campaign_id,
                plan_id=resolved_plan_id,
                test_suite_id=test_suite_id,
                test_case_id=test_case_id,
                environment_id=environment_id,
                execution_status=RUN_RUNNING,
                started_at=now,
                completed_at=None,
                executor_id=executor_id,
                evidence_ids_json="[]",
                failure_reason=None,
                created_at=now,
            )
            await RunRepository(session).add(entity)
        return _run_view(entity)

    async def get_run(self, run_id: str) -> RunView:
        async with self._database.session() as session:
            entity = await RunRepository(session).get(run_id)
        if entity is None:
            raise NotFoundError("验证执行不存在", details={"run_id": run_id})
        return _run_view(entity)

    async def list_runs(
        self, campaign_id: str, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await RunRepository(session).list_for_campaign(
                campaign_id, limit=limit, offset=offset
            )
        return {
            "items": [_run_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    # ---- Agent 集成与验证预算（T19） ----

    async def agent_verification_policy(self) -> dict[str, Any]:
        """Agent 可见的验证操作矩阵与默认预算；不涉及任何项目数据。"""

        return {
            "allowed_actions": sorted(AGENT_ALLOWED_ACTIONS),
            "forbidden_actions": sorted(AGENT_FORBIDDEN_ACTIONS),
            "budgets": {risk: limits.to_dict() for risk, limits in DEFAULT_BUDGET_BY_RISK.items()},
        }

    async def verification_budget(
        self,
        campaign_id: str,
        *,
        risk_level: str = "MEDIUM",
        limits: VerificationBudgetLimits | None = None,
    ) -> dict[str, Any]:
        """按真实持久化数据计算验证预算用量，Agent 无法通过参数伪造用量。"""

        resolved = budget_limits_for(risk_level, limits)
        now = utcnow()
        async with self._database.session() as session:
            campaign = await CampaignRepository(session).get(campaign_id)
            if campaign is None:
                raise NotFoundError("验证活动不存在", details={"campaign_id": campaign_id})
            runs = await RunRepository(session).list_for_campaign_light(campaign_id)
            evidence_rows = await EvidenceRepository(session).list_all(campaign.project_id)
            regression_page = await RegressionPlanRepository(session).list_page(
                project_id=campaign.project_id, limit=1, offset=0
            )
        run_ids = {run.run_id for run in runs}
        attempts: dict[str, int] = {}
        runtime_seconds = 0.0
        for run in runs:
            if run.started_at is not None:
                finished = now if run.completed_at is None else ensure_utc(run.completed_at)
                runtime_seconds += max(0.0, (finished - ensure_utc(run.started_at)).total_seconds())
            key = run.test_case_id or run.test_suite_id or run.run_id
            attempts[key] = attempts.get(key, 0) + 1
        usage = {
            BUDGET_TEST_RUNS: float(len(runs)),
            BUDGET_RUNTIME_SECONDS: round(runtime_seconds, 3),
            BUDGET_SCREENSHOTS: float(
                sum(
                    1
                    for row in evidence_rows
                    if row.verification_run_id in run_ids
                    and row.evidence_type == EVIDENCE_TYPE_SCREENSHOT
                )
            ),
            BUDGET_VIDEOS: float(
                sum(
                    1
                    for row in evidence_rows
                    if row.verification_run_id in run_ids
                    and row.evidence_type == EVIDENCE_TYPE_VIDEO
                )
            ),
            BUDGET_RETRIES: float(sum(max(0, count - 1) for count in attempts.values())),
            BUDGET_REGRESSIONS: float(regression_page.total),
        }
        statuses = budget_statuses(usage, resolved)
        return {
            "campaign_id": campaign_id,
            "project_id": campaign.project_id,
            "risk_level": risk_level,
            "limits": resolved.to_dict(),
            "usage": usage,
            "budgets": [status.to_dict() for status in statuses],
            "exhausted": [status.dimension for status in statuses if status.exhausted],
        }

    async def ensure_verification_budget(
        self,
        campaign_id: str,
        *,
        dimension: str,
        amount: float = 1,
        risk_level: str = "MEDIUM",
        limits: VerificationBudgetLimits | None = None,
    ) -> dict[str, Any]:
        if dimension not in VERIFICATION_BUDGET_DIMENSIONS:
            raise ValidationFailed(
                "未知验证预算维度",
                details={
                    "dimension": dimension,
                    "allowed": list(VERIFICATION_BUDGET_DIMENSIONS),
                },
            )
        status = await self.verification_budget(campaign_id, risk_level=risk_level, limits=limits)
        problems = exhausted_dimensions(
            status["usage"],
            budget_limits_for(risk_level, limits),
            amounts={dimension: amount},
        )
        if problems:
            raise AgentBudgetExceeded(
                "验证预算已耗尽，禁止继续请求执行",
                details={"campaign_id": campaign_id, "budgets": problems},
            )
        return status

    async def agent_request_verification(
        self,
        *,
        project_id: str,
        campaign_type: str,
        actor_id: str,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        task_id: str | None = None,
        changeset_id: str | None = None,
    ) -> CampaignView:
        """Agent 发起验证请求：只能创建活动，不能决定结果。"""

        ensure_agent_action_allowed(AGENT_ACTION_REQUEST_VERIFICATION)
        if not actor_id.strip():
            raise ValidationFailed("Agent 发起验证必须记录 actor_id")
        return await self.create_campaign(
            project_id=project_id,
            campaign_type=campaign_type,
            workflow_id=workflow_id,
            phase_id=phase_id,
            task_id=task_id,
            changeset_id=changeset_id,
            created_by=actor_id.strip(),
        )

    async def agent_request_run(
        self,
        campaign_id: str,
        *,
        risk_level: str = "MEDIUM",
        limits: VerificationBudgetLimits | None = None,
        plan_id: str | None = None,
        test_suite_id: str | None = None,
        test_case_id: str | None = None,
        environment_id: str | None = None,
        executor_id: str | None = None,
    ) -> RunView:
        """Agent 请求执行：先过策略与预算，再复用标准执行入口。"""

        ensure_agent_action_allowed(AGENT_ACTION_REQUEST_RUN)
        await self.ensure_verification_budget(
            campaign_id, dimension=BUDGET_TEST_RUNS, risk_level=risk_level, limits=limits
        )
        if test_case_id is not None or test_suite_id is not None:
            async with self._database.session() as session:
                existing = await RunRepository(session).list_for_campaign_light(campaign_id)
            is_retry = any(
                (test_case_id is not None and run.test_case_id == test_case_id)
                or (test_case_id is None and run.test_suite_id == test_suite_id)
                for run in existing
            )
            if is_retry:
                await self.ensure_verification_budget(
                    campaign_id,
                    dimension=BUDGET_RETRIES,
                    risk_level=risk_level,
                    limits=limits,
                )
        return await self.start_run(
            campaign_id,
            plan_id=plan_id,
            test_suite_id=test_suite_id,
            test_case_id=test_case_id,
            environment_id=environment_id,
            executor_id=executor_id,
        )

    async def complete_run(
        self,
        run_id: str,
        *,
        execution_status: str,
        evidence_ids: tuple[str, ...] = (),
        failure_reason: str | None = None,
    ) -> RunView:
        if execution_status not in RUN_STATUSES:
            raise ValidationFailed("未知执行状态", details={"execution_status": execution_status})
        if execution_status in {RUN_RUNNING, RUN_QUEUED}:
            raise VerificationStateInvalid("完成执行不能回到排队或运行状态")
        if execution_status == RUN_FAILED and not (failure_reason or "").strip():
            raise VerificationResultInvalid("执行失败必须给出失败原因")
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repository = RunRepository(session)
            entity = await repository.get(run_id)
            if entity is None:
                raise NotFoundError("验证执行不存在", details={"run_id": run_id})
            _ensure_transition(
                RUN_TRANSITIONS, entity.execution_status, execution_status, "验证执行"
            )
            from_statuses = frozenset(
                status for status, allowed in RUN_TRANSITIONS.items() if execution_status in allowed
            )
            completed_at = None if execution_status == RUN_UNKNOWN else now
            moved = await repository.transition(
                run_id,
                from_statuses=from_statuses,
                to_status=execution_status,
                now=now,
                completed_at=completed_at,
                evidence_ids_json=_dump(list(evidence_ids)) if evidence_ids else None,
                failure_reason=failure_reason,
            )
            if not moved:
                raise VersionConflict("验证执行已被并发修改，请重新读取")
            updated = await repository.get(run_id)
        assert updated is not None
        return _run_view(updated)

    # ---- Result ----

    async def record_result(
        self,
        *,
        campaign_id: str,
        result_status: str,
        run_id: str | None = None,
        requirement_id: str | None = None,
        criterion_id: str | None = None,
        test_case_id: str | None = None,
        evidence_ids: tuple[str, ...] = (),
        failure_reason: str | None = None,
        confidence_level: str | None = None,
    ) -> ResultView:
        if result_status not in RESULT_STATUSES:
            raise ValidationFailed("未知验证结果状态", details={"result_status": result_status})
        if result_status == RESULT_WAIVED:
            raise VerificationResultInvalid("豁免必须通过独立豁免流程执行")
        if result_status == RESULT_PASSED and not evidence_ids:
            raise VerificationResultInvalid("通过结果必须附带至少一条证据")
        if result_status == RESULT_FAILED and not (failure_reason or "").strip():
            raise VerificationResultInvalid("失败结果必须给出失败原因")
        if confidence_level is not None and confidence_level not in _CONFIDENCE_LEVELS:
            raise ValidationFailed("未知置信度", details={"confidence_level": confidence_level})
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            campaign = await CampaignRepository(session).get(campaign_id)
            if campaign is None:
                raise NotFoundError("验证活动不存在", details={"campaign_id": campaign_id})
            if run_id is not None:
                run = await RunRepository(session).get(run_id)
                if run is None:
                    raise NotFoundError("验证执行不存在", details={"run_id": run_id})
                if run.campaign_id != campaign_id:
                    raise VerificationResultInvalid(
                        "验证执行不属于该活动",
                        details={"run_id": run_id, "campaign_id": campaign_id},
                    )
            await self._ensure_evidence(session, campaign.project_id, evidence_ids)
            verified_at = now if result_status in EXECUTED_RESULT_STATUSES else None
            entity = VerificationResultModel(
                result_id=_new_id("vrs"),
                campaign_id=campaign_id,
                run_id=run_id,
                requirement_id=requirement_id,
                criterion_id=criterion_id,
                test_case_id=test_case_id,
                result_status=result_status,
                evidence_ids_json=_dump(list(evidence_ids)),
                failure_reason=failure_reason,
                confidence_level=confidence_level,
                verified_at=verified_at,
                superseded_by=None,
                created_at=now,
            )
            await ResultRepository(session).add(entity)
        return _result_view(entity)

    async def get_result(self, result_id: str) -> ResultView:
        async with self._database.session() as session:
            entity = await ResultRepository(session).get(result_id)
        if entity is None:
            raise NotFoundError("验证结果不存在", details={"result_id": result_id})
        return _result_view(entity)

    async def list_results(
        self, campaign_id: str, *, limit: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await ResultRepository(session).list_for_campaign(
                campaign_id, limit=limit, offset=offset
            )
        return {
            "items": [_result_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def waive_result(self, result_id: str, *, reason: str, waived_by: str) -> ResultView:
        """豁免必须由 owner 触发；豁免不等于通过，结果状态保持 WAIVED。"""

        if not reason.strip():
            raise VerificationResultInvalid("豁免必须说明原因")
        if not waived_by:
            raise VerificationResultInvalid("豁免必须记录操作人")
        async with self._database.session() as session, transaction(session):
            repository = ResultRepository(session)
            entity = await repository.get(result_id)
            if entity is None:
                raise NotFoundError("验证结果不存在", details={"result_id": result_id})
            _ensure_transition(RESULT_TRANSITIONS, entity.result_status, RESULT_WAIVED, "验证结果")
            moved = await repository.transition(
                result_id,
                from_statuses=frozenset({entity.result_status}),
                to_status=RESULT_WAIVED,
                failure_reason=f"waived_by={waived_by}; reason={reason}",
            )
            if not moved:
                raise VersionConflict("验证结果已被并发修改，请重新读取")
            updated = await repository.get(result_id)
        assert updated is not None
        return _result_view(updated)

    # ---- 运行时环境（T08） ----

    async def register_runtime_environment(
        self,
        *,
        project_id: str,
        project_revision: str = "",
        godot_version: str = "",
        platform: str = "",
        display_resolution: str = "",
        renderer: str = "",
        runtime_instance_id: str | None = None,
        test_configuration: dict[str, Any] | None = None,
        status: str = RUNTIME_ENV_READY,
    ) -> RuntimeEnvironmentView:
        if status not in RUNTIME_ENVIRONMENT_STATUSES:
            raise ValidationFailed(
                "未知运行时环境状态",
                details={"status": status, "allowed": sorted(RUNTIME_ENVIRONMENT_STATUSES)},
            )
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            entity = VerificationRuntimeEnvironmentModel(
                environment_id=_new_id("vre"),
                project_id=project_id,
                project_revision=project_revision,
                godot_version=godot_version,
                platform=platform,
                display_resolution=display_resolution,
                renderer=renderer,
                runtime_instance_id=runtime_instance_id,
                test_configuration_json=_dump(test_configuration or {}),
                status=status,
                created_at=now,
                updated_at=now,
            )
            await RuntimeEnvironmentRepository(session).add(entity)
        return _runtime_environment_view(entity)

    async def get_runtime_environment(self, environment_id: str) -> RuntimeEnvironmentView:
        async with self._database.session() as session:
            entity = await RuntimeEnvironmentRepository(session).get(environment_id)
        if entity is None:
            raise NotFoundError("运行时环境不存在", details={"environment_id": environment_id})
        return _runtime_environment_view(entity)

    async def list_runtime_environments(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in RUNTIME_ENVIRONMENT_STATUSES:
            raise ValidationFailed("未知运行时环境状态", details={"status": status})
        async with self._database.session() as session:
            page = await RuntimeEnvironmentRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_runtime_environment_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def update_runtime_environment(
        self,
        environment_id: str,
        *,
        status: str | None = None,
        runtime_instance_id: str | None = None,
    ) -> RuntimeEnvironmentView:
        if status is None and runtime_instance_id is None:
            raise ValidationFailed("运行时环境更新至少需要提供一个字段")
        if status is not None and status not in RUNTIME_ENVIRONMENT_STATUSES:
            raise ValidationFailed("未知运行时环境状态", details={"status": status})
        async with self._database.session() as session, transaction(session):
            repository = RuntimeEnvironmentRepository(session)
            entity = await repository.get(environment_id)
            if entity is None:
                raise NotFoundError("运行时环境不存在", details={"environment_id": environment_id})
            if status is not None:
                entity.status = status
            if runtime_instance_id is not None:
                entity.runtime_instance_id = runtime_instance_id
            entity.updated_at = utcnow()
            await session.flush()
        return _runtime_environment_view(entity)

    # ---- Debugger 错误（T10） ----

    async def record_debugger_errors(
        self,
        *,
        project_id: str,
        errors: Sequence[DebuggerErrorInput],
        run_id: str | None = None,
        project_revision: str | None = None,
        baseline: bool = False,
    ) -> dict[str, Any]:
        if not errors:
            raise ValidationFailed("至少需要一条 Debugger 错误")
        now = utcnow()
        new_count = 0
        async with self._database.session() as session, transaction(session):
            if run_id is not None:
                run = await RunRepository(session).get(run_id)
                if run is None:
                    raise NotFoundError("验证运行不存在", details={"run_id": run_id})
                if run.project_id != project_id:
                    raise VerificationResultInvalid(
                        "运行不属于该项目", details={"run_id": run_id, "project_id": project_id}
                    )
            repository = DebuggerErrorRepository(session)
            entities: list[VerificationDebuggerErrorModel] = []
            for error in errors:
                if error.category not in DEBUGGER_ERROR_CATEGORIES:
                    raise ValidationFailed(
                        "未知 Debugger 错误分类", details={"category": error.category}
                    )
                if error.severity not in DEBUGGER_SEVERITIES:
                    raise ValidationFailed(
                        "未知 Debugger 严重级别", details={"severity": error.severity}
                    )
                fingerprint = fingerprint_error(error)
                existing = await repository.get_by_fingerprint(project_id, fingerprint)
                if existing is not None:
                    existing.occurrences += 1
                    existing.last_seen_at = now
                    if baseline:
                        existing.is_baseline = True
                    # 已解决的问题再次出现时必须重新打开，不能按历史通过处理
                    if existing.status == ERROR_STATUS_RESOLVED:
                        existing.status = ERROR_STATUS_OPEN
                    if run_id is not None:
                        existing.run_id = run_id
                    if project_revision is not None:
                        existing.project_revision = project_revision
                    entities.append(existing)
                    continue
                entity = VerificationDebuggerErrorModel(
                    error_id=_new_id("vde"),
                    project_id=project_id,
                    run_id=run_id,
                    fingerprint=fingerprint,
                    category=error.category,
                    severity=error.severity,
                    message=error.message,
                    source=error.source,
                    scene=error.scene,
                    node=error.node,
                    script=error.script,
                    stack_trace=error.stack_trace,
                    runtime_instance_id=error.runtime_instance_id,
                    godot_version=error.godot_version,
                    project_revision=project_revision or error.project_revision,
                    changeset_id=error.changeset_id,
                    occurrences=1,
                    is_baseline=baseline,
                    status=ERROR_STATUS_OPEN,
                    first_seen_at=now,
                    last_seen_at=now,
                    metadata_json=_dump({}),
                    created_at=now,
                )
                await repository.add(entity)
                entities.append(entity)
                new_count += 1
            await session.flush()
        return {
            "items": [_debugger_error_view(item) for item in entities],
            "new_count": new_count,
            "baseline_count": len(entities) - new_count,
        }

    async def get_debugger_error(self, error_id: str) -> DebuggerErrorView:
        async with self._database.session() as session:
            entity = await DebuggerErrorRepository(session).get(error_id)
        if entity is None:
            raise NotFoundError("Debugger 错误不存在", details={"error_id": error_id})
        return _debugger_error_view(entity)

    async def list_debugger_errors(
        self,
        project_id: str,
        *,
        severity: str | None = None,
        status: str | None = None,
        is_baseline: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if severity is not None and severity not in DEBUGGER_SEVERITIES:
            raise ValidationFailed("未知 Debugger 严重级别", details={"severity": severity})
        if status is not None and status not in DEBUGGER_ERROR_STATUSES:
            raise ValidationFailed("未知 Debugger 错误状态", details={"status": status})
        async with self._database.session() as session:
            page = await DebuggerErrorRepository(session).list_page(
                project_id=project_id,
                severity=severity,
                status=status,
                is_baseline=is_baseline,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_debugger_error_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def resolve_debugger_error(
        self,
        error_id: str,
        *,
        status: str = ERROR_STATUS_RESOLVED,
        note: str | None = None,
    ) -> DebuggerErrorView:
        if status not in {ERROR_STATUS_RESOLVED, ERROR_STATUS_IGNORED}:
            raise ValidationFailed("只能将错误标记为 RESOLVED 或 IGNORED")
        async with self._database.session() as session, transaction(session):
            repository = DebuggerErrorRepository(session)
            entity = await repository.get(error_id)
            if entity is None:
                raise NotFoundError("Debugger 错误不存在", details={"error_id": error_id})
            entity.status = status
            entity.last_seen_at = utcnow()
            if note is not None:
                metadata = _load(entity.metadata_json, {})
                metadata["resolution_note"] = note
                entity.metadata_json = _dump(metadata)
            await session.flush()
        return _debugger_error_view(entity)

    async def evaluate_debugger_gate(
        self,
        project_id: str,
        *,
        policy: DebuggerGatePolicy | None = None,
    ) -> DebuggerGateDecision:
        async with self._database.session() as session:
            rows = await DebuggerErrorRepository(session).list_for_gate(project_id)
        snapshots = [
            build_snapshot(
                severity=item.severity,
                category=item.category,
                is_baseline=item.is_baseline,
                status=item.status,
                message=item.message,
            )
            for item in rows
        ]
        return evaluate_gate(snapshots, policy)

    # ---- 缺陷管理（T14） ----

    async def create_defect(
        self,
        *,
        project_id: str,
        severity: str,
        category: str,
        title: str,
        description: str = "",
        priority: str | None = None,
        requirement_id: str | None = None,
        source_result_id: str | None = None,
        reproduction_steps: Sequence[str] = (),
        expected_result: str = "",
        actual_result: str = "",
        evidence_ids: Sequence[str] = (),
        assigned_agent_id: str | None = None,
        related_changeset_id: str | None = None,
    ) -> DefectView:
        if not project_id:
            raise ValidationFailed("project_id 不能为空")
        if severity not in DEFECT_SEVERITIES:
            raise ValidationFailed(
                "未知缺陷严重程度",
                details={"severity": severity, "allowed": sorted(DEFECT_SEVERITIES)},
            )
        if category not in DEFECT_CATEGORIES:
            raise ValidationFailed(
                "未知缺陷类别",
                details={"category": category, "allowed": sorted(DEFECT_CATEGORIES)},
            )
        resolved_priority = (priority or default_priority(severity)).upper()
        if resolved_priority not in DEFECT_PRIORITIES:
            raise ValidationFailed("未知缺陷优先级", details={"priority": resolved_priority})
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValidationFailed("缺陷标题不能为空")
        steps = tuple(str(item).strip() for item in reproduction_steps if str(item).strip())
        if not steps and not description.strip():
            raise ValidationFailed("缺陷必须提供复现步骤或描述")
        if requirement_id is not None:
            await self._ensure_requirement(requirement_id)
        if related_changeset_id is not None and self._changesets is not None:
            getter = getattr(self._changesets, "get", None)
            if getter is not None:
                changeset = await getter(related_changeset_id)
                if getattr(changeset, "project_id", None) != project_id:
                    raise ValidationFailed(
                        "变更集不属于该项目",
                        details={"changeset_id": related_changeset_id},
                    )
        now = utcnow()
        entity = VerificationDefectModel(
            defect_id=_new_id("dfc"),
            project_id=project_id,
            requirement_id=requirement_id,
            source_result_id=source_result_id,
            severity=severity,
            priority=resolved_priority,
            category=category,
            title=cleaned_title[:256],
            description=description,
            reproduction_steps_json=_dump(list(steps)),
            expected_result=expected_result,
            actual_result=actual_result,
            evidence_ids_json=_dump([str(item) for item in evidence_ids]),
            assigned_agent_id=assigned_agent_id,
            status=DEFECT_OPEN,
            related_changeset_id=related_changeset_id,
            resolution_reference=None,
            created_at=now,
            updated_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await self._ensure_evidence(session, project_id, tuple(str(i) for i in evidence_ids))
            if source_result_id is not None:
                result = await ResultRepository(session).get(source_result_id)
                if result is None:
                    raise NotFoundError(
                        "缺陷来源结果不存在", details={"result_id": source_result_id}
                    )
                campaign = await CampaignRepository(session).get(result.campaign_id)
                if campaign is None or campaign.project_id != project_id:
                    raise ValidationFailed(
                        "缺陷来源结果不属于该项目",
                        details={"result_id": source_result_id},
                    )
            await DefectRepository(session).add(entity)
        return _defect_view(entity)

    async def get_defect(self, defect_id: str) -> DefectView:
        async with self._database.session() as session:
            entity = await DefectRepository(session).get(defect_id)
        if entity is None:
            raise NotFoundError("缺陷不存在", details={"defect_id": defect_id})
        return _defect_view(entity)

    async def list_defects(
        self,
        project_id: str,
        *,
        status: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in DEFECT_STATUSES:
            raise ValidationFailed("未知缺陷状态", details={"status": status})
        if severity is not None and severity not in DEFECT_SEVERITIES:
            raise ValidationFailed("未知缺陷严重程度", details={"severity": severity})
        if category is not None and category not in DEFECT_CATEGORIES:
            raise ValidationFailed("未知缺陷类别", details={"category": category})
        async with self._database.session() as session:
            page = await DefectRepository(session).list_page(
                project_id=project_id,
                status=status,
                severity=severity,
                category=category,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_defect_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def transition_defect(
        self,
        defect_id: str,
        status: str,
        *,
        assigned_agent_id: str | None = None,
        resolution_reference: str | None = None,
        note: str | None = None,
    ) -> DefectView:
        if status not in DEFECT_STATUSES:
            raise ValidationFailed("未知缺陷状态", details={"status": status})
        async with self._database.session() as session, transaction(session):
            repository = DefectRepository(session)
            entity = await repository.get(defect_id)
            if entity is None:
                raise NotFoundError("缺陷不存在", details={"defect_id": defect_id})
            _ensure_transition(DEFECT_TRANSITIONS, entity.status, status, "缺陷")
            if status == DEFECT_ASSIGNED:
                entity.assigned_agent_id = (
                    assigned_agent_id
                    or entity.assigned_agent_id
                    or recommend_agent(entity.category)
                )
            elif assigned_agent_id is not None:
                entity.assigned_agent_id = assigned_agent_id
            if status == DEFECT_RESOLVED:
                reference = (resolution_reference or entity.resolution_reference or "").strip()
                if not reference:
                    raise VerificationStateInvalid(
                        "缺陷解决前必须提供修复验证引用",
                        details={"defect_id": defect_id},
                    )
                entity.resolution_reference = reference
            elif resolution_reference is not None:
                entity.resolution_reference = resolution_reference
            if note is not None:
                entity.description = f"{entity.description}\n{note}".strip()
            entity.status = status
            entity.updated_at = utcnow()
            await session.flush()
        return _defect_view(entity)

    async def defect_summary(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            rows = await DefectRepository(session).list_all(project_id)
        summary = summarize_defects(rows)
        summary["project_id"] = project_id
        return summary

    # ---- 回归与影响分析（T15） ----

    async def analyze_impact(
        self,
        project_id: str,
        *,
        changeset_id: str | None = None,
        changed_files: Sequence[Any] = (),
        force_full: bool = False,
        security_requested: bool = False,
    ) -> RegressionPlanView:
        if not project_id:
            raise ValidationFailed("project_id 不能为空")
        collected: list[ChangedFile] = []
        if changeset_id is not None:
            if self._changesets is None:
                raise ValidationFailed("未配置 ChangeSet 服务，无法按变更集分析")
            changeset = await self._changesets.get(changeset_id)
            if getattr(changeset, "project_id", None) != project_id:
                raise ValidationFailed("变更集不属于该项目", details={"changeset_id": changeset_id})
            detail = await self._changesets.detail(changeset_id)
            collected.extend(
                ChangedFile.from_manifest_item(item) for item in detail.get("manifest", [])
            )
        collected.extend(coerce_changed_file(item) for item in changed_files)
        deduped: dict[str, ChangedFile] = {}
        for item in collected:
            if item.path:
                deduped[item.path] = item
        if not deduped:
            raise ValidationFailed("影响分析至少需要变更集或变更文件")

        project_root = await self._project_root(project_id)
        reverse = scan_reverse_dependencies(project_root) if project_root else {}
        async with self._database.session() as session:
            test_cases = await TestCaseRepository(session).list_active(project_id)
            links = await TestLinkRepository(session).list_for_project(project_id)
            defects = await DefectRepository(session).list_all(project_id)
        requirements = await self._project_requirements(project_id)
        testable_ids = [
            str(getattr(item, "requirement_id", ""))
            for item in requirements
            if getattr(item, "status", None) not in _REQUIREMENT_NOT_TESTABLE
        ]
        plan: ImpactPlan = build_regression_plan(
            project_id=project_id,
            changeset_id=changeset_id,
            changed_files=sorted(deduped.values(), key=lambda item: item.path),
            reverse_dependencies=reverse,
            test_cases=[
                TestCaseRef(
                    test_case_id=item.test_case_id,
                    name=item.name,
                    test_type=item.test_type,
                    execution_method=item.execution_method,
                    risk_level=item.risk_level,
                    status=item.status,
                    description=item.description or "",
                )
                for item in test_cases
            ],
            links=[
                LinkRef(
                    requirement_id=item.requirement_id,
                    test_case_id=item.test_case_id,
                    coverage_type=item.coverage_type,
                )
                for item in links
            ],
            testable_requirement_ids=testable_ids,
            defects=[
                DefectRef(
                    defect_id=item.defect_id,
                    requirement_id=item.requirement_id,
                    severity=item.severity,
                    category=item.category,
                    status=item.status,
                    title=item.title,
                    related_changeset_id=item.related_changeset_id,
                )
                for item in defects
            ],
            force_full=force_full,
            security_requested=security_requested,
        )
        if plan.strategy not in REGRESSION_STRATEGIES:
            raise ValidationFailed("回归策略非法", details={"strategy": plan.strategy})
        now = utcnow()
        entity = VerificationRegressionPlanModel(
            regression_plan_id=_new_id("rgp"),
            project_id=project_id,
            changeset_id=changeset_id,
            strategy=plan.strategy,
            risk_level=plan.risk_level,
            changed_files_json=_dump(list(plan.changed_files)),
            affected_requirements_json=_dump(list(plan.affected_requirements)),
            affected_test_cases_json=_dump(list(plan.affected_test_cases)),
            affected_scenes_json=_dump(list(plan.affected_scenes)),
            affected_scripts_json=_dump(list(plan.affected_scripts)),
            affected_resources_json=_dump(list(plan.affected_resources)),
            dependents_json=_dump(list(plan.dependents)),
            historical_defects_json=_dump(list(plan.historical_defects)),
            coverage_gaps_json=_dump(list(plan.coverage_gaps)),
            required_checks_json=_dump(list(plan.required_checks)),
            created_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await RegressionPlanRepository(session).add(entity)
        return _regression_plan_view(entity)

    async def get_regression_plan(self, regression_plan_id: str) -> RegressionPlanView:
        async with self._database.session() as session:
            entity = await RegressionPlanRepository(session).get(regression_plan_id)
        if entity is None:
            raise NotFoundError(
                "回归计划不存在", details={"regression_plan_id": regression_plan_id}
            )
        return _regression_plan_view(entity)

    async def list_regression_plans(
        self,
        project_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await RegressionPlanRepository(session).list_page(
                project_id=project_id, limit=limit, offset=offset
            )
        return {
            "items": [_regression_plan_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    # ---- 质量门禁（T16） ----

    async def create_gate_policy(
        self,
        *,
        project_id: str,
        name: str,
        gates: Sequence[str] = (),
        campaign_type: str | None = None,
        risk_level: str | None = None,
        waivers_allowed: bool = False,
        created_by: str | None = None,
    ) -> GatePolicyView:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValidationFailed("门禁策略名称不能为空")
        if campaign_type is not None and campaign_type not in CAMPAIGN_TYPES:
            raise ValidationFailed("未知验证活动类型", details={"campaign_type": campaign_type})
        if risk_level is not None and risk_level not in RISK_LEVELS:
            raise ValidationFailed("未知风险等级", details={"risk_level": risk_level})
        selected = (
            tuple(str(item) for item in gates)
            if gates
            else required_gates(campaign_type, risk_level)
        )
        invalid = [gate for gate in selected if gate not in QUALITY_GATES]
        if invalid or not selected:
            raise ValidationFailed(
                "门禁策略包含非法门禁", details={"invalid_gates": invalid or list(selected)}
            )
        now = utcnow()
        entity = QualityGatePolicyModel(
            gate_policy_id=_new_id("qgp"),
            project_id=project_id,
            name=cleaned_name[:128],
            campaign_type=campaign_type,
            risk_level=risk_level,
            required_gates_json=_dump(list(dict.fromkeys(selected))),
            waivers_allowed=waivers_allowed,
            created_by=created_by,
            version=1,
            created_at=now,
            updated_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await QualityGatePolicyRepository(session).add(entity)
        return _gate_policy_view(entity)

    async def list_gate_policies(self, project_id: str) -> list[GatePolicyView]:
        async with self._database.session() as session:
            rows = await QualityGatePolicyRepository(session).list_for_project(project_id)
        return [_gate_policy_view(item) for item in rows]

    async def evaluate_quality_gate(
        self,
        project_id: str,
        *,
        campaign_id: str,
        policy_id: str | None = None,
        risk_level: str | None = None,
    ) -> GateEvaluationView:
        now = utcnow()
        async with self._database.session() as session:
            campaign = await CampaignRepository(session).get(campaign_id)
            if campaign is None or campaign.project_id != project_id:
                raise NotFoundError("验证活动不存在", details={"campaign_id": campaign_id})
            policy = None
            if policy_id is not None:
                policy = await QualityGatePolicyRepository(session).get(policy_id)
                if policy is None or policy.project_id != project_id:
                    raise NotFoundError("质量门禁策略不存在", details={"gate_policy_id": policy_id})
            plan = await PlanRepository(session).get_for_campaign(campaign_id)
            results = await ResultRepository(session).list_all_for_campaign(campaign_id)
            test_cases = await TestCaseRepository(session).list_active(project_id)
            links = await TestLinkRepository(session).list_for_project(project_id)
            defects = await DefectRepository(session).list_all(project_id)
            evidence_rows = await EvidenceRepository(session).list_all(project_id)
            regression_page = await RegressionPlanRepository(session).list_page(
                project_id=project_id, limit=1, offset=0
            )
            latest_rows = await QualityGateResultRepository(session).latest_for_campaign(
                campaign_id
            )
            waivers: dict[str, QualityGateWaiverModel] = {}
            for row in latest_rows:
                waiver = await QualityGateWaiverRepository(session).active_for_gate(
                    campaign_id, row.gate_name
                )
                if waiver is not None:
                    waivers[row.gate_name] = waiver

        selected = (
            tuple(str(item) for item in _load(policy.required_gates_json, []))
            if policy is not None
            else required_gates(campaign.campaign_type, risk_level)
        )
        selected_set = set(selected)
        plan_layers = set(_load(plan.verification_layers_json, [])) if plan else set()
        requirement_ids = (
            [str(item) for item in _load(plan.requirement_ids_json, [])] if plan is not None else []
        )
        covered = {link.requirement_id for link in links}
        results_by_layer: dict[str, list[str]] = {}
        layer_by_test_case = {
            case.test_case_id: TEST_TYPE_TO_LAYER[case.test_type]
            for case in test_cases
            if case.test_type in TEST_TYPE_TO_LAYER
        }
        for result in results:
            layer = layer_by_test_case.get(result.test_case_id or "")
            if layer is None:
                continue
            results_by_layer.setdefault(layer, []).append(result.result_status)

        layer_gates = {
            GATE_STATIC: "STATIC",
            GATE_STRUCTURAL: "STRUCTURE",
            GATE_RUNTIME: "RUNTIME",
            GATE_FUNCTIONAL: "FUNCTIONAL",
        }
        outcomes: list[GateOutcome] = []
        for gate in QUALITY_GATES:
            if gate not in selected_set:
                outcomes.append(GateOutcome(gate, GATE_NOT_REQUIRED, False, "不在本次门禁策略内"))
                continue
            if gate == GATE_REQUIREMENT_COMPLETENESS:
                missing = [item for item in requirement_ids if item not in covered]
                if not requirement_ids:
                    outcomes.append(
                        GateOutcome(
                            gate,
                            GATE_PENDING,
                            True,
                            "验证计划未关联需求",
                            {"requirements": 0},
                        )
                    )
                elif missing:
                    outcomes.append(
                        GateOutcome(
                            gate,
                            GATE_FAILED,
                            True,
                            "存在未建立测试追踪的需求",
                            {"missing_requirement_ids": sorted(missing)},
                        )
                    )
                else:
                    outcomes.append(
                        GateOutcome(
                            gate,
                            GATE_PASSED,
                            True,
                            "需求均已建立测试追踪",
                            {"requirements": len(requirement_ids)},
                        )
                    )
            elif gate in layer_gates:
                layer = layer_gates[gate]
                if plan is not None and layer not in plan_layers:
                    outcomes.append(
                        GateOutcome(gate, GATE_NOT_REQUIRED, True, "验证计划未包含该层")
                    )
                else:
                    outcomes.append(layer_gate(gate, results_by_layer.get(layer, [])))
            elif gate == GATE_EVIDENCE:
                valid_rows = [row for row in evidence_rows if row.validity_status == EVIDENCE_VALID]
                problems: list[str] = []
                for row in valid_rows:
                    metadata = _load(row.metadata_json, {})
                    problems.extend(evidence_context_problems(row.evidence_type, metadata))
                    problems.extend(verify_file_reference(row.source_reference, row.content_hash))
                if not valid_rows:
                    outcomes.append(
                        GateOutcome(gate, GATE_UNKNOWN, True, "没有可用的有效证据", {"evidence": 0})
                    )
                elif problems:
                    outcomes.append(
                        GateOutcome(
                            gate,
                            GATE_FAILED,
                            True,
                            "存在不完整或失效的证据",
                            {"problems": problems},
                        )
                    )
                else:
                    outcomes.append(
                        GateOutcome(
                            gate,
                            GATE_PASSED,
                            True,
                            "有效证据完整",
                            {"evidence": len(valid_rows)},
                        )
                    )
            elif gate == GATE_DEFECT:
                blocking_defects = [
                    row
                    for row in defects
                    if row.status in DEFECT_ACTIVE_STATUSES
                    and row.severity in {DEFECT_BLOCKER, DEFECT_CRITICAL}
                ]
                if blocking_defects:
                    outcomes.append(
                        GateOutcome(
                            gate,
                            GATE_FAILED,
                            True,
                            "存在未解决的阻断性缺陷",
                            {"defect_ids": sorted(row.defect_id for row in blocking_defects)},
                        )
                    )
                else:
                    outcomes.append(GateOutcome(gate, GATE_PASSED, True, "没有未解决的阻断性缺陷"))
            elif gate == GATE_REGRESSION:
                if not getattr(campaign, "changeset_id", None):
                    outcomes.append(
                        GateOutcome(gate, GATE_NOT_REQUIRED, True, "验证活动未关联变更集")
                    )
                elif regression_page.total == 0:
                    outcomes.append(
                        GateOutcome(gate, GATE_FAILED, True, "存在变更集但没有回归计划")
                    )
                else:
                    outcomes.append(
                        GateOutcome(
                            gate,
                            GATE_UNKNOWN,
                            True,
                            "回归计划已生成，但尚未接入回归执行结果",
                            {"regression_plans": regression_page.total},
                        )
                    )
            elif gate == GATE_LICENSE:
                if campaign.campaign_type == CAMPAIGN_TYPE_ASSET:
                    outcomes.append(
                        GateOutcome(gate, GATE_UNKNOWN, True, "缺少资产与 License 校验数据源")
                    )
                else:
                    outcomes.append(GateOutcome(gate, GATE_NOT_REQUIRED, False, "非资产类验证"))
            elif gate == GATE_SECURITY:
                sensitive: list[str] = []
                if getattr(campaign, "changeset_id", None) and self._changesets is not None:
                    detail = await self._changesets.detail(campaign.changeset_id)
                    sensitive = [
                        str(item.get("resource_path"))
                        for item in detail.get("manifest", [])
                        if is_security_sensitive(str(item.get("resource_path") or ""))
                    ]
                if sensitive:
                    outcomes.append(
                        GateOutcome(
                            gate,
                            GATE_UNKNOWN,
                            True,
                            "存在敏感变更，但缺少专用安全扫描结果",
                            {"sensitive_paths": sorted(sensitive)},
                        )
                    )
                else:
                    outcomes.append(GateOutcome(gate, GATE_NOT_REQUIRED, False, "没有安全敏感变更"))

        adjusted: list[GateOutcome] = []
        for outcome in outcomes:
            waiver = waivers.get(outcome.gate)
            if waiver is not None and outcome.status != GATE_PASSED:
                problem = waiver_problem(
                    GateWaiver(
                        authorized_by=waiver.authorized_by,
                        reason=waiver.reason,
                        risk_statement=waiver.risk_statement,
                        scope=waiver.scope,
                        expires_at=ensure_utc(waiver.expires_at),
                        revoked_at=ensure_utc(waiver.revoked_at)
                        if waiver.revoked_at is not None
                        else None,
                    ),
                    now,
                )
                if problem is None:
                    adjusted.append(
                        GateOutcome(
                            outcome.gate,
                            GATE_WAIVED,
                            outcome.blocking,
                            f"有效豁免：{waiver.reason}",
                            outcome.details,
                        )
                    )
                    continue
            adjusted.append(outcome)

        decision = combine_outcomes(adjusted)
        entities: list[QualityGateResultModel] = []
        async with self._database.session() as session, transaction(session):
            repository = QualityGateResultRepository(session)
            for outcome in adjusted:
                entity = QualityGateResultModel(
                    gate_result_id=_new_id("qgr"),
                    project_id=project_id,
                    campaign_id=campaign_id,
                    gate_policy_id=policy_id,
                    gate_name=outcome.gate,
                    status=outcome.status,
                    blocking=outcome.blocking,
                    reason=outcome.reason,
                    details_json=_dump(outcome.details),
                    evaluated_at=now,
                )
                await repository.add(entity)
                entities.append(entity)
        return GateEvaluationView(
            project_id=project_id,
            campaign_id=campaign_id,
            gate_policy_id=policy_id,
            evaluated_at=now,
            decision=decision.to_dict(),
            gates=tuple(
                _gate_result_view(entity, waivers.get(entity.gate_name)) for entity in entities
            ),
        )

    async def get_gate_result(self, gate_result_id: str) -> GateResultView:
        async with self._database.session() as session:
            entity = await QualityGateResultRepository(session).get(gate_result_id)
            if entity is None:
                raise NotFoundError("门禁结果不存在", details={"gate_result_id": gate_result_id})
            waiver = await QualityGateWaiverRepository(session).active_for_gate(
                entity.campaign_id, entity.gate_name
            )
        return _gate_result_view(entity, waiver)

    async def list_gate_results(self, project_id: str, *, campaign_id: str) -> list[GateResultView]:
        async with self._database.session() as session:
            rows = await QualityGateResultRepository(session).latest_for_campaign(campaign_id)
            views: list[GateResultView] = []
            for row in rows:
                if row.project_id != project_id:
                    continue
                waiver = await QualityGateWaiverRepository(session).active_for_gate(
                    campaign_id, row.gate_name
                )
                views.append(_gate_result_view(row, waiver))
        return views

    async def waive_gate_result(
        self,
        gate_result_id: str,
        *,
        authorized_by: str,
        reason: str,
        risk_statement: str,
        scope: str,
        expires_at: datetime,
    ) -> GateResultView:
        if not authorized_by.strip() or not reason.strip():
            raise ValidationFailed("豁免必须提供授权者与原因")
        if not risk_statement.strip() or not scope.strip():
            raise ValidationFailed("豁免必须提供风险说明与适用范围")
        now = utcnow()
        expires_at = ensure_utc(expires_at)
        if expires_at <= now:
            raise ValidationFailed("豁免有效期必须晚于当前时间")
        async with self._database.session() as session, transaction(session):
            repository = QualityGateResultRepository(session)
            entity = await repository.get(gate_result_id)
            if entity is None:
                raise NotFoundError("门禁结果不存在", details={"gate_result_id": gate_result_id})
            if entity.gate_policy_id is not None:
                policy = await QualityGatePolicyRepository(session).get(entity.gate_policy_id)
                if policy is not None and not policy.waivers_allowed:
                    raise ValidationFailed(
                        "该门禁策略不允许豁免",
                        details={"gate_policy_id": policy.gate_policy_id},
                    )
            _ensure_transition(GATE_TRANSITIONS, entity.status, GATE_WAIVED, "质量门禁")
            waiver = QualityGateWaiverModel(
                waiver_id=_new_id("qgw"),
                project_id=entity.project_id,
                gate_result_id=entity.gate_result_id,
                campaign_id=entity.campaign_id,
                gate_name=entity.gate_name,
                authorized_by=authorized_by.strip(),
                reason=reason.strip(),
                risk_statement=risk_statement.strip(),
                scope=scope.strip(),
                expires_at=expires_at,
                created_at=now,
                revoked_at=None,
            )
            await QualityGateWaiverRepository(session).add(waiver)
            entity.status = GATE_WAIVED
            await session.flush()
        return _gate_result_view(entity, waiver)

    # ---- Phase Review（T17） ----

    async def create_phase_review(
        self,
        project_id: str,
        *,
        workflow_id: str,
        phase_id: str,
        campaign_id: str | None = None,
        goals: Sequence[str] = (),
        completed: Sequence[str] = (),
        incomplete: Sequence[str] = (),
        user_confirmations: Sequence[str] = (),
    ) -> PhaseReviewView:
        if not workflow_id.strip() or not phase_id.strip():
            raise ValidationFailed("workflow_id 与 phase_id 不能为空")
        campaign = None
        if campaign_id is not None:
            async with self._database.session() as session:
                campaign = await CampaignRepository(session).get(campaign_id)
            if campaign is None or campaign.project_id != project_id:
                raise NotFoundError("验证活动不存在", details={"campaign_id": campaign_id})
        gate_view = None
        if campaign_id is not None:
            gate_view = await self.evaluate_quality_gate(project_id, campaign_id=campaign_id)
        async with self._database.session() as session:
            counters = (
                await ResultRepository(session).count_by_status(campaign_id)
                if campaign_id is not None
                else {}
            )
            defects = await DefectRepository(session).list_all(project_id)
            evidence_rows = await EvidenceRepository(session).list_all(project_id)
        active_defects = [
            {
                "defect_id": item.defect_id,
                "title": item.title,
                "severity": item.severity,
                "priority": item.priority,
                "status": item.status,
            }
            for item in defects
            if item.status in DEFECT_ACTIVE_STATUSES
        ]
        gate_decision = gate_view.decision if gate_view is not None else None
        summary = build_review_summary(
            project_id=project_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            campaign_id=campaign_id,
            campaign_status=campaign.status if campaign is not None else None,
            gate_status=gate_decision["status"] if gate_decision else None,
            gate_details=gate_decision,
            result_counts=counters,
            defects=active_defects,
            evidence_total=len(
                [row for row in evidence_rows if row.validity_status == EVIDENCE_VALID]
            ),
            goals=goals,
            completed=completed,
            incomplete=incomplete,
            user_confirmations=user_confirmations,
        )
        recommendation = recommendation_for(
            campaign_status=campaign.status if campaign is not None else None,
            gate_status=gate_decision["status"] if gate_decision else None,
            blocking_defects=summary["defects"]["blocking"],
        )
        now = utcnow()
        entity = PhaseReviewModel(
            review_id=_new_id("prv"),
            project_id=project_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            campaign_id=campaign_id,
            status=PHASE_REVIEW_DRAFT,
            summary_json=_dump(summary),
            recommendation=recommendation,
            submitted_by=None,
            submitted_at=None,
            decided_by=None,
            decided_at=None,
            created_at=now,
            updated_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await PhaseReviewRepository(session).add(entity)
        return _phase_review_view(entity)

    async def get_phase_review(self, review_id: str) -> PhaseReviewView:
        async with self._database.session() as session:
            entity = await PhaseReviewRepository(session).get(review_id)
            if entity is None:
                raise NotFoundError("Phase Review 不存在", details={"review_id": review_id})
            decisions = await PhaseReviewDecisionRepository(session).list_for_review(review_id)
        return _phase_review_view(entity, decisions)

    async def list_phase_reviews(
        self,
        project_id: str,
        *,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in PHASE_REVIEW_STATUSES:
            raise ValidationFailed("未知 Phase Review 状态", details={"status": status})
        async with self._database.session() as session:
            page = await PhaseReviewRepository(session).list_page(
                project_id=project_id,
                workflow_id=workflow_id,
                phase_id=phase_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_phase_review_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def submit_phase_review(
        self, review_id: str, *, submitted_by: str | None = None
    ) -> PhaseReviewView:
        async with self._database.session() as session, transaction(session):
            repository = PhaseReviewRepository(session)
            entity = await repository.get(review_id)
            if entity is None:
                raise NotFoundError("Phase Review 不存在", details={"review_id": review_id})
            _ensure_transition(
                PHASE_REVIEW_TRANSITIONS, entity.status, PHASE_REVIEW_SUBMITTED, "Phase Review"
            )
            entity.status = PHASE_REVIEW_SUBMITTED
            entity.submitted_by = submitted_by
            entity.submitted_at = utcnow()
            entity.updated_at = entity.submitted_at
            await session.flush()
        return await self.get_phase_review(review_id)

    async def decide_phase_review(
        self,
        review_id: str,
        *,
        decision: str,
        actor_id: str,
        comment: str = "",
    ) -> PhaseReviewView:
        if decision not in PHASE_REVIEW_DECISIONS:
            raise ValidationFailed("未知验收决策", details={"decision": decision})
        if not actor_id.strip():
            raise ValidationFailed("验收决策必须记录操作者")
        async with self._database.session() as session, transaction(session):
            repository = PhaseReviewRepository(session)
            entity = await repository.get(review_id)
            if entity is None:
                raise NotFoundError("Phase Review 不存在", details={"review_id": review_id})
            if entity.status == PHASE_REVIEW_SUBMITTED:
                entity.status = PHASE_REVIEW_UNDER_REVIEW
            target = PHASE_REVIEW_DECISION_STATUS[decision]
            _ensure_transition(PHASE_REVIEW_TRANSITIONS, entity.status, target, "Phase Review")
            now = utcnow()
            entity.status = target
            entity.decided_by = actor_id.strip()
            entity.decided_at = now
            entity.updated_at = now
            session.add(
                PhaseReviewDecisionModel(
                    decision_id=_new_id("prd"),
                    review_id=review_id,
                    decision=decision,
                    actor_id=actor_id.strip(),
                    comment=comment,
                    decided_at=now,
                )
            )
            await session.flush()
        return await self.get_phase_review(review_id)

    # ---- Dashboard 聚合（T18） ----

    async def verification_overview(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            campaigns = await CampaignRepository(session).list_all(project_id)
            counts = await ResultRepository(session).counts_for_project(project_id)
            defects = await DefectRepository(session).list_all(project_id)
            test_cases = await TestCaseRepository(session).list_active(project_id)
            latest_gate: list[dict[str, Any]] = []
            if campaigns:
                latest_campaign = max(campaigns, key=lambda item: item.created_at)
                rows = await QualityGateResultRepository(session).latest_for_campaign(
                    latest_campaign.campaign_id
                )
                latest_gate = [
                    {
                        "gate": row.gate_name,
                        "status": row.status,
                        "blocking": row.blocking,
                        "reason": row.reason,
                    }
                    for row in rows
                ]
        by_status: dict[str, int] = {}
        for campaign in campaigns:
            by_status[campaign.status] = by_status.get(campaign.status, 0) + 1
        passed = counts.get(RESULT_PASSED, 0)
        failed = counts.get(RESULT_FAILED, 0)
        executed = passed + failed
        unknown = sum(
            counts.get(status, 0) for status in (RESULT_UNKNOWN, RESULT_NOT_RUN, RESULT_SKIPPED)
        )
        blocking_defects = sum(
            1
            for item in defects
            if item.status in DEFECT_ACTIVE_STATUSES
            and item.severity in {DEFECT_BLOCKER, DEFECT_CRITICAL}
        )
        return {
            "project_id": project_id,
            "campaigns": {"total": len(campaigns), "by_status": by_status},
            "results": {
                "passed": passed,
                "failed": failed,
                "unknown_or_not_run": unknown,
                "waived": counts.get(RESULT_WAIVED, 0),
                "executed": executed,
                "pass_rate": round(passed / executed * 100, 2) if executed else 0.0,
                "fail_rate": round(failed / executed * 100, 2) if executed else 0.0,
            },
            "test_cases": len(test_cases),
            "blocking_defects": blocking_defects,
            "latest_campaign_gate": latest_gate,
        }

    async def requirement_dashboard(self, project_id: str) -> dict[str, Any]:
        coverage = await self.coverage(project_id)
        requirements = await self._project_requirements(project_id)
        by_status: dict[str, int] = {}
        for item in requirements:
            status = str(getattr(item, "status", "") or "UNKNOWN")
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "project_id": project_id,
            "total_requirements": len(requirements),
            "by_status": by_status,
            "coverage": coverage,
        }

    async def test_dashboard(self, project_id: str, *, limit: int = 50) -> dict[str, Any]:
        async with self._database.session() as session:
            test_cases = await TestCaseRepository(session).list_active(project_id)
            runs = await RunRepository(session).list_for_project(project_id, limit=limit)
            environments = await RuntimeEnvironmentRepository(session).list_page(
                project_id=project_id, limit=50
            )
            counters = await ResultRepository(session).counts_for_project(project_id)
        by_type: dict[str, int] = {}
        for case in test_cases:
            by_type[case.test_type] = by_type.get(case.test_type, 0) + 1
        run_items = []
        for run in runs:
            duration = None
            if run.started_at is not None and run.completed_at is not None:
                duration = round((run.completed_at - run.started_at).total_seconds(), 3)
            run_items.append(
                {
                    "run_id": run.run_id,
                    "campaign_id": run.campaign_id,
                    "status": run.execution_status,
                    "started_at": run.started_at,
                    "completed_at": run.completed_at,
                    "duration_seconds": duration,
                }
            )
        return {
            "project_id": project_id,
            "test_case_count": len(test_cases),
            "test_case_by_type": by_type,
            "result_counts": counters,
            "recent_runs": run_items,
            "runtime_environments": [
                {
                    "environment_id": item.environment_id,
                    "name": item.name,
                    "status": item.status,
                    "godot_version": item.godot_version,
                    "runtime_instance_id": item.runtime_instance_id,
                }
                for item in environments.items
            ],
        }

    async def evidence_dashboard(self, project_id: str, *, limit: int = 50) -> dict[str, Any]:
        async with self._database.session() as session:
            rows = await EvidenceRepository(session).list_all(project_id)
        summary = await self.evidence_summary(project_id)
        items = [
            {
                "evidence_id": row.evidence_id,
                "evidence_type": row.evidence_type,
                "source_type": row.source_type,
                "validity_status": row.validity_status,
                "content_hash": row.content_hash,
                "source_reference": row.source_reference,
                "metadata": _load(row.metadata_json, {}),
                "created_at": row.created_at,
            }
            for row in rows[-limit:]
        ]
        summary["items"] = items
        return summary

    # ---- 追踪与覆盖率 ----

    async def coverage(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            links = TestLinkRepository(session)
            covered = await links.covered_requirement_ids(project_id)
            results = ResultRepository(session)
            counts = await results.counts_for_project(project_id)
        requirements = await self._project_requirements(project_id)
        testable = [
            item
            for item in requirements
            if getattr(item, "status", None) not in _REQUIREMENT_NOT_TESTABLE
        ]
        testable_ids = {getattr(item, "requirement_id", "") for item in testable}
        covered_ids = covered & testable_ids
        total = len(testable_ids)
        passed = counts.get(RESULT_PASSED, 0)
        failed = counts.get(RESULT_FAILED, 0)
        executed = passed + failed
        unexecuted = sum(
            counts.get(status, 0)
            for status in (RESULT_NOT_RUN, "UNKNOWN", "SKIPPED", RESULT_WAIVED)
        )
        coverage_rate = round(len(covered_ids) / total * 100, 2) if total else 0.0
        pass_rate = round(passed / executed * 100, 2) if executed else 0.0
        return {
            "project_id": project_id,
            "total_testable_requirements": total,
            "covered_requirements": len(covered_ids),
            "untraceable_requirement_ids": sorted(testable_ids - covered_ids),
            "coverage_rate": coverage_rate,
            "executed_tests": executed,
            "passed_tests": passed,
            "failed_tests": failed,
            "unexecuted_results": unexecuted,
            "pass_rate": pass_rate,
        }

    async def trace_requirement(self, requirement_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            criteria = await CriterionRepository(session).list_for_requirement(requirement_id)
            links = await TestLinkRepository(session).list_for_requirement(requirement_id)
            latest = await ResultRepository(session).latest_for_requirement(requirement_id)
        return {
            "requirement_id": requirement_id,
            "criteria": [_criterion_view(item) for item in criteria],
            "links": [_link_view(item) for item in links],
            "latest_result": None if latest is None else _result_view(latest),
        }

    # ---- 内部校验 ----

    async def _ensure_requirement(self, requirement_id: str) -> None:
        if self._requirements is None:
            return
        getter = getattr(self._requirements, "get", None)
        if getter is None:
            return
        try:
            await getter(requirement_id)
        except NotFoundError as exc:
            raise VerificationRequirementUntraceable(
                "需求不存在，无法建立追踪",
                details={"requirement_id": requirement_id},
            ) from exc

    async def _project_requirements(self, project_id: str) -> list[Any]:
        if self._requirements is None:
            return []
        lister = getattr(self._requirements, "list", None)
        if lister is None:
            return []
        return list(await lister(project_id))

    async def _project_root(self, project_id: str) -> str | None:
        if self._projects is None:
            return None
        getter = getattr(self._projects, "get", None)
        if getter is None:
            return None
        try:
            view = await getter(project_id)
        except NotFoundError:
            return None
        root = getattr(view, "project_root", None)
        return str(root) if root else None

    async def _ensure_evidence(
        self, session: Any, project_id: str, evidence_ids: tuple[str, ...]
    ) -> None:
        if not evidence_ids:
            return
        rows = await EvidenceRepository(session).list_by_ids(evidence_ids)
        found = {row.evidence_id: row for row in rows}
        missing = [item for item in evidence_ids if item not in found]
        if missing:
            raise VerificationEvidenceInvalid("引用的证据不存在", details={"missing": missing})
        stale = [
            item
            for item in evidence_ids
            if found[item].validity_status != EVIDENCE_VALID or found[item].project_id != project_id
        ]
        if stale:
            raise VerificationEvidenceStale(
                "引用的证据已失效或不属于该项目", details={"invalid": stale}
            )
