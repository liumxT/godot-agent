"""健康状态聚合单元测试（E1-T12-UT-001…004）。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.health import HealthStatus, collect_health, readiness
from bootstrap.service_registry import ServiceRegistry
from config.settings import Settings, load_settings
from core.errors import MigrationError
from core.events.registry import EventRegistry
from core.lifecycle.states import LifecycleState
from infrastructure.database import health as database_health
from infrastructure.database.backup import BackupService
from infrastructure.database.manager import MigrationService
from infrastructure.database.service import DatabaseService
from infrastructure.events.dispatcher import EventDispatcher


def _settings(tmp_path: Path) -> Settings:
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'health.db').as_posix()}",
        environment="test",
    )


def _lifecycle(state: LifecycleState) -> SimpleNamespace:
    return SimpleNamespace(state=state)


@pytest.fixture()
async def ready_services() -> AsyncIterator[tuple[Settings, ServiceRegistry]]:
    settings = load_settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        environment="test",
    )
    database = DatabaseService(settings)
    await database.initialize()
    migration = MigrationService(settings, database=database)
    await migration.run()

    services = ServiceRegistry()
    services.register("config", object())
    services.register("database", database)
    services.register("migration", migration)
    services.register("event_dispatcher", EventDispatcher(database, EventRegistry()))
    services.register("backup", BackupService(settings, database=database))

    logging.getLogger().addHandler(logging.NullHandler())
    yield settings, services
    await database.dispose()


async def test_healthy_when_all_dependencies_ready(ready_services) -> None:
    _, services = ready_services

    report = await collect_health(_lifecycle(LifecycleState.RUNNING), services)

    assert report.status is HealthStatus.HEALTHY
    assert {check.name: check.status for check in report.checks}["database"] is HealthStatus.HEALTHY
    assert readiness(report) == (True, "")


async def test_database_unavailable(ready_services) -> None:
    _, services = ready_services
    await services.get("database", DatabaseService).dispose()

    report = await collect_health(_lifecycle(LifecycleState.RUNNING), services)

    assert report.status is HealthStatus.UNHEALTHY
    assert readiness(report) == (False, "database")


async def test_migration_not_at_head(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = DatabaseService(settings)
    await database.initialize()
    services = ServiceRegistry()
    services.register("database", database)
    services.register("migration", MigrationService(settings, database=database))
    logging.getLogger().addHandler(logging.NullHandler())
    try:
        report = await collect_health(_lifecycle(LifecycleState.RUNNING), services)

        checks = {check.name: check for check in report.checks}
        assert checks["migration"].status is HealthStatus.UNHEALTHY
        assert checks["migration"].detail == MigrationError.code
        assert readiness(report) == (False, "migration")
    finally:
        await database.dispose()


async def test_database_integrity_failure_is_unhealthy(ready_services, monkeypatch) -> None:
    _, services = ready_services

    async def _broken(_engine) -> str:
        return "Page 2: btree page is malformed"

    monkeypatch.setattr(database_health, "integrity_check", _broken)

    report = await collect_health(_lifecycle(LifecycleState.RUNNING), services)

    checks = {check.name: check for check in report.checks}
    assert checks["database"].status is HealthStatus.UNHEALTHY
    assert checks["database"].detail == "integrity:Page 2: btree page is malformed"
    assert report.status is HealthStatus.UNHEALTHY
    assert readiness(report) == (False, "database")


async def test_stopped_service_is_unhealthy(ready_services) -> None:
    _, services = ready_services

    report = await collect_health(_lifecycle(LifecycleState.STOPPED), services)

    assert report.status is HealthStatus.UNHEALTHY
    assert readiness(report) == (False, "application")


async def test_starting_state_wins_before_dependencies(ready_services) -> None:
    _, services = ready_services

    report = await collect_health(_lifecycle(LifecycleState.STARTING), services)

    assert report.status is HealthStatus.STARTING
    assert readiness(report)[0] is False


async def test_missing_config_degrades(ready_services) -> None:
    _, services = ready_services
    services.clear()
    services.register("database", ready_services[1].try_get("database"))
    services.register("migration", ready_services[1].try_get("migration"))

    report = await collect_health(_lifecycle(LifecycleState.RUNNING), services)

    assert report.status is HealthStatus.DEGRADED
