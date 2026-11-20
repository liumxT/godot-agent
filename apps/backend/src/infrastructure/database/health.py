"""数据库健康检查（E1-T03 / 供 E1-T12 复用）。

只执行只读探测，不做任何写入：

- ``PRAGMA integrity_check``：文件级完整性；
- ``alembic_version``：当前迁移版本；
- ``SELECT 1``：连接可用性（由 ``DatabaseService.ping`` 提供）。
"""

from __future__ import annotations

from dataclasses import dataclass

from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from infrastructure.database.errors import summarize_error
from infrastructure.database.service import DatabaseService


@dataclass(frozen=True)
class DatabaseHealth:
    available: bool
    revision: str | None
    integrity: str
    error: str | None = None


async def integrity_check(engine: AsyncEngine) -> str:
    """返回 ``ok`` 或完整性错误摘要。"""

    async with engine.connect() as connection:
        rows = (await connection.exec_driver_sql("PRAGMA integrity_check")).scalars().all()
    if [str(row).lower() for row in rows] == ["ok"]:
        return "ok"
    return "; ".join(str(row) for row in rows)


async def schema_revision(engine: AsyncEngine) -> str | None:
    """读取 Alembic 当前版本；表不存在时返回 ``None``。"""

    def _read(sync_connection) -> str | None:
        return MigrationContext.configure(sync_connection).get_current_revision()

    async with engine.connect() as connection:
        return await connection.run_sync(_read)


async def check(service: DatabaseService) -> DatabaseHealth:
    """聚合健康状态；任何失败都转为不可用，不向外抛异常。"""

    if not await service.ping():
        return DatabaseHealth(
            available=False,
            revision=None,
            integrity="unknown",
            error="数据库连接不可用",
        )
    try:
        integrity = await integrity_check(service.engine)
        revision = await schema_revision(service.engine)
    except SQLAlchemyError as exc:
        return DatabaseHealth(
            available=False,
            revision=None,
            integrity="unknown",
            error=summarize_error(exc),
        )
    return DatabaseHealth(available=True, revision=revision, integrity=integrity)
