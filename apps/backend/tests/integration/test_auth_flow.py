"""挑战-响应认证与 Token 生命周期测试（E2-T03-UT / T04）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager

import httpx

from bootstrap.application import create_app
from config.settings import load_settings
from core.security.tokens import secret_name
from infrastructure.security.bootstrap import BootstrapTokenStore
from shared.contracts import validate_instance

AUTH_SCHEMA = "api/auth.schema.json"


@asynccontextmanager
async def _running(tmp_path, **overrides):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'auth.db').as_posix()}",
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


async def _register(app, client) -> dict[str, str]:
    response = await client.post(
        "/api/v1/clients",
        json={"client_type": "godot_editor", "client_name": "Editor"},
        headers={"X-Bootstrap-Token": _bootstrap(app)},
    )
    assert response.status_code == 201
    return response.json()


async def _challenge(client, client_id: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/challenge", json={"client_id": client_id})
    assert response.status_code == 200
    body = response.json()
    assert validate_instance(body, AUTH_SCHEMA) == []
    return body


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _verify(client, client_id: str, secret: str, issue: dict[str, str]):
    return await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": issue["challenge_id"],
            "client_id": client_id,
            "proof": _proof(secret, issue["challenge_id"], issue["challenge"]),
        },
    )


async def test_happy_path_issues_contract_token(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        registered = await _register(app, client)
        issue = await _challenge(client, registered["client_id"])

        response = await _verify(
            client, registered["client_id"], registered["client_secret"], issue
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "Bearer"
        assert body["access_token"].startswith("gda_")
        assert validate_instance(body, AUTH_SCHEMA) == []


async def test_proof_mismatch_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        registered = await _register(app, client)
        issue = await _challenge(client, registered["client_id"])

        response = await client.post(
            "/api/v1/auth/verify",
            json={
                "challenge_id": issue["challenge_id"],
                "client_id": registered["client_id"],
                "proof": "A" * 43,
            },
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_CHALLENGE_INVALID"


async def test_challenge_is_single_use(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        registered = await _register(app, client)
        issue = await _challenge(client, registered["client_id"])

        first = await _verify(client, registered["client_id"], registered["client_secret"], issue)
        replay = await _verify(client, registered["client_id"], registered["client_secret"], issue)

        assert first.status_code == 200
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "AUTH_CHALLENGE_INVALID"


async def test_unknown_client_cannot_get_challenge(tmp_path) -> None:
    async with _running(tmp_path) as (_, client):
        response = await client.post(
            "/api/v1/auth/challenge", json={"client_id": "cli_zzzzzzzzzzzz"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_INVALID"


async def test_revoked_credential_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        registered = await _register(app, client)
        issue = await _challenge(client, registered["client_id"])
        app.state.services.get("secret_store").delete(secret_name(registered["client_id"]))

        response = await _verify(
            client, registered["client_id"], registered["client_secret"], issue
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_INVALID"


async def test_refresh_rotates_access_token(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        registered = await _register(app, client)
        issue = await _challenge(client, registered["client_id"])
        original = (
            await _verify(client, registered["client_id"], registered["client_secret"], issue)
        ).json()

        refreshed = await client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {original['access_token']}"},
        )
        replay = await client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {original['access_token']}"},
        )

        assert refreshed.status_code == 200
        rotated = refreshed.json()
        assert validate_instance(rotated, AUTH_SCHEMA) == []
        assert rotated["access_token"] != original["access_token"]
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "TOKEN_REVOKED"


async def test_missing_and_invalid_bearer_are_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (_, client):
        missing = await client.post("/api/v1/auth/refresh")
        invalid = await client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": "Bearer gda_" + "A" * 43},
        )

        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "AUTH_REQUIRED"
        assert invalid.status_code == 401
        assert invalid.json()["error"]["code"] == "TOKEN_INVALID"


async def test_expired_challenge_is_rejected(tmp_path) -> None:
    async with _running(tmp_path, auth_challenge_ttl_seconds=0) as (app, client):
        registered = await _register(app, client)
        response = await client.post(
            "/api/v1/auth/challenge", json={"client_id": registered["client_id"]}
        )
        issue = response.json()

        verify = await _verify(client, registered["client_id"], registered["client_secret"], issue)

        assert verify.status_code == 401
        assert verify.json()["error"]["code"] == "AUTH_CHALLENGE_INVALID"


async def test_expired_access_token_is_rejected(tmp_path) -> None:
    async with _running(tmp_path, access_token_ttl_seconds=0) as (app, client):
        registered = await _register(app, client)
        issue = await _challenge(client, registered["client_id"])
        token = (
            await _verify(client, registered["client_id"], registered["client_secret"], issue)
        ).json()

        response = await client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_failed_attempts_are_rate_limited(tmp_path) -> None:
    async with _running(tmp_path, rate_limit_auth_per_minute=2) as (app, client):
        registered = await _register(app, client)
        issue = await _challenge(client, registered["client_id"])
        payload = {
            "challenge_id": issue["challenge_id"],
            "client_id": registered["client_id"],
            "proof": "A" * 43,
        }

        first = await client.post("/api/v1/auth/verify", json=payload)
        second = await client.post("/api/v1/auth/verify", json=payload)
        third = await client.post("/api/v1/auth/verify", json=payload)

        assert first.status_code == 401
        assert second.status_code == 401
        assert third.status_code == 429
        assert third.json()["error"]["code"] == "RATE_LIMITED"
        assert int(third.headers["Retry-After"]) >= 1


async def test_invalid_payload_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (_, client):
        response = await client.post("/api/v1/auth/challenge", json={"client_id": "not-a-client"})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"
