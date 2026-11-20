"""Session 接口（E2-T05 / T08 / T10）。

- ``POST /sessions``：用 Access Token 创建 Session，返回 ``gds_`` Session Token；
- ``GET /sessions/current``：查询当前 Session；
- ``DELETE /sessions/current``：撤销当前 Session；
- ``POST /sessions/current/renew``：延长 Session（不超过 ``session_max_ttl``）。

路由级统一挂载认证与限流；每个接口声明最小 Action。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    bearer_token,
    enforce_rate_limit,
    require_access_token,
    require_action,
    require_authenticated,
    require_session,
)
from core.security.principal import (
    ACTION_SESSION_CREATE,
    ACTION_SESSION_READ,
    ACTION_SESSION_REVOKE,
)
from modules.session.service import SessionService, format_issued, format_session

router = APIRouter(
    tags=["sessions"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {
        "description": (
            "认证失败（AUTH_REQUIRED / AUTH_INVALID / TOKEN_INVALID / TOKEN_EXPIRED / "
            "TOKEN_REVOKED / SESSION_INVALID / SESSION_EXPIRED / SESSION_REVOKED）"
        )
    },
    429: {"description": "触发限流（RATE_LIMITED），响应包含 Retry-After"},
}


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    summary="创建 Session",
    description=(
        "使用有效 Access Token 创建 Session，绑定到该 Token 的 client_id。"
        "Session Token 只返回一次，数据库仅保存 SHA-256 摘要。"
    ),
    dependencies=[
        Depends(require_access_token),
        Depends(require_action(ACTION_SESSION_CREATE)),
    ],
    responses=_ERRORS,
)
async def create_session(request: Request) -> dict[str, object]:
    info = await require_access_token(request)
    service = request.app.state.services.get("session_service", SessionService)
    return format_issued(await service.create(info.client_id))


@router.get(
    "/sessions/current",
    summary="查询当前 Session",
    description="返回当前 Session Token 绑定的会话信息，不包含 Token 哈希。",
    dependencies=[
        Depends(require_session),
        Depends(require_action(ACTION_SESSION_READ)),
    ],
    responses=_ERRORS,
)
async def get_current_session(request: Request) -> dict[str, str | None]:
    return format_session(await require_session(request))


@router.delete(
    "/sessions/current",
    summary="撤销当前 Session",
    description="将 Session 置为 REVOKED；后续使用该 Session Token 的请求返回 SESSION_REVOKED。",
    dependencies=[
        Depends(require_session),
        Depends(require_action(ACTION_SESSION_REVOKE)),
    ],
    responses=_ERRORS,
)
async def revoke_current_session(request: Request) -> dict[str, str | None]:
    service = request.app.state.services.get("session_service", SessionService)
    return format_session(await service.revoke(bearer_token(request)))


@router.post(
    "/sessions/current/renew",
    summary="续期当前 Session",
    description=(
        "延长 Session 的有效期，总时长不超过 session_max_ttl_seconds。Heartbeat/Lease 在 E3 实现。"
    ),
    dependencies=[
        Depends(require_session),
        Depends(require_action(ACTION_SESSION_CREATE)),
    ],
    responses=_ERRORS,
)
async def renew_current_session(request: Request) -> dict[str, str | None]:
    service = request.app.state.services.get("session_service", SessionService)
    return format_session(await service.renew(bearer_token(request)))
