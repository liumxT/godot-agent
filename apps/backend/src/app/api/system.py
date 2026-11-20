"""系统信息与运行状态接口（E2-T02 / T08）。

- ``GET /api/v1/system/info``：应用版本、API 版本、协议版本与环境，公开接口；
- ``GET /api/v1/system/status``：需要认证，Action 为 ``system.read``。

两个接口的响应结构由 ``packages/contracts/api/system.schema.json`` 约束。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from app.api.deps import enforce_rate_limit, require_action, require_authenticated
from app.api.version import API_VERSION
from core.security.principal import ACTION_SYSTEM_READ
from infrastructure.database.service import DatabaseService
from shared.contracts import protocol_version

router = APIRouter(tags=["system"])

status_router = APIRouter(
    tags=["system"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)


@router.get(
    "/system/info",
    summary="获取系统与版本信息",
    description="返回应用版本、API 版本、Shared Contracts 协议版本与运行环境。",
)
async def system_info(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "api_version": API_VERSION,
        "protocol_version": protocol_version(),
        "environment": settings.environment.value,
    }


@status_router.get(
    "/system/status",
    summary="获取服务运行状态",
    description="需要认证；返回生命周期状态、启动时间、运行时长与数据库可用性。",
    dependencies=[Depends(require_action(ACTION_SYSTEM_READ))],
    responses={
        401: {"description": "缺少或无效的 Bearer Token"},
        429: {"description": "触发限流（RATE_LIMITED），响应包含 Retry-After"},
    },
)
async def system_status(request: Request) -> dict[str, object]:
    lifecycle = request.app.state.lifecycle
    database = request.app.state.services.try_get("database")
    database_ready = (
        isinstance(database, DatabaseService) and database.is_initialized and await database.ping()
    )
    started_at = lifecycle.manager.started_at
    return {
        "state": lifecycle.state.value,
        "started_at": started_at.isoformat() if started_at is not None else None,
        "uptime_seconds": _uptime_seconds(started_at),
        "database_status": "ready" if database_ready else "unavailable",
    }


def _uptime_seconds(started_at: datetime | None) -> float | None:
    if started_at is None:
        return None
    return round((datetime.now(UTC) - started_at).total_seconds(), 3)
