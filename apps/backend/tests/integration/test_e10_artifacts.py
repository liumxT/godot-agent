"""E10-T08 / T09 / T13 制品、交付包、来源与证据集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    ArtifactHashMismatch,
    BuildStateInvalid,
    NotFoundError,
    ValidationFailed,
)
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.packaging import PackagingService
from modules.build_release.provenance import BuildProvenanceService
from modules.project_registry.service import ProjectRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e10artifacts.db').as_posix()}",
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


def _provenance(app) -> BuildProvenanceService:
    return app.state.services.get("provenance_service", BuildProvenanceService)


def _files(payload: bytes = b"GAME") -> list[dict]:
    return [
        {"path": "game.exe", "size": len(payload), "hash": "sha256:deadbeef"},
    ]


@pytest.mark.asyncio
async def test_artifact_registration_versioning_and_idempotency(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        artifacts = _artifacts(app)
        first = await artifacts.register_artifact(
            project_id=project_id,
            platform="WINDOWS",
            architecture="x86_64",
            storage_reference="build/win/game.exe",
            files=_files(b"AAAA"),
            name="game.exe",
            format="exe",
        )
        assert first.artifact_version == 1
        again = await artifacts.register_artifact(
            project_id=project_id,
            platform="WINDOWS",
            architecture="x86_64",
            storage_reference="build/win/game.exe",
            files=_files(b"AAAA"),
            name="game.exe",
            format="exe",
        )
        assert again.artifact_id == first.artifact_id
        second = await artifacts.register_artifact(
            project_id=project_id,
            platform="WINDOWS",
            architecture="x86_64",
            storage_reference="build/win/game2.exe",
            files=[{"path": "game.exe", "size": 4, "hash": "sha256:cafebabe"}],
            name="game.exe",
            format="exe",
        )
        assert second.artifact_version == 2
        assert second.content_hash != first.content_hash
        assert await artifacts.verify_integrity(first.artifact_id, _files(b"AAAA")) is True
        with pytest.raises(ArtifactHashMismatch):
            await artifacts.verify_integrity(
                first.artifact_id,
                [{"path": "game.exe", "size": 4, "hash": "sha256:tampered"}],
            )


@pytest.mark.asyncio
async def test_artifact_verification_transitions(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        artifacts = _artifacts(app)
        artifact = await artifacts.register_artifact(
            project_id=project_id,
            platform="LINUX",
            architecture="x86_64",
            storage_reference="build/linux/game",
            files=_files(),
        )
        with pytest.raises(BuildStateInvalid):
            await artifacts.transition_verification(artifact.artifact_id, "VERIFIED")
        verified = await artifacts.mark_verified(artifact.artifact_id)
        assert verified.verification_status == "VERIFIED"
        required = await artifacts.require_verified(artifact.artifact_id)
        assert required.artifact_id == artifact.artifact_id


@pytest.mark.asyncio
async def test_package_create_and_verify(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        artifacts = _artifacts(app)
        packages = _packages(app)
        artifact = await artifacts.register_artifact(
            project_id=project_id,
            platform="WINDOWS",
            architecture="x86_64",
            storage_reference="build/win/game.exe",
            files=_files(),
            format="exe",
        )
        package = await packages.create_package(
            project_id=project_id, artifact_id=artifact.artifact_id, format="zip"
        )
        assert package.status == "CREATED"
        assert package.manifest["artifact_content_hash"] == artifact.content_hash
        verified = await packages.verify_package(package.package_id)
        assert verified.status == "VERIFIED"
        required = await packages.require_verified(package.package_id)
        assert required.package_id == package.package_id


@pytest.mark.asyncio
async def test_package_requires_files(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        # 空清单与不存在的制品都必须被拒绝
        with pytest.raises(ValidationFailed):
            await _artifacts(app).register_artifact(
                project_id=project_id,
                platform="WINDOWS",
                architecture="x86_64",
                storage_reference="build/win/empty",
                files=[],
            )
        with pytest.raises(NotFoundError):
            await _packages(app).create_package(
                project_id=project_id, artifact_id="missing-artifact"
            )


@pytest.mark.asyncio
async def test_provenance_and_evidence_append_only(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project(app, tmp_path)
        provenance = _provenance(app)
        first = await provenance.record_provenance(
            project_id=project_id,
            build_id="bld-1",
            attempt_id="bat-1",
            source_revision="abc123",
            environment_fingerprint="sha256:env",
            inputs={"config": "hash"},
            outputs={"artifact": "sha256:out"},
        )
        repeat = await provenance.record_provenance(
            project_id=project_id,
            build_id="bld-1",
            attempt_id="bat-1",
            source_revision="different",
        )
        assert repeat.provenance_id == first.provenance_id
        assert repeat.source_revision == "abc123"
        listed = await provenance.list_provenance("bld-1")
        assert len(listed) == 1

        evidence = await provenance.add_evidence(
            project_id=project_id,
            evidence_type="verification",
            reference="campaign-1",
            details={"status": "PASSED"},
        )
        assert evidence.evidence_type == "verification"
        page = await provenance.list_evidence(project_id)
        assert page["total"] == 1
        candidate = await provenance.add_evidence(
            project_id=project_id,
            evidence_type="approval",
            release_candidate_id="rc-1",
            reference="approval-1",
        )
        by_candidate = await provenance.list_candidate_evidence("rc-1")
        assert [item.evidence_id for item in by_candidate] == [candidate.evidence_id]
