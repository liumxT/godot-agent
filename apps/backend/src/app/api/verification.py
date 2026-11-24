"""E9 验证与质量 API（T18）。

契约规则：

- Agent 只能提交验证请求、计划与自测结果；最终结果状态由 Verification System 拥有；
- 本 API 不修改 Task / Workflow / Approval / ChangeSet 状态；
- 通过结果必须带有效证据；豁免仅 owner 可执行；
- 所有资源访问都先解析项目，再执行项目授权。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.verification import (
    AgentRunRequest,
    CampaignCreateRequest,
    CampaignTransitionRequest,
    CriterionCreateRequest,
    DebuggerErrorIngestRequest,
    DebuggerErrorResolveRequest,
    DebuggerGateRequest,
    DefectCreateRequest,
    DefectTransitionRequest,
    EvidenceCreateRequest,
    EvidenceInvalidateRequest,
    EvidenceStaleRequest,
    GateEvaluateRequest,
    GatePolicyCreateRequest,
    GateWaiverRequest,
    ImpactAnalysisRequest,
    PhaseReviewCreateRequest,
    PhaseReviewDecisionRequest,
    PhaseReviewSubmitRequest,
    PlanCreateRequest,
    PlanProposalRequest,
    PlanTransitionRequest,
    PrepareVerificationRequest,
    RequirementInvalidateRequest,
    ResultCreateRequest,
    ResultWaiveRequest,
    RunCompleteRequest,
    RunStartRequest,
    RuntimeEnvironmentCreateRequest,
    RuntimeEnvironmentUpdateRequest,
    TestCaseCreateRequest,
    TestLinkCreateRequest,
)
from core.errors import NotFoundError
from core.security.principal import (
    ACTION_E9_PHASE_REVIEW_DECIDE,
    ACTION_E9_PHASE_REVIEW_READ,
    ACTION_E9_PHASE_REVIEW_SUBMIT,
    ACTION_E9_QUALITY_GATE_EVALUATE,
    ACTION_E9_QUALITY_GATE_READ,
    ACTION_E9_VERIFICATION_CREATE,
    ACTION_E9_VERIFICATION_READ,
    ACTION_E9_VERIFICATION_REVIEW,
    ACTION_E9_VERIFICATION_RUN,
    ACTION_E9_VERIFICATION_WAIVE,
)
from modules.verification.debugger import DebuggerErrorInput, DebuggerGatePolicy
from modules.verification.orchestrator import VerificationOrchestrator
from modules.verification.planner import PlanProposal
from modules.verification.service import VerificationService

router = APIRouter(
    tags=["verification"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足"},
    404: {"description": "验证活动、计划、执行、结果或证据不存在"},
    409: {"description": "状态冲突、证据失效或版本冲突"},
    422: {"description": "请求参数校验失败"},
    429: {"description": "触发限流"},
}


def _service(request: Request) -> VerificationService:
    return request.app.state.services.get("verification_service", VerificationService)


def _orchestrator(request: Request) -> VerificationOrchestrator:
    return request.app.state.services.get(
        "verification_orchestrator", VerificationOrchestrator
    )


def _proposal_payload(proposal: PlanProposal) -> dict:
    return {
        "project_id": proposal.project_id,
        "requirement_ids": list(proposal.requirement_ids),
        "verification_layers": list(proposal.verification_layers),
        "test_case_ids": list(proposal.test_case_ids),
        "environment_profile": proposal.environment_profile,
        "target_platforms": list(proposal.target_platforms),
        "acceptance_policy": proposal.acceptance_policy,
        "ready": proposal.ready,
        "gaps": [asdict(gap) for gap in proposal.gaps],
    }


async def _campaign_project(request: Request, campaign_id: str, action: str) -> str:
    view = await _service(request).get_campaign(campaign_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


async def _plan_project(request: Request, plan_id: str, action: str) -> str:
    view = await _service(request).get_plan(plan_id)
    campaign = await _service(request).get_campaign(view.campaign_id)
    await authorize_project_action(request, campaign.project_id, action)
    return campaign.project_id


async def _run_project(request: Request, run_id: str, action: str) -> str:
    view = await _service(request).get_run(run_id)
    campaign = await _service(request).get_campaign(view.campaign_id)
    await authorize_project_action(request, campaign.project_id, action)
    return campaign.project_id


async def _result_project(request: Request, result_id: str, action: str) -> str:
    view = await _service(request).get_result(result_id)
    campaign = await _service(request).get_campaign(view.campaign_id)
    await authorize_project_action(request, campaign.project_id, action)
    return campaign.project_id


async def _defect_project(request: Request, defect_id: str, action: str) -> str:
    view = await _service(request).get_defect(defect_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


@router.post(
    "/projects/{project_id}/verification/campaigns",
    status_code=status.HTTP_201_CREATED,
    summary="创建验证活动",
    responses=_ERRORS,
)
async def create_campaign(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: CampaignCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_CREATE)
    view = await _service(request).create_campaign(
        project_id=project_id,
        campaign_type=payload.campaign_type,
        workflow_id=payload.workflow_id,
        phase_id=payload.phase_id,
        task_id=payload.task_id,
        changeset_id=payload.changeset_id,
        verification_policy_id=payload.verification_policy_id,
        created_by=request.state.principal.client_id,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/verification/campaigns",
    summary="列出验证活动",
    responses=_ERRORS,
)
async def list_campaigns(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    campaign_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_campaigns(
        project_id,
        status=status_filter,
        campaign_type=campaign_type,
        limit=limit,
        offset=offset,
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.get("/verification/campaigns/{campaign_id}", summary="读取验证活动", responses=_ERRORS)
async def get_campaign(
    campaign_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_READ)
    return asdict(await _service(request).get_campaign(campaign_id))


@router.post(
    "/verification/campaigns/{campaign_id}/transitions",
    summary="推进验证活动状态",
    responses=_ERRORS,
)
async def transition_campaign(
    campaign_id: str = Path(min_length=1, max_length=64),
    payload: CampaignTransitionRequest = ...,
    request: Request = ...,
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_REVIEW)
    return asdict(await _service(request).transition_campaign(campaign_id, payload.status))


@router.post(
    "/verification/campaigns/{campaign_id}/plans",
    status_code=status.HTTP_201_CREATED,
    summary="创建验证计划",
    description="验证计划必须声明验证层次；活动会被推进到 READY。",
    responses=_ERRORS,
)
async def create_plan(
    campaign_id: str = Path(min_length=1, max_length=64),
    payload: PlanCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_CREATE)
    view = await _service(request).create_plan(
        campaign_id,
        requirement_ids=tuple(payload.requirement_ids),
        test_suite_ids=tuple(payload.test_suite_ids),
        verification_layers=tuple(payload.verification_layers),
        environment_profile=payload.environment_profile,
        target_platforms=tuple(payload.target_platforms),
        acceptance_policy=payload.acceptance_policy,
    )
    return asdict(view)


@router.get(
    "/verification/campaigns/{campaign_id}/plans/latest",
    summary="读取最新验证计划",
    responses=_ERRORS,
)
async def latest_plan(
    campaign_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_READ)
    view = await _service(request).latest_plan(campaign_id)
    return {"plan": None if view is None else asdict(view)}


@router.get("/verification/plans/{plan_id}", summary="读取验证计划", responses=_ERRORS)
async def get_plan(
    plan_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    await _plan_project(request, plan_id, ACTION_E9_VERIFICATION_READ)
    return asdict(await _service(request).get_plan(plan_id))


@router.post(
    "/verification/plans/{plan_id}/transitions",
    summary="推进验证计划状态",
    responses=_ERRORS,
)
async def transition_plan(
    plan_id: str = Path(min_length=1, max_length=64),
    payload: PlanTransitionRequest = ...,
    request: Request = ...,
) -> dict:
    await _plan_project(request, plan_id, ACTION_E9_VERIFICATION_REVIEW)
    return asdict(await _service(request).transition_plan(plan_id, payload.status))


@router.post(
    "/projects/{project_id}/verification/test-cases",
    status_code=status.HTTP_201_CREATED,
    summary="登记测试用例",
    responses=_ERRORS,
)
async def create_test_case(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: TestCaseCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_CREATE)
    view = await _service(request).register_test_case(
        project_id=project_id,
        name=payload.name,
        test_type=payload.test_type,
        execution_method=payload.execution_method,
        description=payload.description,
        preconditions=tuple(payload.preconditions),
        steps=tuple(payload.steps),
        expected_result=payload.expected_result,
        risk_level=payload.risk_level,
        automation_level=payload.automation_level,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/verification/test-cases",
    summary="列出测试用例",
    responses=_ERRORS,
)
async def list_test_cases(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    test_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_test_cases(
        project_id, test_type=test_type, status=status_filter, limit=limit, offset=offset
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.post(
    "/projects/{project_id}/verification/criteria",
    status_code=status.HTTP_201_CREATED,
    summary="登记验收标准",
    responses=_ERRORS,
)
async def create_criterion(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: CriterionCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_CREATE)
    view = await _service(request).register_criterion(
        project_id=project_id,
        requirement_id=payload.requirement_id,
        criterion_type=payload.criterion_type,
        statement=payload.statement,
        verification_method=payload.verification_method,
        expected=payload.expected,
        threshold=payload.threshold,
        required_evidence=tuple(payload.required_evidence),
        priority=payload.priority,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/verification/criteria",
    summary="列出验收标准",
    responses=_ERRORS,
)
async def list_criteria(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    criterion_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_criteria(
        project_id,
        status=status_filter,
        criterion_type=criterion_type,
        limit=limit,
        offset=offset,
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.post(
    "/projects/{project_id}/verification/links",
    status_code=status.HTTP_201_CREATED,
    summary="建立需求与测试追踪",
    responses=_ERRORS,
)
async def create_test_link(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: TestLinkCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_CREATE)
    view = await _service(request).link_test(
        requirement_id=payload.requirement_id,
        test_case_id=payload.test_case_id,
        criterion_id=payload.criterion_id,
        coverage_type=payload.coverage_type,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/verification/coverage",
    summary="需求验证覆盖率",
    description="未建立测试追踪的需求会出现在 untraceable_requirement_ids 中。",
    responses=_ERRORS,
)
async def verification_coverage(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).coverage(project_id)


@router.get(
    "/verification/requirements/{requirement_id}/trace",
    summary="读取需求追踪链",
    responses=_ERRORS,
)
async def trace_verification_requirement(
    requirement_id: str = Path(min_length=1, max_length=64),
    project_id: str = Query(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    trace = await _service(request).trace_requirement(requirement_id)
    trace["criteria"] = [asdict(item) for item in trace["criteria"]]
    trace["links"] = [asdict(item) for item in trace["links"]]
    if trace["latest_result"] is not None:
        trace["latest_result"] = asdict(trace["latest_result"])
    return trace


@router.post(
    "/projects/{project_id}/verification/requirements/{requirement_id}/invalidate",
    summary="需求变更影响分析",
    description="使旧验收标准与旧结果进入待复核状态，不直接修改需求本身。",
    responses=_ERRORS,
)
async def invalidate_requirement(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    requirement_id: str = Path(min_length=1, max_length=64),
    payload: RequirementInvalidateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_REVIEW)
    counts = await _service(request).invalidate_requirement(
        requirement_id, reason=payload.reason
    )
    return {"requirement_id": requirement_id, **counts}


@router.post(
    "/projects/{project_id}/verification/evidence",
    status_code=status.HTTP_201_CREATED,
    summary="登记验证证据",
    responses=_ERRORS,
)
async def create_evidence(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: EvidenceCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_CREATE)
    view = await _service(request).record_evidence(
        project_id=project_id,
        evidence_type=payload.evidence_type,
        source_type=payload.source_type,
        source_reference=payload.source_reference,
        content_hash=payload.content_hash,
        run_id=payload.run_id,
        captured_at=payload.captured_at,
        metadata=payload.metadata,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/verification/evidence",
    summary="列出验证证据",
    responses=_ERRORS,
)
async def list_evidence(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    evidence_type: str | None = Query(default=None),
    validity_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_evidence(
        project_id,
        evidence_type=evidence_type,
        validity_status=validity_status,
        limit=limit,
        offset=offset,
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.post(
    "/verification/evidence/{evidence_id}/invalidate",
    summary="使证据失效",
    responses=_ERRORS,
)
async def invalidate_evidence(
    evidence_id: str = Path(min_length=1, max_length=64),
    payload: EvidenceInvalidateRequest = ...,
    request: Request = ...,
) -> dict:
    view = await _service(request).get_evidence(evidence_id)
    await authorize_project_action(request, view.project_id, ACTION_E9_VERIFICATION_REVIEW)
    return asdict(await _service(request).invalidate_evidence(evidence_id, status=payload.status))


@router.post(
    "/projects/{project_id}/verification/plan-proposals",
    summary="推导验证计划",
    description="根据验收标准与测试追踪推导验证层次；存在缺口时 ready=false。",
    responses=_ERRORS,
)
async def propose_verification_plan(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: PlanProposalRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    proposal = await _service(request).propose_plan(
        project_id,
        tuple(payload.requirement_ids),
        target_platforms=tuple(payload.target_platforms),
        environment_profile=payload.environment_profile,
        acceptance_policy=payload.acceptance_policy,
    )
    return _proposal_payload(proposal)


@router.post(
    "/projects/{project_id}/verification/prepare",
    status_code=status.HTTP_201_CREATED,
    summary="准备验证活动",
    description="需求追踪完整时创建 Campaign 与 VerificationPlan，不修改 Task 状态。",
    responses=_ERRORS,
)
async def prepare_verification(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: PrepareVerificationRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_CREATE)
    prepared = await _orchestrator(request).prepare(
        project_id=project_id,
        campaign_type=payload.campaign_type,
        requirement_ids=tuple(payload.requirement_ids),
        workflow_id=payload.workflow_id,
        phase_id=payload.phase_id,
        task_id=payload.task_id,
        changeset_id=payload.changeset_id,
        target_platforms=tuple(payload.target_platforms),
        environment_profile=payload.environment_profile,
        acceptance_policy=payload.acceptance_policy or None,
        allow_gaps=payload.allow_gaps,
        created_by=request.state.principal.client_id,
    )
    return {
        "campaign": asdict(prepared.campaign),
        "plan": asdict(prepared.plan),
        "proposal": _proposal_payload(prepared.proposal),
    }


@router.post(
    "/verification/campaigns/{campaign_id}/execute",
    summary="编排执行验证计划",
    description="按验证层次顺序执行；未注册执行器的层次记为 NOT_RUN，不算通过。",
    responses=_ERRORS,
)
async def execute_campaign(
    campaign_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_RUN)
    report = await _orchestrator(request).run_plan(
        campaign_id, executor_id=request.state.principal.client_id
    )
    return asdict(report)


@router.post(
    "/verification/campaigns/{campaign_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="开始一次验证执行",
    responses=_ERRORS,
)
async def start_run(
    campaign_id: str = Path(min_length=1, max_length=64),
    payload: RunStartRequest = ...,
    request: Request = ...,
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_RUN)
    view = await _service(request).start_run(
        campaign_id,
        plan_id=payload.plan_id,
        test_suite_id=payload.test_suite_id,
        test_case_id=payload.test_case_id,
        environment_id=payload.environment_id,
        executor_id=request.state.principal.client_id,
    )
    return asdict(view)


@router.get(
    "/verification/campaigns/{campaign_id}/runs",
    summary="列出验证执行",
    responses=_ERRORS,
)
async def list_runs(
    campaign_id: str = Path(min_length=1, max_length=64),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_runs(campaign_id, limit=limit, offset=offset)
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.post(
    "/verification/runs/{run_id}/complete",
    summary="完成一次验证执行",
    responses=_ERRORS,
)
async def complete_run(
    run_id: str = Path(min_length=1, max_length=64),
    payload: RunCompleteRequest = ...,
    request: Request = ...,
) -> dict:
    await _run_project(request, run_id, ACTION_E9_VERIFICATION_RUN)
    view = await _service(request).complete_run(
        run_id,
        execution_status=payload.execution_status,
        evidence_ids=tuple(payload.evidence_ids),
        failure_reason=payload.failure_reason,
    )
    return asdict(view)


@router.post(
    "/verification/campaigns/{campaign_id}/results",
    status_code=status.HTTP_201_CREATED,
    summary="记录验证结果",
    responses=_ERRORS,
)
async def create_result(
    campaign_id: str = Path(min_length=1, max_length=64),
    payload: ResultCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_RUN)
    view = await _service(request).record_result(
        campaign_id=campaign_id,
        result_status=payload.result_status,
        run_id=payload.run_id,
        requirement_id=payload.requirement_id,
        criterion_id=payload.criterion_id,
        test_case_id=payload.test_case_id,
        evidence_ids=tuple(payload.evidence_ids),
        failure_reason=payload.failure_reason,
        confidence_level=payload.confidence_level,
    )
    return asdict(view)


@router.get(
    "/verification/campaigns/{campaign_id}/results",
    summary="列出验证结果",
    responses=_ERRORS,
)
async def list_results(
    campaign_id: str = Path(min_length=1, max_length=64),
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_results(campaign_id, limit=limit, offset=offset)
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.get("/verification/results/{result_id}", summary="读取验证结果", responses=_ERRORS)
async def get_result(
    result_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    await _result_project(request, result_id, ACTION_E9_VERIFICATION_READ)
    return asdict(await _service(request).get_result(result_id))


@router.post(
    "/verification/results/{result_id}/waive",
    summary="豁免验证结果",
    description="仅 owner 可豁免；豁免不等于通过，结果状态为 WAIVED。",
    responses=_ERRORS,
)
async def waive_result(
    result_id: str = Path(min_length=1, max_length=64),
    payload: ResultWaiveRequest = ...,
    request: Request = ...,
) -> dict:
    await _result_project(request, result_id, ACTION_E9_VERIFICATION_WAIVE)
    view = await _service(request).waive_result(
        result_id,
        reason=payload.reason,
        waived_by=request.state.principal.client_id,
    )
    return asdict(view)


# ---- 运行时环境（T08） ----


@router.post(
    "/projects/{project_id}/verification/runtime-environments",
    status_code=status.HTTP_201_CREATED,
    summary="登记运行时测试环境",
    responses=_ERRORS,
)
async def register_runtime_environment(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: RuntimeEnvironmentCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_RUN)
    view = await _service(request).register_runtime_environment(
        project_id=project_id,
        project_revision=payload.project_revision,
        godot_version=payload.godot_version,
        platform=payload.platform,
        display_resolution=payload.display_resolution,
        renderer=payload.renderer,
        runtime_instance_id=payload.runtime_instance_id,
        test_configuration=payload.test_configuration,
        status=payload.status,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/verification/runtime-environments",
    summary="列出运行时测试环境",
    responses=_ERRORS,
)
async def list_runtime_environments(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_runtime_environments(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.get(
    "/verification/runtime-environments/{environment_id}",
    summary="读取运行时测试环境",
    responses=_ERRORS,
)
async def get_runtime_environment(
    environment_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _service(request).get_runtime_environment(environment_id)
    await authorize_project_action(request, view.project_id, ACTION_E9_VERIFICATION_READ)
    return asdict(view)


@router.patch(
    "/projects/{project_id}/verification/runtime-environments/{environment_id}",
    summary="更新运行时测试环境状态",
    responses=_ERRORS,
)
async def update_runtime_environment(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    environment_id: str = Path(min_length=1, max_length=64),
    payload: RuntimeEnvironmentUpdateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_RUN)
    view = await _service(request).update_runtime_environment(
        environment_id,
        status=payload.status,
        runtime_instance_id=payload.runtime_instance_id,
    )
    if view.project_id != project_id:
        raise NotFoundError("运行时环境不属于该项目", details={"environment_id": environment_id})
    return asdict(view)


# ---- Debugger 错误（T10） ----


@router.post(
    "/projects/{project_id}/verification/debugger-errors",
    status_code=status.HTTP_201_CREATED,
    summary="上报结构化 Debugger 错误",
    description="按 fingerprint 聚合；历史错误标记为 baseline，不修改 ChangeSet 状态。",
    responses=_ERRORS,
)
async def ingest_debugger_errors(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: DebuggerErrorIngestRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_RUN)
    errors = [
        DebuggerErrorInput(
            category=item.category,
            severity=item.severity,
            message=item.message,
            source=item.source,
            scene=item.scene,
            node=item.node,
            script=item.script,
            stack_trace=item.stack_trace,
            runtime_instance_id=item.runtime_instance_id,
            godot_version=item.godot_version,
            project_revision=item.project_revision,
            changeset_id=item.changeset_id,
        )
        for item in payload.errors
    ]
    result = await _service(request).record_debugger_errors(
        project_id=project_id,
        errors=errors,
        run_id=payload.run_id,
        project_revision=payload.project_revision,
        baseline=payload.baseline,
    )
    result["items"] = [asdict(item) for item in result["items"]]
    return result


@router.get(
    "/projects/{project_id}/verification/debugger-errors",
    summary="列出 Debugger 错误",
    responses=_ERRORS,
)
async def list_debugger_errors(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    severity: str | None = Query(default=None, max_length=16),
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    is_baseline: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_debugger_errors(
        project_id,
        severity=severity,
        status=status_filter,
        is_baseline=is_baseline,
        limit=limit,
        offset=offset,
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.post(
    "/verification/debugger-errors/{error_id}/resolve",
    summary="标记 Debugger 错误为已解决或忽略",
    responses=_ERRORS,
)
async def resolve_debugger_error(
    error_id: str = Path(min_length=1, max_length=64),
    payload: DebuggerErrorResolveRequest = ...,
    request: Request = ...,
) -> dict:
    existing = await _service(request).get_debugger_error(error_id)
    await authorize_project_action(request, existing.project_id, ACTION_E9_VERIFICATION_REVIEW)
    view = await _service(request).resolve_debugger_error(
        error_id, status=payload.status, note=payload.note
    )
    return asdict(view)


@router.post(
    "/projects/{project_id}/verification/debugger-gate",
    summary="评估 Debugger 错误门禁",
    description="新增 Fatal/Error 未解决时阻止；历史问题只记录基线。",
    responses=_ERRORS,
)
async def evaluate_debugger_gate(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: DebuggerGateRequest | None = None,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_QUALITY_GATE_EVALUATE)
    policy = None
    if payload is not None:
        policy = DebuggerGatePolicy(
            block_new_fatal=payload.block_new_fatal,
            block_new_error=payload.block_new_error,
            require_approval_for_new_error=payload.require_approval_for_new_error,
            block_new_warning=payload.block_new_warning,
            warn_on_new_warning=payload.warn_on_new_warning,
        )
    decision = await _service(request).evaluate_debugger_gate(project_id, policy=policy)
    return decision.to_dict()


# ---- 证据管理（T13） ----


@router.get(
    "/projects/{project_id}/verification/evidence-summary",
    summary="统计项目证据",
    responses=_ERRORS,
)
async def get_evidence_summary(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).evidence_summary(project_id)


@router.get(
    "/projects/{project_id}/verification/evidence-integrity",
    summary="检查证据完整性与可追溯性",
    responses=_ERRORS,
)
async def check_evidence_integrity(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).check_evidence_integrity(project_id)


@router.post(
    "/projects/{project_id}/verification/evidence/mark-stale",
    summary="按项目版本批量标记旧证据失效",
    responses=_ERRORS,
)
async def mark_evidence_stale(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: EvidenceStaleRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_REVIEW)
    return await _service(request).mark_stale_evidence(
        project_id, project_revision=payload.project_revision
    )


# ---- 缺陷管理（T14） ----


@router.post(
    "/projects/{project_id}/verification/defects",
    status_code=status.HTTP_201_CREATED,
    summary="登记缺陷",
    description="缺陷必须带来源、复现步骤与证据引用；Severity 与 Priority 独立。",
    responses=_ERRORS,
)
async def create_defect(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: DefectCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_CREATE)
    view = await _service(request).create_defect(
        project_id=project_id,
        severity=payload.severity,
        category=payload.category,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        requirement_id=payload.requirement_id,
        source_result_id=payload.source_result_id,
        reproduction_steps=payload.reproduction_steps,
        expected_result=payload.expected_result,
        actual_result=payload.actual_result,
        evidence_ids=payload.evidence_ids,
        assigned_agent_id=payload.assigned_agent_id,
        related_changeset_id=payload.related_changeset_id,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/verification/defects",
    summary="列出缺陷",
    responses=_ERRORS,
)
async def list_defects(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    severity: str | None = Query(default=None, max_length=16),
    category: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_defects(
        project_id,
        status=status_filter,
        severity=severity,
        category=category,
        limit=limit,
        offset=offset,
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.get(
    "/projects/{project_id}/verification/defects/summary",
    summary="统计缺陷分布",
    responses=_ERRORS,
)
async def defect_summary(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).defect_summary(project_id)


@router.get(
    "/verification/defects/{defect_id}",
    summary="读取缺陷",
    responses=_ERRORS,
)
async def get_defect(
    defect_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _defect_project(request, defect_id, ACTION_E9_VERIFICATION_READ)
    return asdict(await _service(request).get_defect(defect_id))


@router.post(
    "/verification/defects/{defect_id}/transition",
    summary="迁移缺陷状态",
    description="修复后必须重新验证；解决时必须提供修复验证引用。",
    responses=_ERRORS,
)
async def transition_defect(
    defect_id: str = Path(min_length=1, max_length=64),
    payload: DefectTransitionRequest = ...,
    request: Request = ...,
) -> dict:
    await _defect_project(request, defect_id, ACTION_E9_VERIFICATION_REVIEW)
    view = await _service(request).transition_defect(
        defect_id,
        payload.status,
        assigned_agent_id=payload.assigned_agent_id,
        resolution_reference=payload.resolution_reference,
        note=payload.note,
    )
    return asdict(view)


# ---- 回归与影响分析（T15） ----


@router.post(
    "/projects/{project_id}/verification/impact-analysis",
    status_code=status.HTTP_201_CREATED,
    summary="分析变更影响并生成回归计划",
    description="依据 ChangeSet、依赖图、需求追踪与历史缺陷生成回归策略与必须检查项。",
    responses=_ERRORS,
)
async def analyze_impact(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: ImpactAnalysisRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_CREATE)
    view = await _service(request).analyze_impact(
        project_id,
        changeset_id=payload.changeset_id,
        changed_files=[
            {
                "resource_path": item.resource_path,
                "operation_type": item.operation_type,
                "risk_level": item.risk_level,
            }
            for item in payload.changed_files
        ],
        force_full=payload.force_full,
        security_requested=payload.security_requested,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/verification/regression-plans",
    summary="列出回归计划",
    responses=_ERRORS,
)
async def list_regression_plans(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    page = await _service(request).list_regression_plans(
        project_id, limit=limit, offset=offset
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.get(
    "/verification/regression-plans/{regression_plan_id}",
    summary="读取回归计划",
    responses=_ERRORS,
)
async def get_regression_plan(
    regression_plan_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _service(request).get_regression_plan(regression_plan_id)
    await authorize_project_action(request, view.project_id, ACTION_E9_VERIFICATION_READ)
    return asdict(view)


# ---- 质量门禁（T16） ----


@router.post(
    "/projects/{project_id}/quality-gate-policies",
    status_code=status.HTTP_201_CREATED,
    summary="创建质量门禁策略",
    responses=_ERRORS,
)
async def create_gate_policy(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: GatePolicyCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_QUALITY_GATE_EVALUATE)
    view = await _service(request).create_gate_policy(
        project_id=project_id,
        name=payload.name,
        gates=payload.gates,
        campaign_type=payload.campaign_type,
        risk_level=payload.risk_level,
        waivers_allowed=payload.waivers_allowed,
        created_by=payload.created_by,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/quality-gate-policies",
    summary="列出质量门禁策略",
    responses=_ERRORS,
)
async def list_gate_policies(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_QUALITY_GATE_READ)
    items = await _service(request).list_gate_policies(project_id)
    return {"items": [asdict(item) for item in items], "total": len(items)}


@router.post(
    "/projects/{project_id}/quality-gate/evaluate",
    summary="评估质量门禁",
    description="依据真实验证结果生成门禁结论；未执行与 UNKNOWN 不会计为 PASSED。",
    responses=_ERRORS,
)
async def evaluate_quality_gate(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: GateEvaluateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_QUALITY_GATE_EVALUATE)
    view = await _service(request).evaluate_quality_gate(
        project_id,
        campaign_id=payload.campaign_id,
        policy_id=payload.policy_id,
        risk_level=payload.risk_level,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/quality-gate/results",
    summary="读取最新门禁结果",
    responses=_ERRORS,
)
async def list_gate_results(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    campaign_id: str = Query(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_QUALITY_GATE_READ)
    items = await _service(request).list_gate_results(
        project_id, campaign_id=campaign_id
    )
    return {"items": [asdict(item) for item in items], "total": len(items)}


@router.post(
    "/quality-gate/results/{gate_result_id}/waive",
    summary="豁免门禁结果",
    description="豁免必须记录授权者、原因、风险、范围与有效期。",
    responses=_ERRORS,
)
async def waive_gate_result(
    gate_result_id: str = Path(min_length=1, max_length=64),
    payload: GateWaiverRequest = ...,
    request: Request = ...,
) -> dict:
    current = await _service(request).get_gate_result(gate_result_id)
    await authorize_project_action(
        request, current.project_id, ACTION_E9_VERIFICATION_WAIVE
    )
    view = await _service(request).waive_gate_result(
        gate_result_id,
        authorized_by=payload.authorized_by,
        reason=payload.reason,
        risk_statement=payload.risk_statement,
        scope=payload.scope,
        expires_at=payload.expires_at,
    )
    return asdict(view)


# ---- Phase Review（T17） ----


@router.post(
    "/projects/{project_id}/phase-reviews",
    status_code=status.HTTP_201_CREATED,
    summary="生成 Phase Review 报告",
    description="报告只汇总验证数据；Verification PASSED 不会自动成为 ACCEPTED。",
    responses=_ERRORS,
)
async def create_phase_review(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: PhaseReviewCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(
        request, project_id, ACTION_E9_PHASE_REVIEW_SUBMIT
    )
    view = await _service(request).create_phase_review(
        project_id,
        workflow_id=payload.workflow_id,
        phase_id=payload.phase_id,
        campaign_id=payload.campaign_id,
        goals=payload.goals,
        completed=payload.completed,
        incomplete=payload.incomplete,
        user_confirmations=payload.user_confirmations,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/phase-reviews",
    summary="列出 Phase Review",
    responses=_ERRORS,
)
async def list_phase_reviews(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    workflow_id: str | None = Query(default=None, max_length=64),
    phase_id: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_PHASE_REVIEW_READ)
    page = await _service(request).list_phase_reviews(
        project_id,
        workflow_id=workflow_id,
        phase_id=phase_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.get(
    "/phase-reviews/{review_id}",
    summary="读取 Phase Review",
    responses=_ERRORS,
)
async def get_verification_phase_review(
    review_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _service(request).get_phase_review(review_id)
    await authorize_project_action(request, view.project_id, ACTION_E9_PHASE_REVIEW_READ)
    return asdict(view)


@router.post(
    "/phase-reviews/{review_id}/submit",
    summary="提交 Phase Review",
    responses=_ERRORS,
)
async def submit_verification_phase_review(
    review_id: str = Path(min_length=1, max_length=64),
    payload: PhaseReviewSubmitRequest = ...,
    request: Request = ...,
) -> dict:
    view = await _service(request).get_phase_review(review_id)
    await authorize_project_action(
        request, view.project_id, ACTION_E9_PHASE_REVIEW_SUBMIT
    )
    submitted = await _service(request).submit_phase_review(
        review_id, submitted_by=payload.submitted_by
    )
    return asdict(submitted)


@router.post(
    "/phase-reviews/{review_id}/decide",
    summary="提交用户验收决策",
    description="ACCEPT / REJECT / REQUEST_REVISION 的最终决定权属于用户。",
    responses=_ERRORS,
)
async def decide_phase_review(
    review_id: str = Path(min_length=1, max_length=64),
    payload: PhaseReviewDecisionRequest = ...,
    request: Request = ...,
) -> dict:
    view = await _service(request).get_phase_review(review_id)
    await authorize_project_action(
        request, view.project_id, ACTION_E9_PHASE_REVIEW_DECIDE
    )
    decided = await _service(request).decide_phase_review(
        review_id,
        decision=payload.decision,
        actor_id=payload.actor_id,
        comment=payload.comment,
    )
    return asdict(decided)


# ---- Dashboard（T18） ----


@router.get(
    "/projects/{project_id}/verification/dashboard",
    summary="验证总览看板",
    responses=_ERRORS,
)
async def verification_dashboard(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).verification_overview(project_id)


@router.get(
    "/projects/{project_id}/verification/dashboard/requirements",
    summary="需求覆盖率看板",
    responses=_ERRORS,
)
async def requirement_dashboard(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).requirement_dashboard(project_id)


@router.get(
    "/projects/{project_id}/verification/dashboard/tests",
    summary="测试执行看板",
    responses=_ERRORS,
)
async def test_dashboard(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).test_dashboard(project_id, limit=limit)


@router.get(
    "/projects/{project_id}/verification/dashboard/evidence",
    summary="证据查看看板",
    responses=_ERRORS,
)
async def evidence_dashboard(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).evidence_dashboard(project_id, limit=limit)


# ---- Agent 集成与验证预算（T19） ----


@router.get(
    "/projects/{project_id}/verification/agent-policy",
    summary="Agent 验证策略",
    description="返回 Agent 允许/禁止的验证操作与各风险级别的默认验证预算。",
    responses=_ERRORS,
)
async def verification_agent_policy(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).agent_verification_policy()


@router.get(
    "/verification/campaigns/{campaign_id}/budget",
    summary="读取验证预算用量",
    responses=_ERRORS,
)
async def verification_budget(
    campaign_id: str = Path(min_length=1, max_length=64),
    risk_level: str = Query(default="MEDIUM"),
    request: Request = ...,
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_READ)
    return await _service(request).verification_budget(
        campaign_id, risk_level=risk_level
    )


@router.post(
    "/verification/campaigns/{campaign_id}/agent-runs",
    status_code=status.HTTP_201_CREATED,
    summary="Agent 请求执行验证",
    description="先校验 Agent 策略与验证预算；结果状态仍由 Verification System 拥有。",
    responses=_ERRORS,
)
async def verification_agent_run(
    campaign_id: str = Path(min_length=1, max_length=64),
    payload: AgentRunRequest = ...,
    request: Request = ...,
) -> dict:
    await _campaign_project(request, campaign_id, ACTION_E9_VERIFICATION_RUN)
    view = await _service(request).agent_request_run(
        campaign_id,
        risk_level=payload.risk_level,
        plan_id=payload.plan_id,
        test_suite_id=payload.test_suite_id,
        test_case_id=payload.test_case_id,
        environment_id=payload.environment_id,
        executor_id=request.state.principal.client_id,
    )
    return asdict(view)
