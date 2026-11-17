"""统一启动与关闭入口。

E0 阶段不注册业务资源；后续阶段在此装配数据库、事件、Worker 等，
保持入口本身只做编排，不堆积逻辑。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import Settings
from core.errors import StartupError
from core.logging import get_logger

StartupHook = Callable[[], Awaitable[None] | None]
ShutdownHook = Callable[[], Awaitable[None] | None]


class Lifecycle:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = get_logger("backend.lifecycle")
        self._startup_hooks: list[StartupHook] = []
        self._shutdown_hooks: list[ShutdownHook] = []

    def on_startup(self, hook: StartupHook) -> None:
        self._startup_hooks.append(hook)

    def on_shutdown(self, hook: ShutdownHook) -> None:
        self._shutdown_hooks.append(hook)

    @asynccontextmanager
    async def lifespan(self, _: FastAPI) -> AsyncIterator[None]:
        self._logger.info(
            "application_start",
            extra={"component": "bootstrap", "environment": self._settings.environment.value},
        )
        try:
            await self._run(self._startup_hooks)
            yield
        except Exception as exc:  # noqa: BLE001 - 启动失败必须显式转换
            raise StartupError("应用启动失败", details={"reason": str(exc)}) from exc
        finally:
            await self._run(self._shutdown_hooks)
            self._logger.info("application_stop", extra={"component": "bootstrap"})

    async def _run(self, hooks: list[StartupHook] | list[ShutdownHook]) -> None:
        for hook in hooks:
            result = hook()
            if result is not None:
                await result
