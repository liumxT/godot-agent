"""数据库迁移测试（E0-T06 验收）。

覆盖：升级、幂等、PRAGMA、备份、失败处理。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command as alembic_command

from config.settings import Settings, load_settings
from infrastructure.database import engine as engine_module
from infrastructure.database.manager import (
    MigrationError,
    backup_database,
    head_revision,
    upgrade_to_head,
)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    db_path = tmp_path / "data" / "test.db"
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        environment="test",
    )


def _db_path(settings: Settings) -> Path:
    path = engine_module.sqlite_database_path(settings.database_url)
    assert path is not None
    return path


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in rows}


def test_upgrade_creates_schema(settings: Settings) -> None:
    result = upgrade_to_head(settings)

    assert result.to_revision == head_revision(settings) == "000022"
    assert result.changed is True
    tables = _tables(_db_path(settings))
    assert "alembic_version" in tables
    assert "runtime_metadata" in tables
    assert "migration_history" in tables
    assert "event_outbox" in tables
    assert "event_inbox" in tables
    assert "e2_audit_events" in tables
    assert "projects" in tables
    assert "tasks" in tables
    assert "task_attempts" in tables
    assert "task_events" in tables
    assert "workflow_instances" in tables
    assert "workflow_phases" in tables
    assert "change_sets" in tables
    assert "approvals" in tables
    assert "requirements" in tables
    assert "model_providers" in tables
    assert "provider_configurations" in tables
    assert "models" in tables
    assert "model_capabilities" in tables
    assert "model_price_versions" in tables
    assert "model_requests" in tables
    assert "model_responses" in tables
    assert "model_usage_records" in tables
    assert "model_cost_records" in tables
    assert "model_call_audits" in tables
    assert "prompt_definitions" in tables
    assert "prompt_test_results" in tables
    assert "context_assemblies" in tables
    assert "tool_definitions" in tables
    assert "tool_executions" in tables
    assert "resource_locks" in tables
    assert "tool_audit_records" in tables
    assert "tool_verification_results" in tables


def test_upgrade_is_idempotent(settings: Settings) -> None:
    upgrade_to_head(settings)
    second = upgrade_to_head(settings)

    assert second.changed is False
    assert second.from_revision == second.to_revision == "000022"


def test_backup_created_before_second_upgrade(settings: Settings) -> None:
    first = upgrade_to_head(settings)
    assert first.backup_path is None  # 首次运行时尚无数据库文件

    second = upgrade_to_head(settings)
    assert second.backup_path is not None
    assert second.backup_path.exists()
    with sqlite3.connect(second.backup_path) as connection:
        assert connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] > 0


async def test_pragmas_applied(settings: Settings) -> None:
    engine = engine_module.create_engine(settings)
    try:
        async with engine.connect() as connection:
            journal_mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar()
            foreign_keys = (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar()
    finally:
        await engine.dispose()

    assert str(journal_mode).lower() == "wal"
    assert foreign_keys == 1


def test_manual_backup(settings: Settings) -> None:
    upgrade_to_head(settings)
    backup = backup_database(settings)

    assert backup is not None
    assert backup.parent.name == "backups"
    assert _tables(backup)


def test_failure_is_wrapped(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    upgrade_to_head(settings)

    def _boom(_config, _revision: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(alembic_command, "upgrade", _boom)

    with pytest.raises(MigrationError) as exc_info:
        upgrade_to_head(settings)

    assert exc_info.value.code == "MIGRATION_FAILED"
    assert "boom" not in exc_info.value.message
    assert exc_info.value.details["from_revision"] == "000022"


def test_uncreatable_database_directory_is_reported(tmp_path: Path) -> None:
    """故障注入：库文件父路径被占用为普通文件。"""

    blocker = tmp_path / "data"
    blocker.write_text("not a directory", encoding="utf-8")
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{blocker.as_posix()}/test.db",
        environment="test",
    )

    with pytest.raises(OSError):
        upgrade_to_head(settings, backup=False)
