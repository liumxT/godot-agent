"""数据库服务测试（E1-T03-UT-001…004 / IT-003）。"""

from __future__ import annotations

import stat
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from config.settings import Settings, load_settings
from core.errors import DatabaseError, StartupError
from infrastructure.database.errors import translate_db_error
from infrastructure.database.health import check as check_health
from infrastructure.database.service import DatabaseService


def _settings(tmp_path: Path, *, directory: str = "data") -> Settings:
    database = tmp_path / directory / "service.db"
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{database.as_posix()}",
        environment="test",
    )


@pytest.fixture()
async def service(tmp_path: Path) -> AsyncIterator[DatabaseService]:
    database = DatabaseService(_settings(tmp_path))
    await database.initialize()
    yield database
    await database.dispose()


async def test_initialize_creates_database(service: DatabaseService, tmp_path: Path) -> None:
    assert service.is_initialized is True
    assert (tmp_path / "data" / "service.db").exists()
    async with service.session() as session:
        await session.execute(text("SELECT 1"))


async def test_wal_and_foreign_keys(service: DatabaseService) -> None:
    async with service.engine.connect() as connection:
        journal_mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar()
        foreign_keys = (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar()

    assert str(journal_mode).lower() == "wal"
    assert foreign_keys == 1


async def test_dispose_is_idempotent(service: DatabaseService) -> None:
    await service.dispose()
    await service.dispose()

    assert service.is_initialized is False
    assert await service.ping() is False


async def test_health_reports_integrity(service: DatabaseService) -> None:
    health = await check_health(service)

    assert health.available is True
    assert health.integrity == "ok"
    assert health.error is None


async def test_blocked_parent_directory_raises_startup_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    database = DatabaseService(
        load_settings(
            _env_file=None,
            database_url=f"sqlite+aiosqlite:///{blocker.as_posix()}/service.db",
            environment="test",
        )
    )

    with pytest.raises(StartupError):
        await database.initialize()


async def test_readonly_database_is_rejected(tmp_path: Path) -> None:
    database = DatabaseService(_settings(tmp_path))
    await database.initialize()
    await database.dispose()
    path = tmp_path / "data" / "service.db"
    path.chmod(stat.S_IREAD)
    try:
        readonly = DatabaseService(_settings(tmp_path))
        with pytest.raises(StartupError) as error:
            await readonly.initialize()
        assert "不可写" in str(error.value)
    finally:
        path.chmod(stat.S_IWRITE)


async def test_corrupted_database_is_rejected(tmp_path: Path) -> None:
    database = DatabaseService(_settings(tmp_path))
    await database.initialize()
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
        for index in range(200):
            await connection.exec_driver_sql(
                "INSERT INTO t (value) VALUES (?)", (f"row-{index}-{'x' * 60}",)
            )
    await database.dispose()

    path = tmp_path / "data" / "service.db"
    raw = path.read_bytes()
    assert len(raw) > 8192
    path.write_bytes(raw[:4096] + b"\x00" * 4096 + raw[8192:])

    with pytest.raises((StartupError, DatabaseError)):
        await DatabaseService(_settings(tmp_path)).initialize()


def test_operational_error_maps_to_unavailable() -> None:
    error = translate_db_error(OperationalError("SELECT 1", {}, Exception("disk I/O error")))

    assert error.code == "DATABASE_UNAVAILABLE"
    assert error.retryable is True


def test_integrity_error_maps_to_integrity_code() -> None:
    error = translate_db_error(IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed")))

    assert error.code == "DATABASE_INTEGRITY_ERROR"
    assert error.retryable is False
