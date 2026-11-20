"""审计集成测试（E2-T11-IT / E2-IT-011）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from contextlib import asynccontextmanager

import httpx

from bootstrap.application import create_app
from config.settings import load_settings
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.audit.models import (
    AUDIT_ACCESS_GRANTED,
    AUDIT_ACCESS_REVOKED,
    AUDIT_AUTH_SUCCEEDED,
    AUDIT_AUTHORIZATION_DENIED,
    AUDIT_CLIENT_REGISTERED,
    AUDIT_HIGH_RISK_CALL,
    AUDIT_SESSION_CREATED,
)
from modules.audit.service import AuditService


@asynccontextmanager
async def _running(tmp_path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'audit.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _session(app, client, *, client_type: str = "godot_editor") -> dict[str, str]:
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
    issued = await client.post("/api/v1/sessions", headers=_bearer(verified.json()["access_token"]))
    session = issued.json()
    return {
        "client_id": body["client_id"],
        "client_secret": body["client_secret"],
        "session_token": session["session_token"],
        "session_id": session["session"]["session_id"],
    }


async def _grant(client, token: str, *, session_id: str, project_id: str, level: str):
    return await client.post(
        "/api/v1/projects/access",
        json={"project_id": project_id, "session_id": session_id, "access_level": level},
        headers=_bearer(token),
    )


def _audit(app) -> AuditService:
    return app.state.services.get("audit_service", AuditService)


async def test_audit_records_core_lifecycle(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        owner = await _session(app, client)

        granted = await _grant(
            client,
            admin["session_token"],
            session_id=owner["session_id"],
            project_id="proj_alpha",
            level="owner",
        )
        assert granted.status_code == 201
        revoked = await client.delete(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_alpha"},
            headers=_bearer(owner["session_token"]),
        )
        assert revoked.status_code == 200

        events = await _audit(app).recent(limit=100)
        actions = {event.action for event in events}

        assert {
            AUDIT_CLIENT_REGISTERED,
            AUDIT_AUTH_SUCCEEDED,
            AUDIT_SESSION_CREATED,
            AUDIT_ACCESS_GRANTED,
            AUDIT_ACCESS_REVOKED,
        } <= actions
        granted_event = next(event for event in events if event.action == AUDIT_ACCESS_GRANTED)
        assert granted_event.actor_id == admin["client_id"]
        assert granted_event.resource == "project:proj_alpha"
        assert granted_event.details["access_level"] == "owner"
        assert granted_event.details["project_id"] == "proj_alpha"
        assert granted_event.correlation_id


async def test_denied_authorization_is_audited(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        viewer = await _session(app, client)
        other = await _session(app, client)
        await _grant(
            client,
            admin["session_token"],
            session_id=viewer["session_id"],
            project_id="proj_alpha",
            level="viewer",
        )

        denied = await _grant(
            client,
            viewer["session_token"],
            session_id=other["session_id"],
            project_id="proj_alpha",
            level="owner",
        )

        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_DENIED"

        events = await _audit(app).for_action(AUDIT_AUTHORIZATION_DENIED, limit=20)
        assert events
        latest = events[0]
        assert latest.decision == "DENY"
        assert latest.reason == "role_denied"
        assert latest.client_id == viewer["client_id"]
        assert latest.details["role"] == "viewer"


async def test_audit_details_never_contain_secrets(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        owner = await _session(app, client)
        await _grant(
            client,
            owner["session_token"],
            session_id=owner["session_id"],
            project_id="proj_alpha",
            level="owner",
        )

        events = await _audit(app).recent(limit=100)
        serialized = json.dumps([event.details for event in events], ensure_ascii=False)

        assert owner["client_secret"] not in serialized
        assert owner["session_token"] not in serialized


async def test_diagnostics_access_is_audited_as_high_risk(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        session = await _session(app, client)

        response = await client.get(
            "/api/v1/diagnostics/summary",
            headers=_bearer(session["session_token"]),
        )

        assert response.status_code == 200
        events = await _audit(app).for_action(AUDIT_HIGH_RISK_CALL, limit=10)
        assert events
        assert events[0].details["endpoint"] == "/api/v1/diagnostics/summary"
        assert events[0].client_id == session["client_id"]
