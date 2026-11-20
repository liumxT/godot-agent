"""Project Access 接口（E2-T07 / T08 / T10）。

- ``POST /projects/access``：admin 或项目 owner 授予访问；
- ``GET /projects/access/current``：查询当前 Session 在该项目的有效访问；
- ``DELETE /projects/access/current``：owner/admin 撤销访问（可指定目标 session_id）。

未知项目没有任何访问记录，因此默认返回 ``PROJECT_ACCESS_DENIED``。
项目注册表与完整资源级授权分别在 E4 与后续阶段引入。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import (
    authorize_project_action,
    enforce_rate_limit,
    require_authenticated,
    require_project_action,
    require_session,
)
from app.schemas.access import (
    PROJECT_ID_PATTERN,
    SESSION_ID_PATTERN,
    ProjectAccessGrantRequest,
)
from core.errors import ProjectAccessDenied
from core.security.principal import (
    ACTION_PROJECT_ACCESS_GRANT,
    ACTION_PROJECT_ACCESS_READ,
    ACTION_PROJECT_ACCESS_REVOKE,
)
from modules.access.service import ProjectAccessService, format_access
from modules.session.service import SessionService

router = APIRouter(
    tags=["projects"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {
        "description": (
            "认证失败（AUTH_REQUIRED / AUTH_INVALID / SESSION_INVALID / "
            "SESSION_EXPIRED / SESSION_REVOKED）"
        )
    },
    403: {"description": "无有效项目访问或无权授予（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED），响应包含 Retry-After"},
}


@router.post(
    "/projects/access",
    status_code=status.HTTP_201_CREATED,
    summary="授予项目访问",
    description=(
        "为指定 Session 授予项目访问。调用者必须是 admin 客户端，"
        "或已在该项目拥有 owner 访问。客户端不能为自己申请访问。"
    ),
    dependencies=[Depends(require_session)],
    responses=_ERRORS,
)
async def grant_project_access(
    payload: ProjectAccessGrantRequest, request: Request
) -> dict[str, str]:
    await authorize_project_action(request, payload.project_id, ACTION_PROJECT_ACCESS_GRANT)

    session_service = request.app.state.services.get("session_service", SessionService)
    target = await session_service.get_active(payload.session_id)
    if target is None:
        raise ProjectAccessDenied("目标 Session 无效或已过期")

    access_service = request.app.state.services.get("project_access_service", ProjectAccessService)
    view = await access_service.grant(
        project_id=payload.project_id,
        session_id=target.session_id,
        client_id=target.client_id,
        access_level=payload.access_level,
        granted_by=request.state.principal.client_id,
        expires_at=payload.expires_at,
    )
    return format_access(view)


@router.get(
    "/projects/access/current",
    summary="查询当前项目访问",
    description="返回当前 Session 在指定项目的有效访问；不存在时返回 PROJECT_ACCESS_DENIED。",
    dependencies=[
        Depends(require_session),
        Depends(require_project_action(ACTION_PROJECT_ACCESS_READ)),
    ],
    responses=_ERRORS,
)
async def get_project_access(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict[str, str]:
    session = await require_session(request)
    access_service = request.app.state.services.get("project_access_service", ProjectAccessService)
    view = await access_service.get_current(
        project_id=project_id,
        session_id=session.session_id,
        client_id=session.client_id,
    )
    return format_access(view)


@router.delete(
    "/projects/access/current",
    summary="撤销项目访问",
    description=(
        "撤销当前 Session 的项目访问；owner/admin 可通过 session_id 撤销其他 Session 的访问。"
        "撤销后立即生效。"
    ),
    dependencies=[
        Depends(require_session),
        Depends(require_project_action(ACTION_PROJECT_ACCESS_REVOKE)),
    ],
    responses=_ERRORS,
)
async def revoke_project_access(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
    session_id: str | None = Query(default=None, pattern=SESSION_ID_PATTERN),
) -> dict[str, str]:
    grantor = await require_session(request)

    if session_id is None or session_id == grantor.session_id:
        target_session_id = grantor.session_id
        target_client_id = grantor.client_id
    else:
        session_service = request.app.state.services.get("session_service", SessionService)
        target = await session_service.get_active(session_id)
        if target is None:
            raise ProjectAccessDenied("目标 Session 无效或已过期")
        target_session_id = target.session_id
        target_client_id = target.client_id

    access_service = request.app.state.services.get("project_access_service", ProjectAccessService)
    view = await access_service.revoke(
        project_id=project_id,
        session_id=target_session_id,
        client_id=target_client_id,
    )
    return format_access(view)
