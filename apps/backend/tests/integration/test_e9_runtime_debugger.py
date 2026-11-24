"""E9-T08/T10 运行时环境与 Debugger 错误服务集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from modules.project_registry.service import ProjectRegistryService
from modules.verification.debugger import DebuggerErrorInput
from modules.verification.models import (
    ERROR_CATEGORY_RUNTIME,
    RUNTIME_ENV_BUSY,
    SEVERITY_ERROR,
    SEVERITY_FATAL,
)
from modules.verification.service import VerificationService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9debug.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app) -> VerificationService:
    return app.state.services.get("verification_service", VerificationService)


async def _project(app, tmp_path: Path) -> str:
    registry = app.state.services.get("project_registry_service", ProjectRegistryService)
    root = tmp_path / "game"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name="Game")
    return project.project_id


@pytest.mark.asyncio
async def test_runtime_environment_lifecycle(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        service = _service(app)
        project_id = await _project(app, tmp_path)

        created = await service.register_runtime_environment(
            project_id=project_id,
            project_revision="rev-1",
            godot_version="4.3",
            platform="windows",
            display_resolution="1920x1080",
            renderer="vulkan",
            test_configuration={"headless": False},
        )
        assert created.status == "READY"
        assert created.test_configuration == {"headless": False}

        fetched = await service.get_runtime_environment(created.environment_id)
        assert fetched.environment_id == created.environment_id

        updated = await service.update_runtime_environment(
            created.environment_id, status=RUNTIME_ENV_BUSY, runtime_instance_id="inst_9"
        )
        assert updated.status == RUNTIME_ENV_BUSY
        assert updated.runtime_instance_id == "inst_9"

        page = await service.list_runtime_environments(project_id, status=RUNTIME_ENV_BUSY)
        assert page["total"] == 1
        assert page["items"][0].environment_id == created.environment_id


@pytest.mark.asyncio
async def test_debugger_errors_aggregate_and_gate(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        service = _service(app)
        project_id = await _project(app, tmp_path)
        error = DebuggerErrorInput(
            category=ERROR_CATEGORY_RUNTIME,
            severity=SEVERITY_FATAL,
            message="Segmentation fault at 0x1234",
            source="DEBUGGER",
            scene="res://main.tscn",
            script="res://player.gd",
        )

        first = await service.record_debugger_errors(project_id=project_id, errors=[error])
        assert first["new_count"] == 1
        assert first["baseline_count"] == 0
        assert first["items"][0].is_baseline is False

        second = await service.record_debugger_errors(project_id=project_id, errors=[error])
        assert second["new_count"] == 0
        assert second["baseline_count"] == 1
        assert second["items"][0].occurrences == 2

        gate = await service.evaluate_debugger_gate(project_id)
        assert gate.blocking is True
        assert gate.new_fatal == 1

        error_id = first["items"][0].error_id
        resolved = await service.resolve_debugger_error(error_id, note="已修复")
        assert resolved.status == "RESOLVED"
        assert (await service.evaluate_debugger_gate(project_id)).allowed is True

        # 已解决问题再次出现必须重新打开，不能沿用已解决状态
        reopened = await service.record_debugger_errors(project_id=project_id, errors=[error])
        assert reopened["items"][0].status == "OPEN"
        assert (await service.evaluate_debugger_gate(project_id)).blocking is True


@pytest.mark.asyncio
async def test_baseline_errors_are_recorded_without_blocking(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        service = _service(app)
        project_id = await _project(app, tmp_path)
        legacy = DebuggerErrorInput(
            category=ERROR_CATEGORY_RUNTIME,
            severity=SEVERITY_ERROR,
            message="历史遗留错误",
            source="DEBUGGER",
        )

        result = await service.record_debugger_errors(
            project_id=project_id, errors=[legacy], baseline=True
        )
        assert result["items"][0].is_baseline is True

        gate = await service.evaluate_debugger_gate(project_id)
        assert gate.blocking is False
        assert gate.baseline_open == 1
        assert any("基线" in reason for reason in gate.reasons)

        page = await service.list_debugger_errors(project_id, is_baseline=True)
        assert page["total"] == 1
