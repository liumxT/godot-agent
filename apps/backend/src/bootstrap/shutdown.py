"""关闭步骤注册（E1-T01 / T03 / T10）。

关闭顺序由注册顺序决定：停止事件派发 → 关闭数据库 → 刷新日志。
"""

from __future__ import annotations

from bootstrap.service_registry import ServiceRegistry
from core.lifecycle.manager import LifecycleManager
from core.logging import flush_logging
from infrastructure.database.service import DatabaseService
from infrastructure.events.dispatcher import EventDispatcher
from modules.client.service import AuthCleanupTask

SHUTDOWN_STEP_TIMEOUT = 5.0


def register_shutdown_steps(manager: LifecycleManager, *, services: ServiceRegistry) -> None:
    async def _stop_auth() -> None:
        cleanup = services.try_get("auth_cleanup")
        if isinstance(cleanup, AuthCleanupTask):
            await cleanup.stop()

    async def _stop_events() -> None:
        dispatcher = services.try_get("event_dispatcher")
        if isinstance(dispatcher, EventDispatcher):
            await dispatcher.stop()

    async def _dispose_database() -> None:
        service = services.try_get("database")
        if isinstance(service, DatabaseService):
            await service.dispose()

    manager.register_shutdown_step(
        "auth",
        _stop_auth,
        timeout=SHUTDOWN_STEP_TIMEOUT,
    )
    manager.register_shutdown_step(
        "events",
        _stop_events,
        timeout=SHUTDOWN_STEP_TIMEOUT,
    )
    manager.register_shutdown_step(
        "database",
        _dispose_database,
        timeout=SHUTDOWN_STEP_TIMEOUT,
    )
    manager.register_shutdown_step("flush_logging", flush_logging, timeout=SHUTDOWN_STEP_TIMEOUT)
