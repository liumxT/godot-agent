"""生命周期管理器测试（E1-T01-UT-001…005）。"""

from __future__ import annotations

import asyncio
import logging

import pytest

from core.errors import LifecycleStateError, MigrationError, StartupError
from core.lifecycle import LifecycleManager, LifecycleState
from core.logging import capture_logs


async def test_startup_runs_steps_in_order() -> None:
    order: list[str] = []
    manager = LifecycleManager()
    manager.register_startup_step("first", lambda: order.append("first"))

    async def second() -> None:
        order.append("second")

    manager.register_startup_step("second", second)

    await manager.startup()

    assert order == ["first", "second"]
    assert manager.state is LifecycleState.RUNNING
    assert manager.started_at is not None


async def test_shutdown_runs_steps_in_registration_order() -> None:
    order: list[str] = []
    manager = LifecycleManager()
    manager.register_startup_step("start", lambda: order.append("start"))
    manager.register_shutdown_step("stop-a", lambda: order.append("stop-a"))
    manager.register_shutdown_step("stop-b", lambda: order.append("stop-b"))

    await manager.startup()
    await manager.shutdown()

    assert order == ["start", "stop-a", "stop-b"]
    assert manager.state is LifecycleState.STOPPED


async def test_repeated_shutdown_is_idempotent() -> None:
    calls: list[int] = []
    manager = LifecycleManager()
    manager.register_shutdown_step("stop", lambda: calls.append(1))

    await manager.startup()
    await manager.shutdown()
    await manager.shutdown()

    assert calls == [1]
    assert manager.state is LifecycleState.STOPPED


async def test_startup_failure_rolls_back_executed_steps() -> None:
    events: list[str] = []
    manager = LifecycleManager()
    manager.register_startup_step(
        "config",
        lambda: events.append("config"),
        rollback=lambda: events.append("rollback-config"),
    )

    def broken() -> None:
        events.append("database")
        raise RuntimeError("数据库初始化失败")

    manager.register_startup_step(
        "database", broken, rollback=lambda: events.append("rollback-database")
    )
    manager.register_startup_step("health", lambda: events.append("health"))

    with pytest.raises(StartupError) as exc_info:
        await manager.startup()

    assert events == ["config", "database", "rollback-config"]
    assert exc_info.value.details["step"] == "database"
    assert manager.state is LifecycleState.FAILED

    await manager.shutdown()
    assert manager.state is LifecycleState.STOPPED


async def test_startup_preserves_domain_error_code() -> None:
    manager = LifecycleManager()

    def broken() -> None:
        raise MigrationError("迁移失败")

    manager.register_startup_step("migration", broken)

    with pytest.raises(MigrationError) as exc_info:
        await manager.startup()

    assert exc_info.value.code == "MIGRATION_FAILED"
    assert manager.state is LifecycleState.FAILED


async def test_shutdown_timeout_forces_stopped() -> None:
    async def slow() -> None:
        await asyncio.sleep(5)

    manager = LifecycleManager(shutdown_timeout=0.05)
    manager.register_startup_step("start", lambda: None)
    manager.register_shutdown_step("slow", slow, timeout=10)

    await manager.startup()
    with capture_logs() as records:
        await manager.shutdown()

    assert manager.state is LifecycleState.STOPPED
    timeouts = [item for item in records if item["event"] == "shutdown_timeout"]
    assert timeouts and timeouts[0]["error_code"] == "SHUTDOWN_TIMEOUT"


async def test_steps_cannot_be_registered_after_start() -> None:
    manager = LifecycleManager()
    await manager.startup()

    with pytest.raises(LifecycleStateError):
        manager.register_startup_step("late", lambda: None)


async def test_second_startup_is_rejected() -> None:
    manager = LifecycleManager()
    await manager.startup()

    with pytest.raises(LifecycleStateError):
        await manager.startup()


async def test_shutdown_step_failure_does_not_block_other_steps() -> None:
    order: list[str] = []
    manager = LifecycleManager()

    def broken() -> None:
        raise RuntimeError("stop failed")

    manager.register_shutdown_step("broken", broken)
    manager.register_shutdown_step("flush", lambda: order.append("flush"))

    await manager.startup()
    with capture_logs(level=logging.ERROR) as records:
        await manager.shutdown()

    assert order == ["flush"]
    assert manager.state is LifecycleState.STOPPED
    assert any(item["event"] == "lifecycle_shutdown_step_failed" for item in records)
