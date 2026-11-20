"""事件服务启动接线与后台派发（E1-T09-IT-001 / E1-T10）。"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from bootstrap.application import create_app
from config.settings import Settings, load_settings
from core.events.registry import EventRegistry
from infrastructure.events.dispatcher import EventDispatcher


def _settings(tmp_path: Path) -> Settings:
    database = tmp_path / "startup.db"
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{database.as_posix()}",
        environment="test",
    )


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "startup.db"


def _insert_outbox(tmp_path: Path, event_id: str, event_type: str) -> None:
    with sqlite3.connect(_db_path(tmp_path)) as connection:
        connection.execute(
            "INSERT INTO event_outbox (event_id, event_type, event_version, payload, status) "
            "VALUES (?, ?, 1, '{}', 'pending')",
            (event_id, event_type),
        )


def _outbox_status(tmp_path: Path, event_id: str) -> str | None:
    with sqlite3.connect(_db_path(tmp_path)) as connection:
        row = connection.execute(
            "SELECT status FROM event_outbox WHERE event_id = ?", (event_id,)
        ).fetchone()
    return row[0] if row else None


def test_event_services_are_registered_and_dispatch_in_background(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    received: list = []

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        names = app.state.services.names()
        assert {"event_registry", "event_bus", "event_dispatcher"} <= set(names)

        registry = app.state.services.get("event_registry", EventRegistry)
        registry.register("task.created", received.append, consumer_id="startup-consumer")
        dispatcher = app.state.services.get("event_dispatcher", EventDispatcher)
        assert dispatcher.running is True

        _insert_outbox(tmp_path, "evt-background-1", "task.created")

        deadline = time.time() + 5
        while time.time() < deadline:
            if _outbox_status(tmp_path, "evt-background-1") == "published":
                break
            time.sleep(0.05)

        assert _outbox_status(tmp_path, "evt-background-1") == "published"
        assert len(received) == 1

    assert dispatcher.running is False
