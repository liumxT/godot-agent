"""Repository 基础设施测试（E1-T05-UT-001…004 / IT-001）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import String, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config.settings import load_settings
from core.errors import DatabaseError
from infrastructure.database.repository import BaseRepository, Page
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction


class Base(DeclarativeBase):
    pass


class Probe(Base):
    """仅供测试使用的表模型，生产结构一律走 Migration。"""

    __tablename__ = "probe_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)


class ProbeRepository(BaseRepository[Probe]):
    model = Probe


@pytest.fixture()
async def database(tmp_path: Path) -> AsyncIterator[DatabaseService]:
    service = DatabaseService(
        load_settings(
            _env_file=None,
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'repository.db').as_posix()}",
            environment="test",
        )
    )
    await service.initialize()
    async with service.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield service
    await service.dispose()


async def _seed(database: DatabaseService, *names: str) -> None:
    async with database.session() as session, transaction(session):
        repository = ProbeRepository(session)
        for name in names:
            await repository.add(Probe(name=name))


async def test_get_and_paginate(database: DatabaseService) -> None:
    await _seed(database, "a", "b", "c")

    async with database.session() as session:
        repository = ProbeRepository(session)
        first = await repository.get(1)
        page = await repository.paginate(limit=2, offset=1)

    assert first is not None
    assert first.name == "a"
    assert isinstance(page, Page)
    assert [item.name for item in page.items] == ["b", "c"]
    assert page.total == 3
    assert page.limit == 2
    assert page.offset == 1
    assert page.has_more is False


async def test_paginate_supports_filters(database: DatabaseService) -> None:
    await _seed(database, "a", "b", "c")

    async with database.session() as session:
        page = await ProbeRepository(session).paginate(filters=(Probe.id > 1,))

    assert [item.name for item in page.items] == ["b", "c"]
    assert page.total == 2


async def test_pagination_bounds_are_validated(database: DatabaseService) -> None:
    async with database.session() as session:
        repository = ProbeRepository(session)
        with pytest.raises(ValueError):
            await repository.paginate(limit=0)
        with pytest.raises(ValueError):
            await repository.paginate(limit=201)
        with pytest.raises(ValueError):
            await repository.paginate(offset=-1)


async def test_add_and_delete(database: DatabaseService) -> None:
    async with database.session() as session, transaction(session):
        repository = ProbeRepository(session)
        entity = await repository.add(Probe(name="temp"))
        assert entity.id is not None
        await repository.delete(entity)

    async with database.session() as session:
        assert await ProbeRepository(session).paginate() == Page([], 0, 50, 0)


async def test_repository_joins_injected_transaction(database: DatabaseService) -> None:
    async with database.session() as session, transaction(session):
        await ProbeRepository(session).add(Probe(name="pending"))

        async with database.session() as observer:
            total = await observer.scalar(select(func.count()).select_from(Probe))
        assert total == 0

    async with database.session() as session:
        assert (await ProbeRepository(session).paginate()).total == 1


async def test_integrity_error_is_mapped(database: DatabaseService) -> None:
    await _seed(database, "duplicate")

    async with database.session() as session:
        repository = ProbeRepository(session)
        with pytest.raises(DatabaseError) as exc_info:
            await repository.add(Probe(name="duplicate"))

    assert exc_info.value.code == "DATABASE_INTEGRITY_ERROR"
    assert exc_info.value.retryable is False
