"""ChangeSet 接口（E4-T22）。

ChangeSet 只描述变更意图；应用动作必须在审批哈希匹配后由调用方执行。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.project_workflow import (
    ChangeSetApplyRequest,
    ChangeSetApprovalRequest,
    ChangeSetCreateRequest,
    ChangeSetFinishRequest,
    ManifestReplaceRequest,
)
from core.security.principal import (
    ACTION_E4_CHANGESET_APPROVE,
    ACTION_E4_CHANGESET_MANAGE,
    ACTION_E4_CHANGESET_READ,
)
from modules.changeset.service import ChangeSetService, format_changeset

router = APIRouter(
    tags=["changesets"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    404: {"description": "资源不存在（NOT_FOUND）"},
    409: {
        "description": (
            "状态冲突或审批失效（INVALID_STATE_TRANSITION / APPROVAL_EXPIRED / "
            "APPROVAL_HASH_MISMATCH）"
        )
    },
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


def _changesets(request: Request) -> ChangeSetService:
    return request.app.state.services.get("changeset_service", ChangeSetService)


async def _authorize_changeset(request: Request, changeset_id: str, action: str) -> str:
    entity = await _changesets(request).get(changeset_id)
    await authorize_project_action(request, entity.project_id, action)
    return entity.project_id


@router.post(
    "/changesets",
    status_code=status.HTTP_201_CREATED,
    summary="创建 ChangeSet",
    description="规范化清单并计算内容哈希；初始状态为 DRAFT。",
    responses=_ERRORS,
)
async def create_changeset(payload: ChangeSetCreateRequest, request: Request) -> dict:
    await authorize_project_action(request, payload.project_id, ACTION_E4_CHANGESET_MANAGE)
    view = await _changesets(request).create(
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        task_id=payload.task_id,
        attempt_id=payload.attempt_id,
        base_revision=payload.base_revision,
        items=[item.model_dump() for item in payload.items],
        created_by=request.state.principal.client_id,
    )
    return format_changeset(view)


@router.get(
    "/changesets",
    summary="列出 ChangeSet",
    description="按项目列出 ChangeSet，可按状态过滤。",
    responses=_ERRORS,
)
async def list_changesets(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_CHANGESET_READ)
    return await _changesets(request).list(
        project_id, status=status_filter, limit=limit, offset=offset
    )


@router.get(
    "/changesets/{changeset_id}",
    summary="查询 ChangeSet",
    description="返回 ChangeSet、清单、最近校验结果与版本历史。",
    responses=_ERRORS,
)
async def get_changeset(changeset_id: str, request: Request) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_READ)
    service = _changesets(request)
    entity = await service.get(changeset_id)
    detail = await service.detail(changeset_id)
    return {**format_changeset(entity), **detail}


@router.get(
    "/changesets/{changeset_id}/hash",
    summary="校验 ChangeSet 哈希",
    description="重新计算清单哈希，判断内容是否与记录一致。",
    responses=_ERRORS,
)
async def verify_changeset_hash(changeset_id: str, request: Request) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_READ)
    return await _changesets(request).verify_hash(changeset_id)


@router.patch(
    "/changesets/{changeset_id}/manifest",
    summary="替换 ChangeSet 清单",
    description="替换清单后回到 DRAFT 并重新计算哈希；旧审批自动失效。",
    responses=_ERRORS,
)
async def replace_changeset_manifest(
    changeset_id: str, payload: ManifestReplaceRequest, request: Request
) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_MANAGE)
    view = await _changesets(request).replace_manifest(
        changeset_id, [item.model_dump() for item in payload.items]
    )
    return format_changeset(view)


@router.post(
    "/changesets/{changeset_id}/validate",
    summary="校验 ChangeSet",
    description="检查操作类型与内容哈希是否齐全；通过后进入 READY_FOR_APPROVAL。",
    responses=_ERRORS,
)
async def validate_changeset(changeset_id: str, request: Request) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_MANAGE)
    return await _changesets(request).validate(changeset_id)


@router.post(
    "/changesets/{changeset_id}/submit",
    status_code=status.HTTP_201_CREATED,
    summary="提交 ChangeSet 审批",
    description="为 READY_FOR_APPROVAL 的 ChangeSet 创建绑定内容哈希的审批。",
    responses=_ERRORS,
)
async def submit_changeset(changeset_id: str, request: Request) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_MANAGE)
    from modules.approval.service import format_approval

    view = await _changesets(request).submit_for_approval(
        changeset_id, requested_by=request.state.principal.client_id
    )
    return format_approval(view)


@router.post(
    "/changesets/{changeset_id}/approve",
    summary="批准 ChangeSet",
    description="审批必须绑定当前内容哈希；内容变化后旧审批不能继续生效。",
    responses=_ERRORS,
)
async def approve_changeset(
    changeset_id: str, payload: ChangeSetApprovalRequest, request: Request
) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_APPROVE)
    view = await _changesets(request).approve(
        changeset_id,
        payload.approval_id,
        actor_id=request.state.principal.client_id,
        reason=payload.reason,
    )
    return format_changeset(view)


@router.post(
    "/changesets/{changeset_id}/reject",
    summary="拒绝 ChangeSet",
    description="拒绝后 ChangeSet 进入 REJECTED，可修改清单后重新提交。",
    responses=_ERRORS,
)
async def reject_changeset(
    changeset_id: str, payload: ChangeSetApprovalRequest, request: Request
) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_APPROVE)
    view = await _changesets(request).reject(
        changeset_id,
        payload.approval_id,
        actor_id=request.state.principal.client_id,
        reason=payload.reason,
    )
    return format_changeset(view)


@router.post(
    "/changesets/{changeset_id}/apply",
    summary="开始应用 ChangeSet",
    description="仅 APPROVED 且审批哈希匹配时进入 APPLYING；实际写文件由后续阶段执行。",
    responses=_ERRORS,
)
async def apply_changeset(
    changeset_id: str, payload: ChangeSetApplyRequest, request: Request
) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_MANAGE)
    view = await _changesets(request).start_apply(
        changeset_id, payload.approval_id, actor_id=request.state.principal.client_id
    )
    return format_changeset(view)


@router.post(
    "/changesets/{changeset_id}/finish",
    summary="结束 ChangeSet 应用",
    description="以 APPLIED / FAILED / UNKNOWN 结束应用。",
    responses=_ERRORS,
)
async def finish_changeset(
    changeset_id: str, payload: ChangeSetFinishRequest, request: Request
) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_MANAGE)
    view = await _changesets(request).finish_apply(changeset_id, status=payload.status)
    return format_changeset(view)


@router.post(
    "/changesets/{changeset_id}/cancel",
    summary="取消 ChangeSet",
    description="取消未结束的 ChangeSet。",
    responses=_ERRORS,
)
async def cancel_changeset(changeset_id: str, request: Request) -> dict:
    await _authorize_changeset(request, changeset_id, ACTION_E4_CHANGESET_MANAGE)
    view = await _changesets(request).cancel(
        changeset_id, actor_id=request.state.principal.client_id
    )
    return format_changeset(view)
