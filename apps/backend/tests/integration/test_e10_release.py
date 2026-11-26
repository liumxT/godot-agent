"""E10-T10 / T12 / T15 / T16 签名、审批、发布与本地交付集成测试。"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    ReleaseApprovalMismatch,
    ReleaseApprovalRequired,
    ReleaseStateInvalid,
    SigningInvalid,
    SigningUnknown,
)
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.packaging import PackagingService
from modules.build_release.release_approvals import ReleaseApprovalService
from modules.build_release.release_candidates import ReleaseCandidateService
from modules.build_release.release_manager import ReleaseManagerService
from modules.build_release.signing import SigningOutcome, SigningService
from modules.build_release.smoke_test import SmokeTestService
from modules.project_registry.service import ProjectRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e10release.db').as_posix()}",
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


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


async def _artifact(app, project_id: str, root: Path, payload: bytes = b"GAME"):
    (root / "build").mkdir(parents=True, exist_ok=True)
    (root / "build" / "game.exe").write_bytes(payload)
    files = [
        {
            "path": "build/game.exe",
            "size": len(payload),
            "hash": _digest(payload),
        }
    ]
    artifacts = _service(app, "artifact_registry_service", ArtifactRegistryService)
    artifact = await artifacts.register_artifact(
        project_id=project_id,
        platform="WINDOWS",
        architecture="x86_64",
        storage_reference="build/game.exe",
        files=files,
        format="exe",
    )
    return await artifacts.mark_verified(artifact.artifact_id)


async def _ready_candidate(app, project_id: str, artifact_id: str):
    packages = _service(app, "packaging_service", PackagingService)
    package = await packages.create_package(
        project_id=project_id, artifact_id=artifact_id, format="zip"
    )
    await packages.verify_package(package.package_id)
    candidates = _service(app, "release_candidate_service", ReleaseCandidateService)
    candidate = await candidates.create_candidate(
        project_id=project_id,
        version="1.0.0",
        artifact_id=artifact_id,
        package_id=package.package_id,
    )
    smoke = _service(app, "smoke_test_service", SmokeTestService)
    await smoke.record_smoke_test(
        project_id=project_id,
        artifact_id=artifact_id,
        checks=[{"name": "launch", "status": "PASSED"}],
    )
    result = await candidates.validate_candidate(candidate.release_candidate_id)
    assert result.ready is True
    return candidate


class _FakeSigningAdapter:
    def __init__(self, outcome: SigningOutcome) -> None:
        self._outcome = outcome

    async def sign(self, *, profile, artifact) -> SigningOutcome:
        return self._outcome


@pytest.mark.asyncio
async def test_signing_profile_and_attempt(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, root = await _project(app, tmp_path)
        signing = _service(app, "signing_service", SigningService)
        with pytest.raises(SigningInvalid):
            await signing.register_profile(
                project_id=project_id,
                platform="WINDOWS",
                signing_method="signtool",
                credential_reference="password=hunter2",
            )
        profile = await signing.register_profile(
            project_id=project_id,
            platform="WINDOWS",
            signing_method="signtool",
            certificate_reference="keychain://win/cert",
            credential_reference="keychain://win/key",
        )
        assert profile.status == "ACTIVE"

        artifact = await _artifact(app, project_id, root)
        attempt = await signing.sign_artifact(
            artifact_id=artifact.artifact_id,
            signing_profile_id=profile.signing_profile_id,
            adapter=_FakeSigningAdapter(
                SigningOutcome(
                    status="SUCCEEDED",
                    tool_version="signtool 1.0",
                    certificate_fingerprint="sha256:cert",
                    verified=True,
                )
            ),
        )
        assert attempt.status == "SUCCEEDED"
        assert attempt.verified is True
        required = await signing.require_signed(artifact.artifact_id)
        assert required.signing_attempt_id == attempt.signing_attempt_id


@pytest.mark.asyncio
async def test_signing_unknown_requires_reconciliation(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, root = await _project(app, tmp_path)
        signing = _service(app, "signing_service", SigningService)
        profile = await signing.register_profile(
            project_id=project_id, platform="WINDOWS", signing_method="signtool"
        )
        artifact = await _artifact(app, project_id, root)
        attempt = await signing.sign_artifact(
            artifact_id=artifact.artifact_id,
            signing_profile_id=profile.signing_profile_id,
            adapter=_FakeSigningAdapter(SigningOutcome(status="UNKNOWN")),
        )
        assert attempt.status == "UNKNOWN"
        with pytest.raises(SigningUnknown):
            await signing.sign_artifact(
                artifact_id=artifact.artifact_id,
                signing_profile_id=profile.signing_profile_id,
            )
        reconciled = await signing.reconcile_attempt(
            attempt.signing_attempt_id, succeeded=True, certificate_fingerprint="sha256:cert"
        )
        assert reconciled.status == "SUCCEEDED"
        assert reconciled.verified is True


@pytest.mark.asyncio
async def test_release_requires_approval_binding(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, root = await _project(app, tmp_path)
        artifact = await _artifact(app, project_id, root)
        candidate = await _ready_candidate(app, project_id, artifact.artifact_id)
        approvals = _service(app, "release_approval_service", ReleaseApprovalService)
        approval = await approvals.request_approval(
            release_candidate_id=candidate.release_candidate_id,
            distribution_channel="LOCAL_EXPORT",
        )
        assert approval.status == "PENDING"
        with pytest.raises(ReleaseApprovalRequired):
            await approvals.require_approved(approval.approval_id)

        approved = await approvals.approve(approval.approval_id, approved_by="owner-1")
        assert approved.status == "APPROVED"
        assert approved.approved_by == "owner-1"

        releases = _service(app, "release_manager_service", ReleaseManagerService)
        with pytest.raises(ReleaseApprovalMismatch):
            await releases.create_release(
                release_candidate_id=candidate.release_candidate_id,
                approval_id=approval.approval_id,
                channel="LOCAL",
            )


@pytest.mark.asyncio
async def test_local_release_lifecycle(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, root = await _project(app, tmp_path)
        artifact = await _artifact(app, project_id, root)
        candidate = await _ready_candidate(app, project_id, artifact.artifact_id)
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
        assert release.status == "PENDING"
        with pytest.raises(ReleaseStateInvalid):
            await releases.start_release(release.release_id, target_reference=str(tmp_path))

        authorized = await releases.authorize_release(release.release_id)
        assert authorized.status == "AUTHORIZED"

        target = tmp_path / "delivery"
        target.mkdir()
        published = await releases.start_release(release.release_id, target_reference=str(target))
        assert published.status == "PUBLISHED"
        delivered = target / "game.exe"
        assert delivered.exists()

        repeated = await releases.start_release(release.release_id, target_reference=str(target))
        assert repeated.status == "PUBLISHED"
        operations = await releases.list_operations(release.release_id)
        assert len(operations) == 1
        assert operations[0].operation_status == "SUCCEEDED"

        verified = await releases.verify_release(release.release_id)
        assert verified.status == "COMPLETED"

        rolled_back = await releases.rollback_release(release.release_id)
        assert rolled_back.status == "ROLLED_BACK"


@pytest.mark.asyncio
async def test_local_release_withdraw_removes_delivery(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project_id, root = await _project(app, tmp_path)
        artifact = await _artifact(app, project_id, root)
        candidate = await _ready_candidate(app, project_id, artifact.artifact_id)
        approvals = _service(app, "release_approval_service", ReleaseApprovalService)
        approval = await approvals.request_approval(
            release_candidate_id=candidate.release_candidate_id,
            distribution_channel="LOCAL",
        )
        await approvals.approve(approval.approval_id, approved_by="owner-1")
        releases = _service(app, "release_manager_service", ReleaseManagerService)
        release = await releases.create_release(
            release_candidate_id=candidate.release_candidate_id,
            approval_id=approval.approval_id,
            channel="LOCAL",
        )
        await releases.authorize_release(release.release_id)
        target = tmp_path / "withdraw"
        target.mkdir()
        published = await releases.start_release(release.release_id, target_reference=str(target))
        assert published.status == "PUBLISHED"
        delivered = target / "game.exe"
        assert delivered.exists()

        withdrawn = await releases.withdraw_release(release.release_id)
        assert withdrawn.status == "WITHDRAWN"
        assert not delivered.exists()
