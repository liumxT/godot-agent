"""客户端注册接口（E2-T06）。

``POST /api/v1/clients`` 需要 ``X-Bootstrap-Token``（见 ``data/bootstrap.token``）。
M8 起也允许 admin Session 注册，M7 只实现 Bootstrap 路径。
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.schemas.client import ClientRegisterRequest
from core.errors import AuthInvalid, AuthRequired
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.client.service import ClientService, format_client

router = APIRouter(tags=["clients"])

_ERRORS = {
    401: {"description": "缺少或无效的 Bootstrap Token（AUTH_REQUIRED / AUTH_INVALID）"},
    409: {"description": "client_id 已存在（CLIENT_EXISTS）"},
    422: {"description": "请求体校验失败（VALIDATION_FAILED）"},
}


@router.post(
    "/clients",
    status_code=status.HTTP_201_CREATED,
    summary="注册本地客户端",
    description=(
        "使用 Bootstrap Token 注册 Godot Editor 或本地工具，返回仅展示一次的 client_secret。"
        "client_secret 只写入操作系统凭证库，数据库不保存明文。"
    ),
    responses=_ERRORS,
)
async def register_client(payload: ClientRegisterRequest, request: Request) -> dict[str, str]:
    token = request.headers.get("X-Bootstrap-Token")
    if not token:
        raise AuthRequired("缺少客户端注册令牌")

    services = request.app.state.services
    bootstrap = services.get("bootstrap_token", BootstrapTokenStore)
    if not bootstrap.verify(token):
        raise AuthInvalid("客户端注册令牌无效")

    service = services.get("client_service", ClientService)
    registration = await service.register(
        client_type=payload.client_type,
        client_name=payload.client_name,
        client_version=payload.client_version,
        godot_version=payload.godot_version,
        platform=payload.platform,
        client_id=payload.client_id,
    )
    return format_client(registration)
