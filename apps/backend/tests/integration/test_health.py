"""健康检查集成测试（E0-IT-001 / E1-T12-IT-001）。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from bootstrap.application import create_app
from config.settings import load_settings
from core.lifecycle.states import LifecycleState

DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture()
def app():
    settings = load_settings(_env_file=None, database_url=DB_URL, environment="test")
    return create_app(settings)


@pytest.fixture()
def file_app(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'health.db').as_posix()}",
        environment="test",
    )
    return create_app(settings)


async def test_health_reports_status_and_checks_before_startup(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "STARTING"
    assert body["service"] == "godot-ai-backend"
    assert body["environment"] == "test"
    assert {check["name"] for check in body["checks"]} >= {"application", "database"}
    assert response.headers["X-Request-ID"].startswith("req-")


def test_live_ready_and_aggregation_after_startup(file_app) -> None:
    with TestClient(file_app) as client:
        assert client.get("/health/live").json() == {"status": "alive"}

        health = client.get("/health").json()
        assert health["status"] == "HEALTHY"
        checks = {check["name"]: check["status"] for check in health["checks"]}
        assert checks["database"] == "HEALTHY"
        assert checks["migration"] == "HEALTHY"
        assert checks["events"] == "HEALTHY"
        assert checks["backup"] == "HEALTHY"

        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["ready"] is True

    assert file_app.state.lifecycle.state is LifecycleState.STOPPED
    assert _ready_status_after_stop(file_app) == 503


def _ready_status_after_stop(app) -> int:
    import asyncio

    async def _request() -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return (await client.get("/health/ready")).status_code

    return asyncio.run(_request())


async def test_error_response_shape(app) -> None:
    from core.errors import AppError
    from shared.contracts import validate_instance

    @app.get("/boom")
    async def _boom() -> None:
        raise AppError(
            "测试错误",
            code="INVALID_REQUEST",
            status_code=418,
            details={"k": "v"},
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom")

    assert response.status_code == 418
    body = response.json()["error"]
    assert body["code"] == "INVALID_REQUEST"
    assert body["message"] == "测试错误"
    assert body["details"] == {"k": "v"}
    assert body["retryable"] is False
    assert body["correlation_id"] == response.headers["X-Request-ID"]
    assert validate_instance(body, "errors/error.schema.json") == []
