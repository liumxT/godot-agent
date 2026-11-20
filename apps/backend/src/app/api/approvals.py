"""Approval 接口（E4-T20 / T22）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.project_workflow import ApprovalDecisionRequest
from core.security.principal import ACTION_E4_APPROVAL_DECIDE, ACTION_E4_APPROVAL_READ
from modules.approval.service import (
    ApprovalService,
    format_approval,
    format_decision,
)

router = APIRouter(
    tags=["approvals"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    404: {"description": "审批不存在（NOT_FOUND）"},
    409: {
        "description": (
            "审批已过期或哈希不匹配（APPROVAL_EXPIRED / APPROVAL_HASH_MISMATCH / "
            "INVALID_STATE_TRANSITION）"
        )
    },
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


def _approvals(request: Request) -> ApprovalService:
    return request.app.state.services.get("approval_service", ApprovalService)


async def _authorize_approval(request: Request, approval_id: str, action: str) -> str:
    entity = await _approvals(request).get(approval_id)
    await authorize_project_action(request, entity.project_id, action)
    return entity.project_id


@router.get(
    "/approvals",
    summary="列出审批",
    description="按项目列出审批，可按状态过滤。",
    responses=_ERRORS,
)
async def list_approvals(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_APPROVAL_READ)
    page = await _approvals(request).list(
        project_id=project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [format_approval(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/approvals/{approval_id}",
    summary="查询审批",
    description="返回审批状态、目标哈希与过期时间。",
    responses=_ERRORS,
)
async def get_approval(approval_id: str, request: Request) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E4_APPROVAL_READ)
    return format_approval(await _approvals(request).get(approval_id))


@router.get(
    "/approvals/{approval_id}/decisions",
    summary="列出审批决策",
    description="返回审批的全部决策记录。",
    responses=_ERRORS,
)
async def list_approval_decisions(approval_id: str, request: Request) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E4_APPROVAL_READ)
    rows = await _approvals(request).list_decisions(approval_id)
    return {"items": [format_decision(item) for item in rows]}


@router.post(
    "/approvals/{approval_id}/approve",
    summary="批准审批",
    description="PENDING → APPROVED；过期审批返回 APPROVAL_EXPIRED。",
    responses=_ERRORS,
)
async def approve_approval(
    approval_id: str, payload: ApprovalDecisionRequest, request: Request
) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E4_APPROVAL_DECIDE)
    return format_approval(
        await _approvals(request).approve(
            approval_id,
            actor_id=request.state.principal.client_id,
            reason=payload.reason,
        )
    )


@router.post(
    "/approvals/{approval_id}/reject",
    summary="拒绝审批",
    description="PENDING → REJECTED；重复拒绝幂等返回。",
    responses=_ERRORS,
)
async def reject_approval(
    approval_id: str, payload: ApprovalDecisionRequest, request: Request
) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E4_APPROVAL_DECIDE)
    return format_approval(
        await _approvals(request).reject(
            approval_id,
            actor_id=request.state.principal.client_id,
            reason=payload.reason,
        )
    )


@router.post(
    "/approvals/{approval_id}/cancel",
    summary="取消审批",
    description="PENDING → CANCELLED；已决策审批不能取消。",
    responses=_ERRORS,
)
async def cancel_approval(
    approval_id: str, payload: ApprovalDecisionRequest, request: Request
) -> dict:
    await _authorize_approval(request, approval_id, ACTION_E4_APPROVAL_DECIDE)
    return format_approval(
        await _approvals(request).cancel(
            approval_id,
            actor_id=request.state.principal.client_id,
            reason=payload.reason,
        )
    )
