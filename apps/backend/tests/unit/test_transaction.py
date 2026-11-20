"""事务管理测试（E1-T06-UT-001…004 / IT-001）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text

from config.settings import load_settings
from core.errors import DatabaseError, OperationTimeout
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction

CREATE_TABLE = "CREATE TABLE tx_items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"


@pytest.fixture()
async def database(tmp_path: Path) -> AsyncIterator[DatabaseService]:
    service = DatabaseService(
        load_settings(
            _env_file=None,
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'tx.db').as_posix()}",
            environment="test",
        )
    )
    await service.initialize()
    async with service.engine.begin() as connection:
        await connection.exec_driver_sql(CREATE_TABLE)
    yield service
    await service.dispose()


async def _insert(session, name: str) -> None:
    await session.execute(text("INSERT INTO tx_items (name) VALUES (:name)"), {"name": name})


async def _names(database: DatabaseService) -> list[str]:
    async with database.session() as session:
        rows = (await session.execute(text("SELECT name FROM tx_items ORDER BY id"))).scalars()
        return list(rows)


async def test_commit_persists_changes(database: DatabaseService) -> None:
    async with database.session() as session, transaction(session):
        await _insert(session, "committed")

    assert await _names(database) == ["committed"]


async def test_exception_rolls_back(database: DatabaseService) -> None:
    async with database.session() as session:
        with pytest.raises(RuntimeError):
            async with transaction(session):
                await _insert(session, "rolled-back")
                raise RuntimeError("boom")

    assert await _names(database) == []


async def test_timeout_rolls_back_and_invalidates_session(database: DatabaseService) -> None:
    async with database.session() as session:
        with pytest.raises(OperationTimeout) as exc_info:
            async with transaction(session, timeout=0.05):
                await _insert(session, "timeout")
                await asyncio.sleep(0.2)

        assert exc_info.value.code == "TRANSACTION_TIMEOUT"
        assert exc_info.value.retryable is True
        with pytest.raises(DatabaseError):
            async with transaction(session):
                pass

    assert await _names(database) == []


async def test_nested_transaction_joins_outer(database: DatabaseService) -> None:
    async with database.session() as session:
        with pytest.raises(RuntimeError):
            async with transaction(session):
                await _insert(session, "outer")
                async with transaction(session):
                    await _insert(session, "inner")
                raise RuntimeError("rollback all")

    assert await _names(database) == []


async def test_nested_scope_does_not_commit_early(database: DatabaseService) -> None:
    async with database.session() as session, transaction(session):
        await _insert(session, "outer")
        async with transaction(session):
            await _insert(session, "inner")

        # 内层退出后尚未提交，其他连接不可见
        assert await _names(database) == []

    assert sorted(await _names(database)) == ["inner", "outer"]


async def test_implicit_transaction_is_owned_by_scope(database: DatabaseService) -> None:
    async with database.session() as session:
        await session.execute(text("SELECT 1"))
        assert session.in_transaction() is True

        async with transaction(session):
            await _insert(session, "autobegin")

        assert session.in_transaction() is False

    assert await _names(database) == ["autobegin"]


async def test_concurrent_transactions_both_commit(database: DatabaseService) -> None:
    async def _write(name: str) -> None:
        async with database.session() as session, transaction(session, timeout=5):
            await _insert(session, name)

    await asyncio.gather(_write("a"), _write("b"))

    assert sorted(await _names(database)) == ["a", "b"]
