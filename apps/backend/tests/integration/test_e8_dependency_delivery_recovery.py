"""E8-M6 集成测试：依赖图、交付门禁与 UNKNOWN 恢复。"""

from __future__ import annotations

import io
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    AssetDeliveryBlocked,
    AssetRecoveryRequired,
    InvalidStateTransition,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.delivery import AssetDeliveryService, DeliveryRequest
from modules.asset_pipeline.dependencies import AssetDependencyService, DependencyEntry
from modules.asset_pipeline.license import (
    LicenseEvidenceInput,
    LicenseRequest,
    LicenseService,
)
from modules.asset_pipeline.models import (
    DELIVERY_DELIVERED,
    DELIVERY_READY,
    DELIVERY_UNKNOWN,
    DELIVERY_WAITING_APPROVAL,
    GENERATION_UNKNOWN,
    IMPORT_IMPORTED,
    IMPORT_UNKNOWN,
    PROCESSING_SUCCEEDED,
    PROCESSING_UNKNOWN,
    QUALITY_MACHINE_PASSED,
    SOURCE_AI_GENERATED,
    STORAGE_GENERATED,
    AssetDeliveryModel,
    AssetGenerationModel,
    AssetImportJobModel,
    AssetProcessingJobModel,
    AssetStorageObjectModel,
)
from modules.asset_pipeline.provenance import ProvenanceRequest, ProvenanceService
from modules.asset_pipeline.quality import QualityControlService
from modules.asset_pipeline.recovery import AssetRecoveryService
from modules.asset_pipeline.service import AssetService
from modules.asset_pipeline.storage import AssetStorage
from modules.asset_pipeline.versioning import AssetVersionService
from modules.changeset.service import ChangeSetService
from modules.project_registry.service import ProjectRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8m6.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _database(app) -> DatabaseService:
    return app.state.services.get("database", DatabaseService)


def _png(width: int = 8, height: int = 8) -> bytes:
    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([1, 1, width - 2, height - 2], fill=(10, 20, 30, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _project(app, tmp_path: Path):
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    projects = app.state.services.get(
        "project_registry_service", ProjectRegistryService
    )
    return await projects.register(project_root=str(root), name="E8 M6")


async def _asset(app, project_id: str, *, name: str = "hero"):
    assets = app.state.services.get("asset_service", AssetService)
    return await assets.create(
        project_id=project_id,
        name=name,
        category="IMAGE",
        asset_type="CHARACTER",
    )


async def _seed_version(
    app, project_id: str, asset_id: str, data: bytes, *, filename: str = "hero.png"
):
    storage = app.state.services.get("asset_storage", AssetStorage)
    versions = app.state.services.get(
        "asset_version_service", AssetVersionService
    )
    relative_path = f"{asset_id}/{filename}"
    written = storage.write_bytes(project_id, STORAGE_GENERATED, relative_path, data)
    version = await versions.create_version(
        asset_id,
        content_hash=str(written["content_hash"]),
        source_type=SOURCE_AI_GENERATED,
        metadata={"filename": filename},
        change_reason="initial_asset",
        created_by="tester",
    )
    async with _database(app).session() as session, transaction(session):
        session.add(
            AssetStorageObjectModel(
                object_id="asob_" + uuid4().hex[:12],
                project_id=project_id,
                asset_version_id=version.version_id,
                storage_area=STORAGE_GENERATED,
                relative_path=relative_path,
                content_hash=str(written["content_hash"]),
                size_bytes=int(written["size_bytes"]),
                mime_type="image/png",
                created_at=version.created_at,
            )
        )
    return version


async def _approve_quality(app, project_id: str, asset_id: str, version_id: str):
    quality = app.state.services.get("asset_quality_control", QualityControlService)
    machine = await quality.run_machine_review(project_id, asset_id, version_id)
    assert machine.review_status == QUALITY_MACHINE_PASSED
    human = await quality.request_human_review(project_id, asset_id, version_id)
    await quality.record_human_decision(
        project_id,
        asset_id,
        human.review_id,
        approved=True,
        reviewer_id="artist",
    )


async def _verify_license(app, project_id: str, asset_id: str, version_id: str):
    licenses = app.state.services.get("asset_license_service", LicenseService)
    record = await licenses.record(
        LicenseRequest(
            project_id=project_id,
            asset_id=asset_id,
            asset_version_id=version_id,
            license_name="studio-owned",
            source_type=SOURCE_AI_GENERATED,
            evidence=[
                LicenseEvidenceInput(
                    evidence_type="LICENSE_FILE", reference="legal/studio-eula.pdf"
                )
            ],
        )
    )
    return await licenses.verify(
        project_id,
        record.license_id,
        reviewer_id="legal",
        commercial_use=True,
        modification_allowed=True,
        redistribution_allowed=True,
    )


async def _record_provenance(app, project_id: str, asset_id: str, version):
    provenance = app.state.services.get(
        "asset_provenance_service", ProvenanceService
    )
    return await provenance.record(
        ProvenanceRequest(
            project_id=project_id,
            asset_id=asset_id,
            asset_version_id=version.version_id,
            source_type=SOURCE_AI_GENERATED,
            provider_id="provider-a",
            model_id="image-model",
            generation_id="gen_m6_1",
            output_hashes=[version.content_hash],
        )
    )


async def _deliverable_version(
    app,
    tmp_path: Path,
    *,
    human_review: bool = True,
    license_ready: bool = True,
    provenance_ready: bool = True,
):
    project = await _project(app, tmp_path)
    asset = await _asset(app, project.project_id)
    version = await _seed_version(app, project.project_id, asset.asset_id, _png())
    quality = app.state.services.get("asset_quality_control", QualityControlService)
    await quality.run_machine_review(
        project.project_id, asset.asset_id, version.version_id
    )
    if human_review:
        await _approve_quality(
            app, project.project_id, asset.asset_id, version.version_id
        )
    if license_ready:
        await _verify_license(
            app, project.project_id, asset.asset_id, version.version_id
        )
    if provenance_ready:
        await _record_provenance(
            app, project.project_id, asset.asset_id, version
        )
    return project, asset, version


def _delivery_service(app) -> AssetDeliveryService:
    return app.state.services.get("asset_delivery_service", AssetDeliveryService)


def _delivery_request(project_id: str, asset_id: str, version_id: str) -> DeliveryRequest:
    return DeliveryRequest(
        project_id=project_id,
        asset_id=asset_id,
        asset_version_id=version_id,
        target_path="res://assets/hero.png",
        resource_type="Texture2D",
        created_by="tester",
    )


async def _insert_import(
    app,
    project_id: str,
    asset_version_id: str,
    *,
    status: str = IMPORT_IMPORTED,
    uid: str | None = "uid://e8m6hero",
    import_job_id: str = "aij_m6",
) -> str:
    async with _database(app).session() as session, transaction(session):
        session.add(
            AssetImportJobModel(
                import_job_id=import_job_id,
                project_id=project_id,
                asset_version_id=asset_version_id,
                target_path="res://assets/hero.png",
                godot_resource_type="Texture2D",
                import_status=status,
                godot_uid=uid,
                import_evidence_id=None,
                changeset_id=None,
                editor_session_id=None,
                idempotency_key=None,
                created_by="tester",
                created_at=utcnow(),
                started_at=None,
                completed_at=None,
            )
        )
    return import_job_id


# ----------------------------------------------------------------------
# T14 依赖图
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dependency_record_is_idempotent_and_reports_impact(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(app, project.project_id, asset.asset_id, _png())
        service = app.state.services.get(
            "asset_dependency_service", AssetDependencyService
        )
        entry = DependencyEntry(
            source_type="SCRIPT",
            source_reference="res://scripts/player.gd",
            target_type="TEXTURE",
            target_reference=f"{asset.asset_id}/hero.png",
            dependency_type="SCRIPT_REFERENCE",
        )

        created = await service.record(
            project.project_id, version.version_id, [entry]
        )
        assert len(created) == 1
        assert created[0].dependency_type == "SCRIPT_REFERENCE"

        again = await service.record(
            project.project_id, version.version_id, [entry]
        )
        assert again == []

        references = await service.list_referencing(
            project.project_id, f"{asset.asset_id}/hero.png"
        )
        assert len(references) == 1

        impact = await service.replacement_impact(
            project.project_id, version.version_id
        )
        assert impact.referenced is True
        assert impact.requires_changeset is True

        missing = await service.missing_references(
            project.project_id, ["res://scripts/player.gd"]
        )
        assert [item.target_reference for item in missing] == [
            f"{asset.asset_id}/hero.png"
        ]


@pytest.mark.asyncio
async def test_dependency_cycle_and_orphan_detection(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(app, project.project_id, asset.asset_id, _png())
        orphan_asset = await _asset(app, project.project_id, name="orphan")
        await _seed_version(app, project.project_id, orphan_asset.asset_id, _png())
        service = app.state.services.get(
            "asset_dependency_service", AssetDependencyService
        )
        await service.record(
            project.project_id,
            version.version_id,
            [
                DependencyEntry(
                    source_type="SCRIPT",
                    source_reference="res://a.gd",
                    target_type="SCRIPT",
                    target_reference="res://b.gd",
                    dependency_type="SCRIPT_REFERENCE",
                ),
                DependencyEntry(
                    source_type="SCRIPT",
                    source_reference="res://b.gd",
                    target_type="SCRIPT",
                    target_reference="res://a.gd",
                    dependency_type="SCRIPT_REFERENCE",
                ),
            ],
        )

        cycles = await service.detect_cycles(project.project_id)
        assert cycles == [["res://a.gd", "res://b.gd"]]

        orphans = await service.orphan_asset_ids(project.project_id)
        assert orphan_asset.asset_id in orphans
        assert asset.asset_id not in orphans


# ----------------------------------------------------------------------
# T15 交付与 ChangeSet
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_requires_human_review_and_verified_license(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _deliverable_version(
            app, tmp_path, human_review=False
        )
        service = _delivery_service(app)

        with pytest.raises(AssetDeliveryBlocked):
            await service.prepare(
                _delivery_request(
                    project.project_id, asset.asset_id, version.version_id
                )
            )

        relaxed = DeliveryRequest(
            project_id=project.project_id,
            asset_id=asset.asset_id,
            asset_version_id=version.version_id,
            target_path="res://assets/hero.png",
            require_human_review=False,
            created_by="tester",
        )
        delivery = await service.prepare(relaxed)
        assert delivery.delivery_status == DELIVERY_READY
        assert delivery.target_path == "res://assets/hero.png"
        assert delivery.changeset_id


@pytest.mark.asyncio
async def test_delivery_full_flow_with_import_evidence(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _deliverable_version(app, tmp_path)
        service = _delivery_service(app)
        delivery = await service.prepare(
            _delivery_request(project.project_id, asset.asset_id, version.version_id)
        )

        approval = await service.submit_for_approval(delivery.delivery_id)
        assert approval.target_hash
        waiting = await service.get(delivery.delivery_id)
        assert waiting.delivery_status == DELIVERY_WAITING_APPROVAL

        approved = await service.approve(
            delivery.delivery_id, approval.approval_id, actor_id="lead"
        )
        assert approved.delivery_status == "APPROVED"

        applied = await service.begin_apply(
            delivery.delivery_id, approval.approval_id, actor_id="lead"
        )
        assert applied.delivery_status == "APPLYING"

        job_id = await _insert_import(
            app, project.project_id, version.version_id
        )
        importing = await service.mark_importing(delivery.delivery_id, job_id)
        assert importing.delivery_status == "IMPORTING"

        delivered = await service.mark_delivered(delivery.delivery_id)
        assert delivered.delivery_status == DELIVERY_DELIVERED
        assert delivered.delivered_at is not None
        assert delivered.import_job_id == job_id


@pytest.mark.asyncio
async def test_delivery_hash_change_invalidates_approval(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _deliverable_version(app, tmp_path)
        service = _delivery_service(app)
        delivery = await service.prepare(
            _delivery_request(project.project_id, asset.asset_id, version.version_id)
        )
        await service.submit_for_approval(delivery.delivery_id)
        changesets = app.state.services.get("changeset_service", ChangeSetService)
        await changesets.replace_manifest(
            delivery.changeset_id,
            [
                {
                    "resource_path": "assets/hero.png",
                    "operation_type": "CREATE",
                    "new_content_hash": "f" * 64,
                    "resource_type": "Texture2D",
                    "risk_level": "MEDIUM",
                }
            ],
        )

        check = await service.check_approval(delivery.delivery_id)
        assert check["valid"] is False

        with pytest.raises((InvalidStateTransition, AssetDeliveryBlocked)):
            await service.approve(
                delivery.delivery_id, "apr_missing", actor_id="lead"
            )


@pytest.mark.asyncio
async def test_delivery_blocks_without_real_import(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _deliverable_version(app, tmp_path)
        service = _delivery_service(app)
        delivery = await service.prepare(
            _delivery_request(project.project_id, asset.asset_id, version.version_id)
        )
        approval = await service.submit_for_approval(delivery.delivery_id)
        await service.approve(
            delivery.delivery_id, approval.approval_id, actor_id="lead"
        )
        await service.begin_apply(
            delivery.delivery_id, approval.approval_id, actor_id="lead"
        )
        job_id = await _insert_import(
            app,
            project.project_id,
            version.version_id,
            status=IMPORT_IMPORTED,
            uid=None,
            import_job_id="aij_no_uid",
        )
        await service.mark_importing(delivery.delivery_id, job_id)
        with pytest.raises(AssetDeliveryBlocked):
            await service.mark_delivered(delivery.delivery_id)


# ----------------------------------------------------------------------
# T16 恢复
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_lists_unknown_and_resolves_with_evidence(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _deliverable_version(app, tmp_path)
        now = utcnow()
        async with _database(app).session() as session, transaction(session):
            session.add(
                AssetGenerationModel(
                    generation_id="agn_m6_unknown",
                    asset_id=asset.asset_id,
                    brief_id=None,
                    requested_spec_json="{}",
                    provider_id="provider-a",
                    model_id="image-model",
                    provider_job_id="job-1",
                    generation_status=GENERATION_UNKNOWN,
                    result_version_id=None,
                    error_code=None,
                    idempotency_key="generation:agn_m6_unknown",
                    request_hash="a" * 64,
                    budget_reservation_json="{}",
                    created_by="tester",
                    created_at=now,
                    submitted_at=now,
                    last_checked_at=None,
                    completed_at=None,
                )
            )
            session.add(
                AssetProcessingJobModel(
                    job_id="apj_m6_unknown",
                    asset_id=asset.asset_id,
                    input_version_id=version.version_id,
                    output_version_id=version.version_id,
                    processing_graph_json="{}",
                    processing_status=PROCESSING_UNKNOWN,
                    execution_metadata_json="{}",
                    idempotency_key="processing:apj_m6_unknown",
                    created_by="tester",
                    created_at=now,
                    started_at=now,
                    completed_at=None,
                )
            )
            session.add(
                AssetImportJobModel(
                    import_job_id="aij_m6_unknown",
                    project_id=project.project_id,
                    asset_version_id=version.version_id,
                    target_path="res://assets/hero.png",
                    godot_resource_type="Texture2D",
                    import_status=IMPORT_UNKNOWN,
                    godot_uid=None,
                    import_evidence_id=None,
                    changeset_id=None,
                    editor_session_id=None,
                    idempotency_key=None,
                    created_by="tester",
                    created_at=now,
                    started_at=now,
                    completed_at=None,
                )
            )
            session.add(
                AssetDeliveryModel(
                    delivery_id="adl_m6_unknown",
                    asset_id=asset.asset_id,
                    asset_version_id=version.version_id,
                    project_id=project.project_id,
                    changeset_id=None,
                    approval_id=None,
                    import_job_id=None,
                    delivery_status=DELIVERY_UNKNOWN,
                    delivered_at=None,
                    created_by="tester",
                    created_at=now,
                )
            )
        recovery = app.state.services.get(
            "asset_recovery_service", AssetRecoveryService
        )

        inventory = await recovery.list_unknown(project.project_id)
        assert inventory.generation_ids == ("agn_m6_unknown",)
        assert inventory.processing_job_ids == ("apj_m6_unknown",)
        assert inventory.import_job_ids == ("aij_m6_unknown",)
        assert inventory.delivery_ids == ("adl_m6_unknown",)

        assert (
            AssetRecoveryService.idempotency_key("generation", "agn_m6_unknown")
            == "generation:agn_m6_unknown"
        )
        with pytest.raises(AssetRecoveryRequired):
            AssetRecoveryService.idempotency_key("unknown", "x")

        resolved = await recovery.resolve_processing(
            project.project_id, "apj_m6_unknown"
        )
        assert resolved == PROCESSING_SUCCEEDED

        with pytest.raises(AssetRecoveryRequired):
            await recovery.resolve_import(project.project_id, "aij_m6_unknown")

        with pytest.raises(AssetRecoveryRequired):
            await recovery.resolve_generation(project.project_id, "agn_m6_unknown")


@pytest.mark.asyncio
async def test_recovery_reconciles_unknown_delivery_with_import(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _deliverable_version(app, tmp_path)
        job_id = await _insert_import(
            app,
            project.project_id,
            version.version_id,
            import_job_id="aij_m6_recover",
        )
        now = utcnow()
        async with _database(app).session() as session, transaction(session):
            session.add(
                AssetDeliveryModel(
                    delivery_id="adl_m6_recover",
                    asset_id=asset.asset_id,
                    asset_version_id=version.version_id,
                    project_id=project.project_id,
                    changeset_id=None,
                    approval_id=None,
                    import_job_id=job_id,
                    delivery_status=DELIVERY_UNKNOWN,
                    delivered_at=None,
                    created_by="tester",
                    created_at=now,
                )
            )
        recovery = app.state.services.get(
            "asset_recovery_service", AssetRecoveryService
        )

        view = await recovery.resolve_delivery(
            project.project_id, "adl_m6_recover"
        )
        assert view.delivery_status == DELIVERY_DELIVERED

        summary = await recovery.recover(project.project_id)
        assert summary["inventory"].total == 0
