"""数据库迁移管理：备份、升级、审计与失败处理。

规则：
- 升级前必须备份（库文件存在时，且确实有待执行迁移）。
- 迁移失败统一转换为 MigrationError，并保留备份路径与失败记录。
- 迁移不允许绕过本模块手工执行后不留记录。
- Alembic 的 ``alembic_version`` 是版本事实源，``migration_history`` 只做审计。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import Script, ScriptDirectory
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config.settings import Settings
from core.errors import MigrationError
from core.logging import get_logger, log_event
from infrastructure.database.engine import ensure_database_parent, sqlite_database_path
from infrastructure.database.errors import summarize_error
from infrastructure.database.service import DatabaseService

_BUNDLE_DIR = getattr(sys, "_MEIPASS", None)
BACKEND_ROOT = Path(_BUNDLE_DIR) if _BUNDLE_DIR else Path(__file__).resolve().parents[3]
BACKUP_DIR_NAME = "backups"
HISTORY_TABLE = "migration_history"

_INSERT_HISTORY = text(
    f"INSERT INTO {HISTORY_TABLE} "
    "(revision, name, checksum, status, duration_ms, error) "
    "VALUES (:revision, :name, :checksum, :status, :duration_ms, :error)"
)


@dataclass(frozen=True)
class MigrationResult:
    from_revision: str | None
    to_revision: str | None
    backup_path: Path | None

    @property
    def changed(self) -> bool:
        return self.from_revision != self.to_revision


@dataclass(frozen=True)
class MigrationRun:
    from_revision: str | None
    to_revision: str | None
    head_revision: str | None
    backup_path: Path | None
    applied: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.from_revision != self.to_revision


def alembic_config(settings: Settings) -> Config:
    # 打包后 alembic.ini 的 prepend_sys_path 无意义，直接以编程方式配置
    config = Config() if _BUNDLE_DIR else Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    # 运行时迁移复用应用日志配置，避免 alembic 关闭既有 logger
    config.attributes["configure_logger"] = False
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

    with (
        closing(sqlite3.connect(source)) as source_conn,
        closing(sqlite3.connect(target)) as target_conn,
    ):
        source_conn.backup(target_conn)
        target_conn.commit()

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
        logger.exception(
            "migration_failed",
            extra={
                "component": "database",
                "event": "migration_failed",
                "error_code": "MIGRATION_FAILED",
            },
        )
        raise MigrationError(
            "数据库升级失败",
            details={
                "from_revision": before or "",
                "backup": str(backup_path) if backup_path else "",
            },
        ) from exc

    after = current_revision(settings)
    log_event(
        logger,
        logging.INFO,
        "migration_applied",
        f"migration_applied {before or 'none'} -> {after or 'none'}",
        component="database",
    )
    return MigrationResult(before, after, backup_path if backup else None)


class MigrationService:
    """迁移执行为唯一入口，禁止绕过本服务修改库结构。"""

    def __init__(self, settings: Settings, *, database: DatabaseService) -> None:
        self._settings = settings
        self._database = database
        self._logger = get_logger("backend.database")

    @property
    def database(self) -> DatabaseService:
        return self._database

    def head_revision(self) -> str | None:
        return head_revision(self._settings)

    async def current_revision(self) -> str | None:
        def _read(sync_connection) -> str | None:
            return MigrationContext.configure(sync_connection).get_current_revision()

        async with self._database.engine.connect() as connection:
            return await connection.run_sync(_read)

    async def run(self) -> MigrationRun:
        """备份 → 升级 → 记录 → 校验；任一步失败抛出 ``MigrationError``。"""

        started = time.perf_counter()
        before = await self.current_revision()
        head = self.head_revision()

        if before == head:
            # 已在 head：不重复备份与升级，只校验历史文件完整性
            await self.verify_checksums()
            return MigrationRun(before, before, head, None, ())

        backup_path = await self._backup()

        try:
            await self._upgrade()
        except Exception as exc:
            duration_ms = _elapsed_ms(started)
            await self._record_failure(exc, duration_ms)
            log_event(
                self._logger,
                logging.ERROR,
                "migration_failed",
                "migration_failed",
                component="database",
                error_code="MIGRATION_FAILED",
            )
            raise MigrationError(
                "数据库升级失败",
                details={
                    "from_revision": before or "",
                    "backup": str(backup_path) if backup_path else "",
                },
            ) from exc

        duration_ms = _elapsed_ms(started)
        after = await self.current_revision()
        head = self.head_revision()
        applied = await self._record_applied(head, duration_ms)
        await self.verify_checksums()

        if after != head:
            raise MigrationError(
                "数据库版本与迁移脚本不一致",
                details={
                    "current": after or "",
                    "head": head or "",
                    "backup": str(backup_path) if backup_path else "",
                },
            )

        log_event(
            self._logger,
            logging.INFO,
            "migration_applied",
            f"migration_applied {before or 'none'} -> {after or 'none'}",
            component="database",
        )
        return MigrationRun(before, after, head, backup_path, applied)

    async def verify_at_head(self) -> None:
        """版本落后或超前时拒绝进入 RUNNING（E1-FI-004）。"""

        current = await self.current_revision()
        head = self.head_revision()
        if current != head:
            raise MigrationError(
                "数据库迁移版本与脚本不一致，已拒绝启动",
                details={"current": current or "", "head": head or ""},
            )

    async def verify_checksums(self) -> None:
        """已执行迁移文件被修改时视为完整性破坏。"""

        heads = self.head_revision()
        scripts = {script.revision: script for script in self._ordered_scripts(heads)}
        try:
            rows = await self._applied_rows()
        except SQLAlchemyError:
            # 历史表尚未建立（全新库首次升级前）时无审计记录可校验
            return

        problems: list[dict[str, str]] = []
        for revision, checksum in rows.items():
            script = scripts.get(revision)
            if script is None:
                problems.append({"revision": revision, "reason": "migration_file_missing"})
                continue
            if _checksum(script.path) != checksum:
                problems.append({"revision": revision, "reason": "checksum_mismatch"})

        if problems:
            raise MigrationError("迁移文件校验失败", details={"problems": problems})

    async def _backup(self) -> Path | None:
        try:
            return await asyncio.to_thread(backup_database, self._settings)
        except Exception as exc:
            raise MigrationError(
                "数据库备份失败，已中止升级",
                details={"reason": summarize_error(exc)},
            ) from exc

    async def _upgrade(self) -> None:
        config = alembic_config(self._settings)

        def _run(sync_connection) -> None:
            # env.py 优先使用外部连接，保证内存库与运行时引擎共用同一连接
            config.attributes["connection"] = sync_connection
            command.upgrade(config, "head")

        async with self._database.engine.connect() as connection:
            await connection.run_sync(_run)

    async def _record_applied(self, head: str | None, duration_ms: int) -> tuple[str, ...]:
        if head is None:
            return ()
        scripts = self._ordered_scripts(head)
        try:
            existing = set((await self._applied_rows()).keys())
            added: list[str] = []
            async with self._database.engine.begin() as connection:
                for script in scripts:
                    if script.revision in existing:
                        continue
                    await connection.execute(
                        _INSERT_HISTORY,
                        {
                            "revision": script.revision,
                            "name": _script_name(script),
                            "checksum": _checksum(script.path),
                            "status": "applied",
                            # 总耗时归属于本次升级到的 head，历史补齐记为 0
                            "duration_ms": duration_ms if script.revision == head else 0,
                            "error": None,
                        },
                    )
                    added.append(script.revision)
        except SQLAlchemyError:
            # 历史仅审计；Alembic 版本表仍是事实源，记录失败不阻断启动
            log_event(
                self._logger,
                logging.ERROR,
                "migration_history_write_failed",
                component="database",
                error_code="INFRASTRUCTURE_ERROR",
            )
            return ()
        return tuple(added)

    async def _record_failure(self, exc: BaseException, duration_ms: int) -> None:
        head = self.head_revision()
        if head is None:
            return
        scripts = self._ordered_scripts(head)
        target = scripts[-1] if scripts else None
        if target is None:
            return
        try:
            async with self._database.engine.begin() as connection:
                await connection.execute(
                    _INSERT_HISTORY,
                    {
                        "revision": target.revision,
                        "name": _script_name(target),
                        "checksum": _checksum(target.path),
                        "status": "failed",
                        "duration_ms": duration_ms,
                        "error": self._sanitize(exc),
                    },
                )
        except SQLAlchemyError:
            # 失败发生历史表建立之前（000002 自身失败）时只能依赖日志
            log_event(
                self._logger,
                logging.ERROR,
                "migration_history_unavailable",
                component="database",
                error_code="MIGRATION_FAILED",
            )

    async def _applied_rows(self) -> dict[str, str]:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
                text(
                    f"SELECT revision, checksum FROM {HISTORY_TABLE} "
                    "WHERE status = 'applied' ORDER BY id"
                )
            )
            return {row.revision: row.checksum for row in result}

    def _ordered_scripts(self, head: str | None) -> list[Script]:
        if head is None:
            return []
        script_dir = ScriptDirectory.from_config(alembic_config(self._settings))
        # walk_revisions 返回 head → base，反转后得到执行顺序
        return list(reversed(list(script_dir.walk_revisions(base="base", head=head))))

    def _sanitize(self, exc: BaseException) -> str:
        message = summarize_error(exc)
        path = sqlite_database_path(self._settings.database_url)
        if path is not None:
            message = message.replace(str(path), "<database>")
        return message


def _checksum(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _script_name(script: Script) -> str:
    return Path(script.path).name


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
