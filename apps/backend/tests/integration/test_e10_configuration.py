"""E10-T02 / T03 / T04 构建配置、Export Preset 与环境集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    BuildConfigurationInvalid,
    ExportPresetInvalid,
    ValidationFailed,
)
from modules.build_release.service import BuildReleaseService
from modules.project_registry.service import ProjectRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e10build.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


async def _project(app, tmp_path: Path, name: str = "Platformer") -> str:
    registry = app.state.services.get("project_registry_service", ProjectRegistryService)
    root = tmp_path / "platformer"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name=name)
    return project.project_id


def _builds(app) -> BuildReleaseService:
    return app.state.services.get("build_release_service", BuildReleaseService)


@pytest.mark.asyncio
async def test_platform_capabilities_seeded(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        capabilities = await _builds(app).list_platform_capabilities()
    platforms = {item.platform_id for item in capabilities}
    assert {"WINDOWS", "MACOS", "LINUX"} <= platforms
    assert all(item.export_enabled for item in capabilities)


@pytest.mark.asyncio
async def test_configuration_version_snapshot_and_update(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        builds = _builds(app)
        created = await builds.create_configuration(
            project_id=project_id,
            name="windows-release",
            target_platform="WINDOWS",
            architecture="x86_64",
            export_preset_name="Windows Desktop",
            output_format="zip",
        )
        assert created.current_version == 1
        version_one = await builds.get_configuration_version(created.configuration_id)
        assert version_one.version == 1
        assert version_one.output_format == "zip"

        updated = await builds.update_configuration(
            created.configuration_id, output_format="folder"
        )
        assert updated.current_version == 2
        # 旧版本快照保持不变
        still_one = await builds.get_configuration_version(created.configuration_id, 1)
        assert still_one.output_format == "zip"
        version_two = await builds.get_configuration_version(created.configuration_id, 2)
        assert version_two.output_format == "folder"
        assert version_two.config_hash != still_one.config_hash

        with pytest.raises(BuildConfigurationInvalid):
            await builds.update_configuration(created.configuration_id, output_format="folder")


@pytest.mark.asyncio
async def test_configuration_rejects_invalid_and_secret(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        builds = _builds(app)
        with pytest.raises(BuildConfigurationInvalid):
            await builds.create_configuration(
                project_id=project_id,
                name="mobile",
                target_platform="ANDROID",  # type: ignore[arg-type]
                architecture="arm64",
            )
        with pytest.raises(BuildConfigurationInvalid):
            await builds.create_configuration(
                project_id=project_id,
                name="slow",
                target_platform="LINUX",
                architecture="x86_64",
                build_timeout_seconds=99999,
            )
        with pytest.raises(BuildConfigurationInvalid):
            await builds.create_configuration(
                project_id=project_id,
                name="leaky",
                target_platform="LINUX",
                architecture="x86_64",
                env_allowlist=["API_KEY=sk-abcdefghijklmnopqrstuvwx"],
            )
        with pytest.raises(ValidationFailed):
            await builds.create_configuration(
                project_id=project_id,
                name="",
                target_platform="LINUX",
                architecture="x86_64",
            )


@pytest.mark.asyncio
async def test_export_preset_and_validation(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        builds = _builds(app)
        preset = await builds.register_export_preset(
            project_id=project_id,
            preset_name="Windows Desktop",
            platform="WINDOWS",
            export_path="build/windows/game.exe",
            template_required="windows_release",
            template_available=True,
        )
        assert preset.status == "VALID"

        config = await builds.create_configuration(
            project_id=project_id,
            name="win-release",
            target_platform="WINDOWS",
            architecture="x86_64",
            export_preset_name="Windows Desktop",
        )
        result = await builds.validate_configuration(config.configuration_id)
        assert result.ready is True, result.problems

        invalid_preset = await builds.register_export_preset(
            project_id=project_id,
            preset_name="Mac Missing Template",
            platform="MACOS",
            template_required="macos",
            template_available=False,
        )
        assert invalid_preset.status == "INVALID"
        assert invalid_preset.validation_errors

        mismatch = await builds.create_configuration(
            project_id=project_id,
            name="mac-with-windows-preset",
            target_platform="MACOS",
            architecture="arm64",
            export_preset_name="Windows Desktop",
        )
        mismatch_result = await builds.validate_configuration(mismatch.configuration_id)
        assert mismatch_result.ready is False
        assert any("平台不匹配" in problem for problem in mismatch_result.problems)

        with pytest.raises(ExportPresetInvalid):
            await builds.register_export_preset(
                project_id=project_id,
                preset_name="Leaky Preset",
                platform="LINUX",
                raw={"password": "hunter2"},
            )


@pytest.mark.asyncio
async def test_environment_status_and_dedup(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        builds = _builds(app)

        ready = await builds.register_environment(
            project_id=project_id,
            os_name="Windows",
            os_version="11",
            cpu_architecture="x86_64",
            godot_version="4.5.1",
            export_template_version="4.5.1",
            toolchain_versions={"msvc": "19.40"},
            sdk_versions={"WINDOWS": "10.0"},
            renderer="forward_plus",
            build_executor_version="1.0",
            target_platform="WINDOWS",
        )
        assert ready.status == "READY"

        duplicate = await builds.register_environment(
            project_id=project_id,
            os_name="Windows",
            os_version="11",
            cpu_architecture="x86_64",
            godot_version="4.5.1",
            export_template_version="4.5.1",
            toolchain_versions={"msvc": "19.40"},
            sdk_versions={"WINDOWS": "10.0"},
            renderer="forward_plus",
            build_executor_version="1.0",
            target_platform="WINDOWS",
        )
        assert duplicate.environment_id == ready.environment_id

        warnings = await builds.register_environment(
            project_id=project_id,
            os_name="Linux",
            os_version="24.04",
            cpu_architecture="x86_64",
            godot_version="4.5.1",
            export_template_version="4.5.1",
            sdk_versions={},
            target_platform="LINUX",
        )
        assert warnings.status == "READY_WITH_WARNINGS"

        blocked = await builds.register_environment(
            project_id=project_id,
            os_name="Linux",
            os_version="24.04",
            cpu_architecture="x86_64",
            godot_version="4.5.1",
            export_template_version="",
        )
        assert blocked.status == "BLOCKED"
        assert blocked.diagnostics["problems"]
