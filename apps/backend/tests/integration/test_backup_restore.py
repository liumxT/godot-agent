"""备份恢复集成测试（E1-T11-IT-001…003）。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import text

from config.settings import Settings, load_settings
from core.errors import BackupError
from infrastructure.database.backup import BackupService
from infrastructure.database.manager import MigrationService
from infrastructure.database.service import DatabaseService

ITEMS_TABLE = "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"


def _settings(tmp_path: Path) -> Settings:
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'restore.db').as_posix()}",
        environment="test",
    )


async def _prepare(tmp_path: Path) -> tuple[Settings, DatabaseService]:
    settings = _settings(tmp_path)
    database = DatabaseService(settings)
    await database.initialize()
    await MigrationService(settings, database=database).run()
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql(ITEMS_TABLE)
        await connection.exec_driver_sql("INSERT INTO items (name) VALUES ('before')")
    return settings, database


async def _rename(database: DatabaseService, name: str) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(text("UPDATE items SET name = :name"), {"name": name})


async def _name(database: DatabaseService) -> str:
    async with database.engine.connect() as connection:
        return str((await connection.execute(text("SELECT name FROM items"))).scalar())


def _integrity(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


async def test_restore_returns_to_backup_state(tmp_path: Path) -> None:
    settings, database = await _prepare(tmp_path)
    service = BackupService(settings, database=database)
    try:
        info = await service.create(reason="before-upgrade")
        await _rename(database, "after")

        restored = await service.restore(info.path)

        assert restored.path == info.path
        assert database.is_initialized is True
        assert await _name(database) == "before"
        assert _integrity(tmp_path / "restore.db") == "ok"
        assert await database.ping() is True
    finally:
        await database.dispose()


async def test_restore_rejects_version_mismatch_without_touching_data(tmp_path: Path) -> None:
    settings, database = await _prepare(tmp_path)
    service = BackupService(settings, database=database)
    try:
        info = await service.create()
        await _rename(database, "after")

        with pytest.raises(BackupError):
            await service.restore(info.path, expected_revision="999999")

        assert await _name(database) == "after"
        assert database.is_initialized is True
    finally:
        await database.dispose()


async def test_restore_failure_keeps_current_database(tmp_path: Path) -> None:
    settings, database = await _prepare(tmp_path)
    service = BackupService(settings, database=database)
    try:
        info = await service.create()
        info.path.write_bytes(b"corrupted backup")
        await _rename(database, "after")

        with pytest.raises(BackupError):
            await service.restore(info.path)

        assert database.is_initialized is True
        assert await _name(database) == "after"
        assert _integrity(tmp_path / "restore.db") == "ok"
    finally:
        await database.dispose()
