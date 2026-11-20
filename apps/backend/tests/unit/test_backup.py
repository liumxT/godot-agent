"""备份创建与校验单元测试（E1-T11-UT-001…003）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from config.settings import Settings, load_settings
from core.errors import BackupError
from infrastructure.database.backup import BackupService
from infrastructure.database.manager import MigrationService
from infrastructure.database.service import DatabaseService


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'backup.db').as_posix()}",
        environment="test",
        **overrides,
    )


@pytest.fixture()
async def database(tmp_path: Path) -> AsyncIterator[tuple[Settings, DatabaseService]]:
    settings = _settings(tmp_path)
    service = DatabaseService(settings)
    await service.initialize()
    await MigrationService(settings, database=service).run()
    yield settings, service
    await service.dispose()


async def test_create_backup_with_metadata(database) -> None:
    settings, db = database
    service = BackupService(settings, database=db)

    info = await service.create(reason="test")

    assert info.path.is_file()
    assert info.path.with_suffix(".json").is_file()
    assert info.integrity.lower() == "ok"
    assert info.revision == "000013"
    assert info.size_bytes == info.path.stat().st_size
    assert len(info.sha256) == 64
    assert info.reason == "test"


async def test_verify_rejects_invalid_backup(tmp_path: Path) -> None:
    settings, db = await _plain_database(tmp_path)
    service = BackupService(settings)
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a sqlite database")
    try:
        with pytest.raises(BackupError):
            await service.verify(broken)

        with pytest.raises(BackupError):
            await service.verify(tmp_path / "missing.db")
    finally:
        await db.dispose()


async def test_retention_keeps_latest(tmp_path: Path) -> None:
    settings = _settings(tmp_path, backup_retention=2)
    db = DatabaseService(settings)
    await db.initialize()
    await MigrationService(settings, database=db).run()
    service = BackupService(settings, database=db)
    try:
        for _ in range(3):
            await service.create(reason="retention")

        backups = await service.list()

        assert len(backups) == 2
    finally:
        await db.dispose()


async def test_memory_database_cannot_be_backed_up(tmp_path: Path) -> None:
    settings = load_settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        environment="test",
    )
    service = BackupService(settings)

    with pytest.raises(BackupError):
        await service.create()


async def _plain_database(tmp_path: Path) -> tuple[Settings, DatabaseService]:
    settings = _settings(tmp_path)
    service = DatabaseService(settings)
    await service.initialize()
    return settings, service
