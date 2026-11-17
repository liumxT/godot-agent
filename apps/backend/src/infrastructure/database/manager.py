"""数据库迁移管理：备份、升级与失败处理。

规则：
- 升级前必须备份（库文件存在时）。
- 迁移失败统一转换为 MigrationError，并保留备份路径。
- 迁移不允许绕过本模块手工执行后不留记录。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine as sa_create_engine

from config.settings import Settings
from core.errors import AppError
from core.logging import get_logger
from infrastructure.database.engine import ensure_database_parent, sqlite_database_path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
BACKUP_DIR_NAME = "backups"


class MigrationError(AppError):
    code = "MIGRATION_FAILED"
    status_code = 500


@dataclass(frozen=True)
class MigrationResult:
    from_revision: str | None
    to_revision: str | None
    backup_path: Path | None

    @property
    def changed(self) -> bool:
        return self.from_revision != self.to_revision


def alembic_config(settings: Settings) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def head_revision(settings: Settings) -> str | None:
    return ScriptDirectory.from_config(alembic_config(settings)).get_current_head()


def current_revision(settings: Settings) -> str | None:
    path = sqlite_database_path(settings.database_url)
    if path is not None and not path.exists():
        return None

    engine = sa_create_engine(settings.database_url.replace("+aiosqlite", ""), future=True)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def backup_database(settings: Settings, backup_dir: Path | None = None) -> Path | None:
    """使用 SQLite 在线备份 API，WAL 模式下也保证一致性。"""

    source = sqlite_database_path(settings.database_url)
    if source is None or not source.exists():
        return None

    target_dir = backup_dir or source.parent / BACKUP_DIR_NAME
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"{source.stem}-{stamp}.db"

    with sqlite3.connect(source) as source_conn, sqlite3.connect(target) as target_conn:
        source_conn.backup(target_conn)

    return target


def upgrade_to_head(settings: Settings, *, backup: bool = True) -> MigrationResult:
    logger = get_logger("backend.database")
    ensure_database_parent(settings.database_url)
    before = current_revision(settings)

    try:
        backup_path = backup_database(settings) if backup else None
    except Exception as exc:  # 备份失败必须中止升级
        raise MigrationError("数据库备份失败，已中止升级", details={"reason": str(exc)}) from exc

    try:
        command.upgrade(alembic_config(settings), "head")
    except Exception as exc:  # 统一转换为领域错误
        logger.exception("migration_failed", extra={"component": "database"})
        raise MigrationError(
            "数据库升级失败",
            details={
                "from_revision": before or "",
                "backup": str(backup_path) if backup_path else "",
            },
        ) from exc

    after = current_revision(settings)
    logger.info(
        "migration_applied %s -> %s",
        before or "none",
        after or "none",
        extra={"component": "database"},
    )
    return MigrationResult(before, after, backup_path if backup else None)
