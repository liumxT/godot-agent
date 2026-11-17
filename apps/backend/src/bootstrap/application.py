"""应用装配入口。"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router
from bootstrap.lifecycle import Lifecycle
from config.settings import Settings, load_settings
from core.errors import install_exception_handlers
from core.logging import configure_logging, get_logger


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

    install_exception_handlers(app)
    app.include_router(health_router)

    logger.info(
        "application_configured",
        extra={"component": "bootstrap", "environment": resolved.environment.value},
    )
    return app
