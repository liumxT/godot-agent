"""E10-T11 / T14 发布候选与冒烟测试集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ReleaseCandidateInvalid, ReleaseStateInvalid
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.packaging import PackagingService
from modules.build_release.release_candidates import ReleaseCandidateService
from modules.build_release.smoke_test import SmokeTestService
from modules.project_registry.service import ProjectRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e10rc.db').as_posix()}",
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


def _artifacts(app) -> ArtifactRegistryService:
    return app.state.services.get("artifact_registry_service", ArtifactRegistryService)


def _packages(app) -> PackagingService:
    return app.state.services.get("packaging_service", PackagingService)


def _candidates(app) -> ReleaseCandidateService:
    return app.state.services.get("release_candidate_service", ReleaseCandidateService)


def _smoke(app) -> SmokeTestService:
    return app.state.services.get("smoke_test_service", SmokeTestService)


def _files() -> list[dict]:
    return [{"path": "game.exe", "size": 4, "hash": "sha256:deadbeef"}]


async def _verified_artifact(app, project_id: str):
    artifact = await _artifacts(app).register_artifact(
        project_id=project_id,
        platform="WINDOWS",
        architecture="x86_64",
        storage_reference="build/win/game.exe",
        files=_files(),
        format="exe",
    )
    return await _artifacts(app).mark_verified(artifact.artifact_id)


async def _verified_package(app, project_id: str, artifact_id: str):
    package = await _packages(app).create_package(
        project_id=project_id, artifact_id=artifact_id, format="zip"
    )
    return await _packages(app).verify_package(package.package_id)


@pytest.mark.asyncio
async def test_candidate_requires_verified_artifact(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        artifact = await _artifacts(app).register_artifact(
            project_id=project_id,
            platform="WINDOWS",
            architecture="x86_64",
            storage_reference="build/win/game.exe",
            files=_files(),
            format="exe",
        )
        with pytest.raises(ReleaseCandidateInvalid):
            await _candidates(app).create_candidate(
                project_id=project_id,
                version="1.0.0",
                artifact_id=artifact.artifact_id,
            )
        verified = await _artifacts(app).mark_verified(artifact.artifact_id)
        candidate = await _candidates(app).create_candidate(
            project_id=project_id,
            version="1.0.0",
            artifact_id=verified.artifact_id,
        )
        assert candidate.status == "DRAFT"
        assert candidate.manifest["artifact_content_hash"] == verified.content_hash


@pytest.mark.asyncio
async def test_candidate_requires_verified_package_binding(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        artifact = await _verified_artifact(app, project_id)
        package = await _packages(app).create_package(
            project_id=project_id, artifact_id=artifact.artifact_id, format="zip"
        )
        with pytest.raises(ReleaseCandidateInvalid):
            await _candidates(app).create_candidate(
                project_id=project_id,
                version="1.0.0",
                artifact_id=artifact.artifact_id,
                package_id=package.package_id,
            )
        verified_package = await _packages(app).verify_package(package.package_id)
        candidate = await _candidates(app).create_candidate(
            project_id=project_id,
            version="1.0.0",
            artifact_id=artifact.artifact_id,
            package_id=verified_package.package_id,
        )
        assert candidate.package_id == verified_package.package_id
        assert candidate.manifest["package_hash"] == verified_package.package_hash


@pytest.mark.asyncio
async def test_candidate_rejected_without_passing_smoke(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        artifact = await _verified_artifact(app, project_id)
        candidate = await _candidates(app).create_candidate(
            project_id=project_id,
            version="1.0.0",
            artifact_id=artifact.artifact_id,
        )
        await _smoke(app).record_smoke_test(
            project_id=project_id,
            artifact_id=artifact.artifact_id,
            checks=[{"name": "launch", "status": "SKIPPED"}],
        )
        result = await _candidates(app).validate_candidate(candidate.release_candidate_id)
        assert result.ready is False
        assert result.status == "REJECTED"
        assert any("冒烟" in problem for problem in result.problems)


@pytest.mark.asyncio
async def test_candidate_ready_after_passing_smoke(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        artifact = await _verified_artifact(app, project_id)
        package = await _verified_package(app, project_id, artifact.artifact_id)
        candidate = await _candidates(app).create_candidate(
            project_id=project_id,
            version="1.0.0",
            artifact_id=artifact.artifact_id,
            package_id=package.package_id,
        )
        smoke = await _smoke(app).record_smoke_test(
            project_id=project_id,
            artifact_id=artifact.artifact_id,
            release_candidate_id=candidate.release_candidate_id,
            checks=[
                {"name": "launch", "status": "PASSED"},
                {"name": "screenshot", "status": "PASSED"},
            ],
        )
        assert smoke.status == "PASSED"
        assert await _smoke(app).has_passed_for_artifact(artifact.artifact_id) is True
        result = await _candidates(app).validate_candidate(candidate.release_candidate_id)
        assert result.ready is True
        assert result.problems == []
        ready = await _candidates(app).require_ready(candidate.release_candidate_id)
        assert ready.status == "READY_FOR_APPROVAL"
        listed = await _smoke(app).list_for_candidate(candidate.release_candidate_id)
        assert [item.smoke_test_id for item in listed] == [smoke.smoke_test_id]


@pytest.mark.asyncio
async def test_candidate_idempotency_and_lifecycle(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        artifact = await _verified_artifact(app, project_id)
        first = await _candidates(app).create_candidate(
            project_id=project_id,
            version="1.0.0",
            artifact_id=artifact.artifact_id,
        )
        repeat = await _candidates(app).create_candidate(
            project_id=project_id,
            version="1.0.0",
            artifact_id=artifact.artifact_id,
        )
        assert repeat.release_candidate_id == first.release_candidate_id

        superseded = await _candidates(app).supersede_candidate(first.release_candidate_id)
        assert superseded.status == "SUPERSEDED"

        second = await _candidates(app).create_candidate(
            project_id=project_id,
            version="1.0.1",
            artifact_id=artifact.artifact_id,
        )
        with pytest.raises(ReleaseStateInvalid):
            await _candidates(app).invalidate_candidate(second.release_candidate_id)
