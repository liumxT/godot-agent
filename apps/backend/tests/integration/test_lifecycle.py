"""生命周期启动/关闭集成测试（E0-UT-001 / E0-IT-001）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from bootstrap.application import create_app
from config.settings import load_settings

DB_URL = "sqlite+aiosqlite:///:memory:"


def test_lifespan_starts_and_stops() -> None:
    settings = load_settings(_env_file=None, database_url=DB_URL, environment="test")
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert app.state.settings.environment.value == "test"
