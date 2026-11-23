"""迁移服务测试（E1-T04-UT-001…005 / IT-001）。"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from bootstrap.application import create_app
from config.settings import Settings, load_settings
from core.errors import MigrationError
from infrastructure.database import manager as migration_module
from infrastructure.database.manager import MigrationService
from infrastructure.database.service import DatabaseService


def _settings(tmp_path: Path) -> Settings:
    database = tmp_path / "data" / "migrate.db"
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{database.as_posix()}",
        environment="test",
    )


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "migrate.db"


@pytest.fixture()
async def service(tmp_path: Path) -> AsyncIterator[MigrationService]:
    settings = _settings(tmp_path)
    database = DatabaseService(settings)
    await database.initialize()
    yield MigrationService(settings, database=database)
    await database.dispose()


async def _history(database: DatabaseService) -> list[tuple[str, str]]:
    async with database.engine.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT revision, status FROM migration_history ORDER BY id")
            )
        ).all()
    return [(row.revision, row.status) for row in rows]


async def test_first_migration_applies_and_records(
    service: MigrationService, tmp_path: Path
) -> None:
    result = await service.run()

    assert result.from_revision is None
    assert result.to_revision == "000019"
    assert result.head_revision == "000019"
    assert result.applied == (
        "000001",
        "000002",
        "000003",
        "000004",
        "000005",
        "000006",
        "000007",
        "000008",
        "000009",
        "000010",
        "000011",
        "000012",
        "000013",
        "000014",
        "000015",
        "000016",
        "000017",
        "000018",
        "000019",
    )
    assert result.backup_path is not None and result.backup_path.exists()
    assert await _history(service.database) == [
        ("000001", "applied"),
        ("000002", "applied"),
        ("000003", "applied"),
        ("000004", "applied"),
        ("000005", "applied"),
        ("000006", "applied"),
        ("000007", "applied"),
        ("000008", "applied"),
        ("000009", "applied"),
        ("000010", "applied"),
        ("000011", "applied"),
        ("000012", "applied"),
        ("000013", "applied"),
        ("000014", "applied"),
        ("000015", "applied"),
        ("000016", "applied"),
        ("000017", "applied"),
        ("000018", "applied"),
        ("000019", "applied"),
    ]


async def test_repeated_migration_is_noop(service: MigrationService) -> None:
    await service.run()
    second = await service.run()

    assert second.changed is False
    assert second.applied == ()
    # 已在 head 时不重复备份
    assert second.backup_path is None
    assert len(await _history(service.database)) == 19


async def test_history_keeps_version_order(service: MigrationService) -> None:
    await service.run()

    revisions = [revision for revision, _ in await _history(service.database)]
    assert revisions == [
        "000001",
        "000002",
        "000003",
        "000004",
        "000005",
        "000006",
        "000007",
        "000008",
        "000009",
        "000010",
        "000011",
        "000012",
        "000013",
        "000014",
        "000015",
        "000016",
        "000017",
        "000018",
        "000019",
    ]


async def test_checksum_change_is_detected(service: MigrationService) -> None:
    await service.run()

    async with service.database.engine.begin() as connection:
        await connection.execute(
            text("UPDATE migration_history SET checksum = 'tampered' WHERE revision = '000001'")
        )

    with pytest.raises(MigrationError) as exc_info:
        await service.verify_checksums()

    problems = exc_info.value.details["problems"]
    assert {"revision": "000001", "reason": "checksum_mismatch"} in problems


async def test_failure_is_recorded_and_wrapped(
    service: MigrationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    await service.run()

    # 模拟待升级状态：版本表回退，但历史表保留，便于记录失败
    async with service.database.engine.begin() as connection:
        await connection.execute(text("DELETE FROM alembic_version"))

    def _boom(_config, _revision: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(migration_module.command, "upgrade", _boom)

    with pytest.raises(MigrationError) as exc_info:
        await service.run()

    assert exc_info.value.code == "MIGRATION_FAILED"
    history = await _history(service.database)
    assert history[-1] == ("000019", "failed")


async def test_verify_at_head_rejects_mismatch(service: MigrationService) -> None:
    await service.run()

    async with service.database.engine.begin() as connection:
        await connection.execute(text("DELETE FROM alembic_version"))

    with pytest.raises(MigrationError):
        await service.verify_at_head()


def test_migration_failure_blocks_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(_settings(tmp_path))

    def _boom(_config, _revision: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(migration_module.command, "upgrade", _boom)

    with pytest.raises(MigrationError), TestClient(app):
        pass


def test_startup_runs_migrations(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)

    with TestClient(app) as client:
        assert "database" in app.state.services.names()
        assert "migration" in app.state.services.names()
        assert client.get("/health").status_code == 200

    with sqlite3.connect(_db_path(tmp_path)) as connection:
        revisions = connection.execute(
            "SELECT revision FROM migration_history ORDER BY id"
        ).fetchall()

    assert revisions == [
        ("000001",),
        ("000002",),
        ("000003",),
        ("000004",),
        ("000005",),
        ("000006",),
        ("000007",),
        ("000008",),
        ("000009",),
        ("000010",),
        ("000011",),
        ("000012",),
        ("000013",),
        ("000014",),
        ("000015",),
        ("000016",),
        ("000017",),
        ("000018",),
        ("000019",),
    ]
