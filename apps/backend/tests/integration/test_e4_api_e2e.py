"""E4 API 端到端测试（E4-T24）。

覆盖 admin 会话下的 Project → Task → Workflow → 验收 → ChangeSet → Approval 流程。
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
from infrastructure.security.bootstrap import BootstrapTokenStore


@asynccontextmanager
async def _running(tmp_path: Path, project_root: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e4api.db').as_posix()}",
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


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _admin_session(app, client) -> str:
    return await _session_for(app, client, "admin")


async def _session_for(app, client, client_type: str) -> str:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": client_type, "client_name": f"E4 {client_type}"},
        headers={"X-Bootstrap-Token": bootstrap},
    )
    body = registered.json()
    challenge = (
        await client.post("/api/v1/auth/challenge", json={"client_id": body["client_id"]})
    ).json()
    verified = await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "client_id": body["client_id"],
            "proof": _proof(
                body["client_secret"], challenge["challenge_id"], challenge["challenge"]
            ),
        },
    )
    issued = await client.post("/api/v1/sessions", headers=_bearer(verified.json()["access_token"]))
    return issued.json()["session_token"]


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "e4_project"
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="E4"\n', encoding="utf-8"
    )
    return root


async def test_project_task_workflow_governance_e2e(tmp_path: Path, project_root: Path) -> None:
    async with _running(tmp_path, project_root) as (app, client):
        token = await _admin_session(app, client)
        headers = _bearer(token)

        created = await client.post(
            "/api/v1/projects",
            json={"project_root": str(project_root), "name": "E4 E2E"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["project_id"]

        task = await client.post(
            f"/api/v1/projects/{project_id}/tasks",
            json={"title": "Build level"},
            headers=headers,
        )
        assert task.status_code == 201, task.text
        task_id = task.json()["task_id"]
        assert task.json()["status"] == "READY"

        for target in ("QUEUED", "RUNNING"):
            moved = await client.patch(
                f"/api/v1/tasks/{task_id}/status", json={"status": target}, headers=headers
            )
            assert moved.status_code == 200, moved.text

        paused = await client.post(f"/api/v1/tasks/{task_id}/pause", headers=headers)
        assert paused.status_code == 200 and paused.json()["status"] == "PAUSED"
        resumed = await client.post(f"/api/v1/tasks/{task_id}/resume", headers=headers)
        assert resumed.status_code == 200 and resumed.json()["status"] == "RUNNING"

        definition = await client.post(
            "/api/v1/workflow-definitions",
            params={"project_id": project_id},
            json={
                "name": "E2E flow",
                "category": "GAME_DEVELOPMENT",
                "definition": {
                    "nodes": [
                        {"node_key": "analyze", "node_type": "AI_EXECUTION", "phase_key": "p1"},
                        {
                            "node_key": "implement",
                            "node_type": "TOOL_OPERATION",
                            "dependency_keys": ["analyze"],
                            "phase_key": "p1",
                        },
                    ],
                    "phases": [{"phase_key": "p1", "name": "Phase 1"}],
                },
            },
            headers=headers,
        )
        assert definition.status_code == 201, definition.text
        definition_id = definition.json()["definition_id"]

        instance = await client.post(
            f"/api/v1/tasks/{task_id}/workflow",
            json={"definition_id": definition_id},
            headers=headers,
        )
        assert instance.status_code == 201, instance.text
        instance_id = instance.json()["instance_id"]

        tick = await client.post(f"/api/v1/workflows/{instance_id}/tick", headers=headers)
        assert tick.status_code == 200 and tick.json()["started"]["node_key"] == "analyze"

        completed = await client.post(
            f"/api/v1/workflows/{instance_id}/nodes/analyze/complete",
            json={"output_ref": "res://analysis"},
            headers=headers,
        )
        assert completed.status_code == 200, completed.text
        assert (
            await client.post(f"/api/v1/workflows/{instance_id}/advance", headers=headers)
        ).status_code == 200
        assert (
            await client.post(
                f"/api/v1/workflows/{instance_id}/nodes/implement/start", headers=headers
            )
        ).status_code == 200
        assert (
            await client.post(
                f"/api/v1/workflows/{instance_id}/nodes/implement/complete",
                json={"output_ref": "res://out"},
                headers=headers,
            )
        ).status_code == 200

        phases = await client.get(f"/api/v1/workflows/{instance_id}/phases", headers=headers)
        assert phases.json()["items"][0]["status"] == "REVIEW_PENDING"
        review = await client.post(
            f"/api/v1/workflows/{instance_id}/phases/p1/review",
            json={"summary": "done", "deliverables": ["res://out"]},
            headers=headers,
        )
        assert review.status_code == 200, review.text
        accepted = await client.post(
            f"/api/v1/workflows/{instance_id}/phases/p1/accept", headers=headers
        )
        assert accepted.status_code == 200, accepted.text

        reviewed = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        assert reviewed.json()["status"] == "REVIEW_PENDING"
        finished = await client.post(f"/api/v1/tasks/{task_id}/accept", headers=headers)
        assert finished.status_code == 200 and finished.json()["status"] == "COMPLETED"

        changeset = await client.post(
            "/api/v1/changesets",
            json={
                "project_id": project_id,
                "title": "Add level scene",
                "items": [
                    {
                        "resource_path": "scenes/level.tscn",
                        "operation_type": "CREATE",
                        "new_content_hash": "c" * 64,
                    }
                ],
            },
            headers=headers,
        )
        assert changeset.status_code == 201, changeset.text
        changeset_id = changeset.json()["changeset_id"]
        assert (
            await client.post(f"/api/v1/changesets/{changeset_id}/validate", headers=headers)
        ).json()["status"] == "VALID"

        approvals = await client.get(
            "/api/v1/approvals", params={"project_id": project_id}, headers=headers
        )
        assert approvals.status_code == 200
        submitted = await client.post(f"/api/v1/changesets/{changeset_id}/submit", headers=headers)
        assert submitted.status_code == 201, submitted.text
        approval_id = submitted.json()["approval_id"]

        approved = await client.post(
            f"/api/v1/changesets/{changeset_id}/approve",
            json={"approval_id": approval_id},
            headers=headers,
        )
        assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
        applying = await client.post(
            f"/api/v1/changesets/{changeset_id}/apply",
            json={"approval_id": approval_id},
            headers=headers,
        )
        assert applying.status_code == 200 and applying.json()["status"] == "APPLYING"
        applied = await client.post(
            f"/api/v1/changesets/{changeset_id}/finish",
            json={"status": "APPLIED"},
            headers=headers,
        )
        assert applied.status_code == 200 and applied.json()["status"] == "APPLIED"

        detail = await client.get(f"/api/v1/changesets/{changeset_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["validation"]["status"] == "VALID"


async def test_unknown_task_returns_not_found(tmp_path: Path, project_root: Path) -> None:
    async with _running(tmp_path, project_root) as (app, client):
        headers = _bearer(await _admin_session(app, client))
        response = await client.get("/api/v1/tasks/tsk_missing", headers=headers)
        assert response.status_code == 404


async def test_unauthorized_client_cannot_manage_foreign_project(
    tmp_path: Path, project_root: Path
) -> None:
    async with _running(tmp_path, project_root) as (app, client):
        admin = _bearer(await _admin_session(app, client))
        created = await client.post(
            "/api/v1/projects",
            json={"project_root": str(project_root), "name": "Admin project"},
            headers=admin,
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["project_id"]

        editor = _bearer(await _session_for(app, client, "godot_editor"))
        assert (
            await client.get(f"/api/v1/projects/{project_id}", headers=editor)
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/projects/{project_id}/tasks",
                json={"title": "unauthorized"},
                headers=editor,
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/projects/{project_id}/archive",
                json={"force": True},
                headers=editor,
            )
        ).status_code == 403

        # 版本冲突与非法状态转换必须被拒绝。
        conflict = await client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "renamed", "expected_version": 999},
            headers=admin,
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"

        task = await client.post(
            f"/api/v1/projects/{project_id}/tasks",
            json={"title": "guarded"},
            headers=admin,
        )
        forged = await client.patch(
            f"/api/v1/tasks/{task.json()['task_id']}/status",
            json={"status": "COMPLETED"},
            headers=admin,
        )
        assert forged.status_code == 409
        assert forged.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
