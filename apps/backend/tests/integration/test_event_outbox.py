"""Outbox / Inbox 与派发器测试（E1-T10-UT-001…004 / IT-001…002）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text

from config.settings import Settings, load_settings
from core.events.model import Event
from core.events.registry import EventRegistry
from infrastructure.database.manager import MigrationService
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.events.dispatcher import EventDispatcher
from infrastructure.events.outbox import OutboxRepository

BUSINESS_TABLE = (
    "CREATE TABLE business_items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
)


def _settings(tmp_path: Path, name: str = "events.db") -> Settings:
    database = tmp_path / name
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{database.as_posix()}",
        environment="test",
    )


async def _prepare(settings: Settings) -> DatabaseService:
    service = DatabaseService(settings)
    await service.initialize()
    await MigrationService(settings, database=service).run()
    async with service.engine.begin() as connection:
        await connection.exec_driver_sql(BUSINESS_TABLE)
    return service


@pytest.fixture()
async def database(tmp_path: Path) -> AsyncIterator[DatabaseService]:
    service = await _prepare(_settings(tmp_path))
    yield service
    await service.dispose()


async def _add_event(
    database: DatabaseService, event: Event, *, business: str | None = None
) -> None:
    async with database.session() as session, transaction(session):
        if business is not None:
            await session.execute(
                text("INSERT INTO business_items (name) VALUES (:name)"), {"name": business}
            )
        await OutboxRepository().add(session, event)


async def _outbox_row(database: DatabaseService, event_id: str):
    async with database.engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT status, retry_count, last_error, published_at FROM event_outbox "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            )
        ).first()


async def _inbox_row(database: DatabaseService, event_id: str, consumer_id: str):
    async with database.engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT status, last_error FROM event_inbox "
                    "WHERE event_id = :event_id AND consumer_id = :consumer_id"
                ),
                {"event_id": event_id, "consumer_id": consumer_id},
            )
        ).first()


async def _count(database: DatabaseService, table: str) -> int:
    async with database.engine.connect() as connection:
        return int((await connection.exec_driver_sql(f"SELECT count(*) FROM {table}")).scalar())


async def test_outbox_add_records_pending(database: DatabaseService) -> None:
    event = Event.create("task.created", {"task_id": "t1"})
    await _add_event(database, event)

    async with database.session() as session:
        messages = await OutboxRepository().fetch_dispatchable(session, limit=10, max_retries=5)
        counts = await OutboxRepository().counts(session)

    assert [message.event_id for message in messages] == [event.event_id]
    assert messages[0].payload == '{"task_id": "t1"}'
    assert counts == {"pending": 1}


async def test_successful_dispatch_marks_published(database: DatabaseService) -> None:
    event = Event.create("task.created", {"task_id": "t1"})
    registry = EventRegistry()
    received: list[Event] = []
    registry.register("task.created", received.append, consumer_id="collector")
    await _add_event(database, event)

    report = await EventDispatcher(database, registry).dispatch_once()

    assert (report.claimed, report.published, report.failed) == (1, 1, 0)
    assert received[0].event_id == event.event_id
    row = await _outbox_row(database, event.event_id)
    assert row.status == "published"
    assert row.published_at is not None
    inbox = await _inbox_row(database, event.event_id, "collector")
    assert inbox.status == "processed"


async def test_failure_retries_until_success(database: DatabaseService) -> None:
    event = Event.create("task.created", {})
    registry = EventRegistry()
    calls = {"total": 0}

    def flaky(_event: Event) -> None:
        calls["total"] += 1
        if calls["total"] == 1:
            raise RuntimeError("transient failure")

    registry.register("task.created", flaky, consumer_id="flaky")
    await _add_event(database, event)
    dispatcher = EventDispatcher(database, registry)

    first = await dispatcher.dispatch_once()
    row = await _outbox_row(database, event.event_id)

    assert first.failed == 1
    assert row.status == "failed"
    assert row.retry_count == 1
    assert "transient failure" in row.last_error
    assert (await _inbox_row(database, event.event_id, "flaky")).status == "failed"

    second = await dispatcher.dispatch_once()

    assert second.published == 1
    assert (await _outbox_row(database, event.event_id)).status == "published"
    assert (await _inbox_row(database, event.event_id, "flaky")).status == "processed"
    assert calls["total"] == 2


async def test_retry_limit_stops_dispatch(database: DatabaseService) -> None:
    event = Event.create("task.created", {})
    registry = EventRegistry()

    def always_fails(_event: Event) -> None:
        raise RuntimeError("permanent failure")

    registry.register("task.created", always_fails, consumer_id="broken")
    await _add_event(database, event)
    dispatcher = EventDispatcher(database, registry, max_retries=1)

    first = await dispatcher.dispatch_once()
    second = await dispatcher.dispatch_once()

    assert first.failed == 1
    assert second.claimed == 0
    row = await _outbox_row(database, event.event_id)
    assert row.status == "failed"
    assert row.retry_count == 1


async def test_inbox_prevents_duplicate_consumer_call(database: DatabaseService) -> None:
    event = Event.create("task.created", {})
    registry = EventRegistry()
    calls = {"total": 0}

    def handler(_event: Event) -> None:
        calls["total"] += 1

    registry.register("task.created", handler, consumer_id="idempotent")
    await _add_event(database, event)
    dispatcher = EventDispatcher(database, registry)
    await dispatcher.dispatch_once()

    # 模拟重复投递：把已发布事件重新放回待派发
    async with database.engine.begin() as connection:
        await connection.execute(
            text("UPDATE event_outbox SET status = 'pending', published_at = NULL")
        )

    report = await dispatcher.dispatch_once()

    assert report.skipped == 1
    assert report.published == 1
    assert calls["total"] == 1


async def test_event_without_subscribers_is_published(database: DatabaseService) -> None:
    event = Event.create("task.created", {})
    await _add_event(database, event)

    report = await EventDispatcher(database, EventRegistry()).dispatch_once()

    assert report.published == 1
    assert (await _outbox_row(database, event.event_id)).status == "published"


async def test_business_transaction_and_outbox_are_atomic(database: DatabaseService) -> None:
    rolled_back = Event.create("task.created", {"step": "rollback"})
    with pytest.raises(RuntimeError):
        async with database.session() as session, transaction(session):
            await session.execute(text("INSERT INTO business_items (name) VALUES ('rollback')"))
            await OutboxRepository().add(session, rolled_back)
            raise RuntimeError("rollback")

    assert await _count(database, "business_items") == 0
    assert await _count(database, "event_outbox") == 0

    committed = Event.create("task.created", {"step": "commit"})
    await _add_event(database, committed, business="committed")

    assert await _count(database, "business_items") == 1
    assert await _count(database, "event_outbox") == 1


async def test_startup_resets_publishing_rows(tmp_path: Path) -> None:
    settings = load_settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        environment="test",
    )
    service = await _prepare(settings)
    try:
        event = Event.create("task.created", {})
        await _add_event(service, event)
        async with service.engine.begin() as connection:
            await connection.execute(text("UPDATE event_outbox SET status = 'publishing'"))

        registry = EventRegistry()
        received: list[Event] = []
        registry.register("task.created", received.append, consumer_id="recovered")
        dispatcher = EventDispatcher(service, registry)

        await dispatcher.start()

        # 内存库不启动后台任务，但中断恢复已完成
        assert dispatcher.running is False
        assert (await _outbox_row(service, event.event_id)).status == "pending"

        report = await dispatcher.dispatch_once()

        assert report.published == 1
        assert len(received) == 1
    finally:
        await service.dispose()
