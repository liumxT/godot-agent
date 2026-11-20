#!/usr/bin/env python3
"""E1 Core 性能基线（E1-T14）。

记录冷启动、数据库初始化、Migration、简单读写、事务、事件延迟、日志开销、
备份与恢复耗时，输出 ``artifacts/perf-e1.json`` 并打印 Markdown 表格。

用法（在 Backend 虚拟环境中运行）::

    cd apps/backend
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\testing\\perf_e1.py

结果用于建立基线，不设置硬性阈值；测试环境、数据量与样本数一并记录。
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import io
import json
import logging
import math
import os
import platform
import sqlite3
import statistics
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
OUTPUT = ROOT / "artifacts" / "perf-e1.json"
sys.path.insert(0, str(BACKEND / "src"))

from sqlalchemy import String, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bootstrap.lifecycle import Lifecycle
from config.settings import Settings, load_settings
from core.events import Event, EventRegistry
from core.logging import JsonFormatter, log_event
from infrastructure.database.backup import BackupService
from infrastructure.database.engine import sqlite_database_path
from infrastructure.database.manager import MigrationService
from infrastructure.database.repository import BaseRepository
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.events.dispatcher import EventDispatcher
from infrastructure.events.outbox import OutboxRepository

SAMPLES = 20
LOG_ITERATIONS = 1000
DATASET_ROWS = 200
PACKAGES = ("fastapi", "sqlalchemy", "alembic", "aiosqlite", "pydantic")


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "perf_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)


class ItemRepository(BaseRepository[Item]):
    model = Item


def build_settings(root: Path, name: str = "perf") -> Settings:
    directory = root / name
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(directory / 'perf.db').as_posix()}",
        environment="test",
        log_level="WARNING",
        data_dir=str(directory / "data"),
        log_dir=str(directory / "logs"),
        backup_retention=20,
    )


async def sample_ms_iter(action: Callable[[int], Awaitable[None]], count: int) -> list[float]:
    values: list[float] = []
    for index in range(count):
        started = time.perf_counter()
        await action(index)
        values.append((time.perf_counter() - started) * 1000)
    return values


def summarize(values: list[float], unit: str) -> dict[str, object]:
    ordered = sorted(values)
    return {
        "unit": unit,
        "samples": len(ordered),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 3),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


async def bench_cold_start(root: Path) -> list[float]:
    async def action(index: int) -> None:
        lifecycle = Lifecycle(build_settings(root, f"cold-{index}"))
        await lifecycle.manager.startup()
        await lifecycle.manager.shutdown()

    values: list[float] = []
    for index in range(SAMPLES):
        started = time.perf_counter()
        await action(index)
        values.append((time.perf_counter() - started) * 1000)
    return values


async def bench_database_init(root: Path) -> list[float]:
    async def action(index: int) -> None:
        database = DatabaseService(build_settings(root, f"init-{index}"))
        await database.initialize()
        await database.dispose()

    return await sample_ms_iter(action, SAMPLES)


async def bench_migration(root: Path) -> list[float]:
    async def action(index: int) -> None:
        settings = build_settings(root, f"migrate-{index}")
        database = DatabaseService(settings)
        await database.initialize()
        try:
            await MigrationService(settings, database=database).run()
        finally:
            await database.dispose()

    return await sample_ms_iter(action, SAMPLES)


async def bench_read_write(root: Path) -> tuple[list[float], list[float]]:
    settings = build_settings(root, "read-write")
    database = DatabaseService(settings)
    await database.initialize()
    await MigrationService(settings, database=database).run()
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with database.session() as session, transaction(session):
        repository = ItemRepository(session)
        for index in range(DATASET_ROWS):
            await repository.add(Item(name=f"seed-{index}"))

    writes: list[float] = []
    reads: list[float] = []
    try:
        for index in range(SAMPLES):
            started = time.perf_counter()
            async with database.session() as session, transaction(session):
                item = await ItemRepository(session).add(Item(name=f"perf-{index}"))
            writes.append((time.perf_counter() - started) * 1000)

            started = time.perf_counter()
            async with database.session() as session:
                await ItemRepository(session).get(item.id)
            reads.append((time.perf_counter() - started) * 1000)
    finally:
        await database.dispose()
    return writes, reads


async def bench_transaction(root: Path) -> list[float]:
    settings = build_settings(root, "transaction")
    database = DatabaseService(settings)
    await database.initialize()
    await MigrationService(settings, database=database).run()
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        values: list[float] = []
        for index in range(SAMPLES):
            started = time.perf_counter()
            async with database.session() as session, transaction(session):
                repository = ItemRepository(session)
                for row in range(20):
                    await repository.add(Item(name=f"tx-{index}-{row}"))
            values.append((time.perf_counter() - started) * 1000)
        return values
    finally:
        await database.dispose()


async def bench_events(root: Path) -> list[float]:
    settings = build_settings(root, "events")
    database = DatabaseService(settings)
    await database.initialize()
    await MigrationService(settings, database=database).run()
    registry = EventRegistry()
    registry.register("perf.event", lambda _event: None, consumer_id="perf-consumer")
    dispatcher = EventDispatcher(database, registry, poll_interval=3600, batch_size=10)
    await dispatcher.start()
    await dispatcher.stop()
    outbox = OutboxRepository()
    try:
        values: list[float] = []
        for index in range(SAMPLES):
            async with database.session() as session, transaction(session):
                await outbox.add(session, Event.create("perf.event", {"index": index}))
            started = time.perf_counter()
            await dispatcher.dispatch_once()
            values.append((time.perf_counter() - started) * 1000)
        return values
    finally:
        await dispatcher.stop()
        await database.dispose()


def bench_log() -> list[float]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("perf.logging")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    values: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        for index in range(LOG_ITERATIONS):
            log_event(
                logger,
                logging.INFO,
                "perf_log_write",
                f"perf log {index}",
                component="perf",
                request_id="req-perf",
            )
        values.append((time.perf_counter() - started) * 1_000_000 / LOG_ITERATIONS)
    return values


async def bench_backup_restore(root: Path) -> tuple[list[float], list[float], int]:
    settings = build_settings(root, "backup")
    database = DatabaseService(settings)
    await database.initialize()
    await MigrationService(settings, database=database).run()
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session, transaction(session):
        repository = ItemRepository(session)
        for index in range(DATASET_ROWS):
            await repository.add(Item(name=f"backup-{index}"))

    async with database.session() as session:
        rows = await session.scalar(select(func.count()).select_from(Item))
    database_path = sqlite_database_path(settings.database_url)
    assert database_path is not None
    size_bytes = database_path.stat().st_size
    service = BackupService(settings, database=database)
    backups: list[float] = []
    restores: list[float] = []
    try:
        for _ in range(5):
            started = time.perf_counter()
            info = await service.create(reason="perf")
            backups.append((time.perf_counter() - started) * 1000)

        for _ in range(5):
            started = time.perf_counter()
            await service.restore(info.path, expected_revision="000003")
            restores.append((time.perf_counter() - started) * 1000)
        assert rows == DATASET_ROWS
    finally:
        await database.dispose()
    return backups, restores, size_bytes


def environment() -> dict[str, object]:
    packages: dict[str, str] = {}
    for name in PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "unknown"
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "packages": packages,
    }


async def main() -> int:
    root = ROOT / "artifacts" / "perf-work"
    if root.exists():
        import shutil

        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    metrics: dict[str, dict[str, object]] = {}
    metrics["cold_start_ms"] = summarize(await bench_cold_start(root), "ms")
    metrics["database_init_ms"] = summarize(await bench_database_init(root), "ms")
    metrics["migration_ms"] = summarize(await bench_migration(root), "ms")

    writes, reads = await bench_read_write(root)
    metrics["write_ms"] = summarize(writes, "ms")
    metrics["read_ms"] = summarize(reads, "ms")
    metrics["transaction_20writes_ms"] = summarize(await bench_transaction(root), "ms")
    metrics["event_dispatch_ms"] = summarize(await bench_events(root), "ms")
    metrics["log_write_us"] = summarize(bench_log(), "us")

    backups, restores, size_bytes = await bench_backup_restore(root)
    metrics["backup_ms"] = summarize(backups, "ms")
    metrics["restore_ms"] = summarize(restores, "ms")

    report = {
        "phase": "E1",
        "task": "T14",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": environment(),
        "dataset": {
            "rows": DATASET_ROWS,
            "database_size_bytes": size_bytes,
            "event_batch": 1,
        },
        "method": {
            "samples": SAMPLES,
            "log_iterations_per_sample": LOG_ITERATIONS,
            "backup_restore_samples": 5,
            "percentile": 0.95,
        },
        "metrics": metrics,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"E1 performance baseline -> {OUTPUT}")
    print()
    print("| 指标 | 单位 | 中位数 | P95 | 样本 |")
    print("| --- | --- | --- | --- | --- |")
    for name, metric in metrics.items():
        print(
            f"| {name} | {metric['unit']} | {metric['median']} | "
            f"{metric['p95']} | {metric['samples']} |"
        )
    print()
    print(
        f"环境: {report['environment']['os']} / Python {report['environment']['python']} / "
        f"SQLite {report['environment']['sqlite']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
