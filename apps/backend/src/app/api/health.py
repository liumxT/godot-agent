"""健康检查接口（E1-T12）。

- ``GET /health``：保留 E0 字段并增加依赖检查，始终 200，``status`` 反映真实状态；
- ``GET /health/live``：进程存活探测，不访问依赖；
- ``GET /health/ready``：可接受工作才返回 200，否则 503。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.health import collect_health, readiness

router = APIRouter(tags=["system"])


@router.get("/health/live", summary="存活探测", description="只检查进程是否存活，不访问依赖。")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get(
    "/health/ready",
    summary="就绪探测",
    description="应用、数据库与迁移均就绪时返回 200，否则返回 503。",
)
async def ready(request: Request) -> JSONResponse:
    report = await collect_health(request.app.state.lifecycle, request.app.state.services)
    ok, reason = readiness(report)
    payload = report.to_dict() | {"ready": ok}
    if reason:
        payload["reason"] = reason
    return JSONResponse(status_code=200 if ok else 503, content=payload)


@router.get(
    "/health",
    summary="完整健康视图",
    description="返回应用与依赖的聚合健康状态，始终 200，status 反映真实状态。",
)
async def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    report = await collect_health(request.app.state.lifecycle, request.app.state.services)
    return {
        "status": report.status.value,
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment.value,
        "checks": [check.to_dict() for check in report.checks],
    }
