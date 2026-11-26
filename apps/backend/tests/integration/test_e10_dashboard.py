"""E10-T18 / T19 看板与 Agent 策略集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import PermissionDenied
from modules.build_release.agent_policy import (
    AGENT_ACTION_START_BUILD,
    AGENT_FORBIDDEN_ACTION_SELF_APPROVE,
    ROLE_BUILD_RELEASE_ENGINEER,
    ROLE_QA_ENGINEER,
    agent_policy,
    ensure_agent_action_allowed,
)
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.dashboard import BuildReleaseDashboardService
from modules.project_registry.service import ProjectRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e10dash.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


async def _project(app, tmp_path: Path) -> str:
    registry = app.state.services.get("project_registry_service", ProjectRegistryService)
    root = tmp_path / "game"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name="Platformer")
    return project.project_id


@pytest.mark.asyncio
async def test_dashboard_reports_artifacts(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        dashboard = app.state.services.get(
            "build_release_dashboard_service", BuildReleaseDashboardService
        )
        empty = await dashboard.overview(project_id)
        assert empty["builds"]["recent"] == []
        assert empty["artifacts"]["total"] == 0
        assert any(item["channel"] == "LOCAL_EXPORT" for item in empty["distribution_capabilities"])

        artifacts = app.state.services.get("artifact_registry_service", ArtifactRegistryService)
        await artifacts.register_artifact(
            project_id=project_id,
            platform="WINDOWS",
            architecture="x86_64",
            storage_reference="build/game.exe",
            files=[{"path": "game.exe", "size": 4, "hash": "sha256:deadbeef"}],
            format="exe",
        )
        overview = await dashboard.overview(project_id)
        assert overview["artifacts"]["total"] == 1
        assert overview["releases"]["recent"] == []


def test_agent_policy_matrix() -> None:
    policy = agent_policy()
    assert AGENT_FORBIDDEN_ACTION_SELF_APPROVE in policy["forbidden_actions"]
    assert policy["approval_requires_user"] is True

    ensure_agent_action_allowed(ROLE_BUILD_RELEASE_ENGINEER, AGENT_ACTION_START_BUILD)
    with pytest.raises(PermissionDenied):
        ensure_agent_action_allowed(ROLE_QA_ENGINEER, AGENT_ACTION_START_BUILD)
    with pytest.raises(PermissionDenied):
        ensure_agent_action_allowed(
            ROLE_BUILD_RELEASE_ENGINEER, AGENT_FORBIDDEN_ACTION_SELF_APPROVE
        )
