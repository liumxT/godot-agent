"""E8-T20 验收测试：Platformer Demo 资产闭环、安全与故障注入。"""

from __future__ import annotations

import hashlib
import io
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    AssetDeliveryBlocked,
    AssetPathInvalid,
    AssetRecoveryRequired,
    NotFoundError,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.briefs import AssetBriefService
from modules.asset_pipeline.dashboard import AssetDashboardService
from modules.asset_pipeline.delivery import AssetDeliveryService, DeliveryRequest
from modules.asset_pipeline.dependencies import AssetDependencyService, DependencyEntry
from modules.asset_pipeline.imports import GodotImportService, ImportRequest
from modules.asset_pipeline.license import (
    LicenseEvidenceInput,
    LicenseRequest,
    LicenseService,
)
from modules.asset_pipeline.models import (
    DELIVERY_DELIVERED,
    IMPORT_IMPORTED,
    LICENSE_EXPIRED,
    PROCESSING_UNKNOWN,
    QUALITY_HUMAN_APPROVED,
    SOURCE_AI_GENERATED,
    STORAGE_GENERATED,
    AssetProcessingJobModel,
    AssetStorageObjectModel,
)
from modules.asset_pipeline.processing import (
    ProcessingPipelineService,
    ProcessingRequest,
)
from modules.asset_pipeline.provenance import ProvenanceRequest, ProvenanceService
from modules.asset_pipeline.quality import QualityControlService
from modules.asset_pipeline.recovery import AssetRecoveryService
from modules.asset_pipeline.repository import AssetStorageObjectRepository
from modules.asset_pipeline.service import AssetService
from modules.asset_pipeline.storage import AssetStorage
from modules.asset_pipeline.versioning import AssetVersionService
from modules.client.models import CLIENT_STATUS_ACTIVE, ClientModel
from modules.editor_command.hub import EditorCommandResponse
from modules.editor_session.models import BINDING_CONNECTED, EditorSessionModel
from modules.project_registry.service import ProjectRegistryService
from modules.session.models import SESSION_STATUS_ACTIVE, SessionModel


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8m8.db').as_posix()}",
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
    draw.rectangle([1, 1, width - 2, height - 2], fill=(30, 140, 200, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _project(app, tmp_path: Path, *, name: str = "Platformer Demo"):
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    projects = app.state.services.get(
        "project_registry_service", ProjectRegistryService
    )
    return await projects.register(project_root=str(root), name=name)


async def _asset(app, project_id: str, *, name: str = "player") -> object:
    assets = app.state.services.get("asset_service", AssetService)
    return await assets.create(
        project_id=project_id,
        name=name,
        category="IMAGE",
        asset_type="CHARACTER",
    )


async def _seed_version(app, project_id: str, asset_id: str, data: bytes):
    storage = app.state.services.get("asset_storage", AssetStorage)
    versions = app.state.services.get("asset_version_service", AssetVersionService)
    relative_path = f"{asset_id}/player_idle.png"
    written = storage.write_bytes(project_id, STORAGE_GENERATED, relative_path, data)
    version = await versions.create_version(
        asset_id,
        content_hash=str(written["content_hash"]),
        source_type=SOURCE_AI_GENERATED,
        metadata={"filename": "player_idle.png"},
        change_reason="platformer_generation",
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


async def _bind_editor(app, project_id: str, *, session_id: str = "ses_e8m8"):
    now = utcnow()
    async with _database(app).session() as session, transaction(session):
        session.add(
            ClientModel(
                client_id="cli_e8m8",
                client_type="editor",
                client_name="E8 M8",
                status=CLIENT_STATUS_ACTIVE,
                created_at=now,
                last_seen_at=now,
            )
        )
        await session.flush()
        session.add(
            SessionModel(
                session_id=session_id,
                client_id="cli_e8m8",
                token_hash=hashlib.sha256(session_id.encode()).hexdigest(),
                status=SESSION_STATUS_ACTIVE,
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        await session.flush()
        session.add(
            EditorSessionModel(
                session_id=session_id,
                editor_instance_id="edi_e8m8",
                project_id=project_id,
                godot_version="4.5.1",
                plugin_version="0.1.0",
                transport="websocket",
                binding_status=BINDING_CONNECTED,
                connected_at=now,
                last_seen_at=now,
            )
        )
    return session_id


class _FakeConnection:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def send_command(self, action: str, payload: dict, *, timeout: float):
        self.calls.append((action, payload))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeHub:
    def __init__(self, connection) -> None:
        self.connection = connection

    def get(self, session_id: str):
        return self.connection


def _imported(uid: str = "uid://e8m8player") -> EditorCommandResponse:
    return EditorCommandResponse(
        success=True,
        data={
            "status": "SUCCEEDED",
            "output": {
                "phase": "IMPORTED",
                "imported": True,
                "scanning": False,
                "resource_uid": uid,
                "resource_type": "Texture2D",
                "godot_version": "4.5.1",
                "path": "res://art/player.png",
            },
            "checks": [],
            "evidence_refs": [],
        },
        error=None,
    )


@pytest.mark.asyncio
async def test_platformer_demo_full_asset_pipeline_closure(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(
            app, project.project_id, asset.asset_id, _png()
        )

        briefs = app.state.services.get("asset_brief_service", AssetBriefService)
        brief = await briefs.create(
            project_id=project.project_id,
            title="Player Idle",
            asset_category="IMAGE",
            asset_id=asset.asset_id,
            visual_direction="统一像素风，16x16",
            technical_constraints={
                "format": "png",
                "width": 16,
                "height": 16,
                "alpha_required": True,
                "transparent_background": True,
                "pixel_art": True,
                "godot_resource": {"resource_type": "Texture2D", "properties": {}},
            },
            acceptance_criteria=("角色轮廓清晰", "透明背景"),
            created_by="designer",
        )
        await briefs.propose(brief.brief_id)
        approved_brief = await briefs.approve(brief.brief_id)
        assert approved_brief.status == "APPROVED"

        provenance = app.state.services.get(
            "asset_provenance_service", ProvenanceService
        )
        await provenance.record(
            ProvenanceRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                asset_version_id=version.version_id,
                source_type=SOURCE_AI_GENERATED,
                provider_id="provider-a",
                model_id="image-model",
                generation_id="gen_platformer_1",
                prompt_version_id=brief.brief_id,
                seed=str(42),
                output_hashes=[version.content_hash],
                operator_user_id="designer",
            )
        )

        processing = app.state.services.get(
            "asset_processing_pipeline", ProcessingPipelineService
        )
        job = await processing.submit(
            ProcessingRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                input_version_id=version.version_id,
                graph={
                    "nodes": [
                        {"id": "decode", "processor": "image.decode"},
                        {
                            "id": "resize",
                            "processor": "image.resize",
                            "depends_on": ["decode"],
                            "parameters": {
                                "width": 16,
                                "height": 16,
                                "resample": "nearest",
                            },
                        },
                    ]
                },
                created_by="tester",
            )
        )
        assert job.output_version_id is not None
        processed_id = job.output_version_id

        async with _database(app).session() as session:
            objects = await AssetStorageObjectRepository(session).list_for_version(
                processed_id
            )
        assert len(objects) == 1
        output = objects[0]
        processed_bytes = app.state.services.get(
            "asset_storage", AssetStorage
        ).read_bytes(project.project_id, output.storage_area, output.relative_path)

        quality = app.state.services.get(
            "asset_quality_control", QualityControlService
        )
        machine = await quality.run_machine_review(
            project.project_id, asset.asset_id, processed_id
        )
        assert machine.review_status == "MACHINE_PASSED"
        human = await quality.request_human_review(
            project.project_id, asset.asset_id, processed_id
        )
        final_review = await quality.record_human_decision(
            project.project_id,
            asset.asset_id,
            human.review_id,
            approved=True,
            reviewer_id="artist",
        )
        assert final_review.review_status == QUALITY_HUMAN_APPROVED

        licenses = app.state.services.get("asset_license_service", LicenseService)
        license_view = await licenses.record(
            LicenseRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                asset_version_id=processed_id,
                license_name="studio-owned",
                source_type=SOURCE_AI_GENERATED,
                evidence=[
                    LicenseEvidenceInput(
                        evidence_type="LICENSE_FILE",
                        reference="legal/studio-eula.pdf",
                    )
                ],
            )
        )
        verified = await licenses.verify(
            project.project_id,
            license_view.license_id,
            reviewer_id="legal",
            commercial_use=True,
            modification_allowed=True,
            redistribution_allowed=True,
        )
        assert verified.verification_status == "VERIFIED"

        dependencies = app.state.services.get(
            "asset_dependency_service", AssetDependencyService
        )
        await dependencies.record(
            project.project_id,
            processed_id,
            [
                DependencyEntry(
                    source_type="SCENE",
                    source_reference="res://scenes/player.tscn",
                    target_type="TEXTURE",
                    target_reference=output.relative_path,
                    dependency_type="DIRECT_REFERENCE",
                )
            ],
        )

        delivery_service = app.state.services.get(
            "asset_delivery_service", AssetDeliveryService
        )
        delivery = await delivery_service.prepare(
            DeliveryRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                asset_version_id=processed_id,
                target_path="res://art/player.png",
                resource_type="Texture2D",
                created_by="pipeline",
            )
        )
        approval = await delivery_service.submit_for_approval(delivery.delivery_id)
        await delivery_service.approve(
            delivery.delivery_id, approval.approval_id, actor_id="lead"
        )
        await delivery_service.begin_apply(
            delivery.delivery_id, approval.approval_id, actor_id="lead"
        )

        target = tmp_path / "game" / "art" / "player.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(processed_bytes)
        session_id = await _bind_editor(app, project.project_id)
        imports = GodotImportService(
            _database(app),
            hub=_FakeHub(_FakeConnection([_imported()])),
            projects=app.state.services.get(
                "project_registry_service", ProjectRegistryService
            ),
        )
        import_view = await imports.submit(
            ImportRequest(
                project_id=project.project_id,
                asset_version_id=processed_id,
                target_path="res://art/player.png",
                session_id=session_id,
                resource_type="Texture2D",
                created_by="pipeline",
            )
        )
        assert import_view.import_status == IMPORT_IMPORTED
        assert import_view.godot_uid == "uid://e8m8player"

        await delivery_service.mark_importing(
            delivery.delivery_id, import_view.import_job_id
        )
        delivered = await delivery_service.mark_delivered(delivery.delivery_id)
        assert delivered.delivery_status == DELIVERY_DELIVERED
        assert delivered.delivered_at is not None

        impact = await dependencies.replacement_impact(
            project.project_id, processed_id
        )
        assert [item.source_reference for item in impact.references] == [
            "res://scenes/player.tscn"
        ]

        dashboard = app.state.services.get(
            "asset_dashboard_service", AssetDashboardService
        )
        snapshot = await dashboard.snapshot(project.project_id)
        row = next(item for item in snapshot["items"] if item["asset_id"] == asset.asset_id)
        assert row["quality_status"] == QUALITY_HUMAN_APPROVED
        assert row["license_status"] == "VERIFIED"
        assert row["import_status"] == IMPORT_IMPORTED
        assert row["godot_uid"] == "uid://e8m8player"
        assert row["delivery_status"] == DELIVERY_DELIVERED
        assert row["dependency_count"] == 1
        assert snapshot["unknown"]["total"] == 0


@pytest.mark.asyncio
async def test_security_path_traversal_and_cross_project_isolation(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(
            app, project.project_id, asset.asset_id, _png()
        )
        storage = app.state.services.get("asset_storage", AssetStorage)
        with pytest.raises(AssetPathInvalid):
            storage.write_bytes(
                project.project_id, STORAGE_GENERATED, "../escape.png", _png()
            )

        other_root = tmp_path / "other"
        other_root.mkdir()
        (other_root / "project.godot").write_text("[application]\n", encoding="utf-8")
        projects = app.state.services.get(
            "project_registry_service", ProjectRegistryService
        )
        other = await projects.register(project_root=str(other_root), name="Other")
        licenses = app.state.services.get("asset_license_service", LicenseService)
        with pytest.raises(NotFoundError):
            await licenses.latest_for_version(
                other.project_id, version.version_id
            )

        delivery = app.state.services.get(
            "asset_delivery_service", AssetDeliveryService
        )
        with pytest.raises(NotFoundError):
            await delivery.prepare(
                DeliveryRequest(
                    project_id=other.project_id,
                    asset_id=asset.asset_id,
                    asset_version_id=version.version_id,
                    target_path="res://art/player.png",
                    created_by="attacker",
                )
            )


@pytest.mark.asyncio
async def test_fault_injection_license_expiry_and_unknown_processing(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(
            app, project.project_id, asset.asset_id, _png()
        )
        licenses = app.state.services.get("asset_license_service", LicenseService)
        expired = await licenses.record(
            LicenseRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                asset_version_id=version.version_id,
                license_name="expired-license",
                source_type=SOURCE_AI_GENERATED,
                expiration_at=utcnow() - timedelta(days=1),
                evidence=[
                    LicenseEvidenceInput(
                        evidence_type="LICENSE_FILE", reference="legal/old.pdf"
                    )
                ],
            )
        )
        assert expired.verification_status in {LICENSE_EXPIRED, "PENDING_REVIEW"}
        with pytest.raises(AssetDeliveryBlocked):
            await licenses.check_deliverable(
                project.project_id, version.version_id
            )

        now = utcnow()
        async with _database(app).session() as session, transaction(session):
            session.add(
                AssetProcessingJobModel(
                    job_id="apj_e8m8_unknown",
                    asset_id=asset.asset_id,
                    input_version_id=version.version_id,
                    output_version_id=None,
                    processing_graph_json="{}",
                    processing_status=PROCESSING_UNKNOWN,
                    execution_metadata_json="{}",
                    idempotency_key="processing:apj_e8m8_unknown",
                    created_by="tester",
                    created_at=now,
                    started_at=now,
                    completed_at=None,
                )
            )
        recovery = app.state.services.get(
            "asset_recovery_service", AssetRecoveryService
        )
        inventory = await recovery.list_unknown(project.project_id)
        assert inventory.processing_job_ids == ("apj_e8m8_unknown",)
        with pytest.raises(AssetRecoveryRequired):
            await recovery.resolve_processing(
                project.project_id, "apj_e8m8_unknown"
            )
