"""E1 Core 全链路集成测试（E1-T14）。

覆盖：启动/关闭、配置、数据库、迁移、Repository、事务提交/回滚、事件发布、
Outbox 派发与中断恢复、备份、恢复、健康检查。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path

import pytest
from sqlalchemy import String, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.health import HealthStatus, collect_health, readiness
from bootstrap.lifecycle import Lifecycle
from config.settings import load_settings
from core.events import Event, EventBus, EventRegistry
from core.lifecycle.states import LifecycleState
from infrastructure.database.backup import BackupService
from infrastructure.database.manager import MigrationService
from infrastructure.database.repository import BaseRepository
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.events.dispatcher import EventDispatcher
from infrastructure.events.outbox import OutboxRepository


class _Base(DeclarativeBase):
    pass


class Item(_Base):
    __tablename__ = "e1_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)


class ItemRepository(BaseRepository[Item]):
    model = Item


def _settings(tmp_path: Path):
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e1.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
    )


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("等待条件超时")


async def test_core_end_to_end(tmp_path: Path) -> None:
    lifecycle = Lifecycle(_settings(tmp_path))
    await lifecycle.manager.startup()

    try:
        services = lifecycle.services
        assert lifecycle.state is LifecycleState.RUNNING
        assert {
            "config",
            "database",
            "migration",
            "event_registry",
            "event_bus",
            "event_dispatcher",
            "backup",
        } <= set(services.names())

        database = services.get("database", DatabaseService)
        migration = services.get("migration", MigrationService)
        registry = services.get("event_registry", EventRegistry)
        bus = services.get("event_bus", EventBus)
        dispatcher = services.get("event_dispatcher", EventDispatcher)
        backup = services.get("backup", BackupService)

        assert await database.ping() is True
        assert await migration.current_revision() == "000018"

        async with database.engine.begin() as connection:
            await connection.run_sync(_Base.metadata.create_all)

        async with database.session() as session, transaction(session):
            item = await ItemRepository(session).add(Item(name="alpha"))
            item_id = item.id

        async with database.session() as session:
            loaded = await ItemRepository(session).get(item_id)
            page = await ItemRepository(session).paginate(limit=10)
        assert loaded is not None and loaded.name == "alpha"
        assert page.total == 1 and page.items[0].name == "alpha"

        with pytest.raises(RuntimeError):
            async with database.session() as session, transaction(session):
                await ItemRepository(session).add(Item(name="rolled-back"))
                raise RuntimeError("force rollback")

        async with database.session() as session:
            total = await session.scalar(select(func.count()).select_from(Item))
        assert total == 1

        delivered: list[Event] = []
        registry.register("core.event", delivered.append, consumer_id="e1-consumer")
        await bus.publish(Event.create("core.event", {"step": "bus"}))
        assert len(delivered) == 1

        await dispatcher.stop()
        outbox = OutboxRepository()
        async with database.session() as session, transaction(session):
            await outbox.add(session, Event.create("core.event", {"step": "outbox"}))

        report = await dispatcher.dispatch_once()
        assert report.published == 1
        assert len(delivered) == 2

        async with database.session() as session, transaction(session):
            await outbox.add(session, Event.create("core.event", {"step": "recover"}))
            stuck = (await outbox.fetch_dispatchable(session, limit=10, max_retries=5))[-1]
            await outbox.mark_publishing(session, stuck.id)

        await dispatcher.start()
        await _wait_for(lambda: _delivered(delivered, 3))
        assert _delivered(delivered, 3)

        async with database.session() as session:
            counts = await outbox.counts(session)
        assert counts.get("published", 0) >= 2
        assert counts.get("publishing", 0) == 0

        info = await backup.create(reason="e1-integration")
        assert info.integrity.lower() == "ok"
        restored = await backup.restore(info.path, expected_revision="000018")
        assert restored.revision == "000018"
        assert database.is_initialized is True
        assert dispatcher.running is True

        health = await collect_health(lifecycle, services)
        assert health.status is HealthStatus.HEALTHY
        assert readiness(health) == (True, "")
    finally:
        await lifecycle.manager.shutdown()

    assert lifecycle.state is LifecycleState.STOPPED
    assert database.is_initialized is False

    await lifecycle.manager.shutdown()
    assert lifecycle.state is LifecycleState.STOPPED


def _delivered(events: list[Event], minimum: int) -> bool:
    return len(events) >= minimum
