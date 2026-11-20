"""API 依赖：认证、Session、项目范围与统一授权（E2-T08 / T09 / T10）。

受保护路由在 Router 级挂载 ``require_authenticated`` 与 ``enforce_rate_limit``；
Action 依赖按接口声明最小能力。客户端提交的 client_id / session_id / project_id
一律不作为授权依据。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace

from fastapi import Request

from core.errors import (
    AuthInvalid,
    AuthRequired,
    PermissionDenied,
    RateLimited,
    SessionInvalid,
    TokenInvalid,
)
from core.security.policy import evaluate
from core.security.principal import Principal, Resource
from core.security.tokens import SESSION_TOKEN_PREFIX
from infrastructure.security.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter
from modules.access.service import ProjectAccessService
from modules.audit.models import AUDIT_AUTHORIZATION_DENIED
from modules.audit.service import AuditService
from modules.client.service import AccessTokenInfo, AuthService, ClientService, ClientView
from modules.session.service import SessionService, SessionView

DEFAULT_RATE_LIMIT_PER_MINUTE = 120
DEFAULT_MAX_CONCURRENCY = 20


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header:
        raise AuthRequired("缺少 Bearer Token")
    scheme, _, value = header.partition(" ")
    token = value.strip()
    if scheme.lower() != "bearer" or not token:
        raise AuthInvalid("Authorization 头格式非法")
    return token


def _services(request: Request):
    return request.app.state.services


def _client_service(request: Request) -> ClientService:
    return _services(request).get("client_service", ClientService)


async def _resolve_client(request: Request, client_id: str) -> ClientView:
    client = await _client_service(request).get(client_id)
    if client is None:
        raise AuthInvalid("客户端无效")
    return client


async def require_authenticated(request: Request) -> None:
    """认证依赖：接受 Access Token（gda_）或 Session Token（gds_）。"""

    token = bearer_token(request)
    services = _services(request)
    if token.startswith(SESSION_TOKEN_PREFIX):
        session = await services.get("session_service", SessionService).authenticate(token)
        client = await _resolve_client(request, session.client_id)
        request.state.session = session
        request.state.access_token = None
        request.state.principal = Principal(
            client_id=session.client_id,
            client_type=client.client_type,
            session_id=session.session_id,
            role="admin" if client.client_type == "admin" else "client",
        )
        return

    info: AccessTokenInfo = await services.get("auth_service", AuthService).verify_access_token(
        token
    )
    client = await _resolve_client(request, info.client_id)
    request.state.session = None
    request.state.access_token = info
    request.state.principal = Principal(
        client_id=info.client_id,
        client_type=client.client_type,
        session_id=None,
        role="admin" if client.client_type == "admin" else "client",
    )


def _principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise AuthRequired("需要认证")
    return principal


async def require_session(request: Request) -> SessionView:
    session = getattr(request.state, "session", None)
    if session is None:
        raise SessionInvalid("当前接口要求 Session Token")
    return session


async def require_access_token(request: Request) -> AccessTokenInfo:
    info = getattr(request.state, "access_token", None)
    if info is None:
        raise TokenInvalid("当前接口要求 Access Token")
    return info


async def _raise_denied(request: Request, decision, action: str, resource: str) -> None:
    principal = getattr(request.state, "principal", None)
    audit = _services(request).try_get("audit_service")
    if isinstance(audit, AuditService) and principal is not None:
        await audit.record(
            AUDIT_AUTHORIZATION_DENIED,
            actor_id=principal.client_id,
            client_id=principal.client_id,
            session_id=principal.session_id,
            resource=resource,
            decision="DENY",
            reason=decision.reason,
            details={
                "action": action,
                "role": principal.role,
                "policy_id": decision.policy_id,
            },
        )
    raise PermissionDenied(
        "权限不足",
        details={"action": action, "reason": decision.reason},
    )


def require_action(action: str):
    """按 Action 做 Capability + RBAC 检查（项目类动作需配合 require_project_action）。"""

    async def _dependency(request: Request) -> None:
        principal = _principal(request)
        project_id = request.query_params.get("project_id")
        resource = Resource(kind="project", project_id=project_id) if project_id else None
        decision = evaluate(principal, action, resource)
        if not decision.allowed:
            scope = f"project:{project_id}" if project_id else "api"
            await _raise_denied(request, decision, action, scope)

    return _dependency


async def authorize_project_action(request: Request, project_id: str, action: str) -> None:
    """加载服务端项目访问记录，再按 ABAC + RBAC 授权。"""

    principal = _principal(request)
    resource = f"project:{project_id}"
    if principal.role == "admin":
        decision = evaluate(principal, action, Resource(kind="project", project_id=project_id))
        if not decision.allowed:
            await _raise_denied(request, decision, action, resource)
        return

    session = await require_session(request)
    access = (
        await _services(request)
        .get("project_access_service", ProjectAccessService)
        .get_current(
            project_id=project_id,
            session_id=session.session_id,
            client_id=session.client_id,
        )
    )
    scoped = replace(principal, role=access.access_level, project_id=project_id)
    request.state.principal = scoped
    request.state.project_access = access
    decision = evaluate(scoped, action, Resource(kind="project", project_id=project_id))
    if not decision.allowed:
        await _raise_denied(request, decision, action, resource)


def require_project_action(action: str):
    """从查询参数读取 project_id 并执行项目级授权。"""

    async def _dependency(request: Request) -> None:
        project_id = request.query_params.get("project_id")
        if not project_id:
            # 交给接口参数校验返回 422，避免在依赖中伪造请求范围。
            return
        await authorize_project_action(request, project_id, action)

    return _dependency


def endpoint_group(request: Request) -> str:
    parts = [part for part in request.url.path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "api":
        return parts[2]
    return parts[0] if parts else "root"


async def enforce_rate_limit(request: Request) -> AsyncIterator[None]:
    """按 Session/Client 与接口组做频率与并发限流（E2-T10）。"""

    services = _services(request)
    limiter = services.get("rate_limiter", SlidingWindowRateLimiter)
    concurrency = services.get("concurrency_limiter", ConcurrencyLimiter)
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        identity = principal.session_id or principal.client_id
    elif request.client is not None:
        identity = request.client.host
    else:
        identity = "unknown"
    key = f"{endpoint_group(request)}:{identity}"

    decision = limiter.check(key)
    if not decision.allowed:
        raise RateLimited(
            "请求过于频繁",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    if not concurrency.try_acquire():
        raise RateLimited("并发请求过多", headers={"Retry-After": "1"})

    limiter.record(key)
    try:
        yield
    finally:
        concurrency.release()
