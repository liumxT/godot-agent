"""诊断接口集成测试（E1-T13-IT-001…002）。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from bootstrap.application import create_app
from config.settings import load_settings
from core.diagnostics import clear_recent_errors, record_recent_error
from infrastructure.database.service import DatabaseService


def _settings(tmp_path: Path, *, environment: str = "test"):
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'diag.db').as_posix()}",
        environment=environment,
    )


@pytest.fixture()
def client(tmp_path: Path):
    clear_recent_errors()
    app = create_app(_settings(tmp_path))
    with TestClient(app) as test_client:
        yield test_client
    clear_recent_errors()


def test_summary_includes_runtime_and_migration(client) -> None:
    body = client.get("/diagnostics/summary").json()

    assert body["application"]["state"] == "RUNNING"
    assert body["application"]["uptime_seconds"] is not None
    assert body["database"] == {"status": "ready", "revision": "000019"}
    assert body["migration"]["at_head"] is True
    assert body["logging"]["log_file"].endswith("backend.log")
    assert body["backup"]["available"] is True


def test_summary_reports_outbox_backlog(client, tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "diag.db")) as connection:
        connection.execute(
            "INSERT INTO event_outbox "
            "(event_id, event_type, payload, status, retry_count) "
            "VALUES ('evt-diag-1', 'task.created', '{}', 'failed', 99)"
        )
        connection.commit()

    body = client.get("/diagnostics/summary").json()

    assert body["events"]["outbox"].get("failed") == 1
    assert body["events"]["backlog"] == 1


def test_summary_recent_errors_are_redacted(client) -> None:
    record_recent_error(
        component="config",
        event="config_invalid",
        error_code="CONFIG_ERROR",
        message="api_key=sk-live-1234567890",
    )

    body = client.get("/diagnostics/summary").json()

    assert body["recent_errors"][0]["error_code"] == "CONFIG_ERROR"
    assert "sk-live-1234567890" not in body["recent_errors"][0]["message"]


def test_summary_reports_database_outage(client, monkeypatch) -> None:
    async def _down(_self) -> bool:
        return False

    monkeypatch.setattr(DatabaseService, "ping", _down)

    body = client.get("/diagnostics/summary").json()

    assert body["database"]["status"] == "unavailable"
    assert body["events"]["outbox"] == {}


async def test_production_requires_diagnostics_token(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, environment="production"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/diagnostics/summary")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
