"""Project Access 测试（E2-T07-UT / IT）。"""

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

ACCESS_SCHEMA = "api/project-access.schema.json"
ERROR_SCHEMA = "errors/error.schema.json"


@asynccontextmanager
async def _running(tmp_path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'access.db').as_posix()}",
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
    """注册客户端、完成认证并创建 Session。"""

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
        "session_token": session["session_token"],
        "session_id": session["session"]["session_id"],
    }


async def _grant(client, grantor_token: str, *, session_id: str, project_id: str, level: str):
    return await client.post(
        "/api/v1/projects/access",
        json={"project_id": project_id, "session_id": session_id, "access_level": level},
        headers=_bearer(grantor_token),
    )


async def test_admin_grants_project_access(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        editor = await _session(app, client)

        response = await _grant(
            client,
            admin["session_token"],
            session_id=editor["session_id"],
            project_id="proj_alpha",
            level="editor",
        )

        assert response.status_code == 201
        body = response.json()
        assert validate_instance(body, ACCESS_SCHEMA) == []
        assert body["client_id"] == editor["client_id"]
        assert body["access_level"] == "editor"
        assert body["status"] == "ACTIVE"

        current = await client.get(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_alpha"},
            headers=_bearer(editor["session_token"]),
        )
        assert current.status_code == 200
        assert current.json()["access_id"] == body["access_id"]


async def test_ungranted_project_is_denied(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        editor = await _session(app, client)
        await _grant(
            client,
            admin["session_token"],
            session_id=editor["session_id"],
            project_id="proj_alpha",
            level="viewer",
        )

        response = await client.get(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_beta"},
            headers=_bearer(editor["session_token"]),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PROJECT_ACCESS_DENIED"
        assert validate_instance(response.json()["error"], ERROR_SCHEMA) == []


async def test_non_owner_cannot_grant(tmp_path) -> None:
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

        response = await _grant(
            client,
            viewer["session_token"],
            session_id=other["session_id"],
            project_id="proj_alpha",
            level="owner",
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_client_without_project_access_cannot_grant(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        editor = await _session(app, client)
        other = await _session(app, client)

        response = await _grant(
            client,
            editor["session_token"],
            session_id=other["session_id"],
            project_id="proj_alpha",
            level="owner",
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PROJECT_ACCESS_DENIED"


async def test_owner_can_grant_after_being_granted_owner(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        owner = await _session(app, client)
        viewer = await _session(app, client)
        await _grant(
            client,
            admin["session_token"],
            session_id=owner["session_id"],
            project_id="proj_alpha",
            level="owner",
        )

        response = await _grant(
            client,
            owner["session_token"],
            session_id=viewer["session_id"],
            project_id="proj_alpha",
            level="viewer",
        )

        assert response.status_code == 201
        assert response.json()["granted_by"] == owner["client_id"]


async def test_revoked_access_is_denied_immediately(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        editor = await _session(app, client)
        await _grant(
            client,
            admin["session_token"],
            session_id=editor["session_id"],
            project_id="proj_alpha",
            level="editor",
        )

        revoked = await client.delete(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_alpha", "session_id": editor["session_id"]},
            headers=_bearer(admin["session_token"]),
        )
        denied = await client.get(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_alpha"},
            headers=_bearer(editor["session_token"]),
        )

        assert revoked.status_code == 200
        assert revoked.json()["status"] == "REVOKED"
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PROJECT_ACCESS_DENIED"


async def test_multi_project_isolation(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        editor = await _session(app, client)
        outsider = await _session(app, client)
        await _grant(
            client,
            admin["session_token"],
            session_id=editor["session_id"],
            project_id="proj_alpha",
            level="editor",
        )
        await _grant(
            client,
            admin["session_token"],
            session_id=editor["session_id"],
            project_id="proj_beta",
            level="viewer",
        )

        alpha = await client.get(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_alpha"},
            headers=_bearer(editor["session_token"]),
        )
        beta = await client.get(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_beta"},
            headers=_bearer(editor["session_token"]),
        )
        tampered = await client.get(
            "/api/v1/projects/access/current",
            params={"project_id": "proj_alpha"},
            headers=_bearer(outsider["session_token"]),
        )

        assert alpha.status_code == 200
        assert alpha.json()["access_level"] == "editor"
        assert beta.status_code == 200
        assert beta.json()["access_level"] == "viewer"
        assert alpha.json()["access_id"] != beta.json()["access_id"]
        assert tampered.status_code == 403
        assert tampered.json()["error"]["code"] == "PROJECT_ACCESS_DENIED"


async def test_invalid_access_level_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as (app, client):
        admin = await _session(app, client, client_type="admin")
        editor = await _session(app, client)

        response = await _grant(
            client,
            admin["session_token"],
            session_id=editor["session_id"],
            project_id="proj_alpha",
            level="superuser",
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"
