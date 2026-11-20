"""生命周期管理器（E1-T01）。

负责有序启动、失败回滚、优雅关闭与关闭超时：

- 启动步骤按注册顺序执行，任一步失败按已执行步骤逆序回滚；
- 关闭步骤按注册顺序执行，单个步骤失败记录日志后继续；
- 重复关闭幂等；关闭超时记录 ``SHUTDOWN_TIMEOUT`` 并强制进入 ``STOPPED``；
- 信号处理由 uvicorn 负责，本模块不注册信号。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from core.errors import AppError, LifecycleStateError, StartupError
from core.lifecycle.states import LifecycleState, can_transition
from core.logging import get_logger, log_event

StepAction = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True)
class LifecycleStep:
    name: str
    action: StepAction
    rollback: StepAction | None = None
    timeout: float | None = None


class LifecycleManager:
    def __init__(
        self,
        *,
        shutdown_timeout: float = 10.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._state = LifecycleState.CREATED
        self._shutdown_timeout = shutdown_timeout
        self._logger = logger or get_logger("backend.lifecycle")
        self._startup_steps: list[LifecycleStep] = []
        self._shutdown_steps: list[LifecycleStep] = []
        self._started_at: datetime | None = None

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    def register_startup_step(
        self,
        name: str,
        action: StepAction,
        *,
        rollback: StepAction | None = None,
        timeout: float | None = None,
    ) -> None:
        self._ensure_registerable()
        self._startup_steps.append(LifecycleStep(name, action, rollback, timeout))

    def register_shutdown_step(
        self,
        name: str,
        action: StepAction,
        *,
        timeout: float | None = None,
    ) -> None:
        self._ensure_registerable()
        self._shutdown_steps.append(LifecycleStep(name, action, timeout=timeout))

    async def startup(self) -> None:
        """按注册顺序启动；失败时回滚并抛出 StartupError。"""

        if self._state is not LifecycleState.CREATED:
            raise LifecycleStateError(
                "应用已启动或已关闭，不能重复启动",
                details={"state": self._state.value},
            )

        self._transition(LifecycleState.INITIALIZING)
        log_event(self._logger, logging.INFO, "lifecycle_startup_begin", component="lifecycle")

        executed: list[LifecycleStep] = []
        current: LifecycleStep | None = None
        try:
            for step in self._startup_steps:
                current = step
                await self._run(step)
                executed.append(step)
            self._transition(LifecycleState.STARTING)
            self._transition(LifecycleState.RUNNING)
        except Exception as exc:
            await self._rollback(executed)
            self._force_state(LifecycleState.FAILED)
            log_event(
                self._logger,
                logging.ERROR,
                "lifecycle_startup_failed",
                f"启动失败，步骤 {current.name if current else 'unknown'}",
                component="lifecycle",
                error_code=exc.code if isinstance(exc, AppError) else "STARTUP_ERROR",
            )
            if isinstance(exc, AppError):
                # 保留领域错误码（如 MIGRATION_FAILED / CONFIG_ERROR），
                # 仅包装未分类异常为 STARTUP_ERROR
                raise
            raise StartupError(
                "应用启动失败",
                details={
                    "step": current.name if current else "",
                    "reason": str(exc),
                },
            ) from exc

        self._started_at = datetime.now(UTC)
        log_event(self._logger, logging.INFO, "lifecycle_running", component="lifecycle")

    async def shutdown(self) -> None:
        """优雅关闭；重复调用幂等，超时强制进入 STOPPED。"""

        if self._state is LifecycleState.STOPPED:
            return
        if self._state is LifecycleState.CREATED:
            self._transition(LifecycleState.STOPPED)
            return
        if self._state is LifecycleState.FAILED:
            self._force_state(LifecycleState.STOPPED)
            return

        self._transition(LifecycleState.STOPPING)
        log_event(self._logger, logging.INFO, "lifecycle_shutdown_begin", component="lifecycle")

        try:
            async with asyncio.timeout(self._shutdown_timeout):
                for step in self._shutdown_steps:
                    try:
                        await self._run(step)
                    except Exception as exc:  # noqa: BLE001 - 单个关闭步骤失败不能阻断其余清理
                        log_event(
                            self._logger,
                            logging.ERROR,
                            "lifecycle_shutdown_step_failed",
                            f"关闭步骤失败: {step.name}",
                            component="lifecycle",
                            error_code="INFRASTRUCTURE_ERROR",
                        )
                        self._logger.debug("shutdown step %s failed: %s", step.name, exc)
        except TimeoutError:
            log_event(
                self._logger,
                logging.ERROR,
                "shutdown_timeout",
                f"关闭超时（>{self._shutdown_timeout}s），强制停止",
                component="lifecycle",
                error_code="SHUTDOWN_TIMEOUT",
            )
        finally:
            self._force_state(LifecycleState.STOPPED)
            log_event(self._logger, logging.INFO, "lifecycle_stopped", component="lifecycle")

    async def _run(self, step: LifecycleStep) -> None:
        if step.timeout is None:
            await self._invoke(step.action)
            return
        async with asyncio.timeout(step.timeout):
            await self._invoke(step.action)

    async def _rollback(self, executed: list[LifecycleStep]) -> None:
        for step in reversed(executed):
            if step.rollback is None:
                continue
            try:
                await self._run(LifecycleStep(step.name, step.rollback, timeout=step.timeout))
            except Exception as exc:  # noqa: BLE001 - 回滚失败不得覆盖原始启动错误
                log_event(
                    self._logger,
                    logging.ERROR,
                    "lifecycle_rollback_failed",
                    f"回滚步骤失败: {step.name}",
                    component="lifecycle",
                )
                self._logger.debug("rollback step %s failed: %s", step.name, exc)

    @staticmethod
    async def _invoke(action: StepAction) -> None:
        result = action()
        if inspect.isawaitable(result):
            await result

    def _ensure_registerable(self) -> None:
        if self._state is not LifecycleState.CREATED:
            raise LifecycleStateError(
                "启动后不允许再注册生命周期步骤",
                details={"state": self._state.value},
            )

    def _transition(self, target: LifecycleState) -> None:
        if not can_transition(self._state, target):
            raise LifecycleStateError(
                "生命周期状态迁移非法",
                details={"from": self._state.value, "to": target.value},
            )
        self._state = target

    def _force_state(self, target: LifecycleState) -> None:
        self._state = target
