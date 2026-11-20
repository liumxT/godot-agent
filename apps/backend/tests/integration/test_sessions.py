"""Session 生命周期测试（E2-T05-UT / IT）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import httpx

from bootstrap.application import create_app
from config.settings import load_settings
from infrastructure.security.bootstrap import BootstrapTokenStore
from shared.contracts import validate_instance

SESSION_SCHEMA = "api/session.schema.json"
ERROR_SCHEMA = "errors/error.schema.json"


@asynccontextmanager
async def _running(tmp_path, **overrides):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'sessions.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
        **overrides,
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


def _bootstrap(app) -> str:
    return app.state.services.get("bootstrap_token", BootstrapTokenStore).token


async def _credentials(app, client, *, client_type: str = "godot_editor") -> dict[str, str]:
    """注册客户端并完成挑战认证，返回 Access Token 与 client_id。"""

    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": client_type, "client_name": f"Editor {client_type}"},
        headers={"X-Bootstrap-Token": _bootstrap(app)},
    )
    assert registered.status_code == 201
    body = registered.json()

    challenge = (
        await client.post("/api/v1/auth/challenge", json={"client_id": body["client_id"]})
    ).json()
    digest = hmac.new(
        body["client_secret"].encode(),
        f"{challenge['challenge_id']}.{challenge['challenge']}".encode(),
        hashlib.sha256,
    ).digest()
    verified = await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "client_id": body["client_id"],
            "proof": base64.urlsafe_b64encode(digest).decode().rstrip("="),
        },
    )
    assert verified.status_code == 200
    return {"client_id": body["client_id"], "access_token": verified.json()["access_token"]}


async def _create_session(client, access_token: str) -> dict:
    response = await client.post(
        "/api/v1/sessions", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 201
    body = response.json()
    assert validate_instance(body, SESSION_SCHEMA) == []
    return body


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_create_session_binds_client_and_returns_contract(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        credentials = await _credentials(app, client)

        issued = await _create_session(client, credentials["access_token"])

        assert issued["token_type"] == "Bearer"
        assert issued["session_token"].startswith("gds_")
        assert issued["session"]["client_id"] == credentials["client_id"]
        assert issued["session"]["status"] == "ACTIVE"


async def test_get_current_session(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        credentials = await _credentials(app, client)
        issued = await _create_session(client, credentials["access_token"])

        response = await client.get(
            "/api/v1/sessions/current", headers=_bearer(issued["session_token"])
        )

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == issued["session"]["session_id"]
        assert body["client_id"] == credentials["client_id"]
        assert validate_instance(body, SESSION_SCHEMA) == []


async def test_expired_session_is_rejected(tmp_path) -> None:
    async with _running(tmp_path, session_ttl_seconds=0) as (app, client):
        credentials = await _credentials(app, client)
        issued = await _create_session(client, credentials["access_token"])

        response = await client.get(
            "/api/v1/sessions/current", headers=_bearer(issued["session_token"])
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "SESSION_EXPIRED"
        assert validate_instance(response.json()["error"], ERROR_SCHEMA) == []


async def test_revoked_session_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        credentials = await _credentials(app, client)
        issued = await _create_session(client, credentials["access_token"])

        revoked = await client.delete(
            "/api/v1/sessions/current", headers=_bearer(issued["session_token"])
        )
        replay = await client.get(
            "/api/v1/sessions/current", headers=_bearer(issued["session_token"])
        )

        assert revoked.status_code == 200
        assert revoked.json()["status"] == "REVOKED"
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "SESSION_REVOKED"


async def test_sessions_are_client_scoped(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        first = await _credentials(app, client)
        second = await _credentials(app, client)
        issued_first = await _create_session(client, first["access_token"])
        issued_second = await _create_session(client, second["access_token"])

        current_first = (
            await client.get(
                "/api/v1/sessions/current", headers=_bearer(issued_first["session_token"])
            )
        ).json()
        current_second = (
            await client.get(
                "/api/v1/sessions/current", headers=_bearer(issued_second["session_token"])
            )
        ).json()

        assert current_first["client_id"] == first["client_id"]
        assert current_second["client_id"] == second["client_id"]
        assert current_first["session_id"] != current_second["session_id"]


async def test_session_token_cannot_create_session(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        credentials = await _credentials(app, client)
        issued = await _create_session(client, credentials["access_token"])

        response = await client.post("/api/v1/sessions", headers=_bearer(issued["session_token"]))

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_INVALID"


async def test_missing_or_invalid_session_token(tmp_path) -> None:
    async with _running(tmp_path) as (_, client):
        missing = await client.get("/api/v1/sessions/current")
        invalid = await client.get("/api/v1/sessions/current", headers=_bearer("gds_" + "A" * 43))

        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "AUTH_REQUIRED"
        assert invalid.status_code == 401
        assert invalid.json()["error"]["code"] == "SESSION_INVALID"


async def test_full_session_lifecycle(tmp_path) -> None:
    async with _running(tmp_path, session_ttl_seconds=600, session_max_ttl_seconds=600) as (
        app,
        client,
    ):
        credentials = await _credentials(app, client)
        issued = await _create_session(client, credentials["access_token"])

        current = (
            await client.get("/api/v1/sessions/current", headers=_bearer(issued["session_token"]))
        ).json()
        renewed = await client.post(
            "/api/v1/sessions/current/renew", headers=_bearer(issued["session_token"])
        )
        assert renewed.status_code == 200
        assert validate_instance(renewed.json(), SESSION_SCHEMA) == []

        created_at = datetime.fromisoformat(current["created_at"])
        renewed_expiry = datetime.fromisoformat(renewed.json()["expires_at"])
        assert renewed_expiry <= created_at + timedelta(seconds=600)

        revoked = await client.delete(
            "/api/v1/sessions/current", headers=_bearer(issued["session_token"])
        )
        expired_after = await client.post(
            "/api/v1/sessions/current/renew", headers=_bearer(issued["session_token"])
        )

        assert revoked.status_code == 200
        assert expired_after.status_code == 401
        assert expired_after.json()["error"]["code"] == "SESSION_REVOKED"
