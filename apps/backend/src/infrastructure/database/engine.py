"""SQLite 引擎与连接规范。

所有连接建立后统一执行 PRAGMA，避免不同调用点行为不一致。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from config.settings import Settings

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
)


def sqlite_database_path(database_url: str) -> Path | None:
    """从 URL 解析 SQLite 文件路径；内存库返回 None。"""

    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser()


def ensure_database_parent(database_url: str) -> None:
    """SQLite 不会自动创建目录，连接前先确保父目录存在。"""

    path = sqlite_database_path(database_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)


def create_engine(settings: Settings) -> AsyncEngine:
    ensure_database_parent(settings.database_url)
    engine = create_async_engine(settings.database_url, future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _apply_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for statement in PRAGMAS:
                cursor.execute(statement)
        finally:
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
