"""应用装配入口。"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from app.api.diagnostics import router as diagnostics_router
from app.api.health import router as health_router
from app.api.openapi import install_openapi_security
from app.api.router import build_api_router
from app.middleware.size_limit import BodySizeLimitMiddleware
from app.middleware.timeout import RequestTimeoutMiddleware
from app.ws.editor import router as editor_ws_router
from app.ws.runtime import router as runtime_ws_router
from bootstrap.lifecycle import Lifecycle
from bootstrap.service_registry import ServiceRegistry
from config.layers import load_layered_settings
from config.settings import Settings
from core.errors import install_exception_handlers
from core.logging import configure_logging, get_logger, log_event, request_context


def create_app(settings: Settings | None = None) -> FastAPI:
    """构建 FastAPI 应用。测试可注入自定义 settings。"""

    resolved = settings or load_layered_settings()
    configure_logging(resolved.log_level.value)
    logger = get_logger("backend.bootstrap")

    services = ServiceRegistry()
    lifecycle = Lifecycle(resolved, services=services)

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        lifespan=lifecycle.lifespan,
    )
    app.state.settings = resolved
    app.state.lifecycle = lifecycle
    app.state.services = services

    @app.middleware("http")
    async def _request_context_middleware(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or f"req-{uuid4().hex}"
        correlation_id = request.headers.get("X-Correlation-ID") or request_id
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        with request_context(request_id=request_id, correlation_id=correlation_id):
            response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    install_exception_handlers(app)
    # 后添加者位于外层：大小限制 → 超时 → 请求上下文 → 路由。
    app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=resolved.request_timeout_seconds)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=resolved.request_max_body_bytes)
    app.include_router(health_router)
    app.include_router(diagnostics_router)
    app.include_router(build_api_router())
    app.include_router(editor_ws_router)
    app.include_router(runtime_ws_router)
    install_openapi_security(app)

    log_event(
        logger,
        logging.INFO,
        "application_configured",
        component="bootstrap",
        environment=resolved.environment.value,
    )
    return app
