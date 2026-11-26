"""E10 签名、发布审批、发布与分发 API（Batch E）。

- 签名只接受证书/凭证引用，绝不返回密钥本体；
- 发布审批与发布操作仅限项目 Owner；
- 本地交付与线上发布严格区分；
- 分发操作幂等，UNKNOWN 必须核对后收敛。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.build_release import (
    ReleaseApprovalDecisionRequest,
    ReleaseApprovalInvalidateRequest,
    ReleaseApprovalRejectRequest,
    ReleaseApprovalRequest,
    ReleaseCreateRequest,
    ReleaseReconcileRequest,
    ReleaseStartRequest,
    SigningExecuteRequest,
    SigningProfileRegisterRequest,
    SigningReconcileRequest,
)
from core.security.principal import (
    ACTION_E10_ARTIFACT_READ,
    ACTION_E10_DASHBOARD_READ,
    ACTION_E10_DISTRIBUTION_MANAGE,
    ACTION_E10_RELEASE_APPROVE,
    ACTION_E10_RELEASE_MANAGE,
    ACTION_E10_RELEASE_PUBLISH,
    ACTION_E10_RELEASE_READ,
    ACTION_E10_SIGNING_MANAGE,
)
from modules.build_release.agent_policy import agent_policy
from modules.build_release.dashboard import BuildReleaseDashboardService
from modules.build_release.distribution import build_default_registry
from modules.build_release.release_approvals import ReleaseApprovalService
from modules.build_release.release_candidates import ReleaseCandidateService
from modules.build_release.release_manager import ReleaseManagerService
from modules.build_release.signing import SigningService

router = APIRouter(
    tags=["releases"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足"},
    404: {"description": "签名配置、审批或发布不存在"},
    409: {"description": "状态冲突或审批绑定失效"},
    422: {"description": "请求参数校验失败"},
    429: {"description": "触发限流"},
}


def _signing(request: Request) -> SigningService:
    return request.app.state.services.get("signing_service", SigningService)


def _approvals(request: Request) -> ReleaseApprovalService:
    return request.app.state.services.get("release_approval_service", ReleaseApprovalService)


def _releases(request: Request) -> ReleaseManagerService:
    return request.app.state.services.get("release_manager_service", ReleaseManagerService)


async def _authorize_approval(request: Request, approval_id: str, action: str) -> str:
    view = await _approvals(request).get_approval(approval_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


async def _authorize_release(request: Request, release_id: str, action: str) -> str:
    view = await _releases(request).get_release(release_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


@router.post(
    "/projects/{project_id}/signing-profiles",
    status_code=status.HTTP_201_CREATED,
    summary="注册签名配置",
    responses=_ERRORS,
)
async def register_signing_profile(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: SigningProfileRegisterRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_SIGNING_MANAGE)
    view = await _signing(request).register_profile(
        project_id=project_id,
        platform=payload.platform,
        signing_method=payload.signing_method,
        certificate_reference=payload.certificate_reference,
        credential_reference=payload.credential_reference,
        allowed_channels=list(payload.allowed_channels),
        expiration=payload.expiration,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/signing-profiles",
    summary="列出签名配置",
    responses=_ERRORS,
)
async def list_signing_profiles(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_SIGNING_MANAGE)
    page = await _signing(request).list_profiles(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/signing-profiles/{signing_profile_id}",
    summary="获取签名配置",
    responses=_ERRORS,
)
async def get_signing_profile(
    signing_profile_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _signing(request).get_profile(signing_profile_id)
    await authorize_project_action(request, view.project_id, ACTION_E10_SIGNING_MANAGE)
    return asdict(view)


@router.post(
    "/signing-profiles/{signing_profile_id}/disable",
    summary="禁用签名配置",
    responses=_ERRORS,
)
async def disable_signing_profile(
    signing_profile_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    profile = await _signing(request).get_profile(signing_profile_id)
    await authorize_project_action(request, profile.project_id, ACTION_E10_SIGNING_MANAGE)
    view = await _signing(request).disable_profile(signing_profile_id)
    return asdict(view)


@router.post(
    "/artifacts/{artifact_id}/sign",
    summary="对制品执行签名",
    responses=_ERRORS,
)
async def sign_artifact_for_release(
    artifact_id: str = Path(min_length=1, max_length=64),
    payload: SigningExecuteRequest = ...,
    request: Request = ...,
) -> dict:
    profile = await _signing(request).get_profile(payload.signing_profile_id)
    await authorize_project_action(request, profile.project_id, ACTION_E10_SIGNING_MANAGE)
    view = await _signing(request).sign_artifact(
        artifact_id=artifact_id,
        signing_profile_id=payload.signing_profile_id,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/signing-attempts",
    summary="列出签名尝试",
    responses=_ERRORS,
)
async def list_signing_attempts(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_SIGNING_MANAGE)
    page = await _signing(request).list_attempts(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.post(
    "/signing-attempts/{signing_attempt_id}/reconcile",
    summary="核对 UNKNOWN 签名尝试",
    responses=_ERRORS,
)
async def reconcile_signing_attempt(
    signing_attempt_id: str = Path(min_length=1, max_length=64),
    payload: SigningReconcileRequest = ...,
    request: Request = ...,
) -> dict:
    attempt = await _signing(request).get_attempt(signing_attempt_id)
    await authorize_project_action(request, attempt.project_id, ACTION_E10_SIGNING_MANAGE)
    view = await _signing(request).reconcile_attempt(
        signing_attempt_id,
        succeeded=payload.succeeded,
        certificate_fingerprint=payload.certificate_fingerprint,
        detail=payload.detail,
    )
    return asdict(view)


@router.post(
    "/projects/{project_id}/release-approvals",
    status_code=status.HTTP_201_CREATED,
    summary="请求发布审批",
    responses=_ERRORS,
)
async def request_release_approval(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: ReleaseApprovalRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_RELEASE_MANAGE)
    principal = getattr(request.state, "principal", None)
    requested_by = getattr(principal, "client_id", None)
    view = await _approvals(request).request_approval(
        release_candidate_id=payload.release_candidate_id,
        distribution_channel=payload.distribution_channel,
        policy_version=payload.policy_version,
        requested_by=requested_by,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/release-approvals",
    summary="列出发布审批",
    responses=_ERRORS,
)
async def list_release_approvals(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_RELEASE_READ)
    page = await _approvals(request).list_approvals(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/release-approvals/{approval_id}",
    summary="获取发布审批",
    responses=_ERRORS,
)
async def get_release_approval(
    approval_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E10_RELEASE_READ)
    view = await _approvals(request).get_approval(approval_id)
    return asdict(view)


@router.get(
    "/release-candidates/{release_candidate_id}/release-approvals",
    summary="列出候选的发布审批",
    responses=_ERRORS,
)
async def list_candidate_release_approvals(
    release_candidate_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    candidate_service = request.app.state.services.get(
        "release_candidate_service", ReleaseCandidateService
    )
    candidate = await candidate_service.get_candidate(release_candidate_id)
    await authorize_project_action(request, candidate.project_id, ACTION_E10_RELEASE_READ)
    items = await _approvals(request).list_for_candidate(release_candidate_id)
    return {"items": [asdict(item) for item in items]}


@router.post(
    "/release-approvals/{approval_id}/approve",
    summary="批准发布审批（仅用户）",
    responses=_ERRORS,
)
async def approve_release(
    approval_id: str = Path(min_length=1, max_length=64),
    payload: ReleaseApprovalDecisionRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E10_RELEASE_APPROVE)
    view = await _approvals(request).approve(approval_id, approved_by=payload.approved_by)
    return asdict(view)


@router.post(
    "/release-approvals/{approval_id}/reject",
    summary="驳回发布审批（仅用户）",
    responses=_ERRORS,
)
async def reject_release(
    approval_id: str = Path(min_length=1, max_length=64),
    payload: ReleaseApprovalRejectRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E10_RELEASE_APPROVE)
    view = await _approvals(request).reject(approval_id, rejected_by=payload.rejected_by)
    return asdict(view)


@router.post(
    "/release-approvals/{approval_id}/invalidate",
    summary="作废发布审批",
    responses=_ERRORS,
)
async def invalidate_release_approval(
    approval_id: str = Path(min_length=1, max_length=64),
    payload: ReleaseApprovalInvalidateRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E10_RELEASE_MANAGE)
    view = await _approvals(request).invalidate(approval_id, reason=payload.reason)
    return asdict(view)


@router.post(
    "/projects/{project_id}/releases",
    status_code=status.HTTP_201_CREATED,
    summary="创建发布",
    responses=_ERRORS,
)
async def create_release(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: ReleaseCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_RELEASE_MANAGE)
    view = await _releases(request).create_release(
        release_candidate_id=payload.release_candidate_id,
        approval_id=payload.approval_id,
        channel=payload.channel,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/releases",
    summary="列出发布",
    responses=_ERRORS,
)
async def list_releases(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_RELEASE_READ)
    page = await _releases(request).list_releases(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/releases/{release_id}",
    summary="获取发布",
    responses=_ERRORS,
)
async def get_release(
    release_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_release(request, release_id, ACTION_E10_RELEASE_READ)
    view = await _releases(request).get_release(release_id)
    return asdict(view)


@router.post(
    "/releases/{release_id}/authorize",
    summary="授权发布",
    responses=_ERRORS,
)
async def authorize_release(
    release_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_release(request, release_id, ACTION_E10_RELEASE_PUBLISH)
    view = await _releases(request).authorize_release(release_id)
    return asdict(view)


@router.post(
    "/releases/{release_id}/start",
    summary="开始本地交付",
    responses=_ERRORS,
)
async def start_release(
    release_id: str = Path(min_length=1, max_length=64),
    payload: ReleaseStartRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_release(request, release_id, ACTION_E10_RELEASE_PUBLISH)
    view = await _releases(request).start_release(
        release_id,
        target_reference=payload.target_reference,
        idempotency_key=payload.idempotency_key,
    )
    return asdict(view)


@router.post(
    "/releases/{release_id}/verify",
    summary="发布后验证",
    responses=_ERRORS,
)
async def verify_release(
    release_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_release(request, release_id, ACTION_E10_RELEASE_PUBLISH)
    view = await _releases(request).verify_release(release_id)
    return asdict(view)


@router.post(
    "/releases/{release_id}/withdraw",
    summary="撤回本地交付",
    responses=_ERRORS,
)
async def withdraw_release(
    release_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_release(request, release_id, ACTION_E10_DISTRIBUTION_MANAGE)
    view = await _releases(request).withdraw_release(release_id)
    return asdict(view)


@router.post(
    "/releases/{release_id}/rollback",
    summary="标记本地发布回滚",
    responses=_ERRORS,
)
async def rollback_release(
    release_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_release(request, release_id, ACTION_E10_DISTRIBUTION_MANAGE)
    view = await _releases(request).rollback_release(release_id)
    return asdict(view)


@router.post(
    "/releases/{release_id}/reconcile",
    summary="核对 UNKNOWN 发布",
    responses=_ERRORS,
)
async def reconcile_release(
    release_id: str = Path(min_length=1, max_length=64),
    payload: ReleaseReconcileRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_release(request, release_id, ACTION_E10_RELEASE_PUBLISH)
    view = await _releases(request).reconcile_release(
        release_id,
        status=payload.status,
        external_operation_id=payload.external_operation_id,
    )
    return asdict(view)


@router.get(
    "/releases/{release_id}/operations",
    summary="列出分发操作",
    responses=_ERRORS,
)
async def list_release_operations(
    release_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_release(request, release_id, ACTION_E10_RELEASE_READ)
    items = await _releases(request).list_operations(release_id)
    return {"items": [asdict(item) for item in items]}


@router.get(
    "/distribution/capabilities",
    summary="列出分发渠道能力",
    responses=_ERRORS,
)
async def list_distribution_capabilities(request: Request = ...) -> dict:
    capabilities = build_default_registry().capabilities()
    return {"items": [asdict(item) for item in capabilities]}


@router.get(
    "/projects/{project_id}/artifacts/{artifact_id}/signature",
    summary="查询制品签名状态",
    responses=_ERRORS,
)
async def get_artifact_signature(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    artifact_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_ARTIFACT_READ)
    attempt = await _signing(request).require_signed(artifact_id)
    return asdict(attempt)


@router.get(
    "/projects/{project_id}/build-release/dashboard",
    summary="构建与发布看板",
    responses=_ERRORS,
)
async def build_release_dashboard(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_DASHBOARD_READ)
    service = request.app.state.services.get(
        "build_release_dashboard_service", BuildReleaseDashboardService
    )
    return await service.overview(project_id)


@router.get(
    "/projects/{project_id}/build-release/agent-policy",
    summary="构建发布 Agent 策略",
    description="返回 Agent 允许/禁止的构建发布操作与各角色权限矩阵。",
    responses=_ERRORS,
)
async def build_release_agent_policy(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_DASHBOARD_READ)
    return agent_policy()
