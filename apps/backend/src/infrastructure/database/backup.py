"""数据库备份与恢复（E1-T11）。

- 备份：SQLite 在线备份 API（WAL 下保持一致），同时写 ``.json`` 元数据；
- 校验：``PRAGMA integrity_check`` + revision 比对，不通过拒绝恢复（E1-FI-008）；
- 恢复：停派发 → 关连接 → 保护副本 → 覆盖 → 完整性/版本检查 → 重开服务；
  任一步失败回滚到保护副本（E1-FI-009），绝不删除当前数据；
- 保留：按数量保留最近 N 份，删除前记录审计日志。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from config.settings import Settings
from core.errors import BackupError
from core.logging import get_logger, log_event
from infrastructure.database.engine import sqlite_database_path
from infrastructure.database.errors import summarize_error

if TYPE_CHECKING:
    from infrastructure.database.service import DatabaseService
    from infrastructure.events.dispatcher import EventDispatcher

BACKUP_DIR_NAME = "backups"
RESTORE_SUBDIR = "restore"
_STAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    created_at: str
    reason: str
    size_bytes: int
    sha256: str
    revision: str | None
    integrity: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.path.name,
            "created_at": self.created_at,
            "reason": self.reason,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "revision": self.revision,
            "integrity": self.integrity,
        }


class BackupService:
    """备份创建、校验、恢复与保留；默认与数据库同目录。"""

    def __init__(
        self,
        settings: Settings,
        *,
        database: DatabaseService | None = None,
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        self._settings = settings
        self._database = database
        self._dispatcher = dispatcher
        self._logger = get_logger("backend.backup")

    @property
    def directory(self) -> Path:
        if self._settings.backup_dir:
            return Path(self._settings.backup_dir)
        source = sqlite_database_path(self._settings.database_url)
        base = source.parent if source is not None else Path(self._settings.data_dir)
        return base / BACKUP_DIR_NAME

    async def create(self, *, reason: str = "manual") -> BackupInfo:
        return await asyncio.to_thread(self._create_sync, reason)

    async def verify(self, path: str | Path) -> BackupInfo:
        return await asyncio.to_thread(self._verify_sync, Path(path))

    async def list(self) -> list[BackupInfo]:
        return await asyncio.to_thread(self._list_sync)

    async def restore(
        self,
        path: str | Path,
        *,
        expected_revision: str | None = None,
    ) -> BackupInfo:
        """恢复备份；失败时回滚到保护副本并抛出 ``BackupError``。"""

        info = await self.verify(path)
        if expected_revision is not None and info.revision != expected_revision:
            raise BackupError(
                "备份版本与目标版本不一致",
                details={
                    "backup_revision": info.revision or "",
                    "expected_revision": expected_revision,
                },
            )

        source = sqlite_database_path(self._settings.database_url)
        if source is None:
            raise BackupError("内存数据库不支持恢复", details={"database": ":memory:"})

        dispatcher_stopped = False
        if self._dispatcher is not None:
            await self._dispatcher.stop()
            dispatcher_stopped = True
        if self._database is not None:
            await self._database.dispose()

        protection = await asyncio.to_thread(self._protect_current, source)
        try:
            await asyncio.to_thread(self._replace_database, info.path, source)
            await asyncio.to_thread(self._verify_restored, source, info)
            await self._reopen_database()
        except Exception as exc:
            if protection is not None:
                await asyncio.to_thread(self._replace_database, protection, source)
            await self._reopen_database(best_effort=True)
            await self._restart_dispatcher(dispatcher_stopped)
            if isinstance(exc, BackupError):
                raise
            raise BackupError(
                "数据库恢复失败，已回滚到保护副本",
                details={"reason": summarize_error(exc)},
            ) from exc

        await self._restart_dispatcher(dispatcher_stopped)
        log_event(
            self._logger,
            logging.INFO,
            "database_restored",
            f"database_restored {info.path.name}",
            component="backup",
        )
        return info

    def _create_sync(self, reason: str) -> BackupInfo:
        source = sqlite_database_path(self._settings.database_url)
        if source is None or not source.exists():
            raise BackupError("数据库文件不存在，无法备份", details={"database": ":memory:"})

        target_dir = self.directory
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackupError("备份目录不可用", details={"reason": summarize_error(exc)}) from exc

        stamp = datetime.now(UTC).strftime(_STAMP_FORMAT)
        target = target_dir / f"{source.stem}-{stamp}.db"
        try:
            with (
                closing(sqlite3.connect(source)) as source_conn,
                closing(sqlite3.connect(target)) as target_conn,
            ):
                source_conn.backup(target_conn)
                target_conn.commit()
        except sqlite3.Error as exc:
            target.unlink(missing_ok=True)
            raise BackupError("备份写入失败", details={"reason": summarize_error(exc)}) from exc

        info = self._describe(target, reason=reason)
        if info.integrity.lower() != "ok":
            target.unlink(missing_ok=True)
            raise BackupError("备份完整性检查失败", details={"result": info.integrity})

        metadata = info.to_dict() | {"source": source.name}
        target.with_suffix(".json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log_event(
            self._logger,
            logging.INFO,
            "backup_created",
            f"backup_created {target.name}",
            component="backup",
        )
        self._prune_sync()
        return info

    def _verify_sync(self, path: Path) -> BackupInfo:
        if not path.is_file():
            raise BackupError("备份文件不存在", details={"file": path.name})
        info = self._describe(path, reason=self._read_metadata(path).get("reason", "unknown"))
        if info.integrity.lower() != "ok":
            raise BackupError(
                "备份完整性检查失败，已拒绝恢复",
                details={"file": path.name, "result": info.integrity},
            )
        return info

    def _describe(self, path: Path, *, reason: str) -> BackupInfo:
        try:
            with closing(
                sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            ) as connection:
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
                revision_row = None
                try:
                    revision_row = connection.execute(
                        "SELECT version_num FROM alembic_version"
                    ).fetchone()
                except sqlite3.Error:
                    revision_row = None
        except sqlite3.Error as exc:
            raise BackupError("备份文件无法读取", details={"reason": summarize_error(exc)}) from exc

        metadata = self._read_metadata(path)
        return BackupInfo(
            path=path,
            created_at=metadata.get("created_at", _file_time(path)),
            reason=reason,
            size_bytes=path.stat().st_size,
            sha256=_sha256(path),
            revision=revision_row[0] if revision_row else None,
            integrity=integrity,
        )

    def _list_sync(self) -> list[BackupInfo]:
        directory = self.directory
        if not directory.is_dir():
            return []
        infos: list[BackupInfo] = []
        for path in sorted(directory.glob("*.db"), reverse=True):
            try:
                infos.append(self._verify_sync(path))
            except BackupError:
                continue
        return infos

    def _prune_sync(self) -> None:
        directory = self.directory
        if not directory.is_dir():
            return
        backups = sorted(directory.glob("*.db"), reverse=True)
        for stale in backups[self._settings.backup_retention :]:
            stale.unlink(missing_ok=True)
            stale.with_suffix(".json").unlink(missing_ok=True)
            log_event(
                self._logger,
                logging.INFO,
                "backup_pruned",
                f"backup_pruned {stale.name}",
                component="backup",
            )

    def _protect_current(self, source: Path) -> Path | None:
        if not source.exists():
            return None
        target_dir = self.directory / RESTORE_SUBDIR
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime(_STAMP_FORMAT)
        target = target_dir / f"{source.stem}-pre-restore-{stamp}.db"
        shutil.copy2(source, target)
        log_event(
            self._logger,
            logging.INFO,
            "restore_protection_created",
            f"restore_protection_created {target.name}",
            component="backup",
        )
        return target

    def _replace_database(self, backup: Path, target: Path) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{target}{suffix}").unlink(missing_ok=True)
        shutil.copy2(backup, target)

    def _verify_restored(self, source: Path, info: BackupInfo) -> None:
        restored = self._describe(source, reason="restored")
        if restored.integrity.lower() != "ok":
            raise BackupError(
                "恢复后数据库完整性检查失败",
                details={"result": restored.integrity},
            )
        if info.revision is not None and restored.revision != info.revision:
            raise BackupError(
                "恢复后数据库版本与备份不一致",
                details={
                    "backup_revision": info.revision,
                    "restored_revision": restored.revision or "",
                },
            )

    async def _reopen_database(self, *, best_effort: bool = False) -> None:
        if self._database is None or self._database.is_initialized:
            return
        try:
            await self._database.initialize()
        except Exception:
            if not best_effort:
                raise
            log_event(
                self._logger,
                logging.ERROR,
                "restore_reopen_failed",
                "restore_reopen_failed",
                component="backup",
                error_code="BACKUP_FAILED",
            )

    async def _restart_dispatcher(self, was_stopped: bool) -> None:
        if not was_stopped or self._dispatcher is None:
            return
        try:
            await self._dispatcher.start()
        except Exception:  # noqa: BLE001 - 重启失败保留服务可用，记录错误
            log_event(
                self._logger,
                logging.ERROR,
                "restore_dispatcher_restart_failed",
                "restore_dispatcher_restart_failed",
                component="backup",
                error_code="BACKUP_FAILED",
            )

    def _read_metadata(self, path: Path) -> dict[str, str]:
        metadata_path = path.with_suffix(".json")
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            return {}
        return {key: str(value) for key, value in data.items() if value is not None}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
