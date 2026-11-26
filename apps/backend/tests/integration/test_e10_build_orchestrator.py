"""E10-T05 / T06 / T07 / T17 构建编排与恢复集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    BuildRecoveryRequired,
    BuildStateInvalid,
    ExportPresetInvalid,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.build_release.adapter import (
    EXEC_FAILED,
    EXEC_SUCCEEDED,
    EXEC_TIMEOUT,
    BuildCommand,
    ExecutionResult,
)
from modules.build_release.orchestrator import BuildOrchestrator
from modules.build_release.service import BuildReleaseService
from modules.project_registry.service import ProjectRegistryService


class FakeExecutor:
    """可编排结果的受控执行器替身。"""

    def __init__(self, mode: str = "success", write_output: bool = True) -> None:
        self.mode = mode
        self.write_output = write_output
        self.calls: list[BuildCommand] = []

    async def run(self, command: BuildCommand) -> ExecutionResult:
        self.calls.append(command)
        now = utcnow()
        output = Path(command.display["output"])
        if self.mode == "timeout":
            if self.write_output:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"GAME")
            return ExecutionResult(EXEC_TIMEOUT, None, "", "timeout", now, now)
        if self.mode == "fail":
            return ExecutionResult(EXEC_FAILED, 1, "stderr", "boom", now, now)
        if self.write_output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"GAME-BINARY")
        return ExecutionResult(EXEC_SUCCEEDED, 0, "exported", "", now, now)


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e10orchestrator.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


async def _project(app, tmp_path: Path) -> tuple[str, Path]:
    registry = app.state.services.get("project_registry_service", ProjectRegistryService)
    root = tmp_path / "game"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name="Platformer")
    return project.project_id, root


def _builds(app) -> BuildReleaseService:
    return app.state.services.get("build_release_service", BuildReleaseService)


def _orchestrator(app, executor: FakeExecutor, writes: bool = True) -> BuildOrchestrator:
    database = app.state.services.get("database", DatabaseService)
    return BuildOrchestrator(
        database,
        builds=_builds(app),
        executor=executor,
        projects=app.state.services.get("project_registry_service", ProjectRegistryService),
    )


async def _fixtures(app, project_id: str, *, template_available: bool = True) -> tuple[str, str]:
    builds = _builds(app)
    await builds.register_export_preset(
        project_id=project_id,
        preset_name="Windows Desktop",
        platform="WINDOWS",
        template_required="windows_release",
        template_available=template_available,
    )
    environment = await builds.register_environment(
        project_id=project_id,
        os_name="Windows",
        os_version="11",
        cpu_architecture="x86_64",
        godot_version="4.5.1",
        export_template_version="4.5.1",
        toolchain_versions={"msvc": "19.40"},
        sdk_versions={"WINDOWS": "10.0"},
        target_platform="WINDOWS",
    )
    config = await builds.create_configuration(
        project_id=project_id,
        name="win-release",
        target_platform="WINDOWS",
        architecture="x86_64",
        export_preset_name="Windows Desktop",
        build_timeout_seconds=60,
    )
    return config.configuration_id, environment.environment_id


@pytest.mark.asyncio
async def test_build_success_records_attempt_and_manifest(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, _ = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id)
        executor = FakeExecutor()
        orchestrator = _orchestrator(app, executor)
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        assert build.status == "QUEUED"
        result = await orchestrator.start_build(build.build_id)
        assert result.status == "SUCCEEDED"
        attempts = await orchestrator.list_attempts(build.build_id)
        assert len(attempts) == 1
        assert attempts[0].status == "SUCCEEDED"
        assert attempts[0].output_manifest
        assert attempts[0].exit_code == 0
        assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_zero_exit_without_output_is_failure(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, _ = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id)
        executor = FakeExecutor(write_output=False)
        orchestrator = _orchestrator(app, executor)
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        result = await orchestrator.start_build(build.build_id)
        assert result.status == "FAILED"
        assert result.error_code == "BUILD_OUTPUT_MISSING"


@pytest.mark.asyncio
async def test_retry_creates_new_attempt(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, _ = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id)
        executor = FakeExecutor(mode="fail")
        orchestrator = _orchestrator(app, executor)
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        failed = await orchestrator.start_build(build.build_id)
        assert failed.status == "FAILED"
        assert failed.error_code == "BUILD_EXIT_NONZERO"

        executor.mode = "success"
        retried = await orchestrator.retry_build(build.build_id)
        assert retried.status == "SUCCEEDED"
        attempts = await orchestrator.list_attempts(build.build_id)
        assert [item.attempt_number for item in attempts] == [1, 2]
        assert attempts[0].status == "FAILED"
        assert attempts[1].status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_timeout_enters_unknown_and_requires_recovery(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, _ = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id)
        executor = FakeExecutor(mode="timeout", write_output=True)
        orchestrator = _orchestrator(app, executor)
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        result = await orchestrator.start_build(build.build_id)
        assert result.status == "UNKNOWN"
        with pytest.raises(BuildRecoveryRequired):
            await orchestrator.retry_build(build.build_id)

        recovery = await orchestrator.recover_build(build.build_id)
        assert recovery.previous_status == "UNKNOWN"
        assert recovery.has_output is True
        assert recovery.resolved_status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_recovery_without_output_resolves_failed(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, _ = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id)
        executor = FakeExecutor(mode="timeout", write_output=False)
        orchestrator = _orchestrator(app, executor)
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        await orchestrator.start_build(build.build_id)
        recovery = await orchestrator.recover_build(build.build_id)
        assert recovery.has_output is False
        assert recovery.resolved_status == "FAILED"


@pytest.mark.asyncio
async def test_cancel_queued_build(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, _ = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id)
        orchestrator = _orchestrator(app, FakeExecutor())
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        cancelled = await orchestrator.cancel_build(build.build_id)
        assert cancelled.status == "CANCELLED"
        with pytest.raises(BuildStateInvalid):
            await orchestrator.start_build(build.build_id)


@pytest.mark.asyncio
async def test_missing_template_blocks_start_before_running(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, _ = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id, template_available=False)
        orchestrator = _orchestrator(app, FakeExecutor())
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        with pytest.raises(ExportPresetInvalid):
            await orchestrator.start_build(build.build_id)
        still = await orchestrator.get_build(build.build_id)
        assert still.status == "QUEUED"
