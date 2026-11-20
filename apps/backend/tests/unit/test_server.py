"""API Server 监听与生命周期测试（E2-T01-UT-001…003）。"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import server
from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import StartupError
from core.lifecycle.states import LifecycleState

DB_URL = "sqlite+aiosqlite:///:memory:"


def _settings(**overrides: object):
    return load_settings(_env_file=None, database_url=DB_URL, environment="test", **overrides)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_run_starts_server_with_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        uvicorn, "run", lambda app, **kwargs: captured.update({"app": app, **kwargs})
    )

    server.run(_settings(port=port))

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == port
    assert captured["log_config"] is None
    assert captured["app"].state.settings.port == port


def test_run_accepts_prebuilt_app(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(port=_free_port())
    app = create_app(settings)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda application, **kwargs: captured.update({"app": application, **kwargs}),
    )

    server.run(settings, app=app)

    assert captured["app"] is app


def test_port_available_passes() -> None:
    server.ensure_port_available("127.0.0.1", _free_port())


def test_port_in_use_raises_startup_error() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = int(listener.getsockname()[1])

        with pytest.raises(StartupError) as exc_info:
            server.ensure_port_available("127.0.0.1", port)

    assert exc_info.value.code == "SERVER_PORT_IN_USE"
    assert exc_info.value.details == {"host": "127.0.0.1", "port": port}


def test_shutdown_stops_lifecycle(tmp_path: Path) -> None:
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'server.db').as_posix()}",
        environment="test",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        assert app.state.lifecycle.state is LifecycleState.RUNNING
        assert client.get("/health/live").status_code == 200

    assert app.state.lifecycle.state is LifecycleState.STOPPED
