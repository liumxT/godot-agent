"""E2 §11.4 安全测试（12 项）。

每项测试对应一条安全要求；通过 HTTP 或纯函数验证攻击面。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ConfigError
from core.logging import capture_logs
from core.security.policy import evaluate
from core.security.principal import ROLE_CLIENT, Principal
from infrastructure.security.bootstrap import BootstrapTokenStore


@asynccontextmanager
async def _running(tmp_path: Path, **overrides):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'security.db').as_posix()}",
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


async def _register(app, client) -> dict[str, str]:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    response = await client.post(
        "/api/v1/clients",
        json={"client_type": "godot_editor", "client_name": "Security Client"},
        headers={"X-Bootstrap-Token": bootstrap},
    )
    return response.json()


async def _challenge(client, client_id: str) -> dict[str, str]:
    return (await client.post("/api/v1/auth/challenge", json={"client_id": client_id})).json()


def _proof(client_secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        client_secret.encode(),
        f"{challenge_id}.{challenge}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _access_token(app, client) -> tuple[dict[str, str], str]:
    registered = await _register(app, client)
    issue = await _challenge(client, registered["client_id"])
    verified = await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": issue["challenge_id"],
            "client_id": registered["client_id"],
            "proof": _proof(registered["client_secret"], issue["challenge_id"], issue["challenge"]),
        },
    )
    return registered, verified.json()["access_token"]


async def _session(app, client, *, client_type: str = "godot_editor") -> dict[str, str]:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": client_type, "client_name": f"Client {client_type}"},
        headers={"X-Bootstrap-Token": bootstrap},
    )
    body = registered.json()
    issue = await _challenge(client, body["client_id"])
    verified = await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": issue["challenge_id"],
            "client_id": body["client_id"],
            "proof": _proof(body["client_secret"], issue["challenge_id"], issue["challenge"]),
        },
    )
    issued = await client.post("/api/v1/sessions", headers=_bearer(verified.json()["access_token"]))
    session = issued.json()
    return {
        "client_id": body["client_id"],
        "client_secret": body["client_secret"],
        "session_token": session["session_token"],
        "session_id": session["session"]["session_id"],
    }


async def test_unauthenticated_requests_are_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (_app, client):
        for path in (
            "/api/v1/system/status",
            "/api/v1/sessions/current",
            "/api/v1/projects/access/current?project_id=proj_alpha",
            "/api/v1/diagnostics/summary",
        ):
            response = await client.get(path)
            assert response.status_code == 401, path
            assert response.json()["error"]["code"] == "AUTH_REQUIRED", path


async def test_expired_token_is_rejected(tmp_path) -> None:
    async with _running(tmp_path, access_token_ttl_seconds=0) as (app, client):
        _, token = await _access_token(app, client)

        response = await client.get("/api/v1/system/status", headers=_bearer(token))

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_revoked_token_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        _, token = await _access_token(app, client)
        rotated = await client.post("/api/v1/auth/refresh", headers=_bearer(token))
        assert rotated.status_code == 200

        replay = await client.get("/api/v1/system/status", headers=_bearer(token))

        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "TOKEN_REVOKED"


async def test_session_cannot_cross_client(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        owner = await _session(app, client)
        intruder = await _session(app, client)
        granted = await client.post(
            "/api/v1/projects/access",
            json={
                "project_id": "proj_alpha",
                "session_id": owner["session_id"],
                "access_level": "owner",
            },
            headers=_bearer(admin["session_token"]),
        )
        assert granted.status_code == 201

        response = await client.get(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_alpha"},
            headers=_bearer(intruder["session_token"]),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PROJECT_ACCESS_DENIED"


async def test_project_id_tampering_is_denied(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        owner = await _session(app, client)
        await client.post(
            "/api/v1/projects/access",
            json={
                "project_id": "proj_alpha",
                "session_id": owner["session_id"],
                "access_level": "owner",
            },
            headers=_bearer(admin["session_token"]),
        )

        response = await client.get(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_beta"},
            headers=_bearer(owner["session_token"]),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PROJECT_ACCESS_DENIED"


def test_unknown_action_is_denied_by_default() -> None:
    decision = evaluate(
        Principal(client_id="cli_1", client_type="godot_editor", role=ROLE_CLIENT),
        "project.unknown.action",
    )

    assert decision.allowed is False
    assert decision.reason == "capability_missing"


async def test_untrusted_client_cannot_self_grant(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        viewer = await _session(app, client)
        other = await _session(app, client)
        await client.post(
            "/api/v1/projects/access",
            json={
                "project_id": "proj_alpha",
                "session_id": viewer["session_id"],
                "access_level": "viewer",
            },
            headers=_bearer(admin["session_token"]),
        )

        denied = await client.post(
            "/api/v1/projects/access",
            json={
                "project_id": "proj_alpha",
                "session_id": other["session_id"],
                "access_level": "owner",
            },
            headers=_bearer(viewer["session_token"]),
        )

        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_challenge_cannot_be_reused(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        registered = await _register(app, client)
        issue = await _challenge(client, registered["client_id"])
        payload = {
            "challenge_id": issue["challenge_id"],
            "client_id": registered["client_id"],
            "proof": _proof(registered["client_secret"], issue["challenge_id"], issue["challenge"]),
        }

        first = await client.post("/api/v1/auth/verify", json=payload)
        second = await client.post("/api/v1/auth/verify", json=payload)

        assert first.status_code == 200
        assert second.status_code == 401
        assert second.json()["error"]["code"] == "AUTH_CHALLENGE_INVALID"


async def test_tokens_never_enter_logs(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        with capture_logs() as records:
            session = await _session(app, client)
            _, access_token = await _access_token(app, client)

        text = str(records)
        assert session["session_token"] not in text
        assert session["client_secret"] not in text
        assert access_token not in text


async def test_oversized_request_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
        payload = b"x" * (2 * 1024 * 1024)

        response = await client.post(
            "/api/v1/clients",
            content=payload,
            headers={
                "X-Bootstrap-Token": bootstrap,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_api_binds_loopback_by_default() -> None:
    settings = load_settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")

    assert settings.host in {"127.0.0.1", "::1", "localhost"}
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", host="0.0.0.0")


async def test_diagnostics_does_not_leak_sensitive_data(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        session = await _session(app, client)

        response = await client.get(
            "/api/v1/diagnostics/summary",
            headers=_bearer(session["session_token"]),
        )

        assert response.status_code == 200
        text = response.text
        assert session["client_secret"] not in text
        assert session["session_token"] not in text
        assert "database_url" not in text
