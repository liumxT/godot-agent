"""认证、授权、限流与请求保护集成测试（E2-T08 / T09 / T10）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager

import httpx

from bootstrap.application import create_app
from config.settings import load_settings
from infrastructure.security.bootstrap import BootstrapTokenStore
from shared.contracts import validate_instance

SYSTEM_SCHEMA = "api/system.schema.json"
ERROR_SCHEMA = "errors/error.schema.json"


@asynccontextmanager
async def _running(tmp_path, **overrides):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'authz.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
        **overrides,
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _credentials(
    app, client, *, client_type: str = "godot_editor", session: bool = False
) -> dict[str, str]:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": client_type, "client_name": f"Client {client_type}"},
        headers={"X-Bootstrap-Token": bootstrap},
    )
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
    credentials = {
        "client_id": body["client_id"],
        "access_token": verified.json()["access_token"],
        "session_token": "",
        "session_id": "",
    }
    if session:
        issued = await client.post("/api/v1/sessions", headers=_bearer(credentials["access_token"]))
        payload = issued.json()
        credentials["session_token"] = payload["session_token"]
        credentials["session_id"] = payload["session"]["session_id"]
    return credentials


async def test_authenticated_system_status_returns_contract(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        credentials = await _credentials(app, client)

        response = await client.get(
            "/api/v1/system/status", headers=_bearer(credentials["access_token"])
        )

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "RUNNING"
        assert body["database_status"] == "ready"
        assert validate_instance(body, SYSTEM_SCHEMA) == []


async def test_access_token_is_rejected_by_session_endpoint(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        credentials = await _credentials(app, client)

        response = await client.get(
            "/api/v1/sessions/current", headers=_bearer(credentials["access_token"])
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "SESSION_INVALID"


async def test_invalid_token_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (_app, client):
        response = await client.get("/api/v1/system/status", headers=_bearer("gda_" + "A" * 43))

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_INVALID"
        assert validate_instance(response.json()["error"], ERROR_SCHEMA) == []


async def test_rate_limit_returns_retry_after(tmp_path) -> None:
    async with _running(tmp_path, rate_limit_default_per_minute=2) as (app, client):
        credentials = await _credentials(app, client, session=True)

        first = await client.get(
            "/api/v1/sessions/current", headers=_bearer(credentials["session_token"])
        )
        second = await client.get(
            "/api/v1/sessions/current", headers=_bearer(credentials["session_token"])
        )
        limited = await client.get(
            "/api/v1/sessions/current", headers=_bearer(credentials["session_token"])
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "RATE_LIMITED"
        assert int(limited.headers["Retry-After"]) >= 1
        assert validate_instance(limited.json()["error"], ERROR_SCHEMA) == []


async def test_oversized_body_is_rejected(tmp_path) -> None:
    async with _running(tmp_path, request_max_body_bytes=64) as (_app, client):
        response = await client.post(
            "/api/v1/projects/access",
            json={
                "project_id": "p" * 200,
                "session_id": "ses_ab2cd3ef4g5h",
                "access_level": "owner",
            },
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
        assert validate_instance(response.json()["error"], ERROR_SCHEMA) == []


async def test_viewer_cannot_grant_project_access(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _credentials(app, client, client_type="admin", session=True)
        viewer = await _credentials(app, client, session=True)
        other = await _credentials(app, client, session=True)
        granted = await client.post(
            "/api/v1/projects/access",
            json={
                "project_id": "proj_alpha",
                "session_id": viewer["session_id"],
                "access_level": "viewer",
            },
            headers=_bearer(admin["session_token"]),
        )
        assert granted.status_code == 201

        response = await client.post(
            "/api/v1/projects/access",
            json={
                "project_id": "proj_alpha",
                "session_id": other["session_id"],
                "access_level": "owner",
            },
            headers=_bearer(viewer["session_token"]),
        )

        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "PERMISSION_DENIED"
        assert error["details"]["reason"] == "role_denied"
