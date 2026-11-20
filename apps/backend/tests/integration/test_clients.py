"""客户端注册、更新与注销测试（E2-T06-UT / IT）。"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import NotFoundError
from core.security.tokens import secret_name
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.client.service import ClientService
from shared.contracts import validate_instance

CLIENT_SCHEMA = "api/client.schema.json"
ERROR_SCHEMA = "errors/error.schema.json"


@asynccontextmanager
async def _running(tmp_path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'clients.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


@asynccontextmanager
async def _http(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture()
async def running(tmp_path):
    async with _running(tmp_path) as app, _http(app) as client:
        yield app, client


def _bootstrap(app) -> str:
    return app.state.services.get("bootstrap_token", BootstrapTokenStore).token


async def _register(app, client, *, client_id: str | None = None, **overrides):
    payload = {
        "client_type": "godot_editor",
        "client_name": "Godot Editor",
        "client_version": "0.1.0",
        "godot_version": "4.5.1",
        "platform": "windows",
    }
    payload.update(overrides)
    if client_id is not None:
        payload["client_id"] = client_id
    return await client.post(
        "/api/v1/clients",
        json=payload,
        headers={"X-Bootstrap-Token": _bootstrap(app)},
    )


async def test_register_returns_contract_payload(running) -> None:
    app, client = running

    response = await _register(app, client)

    assert response.status_code == 201
    body = response.json()
    assert validate_instance(body, CLIENT_SCHEMA) == []
    assert body["client_type"] == "godot_editor"
    assert body["status"] == "active"


async def test_register_requires_bootstrap_token(running) -> None:
    _, client = running
    payload = {"client_type": "tool", "client_name": "tool"}

    missing = await client.post("/api/v1/clients", json=payload)
    wrong = await client.post(
        "/api/v1/clients", json=payload, headers={"X-Bootstrap-Token": "not-the-token"}
    )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTH_REQUIRED"
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "AUTH_INVALID"
    assert validate_instance(wrong.json()["error"], ERROR_SCHEMA) == []


async def test_register_rejects_invalid_payload(running) -> None:
    app, client = running

    response = await _register(app, client, client_type="robot")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_duplicate_client_id_is_rejected(running) -> None:
    app, client = running
    client_id = "cli_ab2cd3ef4g5h"

    first = await _register(app, client, client_id=client_id)
    second = await _register(app, client, client_id=client_id)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CLIENT_EXISTS"


async def test_multiple_clients_get_distinct_ids(running) -> None:
    app, client = running

    first = (await _register(app, client, client_name="Editor A")).json()
    second = (await _register(app, client, client_name="Editor B")).json()

    assert first["client_id"] != second["client_id"]
    assert first["client_secret"] != second["client_secret"]


async def test_client_update_keeps_identity(running) -> None:
    app, client = running
    registered = (await _register(app, client)).json()
    service = app.state.services.get("client_service", ClientService)

    updated = await service.update(registered["client_id"], client_name="Renamed", platform="linux")

    assert updated.client_id == registered["client_id"]
    assert updated.client_name == "Renamed"
    assert updated.platform == "linux"


async def test_client_deactivation_revokes_secret_and_status(running) -> None:
    app, client = running
    registered = (await _register(app, client)).json()
    service = app.state.services.get("client_service", ClientService)
    secrets = app.state.services.get("secret_store")

    await service.deactivate(registered["client_id"])

    view = await service.get(registered["client_id"])
    assert view is not None
    assert view.status == "revoked"
    assert await service.is_active(registered["client_id"]) is False
    assert secrets.get(secret_name(registered["client_id"])) is None

    challenge = await client.post(
        "/api/v1/auth/challenge", json={"client_id": registered["client_id"]}
    )
    assert challenge.status_code == 401
    assert challenge.json()["error"]["code"] == "AUTH_INVALID"


async def test_update_unknown_client_raises_not_found(running) -> None:
    app, _ = running
    service = app.state.services.get("client_service", ClientService)

    with pytest.raises(NotFoundError):
        await service.update("cli_ab2cd3ef4g5h", client_name="ghost")
