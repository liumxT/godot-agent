"""E10-T20 验收：从构建到本地交付的闭环。

流程：环境 → 配置 → 受控构建 → 不可变制品 → 交付包 → 发布候选 →
冒烟测试 → 用户审批 → 本地交付 → 发布后验证；另覆盖 UNKNOWN 恢复。
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import BuildRecoveryRequired
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.build_release.adapter import (
    EXEC_SUCCEEDED,
    EXEC_TIMEOUT,
    BuildCommand,
    ExecutionResult,
)
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.orchestrator import BuildOrchestrator
from modules.build_release.packaging import PackagingService
from modules.build_release.release_approvals import ReleaseApprovalService
from modules.build_release.release_candidates import ReleaseCandidateService
from modules.build_release.release_manager import ReleaseManagerService
from modules.build_release.service import BuildReleaseService
from modules.build_release.smoke_test import SmokeTestService
from modules.project_registry.service import ProjectRegistryService


class FakeExecutor:
    """受控执行器：写入真实导出文件，便于后续制品与交付校验。"""

    def __init__(self, mode: str = "success") -> None:
        self.mode = mode

    async def run(self, command: BuildCommand) -> ExecutionResult:
        now = utcnow()
        output = Path(command.display["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PLATFORMER-BINARY")
        if self.mode == "timeout":
            return ExecutionResult(EXEC_TIMEOUT, None, "", "timeout", now, now)
        return ExecutionResult(EXEC_SUCCEEDED, 0, "exported", "", now, now)


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e10acceptance.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, key: str, default):
    return app.state.services.get(key, default)


async def _project(app, tmp_path: Path) -> tuple[str, Path]:
    registry = _service(app, "project_registry_service", ProjectRegistryService)
    root = tmp_path / "game"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name="Platformer")
    return project.project_id, root


async def _fixtures(app, project_id: str) -> tuple[str, str]:
    builds = _service(app, "build_release_service", BuildReleaseService)
    await builds.register_export_preset(
        project_id=project_id,
        preset_name="Windows Desktop",
        platform="WINDOWS",
        template_required="windows_release",
        template_available=True,
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


def _orchestrator(app, executor: FakeExecutor) -> BuildOrchestrator:
    database = _service(app, "database", DatabaseService)
    return BuildOrchestrator(
        database,
        builds=_service(app, "build_release_service", BuildReleaseService),
        executor=executor,
        projects=_service(app, "project_registry_service", ProjectRegistryService),
    )


@pytest.mark.asyncio
async def test_build_to_local_delivery_closed_loop(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, root = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id)

        orchestrator = _orchestrator(app, FakeExecutor())
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        started = await orchestrator.start_build(build.build_id)
        assert started.status == "SUCCEEDED"
        attempts = await orchestrator.list_attempts(build.build_id)
        assert attempts[0].output_manifest

        attempt_dir = root / "build" / "e10" / build.build_id / "attempt-1"
        files = [
            {
                "path": str((attempt_dir / item["path"]).relative_to(root)),
                "size": item["size"],
                "hash": item["hash"],
            }
            for item in attempts[0].output_manifest
        ]
        source = root / files[0]["path"]
        assert source.exists()

        artifacts = _service(app, "artifact_registry_service", ArtifactRegistryService)
        artifact = await artifacts.register_artifact(
            project_id=project_id,
            platform="WINDOWS",
            architecture="x86_64",
            storage_reference=files[0]["path"],
            files=files,
            build_id=build.build_id,
            attempt_id=attempts[0].attempt_id,
            format="exe",
        )
        artifact = await artifacts.mark_verified(artifact.artifact_id)

        packages = _service(app, "packaging_service", PackagingService)
        package = await packages.create_package(
            project_id=project_id, artifact_id=artifact.artifact_id, format="zip"
        )
        package = await packages.verify_package(package.package_id)

        candidates = _service(app, "release_candidate_service", ReleaseCandidateService)
        candidate = await candidates.create_candidate(
            project_id=project_id,
            version="1.0.0",
            artifact_id=artifact.artifact_id,
            package_id=package.package_id,
        )
        smoke = _service(app, "smoke_test_service", SmokeTestService)
        await smoke.record_smoke_test(
            project_id=project_id,
            artifact_id=artifact.artifact_id,
            release_candidate_id=candidate.release_candidate_id,
            checks=[{"name": "launch", "status": "PASSED"}],
        )
        validation = await candidates.validate_candidate(candidate.release_candidate_id)
        assert validation.ready is True

        approvals = _service(app, "release_approval_service", ReleaseApprovalService)
        approval = await approvals.request_approval(
            release_candidate_id=candidate.release_candidate_id,
            distribution_channel="LOCAL_EXPORT",
        )
        await approvals.approve(approval.approval_id, approved_by="owner-1")

        releases = _service(app, "release_manager_service", ReleaseManagerService)
        release = await releases.create_release(
            release_candidate_id=candidate.release_candidate_id,
            approval_id=approval.approval_id,
            channel="LOCAL_EXPORT",
        )
        await releases.authorize_release(release.release_id)
        target = tmp_path / "delivery"
        target.mkdir()
        published = await releases.start_release(release.release_id, target_reference=str(target))
        assert published.status == "PUBLISHED"
        delivered = target / source.name
        assert delivered.read_bytes() == source.read_bytes()
        assert file_digest(delivered) == file_digest(source)
        verified = await releases.verify_release(release.release_id)
        assert verified.status == "COMPLETED"


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_unknown_build_requires_recovery_before_release(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, _ = await _project(app, tmp_path)
        config_id, env_id = await _fixtures(app, project_id)
        orchestrator = _orchestrator(app, FakeExecutor(mode="timeout"))
        build = await orchestrator.create_build(
            project_id=project_id, build_config_id=config_id, environment_id=env_id
        )
        result = await orchestrator.start_build(build.build_id)
        assert result.status == "UNKNOWN"
        with pytest.raises(BuildRecoveryRequired):
            await orchestrator.retry_build(build.build_id)
        recovery = await orchestrator.recover_build(build.build_id)
        assert recovery.resolved_status == "SUCCEEDED"
