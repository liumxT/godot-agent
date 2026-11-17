"""应用装配入口。"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from app.api.health import router as health_router
from bootstrap.lifecycle import Lifecycle
from config.settings import Settings, load_settings
from core.errors import install_exception_handlers
from core.logging import configure_logging, get_logger, log_event, request_context


def create_app(settings: Settings | None = None) -> FastAPI:
    """构建 FastAPI 应用。测试可注入自定义 settings。"""

    resolved = settings or load_settings()
    configure_logging(resolved.log_level)
    logger = get_logger("backend.bootstrap")

    lifecycle = Lifecycle(resolved)

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        lifespan=lifecycle.lifespan,
    )
    app.state.settings = resolved
    app.state.lifecycle = lifecycle

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
    app.include_router(health_router)

    log_event(
        logger,
        logging.INFO,
        "application_configured",
        component="bootstrap",
        environment=resolved.environment.value,
    )
    return app
