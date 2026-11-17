"""健康检查集成测试（E0-IT-001）。"""

from __future__ import annotations

import httpx
import pytest

from bootstrap.application import create_app
from config.settings import load_settings

DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture()
def app():
    settings = load_settings(_env_file=None, database_url=DB_URL, environment="test")
    return create_app(settings)


async def test_health_returns_ok(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "godot-ai-backend"
    assert body["environment"] == "test"
    assert response.headers["X-Request-ID"].startswith("req-")


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
