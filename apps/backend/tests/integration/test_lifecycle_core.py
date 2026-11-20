"""完整生命周期集成测试（E1-T01-IT-001）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from bootstrap.application import create_app
from config.service import ConfigService
from config.settings import load_settings
from core.lifecycle.states import LifecycleState

DB_URL = "sqlite+aiosqlite:///:memory:"


def test_full_lifecycle_registers_services_and_stops() -> None:
    settings = load_settings(_env_file=None, database_url=DB_URL, environment="test")
    app = create_app(settings)

    with TestClient(app) as client:
        assert app.state.lifecycle.state is LifecycleState.RUNNING
        assert "config" in app.state.services.names()

        config = app.state.services.get("config", ConfigService)
        assert config.current.database_url == DB_URL
        assert client.get("/health").status_code == 200

        hot_reloaded = config.update(log_level="DEBUG")
        assert hot_reloaded.log_level.value == "DEBUG"

    assert app.state.lifecycle.state is LifecycleState.STOPPED
    assert app.state.lifecycle.manager.started_at is not None
