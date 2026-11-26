"""E11-T01 / T02 需求规格与游戏设计集成测试。"""

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
from core.errors import NotFoundError, ValidationFailed
from core.security.policy import evaluate
from core.security.principal import (
    ACTION_E11_DEMO_ACCEPT,
    ACTION_E11_DEMO_READ,
    Principal,
    Resource,
)
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.demo_game.service import DemoGameService
from modules.demo_game.specification import REQUIREMENTS, SCENARIOS
from modules.project_registry.service import ProjectRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e11spec.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


async def _project(app, tmp_path: Path, name: str = "Platformer") -> str:
    registry = app.state.services.get("project_registry_service", ProjectRegistryService)
    root = tmp_path / name.lower()
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name=name)
    return project.project_id


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_complete(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        service = app.state.services.get("demo_game_service", DemoGameService)

        first = await service.seed_platformer(project_id)
        second = await service.seed_platformer(project_id)

        assert first["spec"]["codename"] == "PF-DEMO-001"
        assert first["spec"]["status"] == "DRAFT"
        assert first["spec"]["scope"]["out_of_scope"]
        assert second["spec"]["spec_id"] == first["spec"]["spec_id"]
        counts = first["counts"]
        assert counts["requirements"] == len(REQUIREMENTS)
        assert counts["mechanics"] == 8
        assert counts["levels"] == 1
        assert counts["features"] == 8
        assert counts["scenarios"] == len(SCENARIOS)
        assert counts["criteria"] == sum(len(item["criteria"]) for item in REQUIREMENTS)


@pytest.mark.asyncio
async def test_requirements_are_traceable(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        service = app.state.services.get("demo_game_service", DemoGameService)
        await service.seed_platformer(project_id)

        page = await service.list_requirements(project_id)
        assert page["total"] == len(REQUIREMENTS)
        for item in page["items"]:
            assert item["criteria"], item["requirement_key"]
            assert item["scenarios"], item["requirement_key"]

        p1 = await service.list_requirements(project_id, priority="P1")
        assert [item["requirement_key"] for item in p1["items"]] == ["REQ-SAVE-001"]

        traceability = await service.traceability(project_id)
        assert len(traceability) == len(REQUIREMENTS)
        report = await service.system_report(project_id)
        assert report["readiness"]["requirements_traced"] is True
        assert report["verification"]["total"] == 0
        assert report["spec"]["godot_version"] == "4.5.1"


@pytest.mark.asyncio
async def test_criterion_and_scenario_statuses(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        service = app.state.services.get("demo_game_service", DemoGameService)
        await service.seed_platformer(project_id)

        criterion = await service.set_criterion_status(project_id, "REQ-COMBAT-002", "AC-1", "MET")
        assert criterion["status"] == "VERIFIED"

        await service.set_scenario_status(project_id, "TC-005", "FAILED")
        summary = await service.acceptance_summary(project_id)
        assert summary["coverage"]["scenarios"]["FAILED"] == 1
        report = await service.system_report(project_id)
        assert report["readiness"]["blocking_scenarios"] == 1

        with pytest.raises(ValidationFailed):
            await service.set_scenario_status(project_id, "TC-005", "UNKNOWN")
        with pytest.raises(NotFoundError):
            await service.set_scenario_status(project_id, "TC-999", "PASSED")


@pytest.mark.asyncio
async def test_acceptance_review_rules(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        service = app.state.services.get("demo_game_service", DemoGameService)
        await service.seed_platformer(project_id)
        await service.freeze_spec(project_id)

        with pytest.raises(ValidationFailed):
            await service.review(project_id, decision="REJECTED", reviewer="admin", summary="no")

        accepted = await service.review(
            project_id,
            decision="ACCEPTED_WITH_NOTES",
            reviewer="admin",
            summary="可交付，保留已知问题",
            known_issues=["音频占位"],
            remaining_risks=["导出环境差异"],
        )
        assert accepted["decision"] == "ACCEPTED_WITH_NOTES"
        summary = await service.acceptance_summary(project_id)
        assert summary["spec_status"] == "FROZEN"
        assert summary["latest"]["decision"] == "ACCEPTED_WITH_NOTES"
        assert summary["latest"]["payload"]["spec_status"] == "FROZEN"

        with pytest.raises(NotFoundError):
            await service.get_spec("prj_missing")


def test_acceptance_requires_owner_role() -> None:
    resource = Resource(kind="project", project_id="prj_1")
    owner = Principal(client_id="c1", client_type="tool", role="owner", project_id="prj_1")
    editor = Principal(client_id="c2", client_type="tool", role="editor", project_id="prj_1")

    assert evaluate(owner, ACTION_E11_DEMO_ACCEPT, resource).allowed is True
    assert evaluate(editor, ACTION_E11_DEMO_ACCEPT, resource).allowed is False
    assert evaluate(editor, ACTION_E11_DEMO_READ, resource).allowed is True


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _admin_session(app, client) -> str:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": "admin", "client_name": "E11 Demo"},
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


@pytest.mark.asyncio
async def test_demo_api_end_to_end(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            token = await _admin_session(app, client)
            headers = _bearer(token)

            seeded = await client.post(f"/api/v1/demo/projects/{project_id}/spec", headers=headers)
            assert seeded.status_code == 200
            assert seeded.json()["counts"]["requirements"] == len(REQUIREMENTS)

            requirements = await client.get(
                f"/api/v1/demo/projects/{project_id}/requirements", headers=headers
            )
            assert requirements.status_code == 200
            assert requirements.json()["total"] == len(REQUIREMENTS)

            review = await client.post(
                f"/api/v1/demo/projects/{project_id}/acceptance/review",
                headers=headers,
                json={"decision": "ACCEPTED", "summary": "系统级验收通过"},
            )
            assert review.status_code == 201
            assert review.json()["decision"] == "ACCEPTED"

            report = await client.get(
                f"/api/v1/demo/projects/{project_id}/system-report", headers=headers
            )
            assert report.status_code == 200
            payload = report.json()
            assert payload["acceptance"]["decision"] == "ACCEPTED"
            assert payload["readiness"]["requirements_traced"] is True
            assert payload["verification"]["total"] == 0
