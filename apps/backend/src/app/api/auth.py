"""挑战-响应认证与 Token 接口（E2-T03 / T04 / T09）。

- ``POST /auth/challenge``：获取一次性挑战（60s）；
- ``POST /auth/verify``：提交 proof，换取短期 Access Token；
- ``POST /auth/refresh``：轮换 Access Token，旧 Token 立即失效（需认证）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import (
    bearer_token,
    enforce_rate_limit,
    require_access_token,
    require_authenticated,
)
from app.schemas.auth import ChallengeRequest, VerifyRequest
from core.security.tokens import isoformat
from modules.client.service import AuthService

router = APIRouter(tags=["auth"])

protected_router = APIRouter(
    tags=["auth"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {
        "description": (
            "认证失败（AUTH_REQUIRED / AUTH_INVALID / AUTH_CHALLENGE_INVALID / "
            "TOKEN_INVALID / TOKEN_EXPIRED / TOKEN_REVOKED）"
        )
    },
    429: {"description": "认证尝试过于频繁（RATE_LIMITED），响应头含 Retry-After"},
    422: {"description": "请求体校验失败（VALIDATION_FAILED）"},
}


@router.post(
    "/auth/challenge",
    summary="获取认证挑战",
    description="为已注册客户端签发一次性挑战，有效期由 auth_challenge_ttl_seconds 控制。",
    responses=_ERRORS,
)
async def create_challenge(payload: ChallengeRequest, request: Request) -> dict[str, str]:
    service = request.app.state.services.get("auth_service", AuthService)
    issue = await service.create_challenge(payload.client_id)
    return {
        "challenge_id": issue.challenge_id,
        "challenge": issue.challenge,
        "expires_at": isoformat(issue.expires_at),
    }


@router.post(
    "/auth/verify",
    summary="校验挑战并签发 Access Token",
    description=(
        "proof = base64url(HMAC-SHA256(client_secret, challenge_id + '.' + challenge))。"
        "挑战只能使用一次，成功与失败都会记录结构化日志。"
    ),
    responses=_ERRORS,
)
async def verify_challenge(payload: VerifyRequest, request: Request) -> dict[str, str]:
    service = request.app.state.services.get("auth_service", AuthService)
    issued = await service.verify_challenge(
        challenge_id=payload.challenge_id,
        client_id=payload.client_id,
        proof=payload.proof,
    )
    return {
        "access_token": issued.access_token,
        "token_type": issued.token_type,
        "expires_at": isoformat(issued.expires_at),
    }


@protected_router.post(
    "/auth/refresh",
    summary="轮换 Access Token",
    description="使用有效的 Access Token 换取新 Token，旧 Token 立即撤销。",
    dependencies=[Depends(require_access_token)],
    responses=_ERRORS,
)
async def refresh_token(request: Request) -> dict[str, str]:
    issued = await request.app.state.services.get("auth_service", AuthService).refresh(
        bearer_token(request)
    )
    return {
        "access_token": issued.access_token,
        "token_type": issued.token_type,
        "expires_at": isoformat(issued.expires_at),
    }
