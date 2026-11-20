"""FastAPI lifespan 适配器（E1-T01）。

信号处理由 uvicorn 负责，本模块只把启动/关闭委托给 ``LifecycleManager``，
不重复注册信号；重复关闭由 Manager 保证幂等。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from bootstrap.service_registry import ServiceRegistry
from bootstrap.shutdown import register_shutdown_steps
from bootstrap.startup import register_startup_steps
from config.settings import Settings
from core.lifecycle.manager import LifecycleManager
from core.lifecycle.states import LifecycleState
from core.logging import get_logger, log_event

DEFAULT_SHUTDOWN_TIMEOUT = 10.0


class Lifecycle:
    def __init__(
        self,
        settings: Settings,
        *,
        services: ServiceRegistry | None = None,
        shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        self._settings = settings
        self._logger = get_logger("backend.bootstrap")
        self.services = services if services is not None else ServiceRegistry()
        self.manager = LifecycleManager(shutdown_timeout=shutdown_timeout)
        register_startup_steps(self.manager, settings=settings, services=self.services)
        register_shutdown_steps(self.manager, services=self.services)

    @property
    def state(self) -> LifecycleState:
        return self.manager.state

    @asynccontextmanager
    async def lifespan(self, _: FastAPI) -> AsyncIterator[None]:
        log_event(
            self._logger,
            logging.INFO,
            "application_start",
            component="bootstrap",
            environment=self._settings.environment.value,
        )
        await self.manager.startup()
        try:
            yield
        finally:
            await self.manager.shutdown()
            log_event(self._logger, logging.INFO, "application_stop", component="bootstrap")
