"""数据库服务（E1-T03）。

统一持有引擎与会话工厂，负责初始化、健康探测与关闭：

- 初始化顺序：建目录 → 引擎（PRAGMA）→ ``SELECT 1`` → ``PRAGMA quick_check``；
- 运行期异常统一翻译为 ``DatabaseError``；
- 启动阶段文件不可写/只读直接 ``StartupError``，不带病运行；
- ``dispose()`` 幂等，供关闭流程重复调用。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config.settings import Settings
from core.errors import DatabaseError, StartupError
from core.logging import get_logger, log_event
from infrastructure.database.engine import (
    create_engine,
    create_session_factory,
    ensure_database_parent,
    sqlite_database_path,
)
from infrastructure.database.errors import (
    is_readonly_error,
    summarize_error,
    translate_db_error,
)


class DatabaseService:
    """数据库连接生命周期与访问入口。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = get_logger("backend.database")
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._disposed = False

    @property
    def database_url(self) -> str:
        return self._settings.database_url

    @property
    def is_ephemeral(self) -> bool:
        """内存库不跨连接/重启持久化，后台任务应避免依赖其并发连接。"""

        return sqlite_database_path(self.database_url) is None

    @property
    def is_initialized(self) -> bool:
        return self._engine is not None and not self._disposed

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise StartupError("数据库尚未初始化")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise StartupError("数据库尚未初始化")
        return self._session_factory

    async def initialize(self) -> None:
        """建立引擎并验证可读写；重复调用无副作用。"""

        if self._engine is not None:
            return

        try:
            ensure_database_parent(self.database_url)
        except OSError as exc:
            raise StartupError(
                "数据库目录不可用",
                details={"database": _display_path(self), "reason": summarize_error(exc)},
            ) from exc

        engine = create_engine(self._settings)
        try:
            async with engine.connect() as connection:
                await connection.exec_driver_sql("SELECT 1")
                check = (await connection.exec_driver_sql("PRAGMA quick_check")).scalar()
                # 只读文件上的 SELECT/PRAGMA/BEGIN 仍会成功，必须在回滚事务中真正写一次
                # 才能发现只读。DDL 在 SQLite 中可回滚，探测表不会留下。
                await connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    await connection.exec_driver_sql("CREATE TABLE __e1_write_probe (id INTEGER)")
                finally:
                    await connection.exec_driver_sql("ROLLBACK")
        except OperationalError as exc:
            await engine.dispose()
            if is_readonly_error(exc):
                raise StartupError(
                    "数据库文件不可写",
                    details={"database": _display_path(self), "reason": summarize_error(exc)},
                ) from exc
            raise translate_db_error(exc) from exc
        except SQLAlchemyError as exc:
            await engine.dispose()
            raise translate_db_error(exc) from exc
        except BaseException:
            await engine.dispose()
            raise

        if str(check).lower() != "ok":
            await engine.dispose()
            raise DatabaseError(
                "数据库完整性检查失败",
                code="DATABASE_INTEGRITY_ERROR",
                retryable=False,
                details={"result": summarize_error(Exception(str(check)))},
            )

        self._engine = engine
        self._session_factory = create_session_factory(engine)
        self._disposed = False
        log_event(
            self._logger,
            logging.INFO,
            "database_ready",
            "database_ready",
            component="database",
            environment=self._settings.environment.value,
        )

    async def dispose(self) -> None:
        """释放连接池；幂等，关闭流程可重复调用。

        释放后清空引擎引用，使恢复流程可以重新 ``initialize()``。
        """

        if self._engine is None or self._disposed:
            return
        self._disposed = True
        await self._engine.dispose()
        self._engine = None
        self._session_factory = None
        log_event(self._logger, logging.INFO, "database_closed", component="database")

    async def ping(self) -> bool:
        """轻量可用性探测；异常不向外抛出，供健康检查使用。"""

        if self._engine is None or self._disposed:
            return False
        try:
            async with self._engine.connect() as connection:
                await connection.exec_driver_sql("SELECT 1")
        except SQLAlchemyError:
            return False
        return True

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """会话作用域：只负责打开/关闭，提交由事务边界负责。"""

        async with self.session_factory() as session:
            yield session


def _display_path(service: DatabaseService) -> str:
    path = sqlite_database_path(service.database_url)
    return str(path) if path is not None else ":memory:"
