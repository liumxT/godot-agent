"""E8-M5 集成测试：Godot 导入、来源追踪与授权门禁。"""

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
    AssetImportInvalid,
    AssetLicenseInvalid,
    AssetStateInvalid,
    EditorCommandTimeout,
    EditorNotConnected,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.imports import GodotImportService, ImportRequest
from modules.asset_pipeline.license import (
    LicenseEvidenceInput,
    LicenseRequest,
    LicenseService,
)
from modules.asset_pipeline.models import (
    IMPORT_FAILED,
    IMPORT_IMPORTED,
    IMPORT_UNKNOWN,
    LICENSE_EXPIRED,
    LICENSE_PENDING_REVIEW,
    LICENSE_UNKNOWN,
    LICENSE_VERIFIED,
    SOURCE_AI_GENERATED,
    SOURCE_PROJECT_DERIVED,
    SOURCE_UNKNOWN,
    SOURCE_USER_UPLOADED,
    STORAGE_GENERATED,
    AssetStorageObjectModel,
)
from modules.asset_pipeline.processing import (
    ProcessingPipelineService,
    ProcessingRequest,
)
from modules.asset_pipeline.provenance import ProvenanceRequest, ProvenanceService
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
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8m5.db').as_posix()}",
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


async def _project(app, tmp_path: Path, *, name: str = "E8 M5"):
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    projects = app.state.services.get("project_registry_service", ProjectRegistryService)
    return await projects.register(project_root=str(root), name=name)


async def _asset(app, project_id: str, *, name: str = "hero"):
    assets = app.state.services.get("asset_service", AssetService)
    return await assets.create(
        project_id=project_id,
        name=name,
        category="IMAGE",
        asset_type="CHARACTER",
    )


async def _seed_version(
    app,
    project_id: str,
    asset_id: str,
    data: bytes,
    *,
    source_type: str,
    filename: str = "hero.png",
):
    storage = app.state.services.get("asset_storage", AssetStorage)
    versions = app.state.services.get("asset_version_service", AssetVersionService)
    relative_path = f"{asset_id}/{filename}"
    written = storage.write_bytes(project_id, STORAGE_GENERATED, relative_path, data)
    version = await versions.create_version(
        asset_id,
        content_hash=str(written["content_hash"]),
        source_type=source_type,
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


async def _bind_editor(app, project_id: str, *, session_id: str = "ses_e8m5"):
    now = utcnow()
    async with _database(app).session() as session, transaction(session):
        session.add(
            ClientModel(
                client_id="cli_e8m5",
                client_type="editor",
                client_name="E8 M5",
                status=CLIENT_STATUS_ACTIVE,
                created_at=now,
                last_seen_at=now,
            )
        )
        await session.flush()
        session.add(
            SessionModel(
                session_id=session_id,
                client_id="cli_e8m5",
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
                editor_instance_id="edi_e8m5",
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


def _imported(uid: str = "uid://e8m5hero") -> EditorCommandResponse:
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
                "path": "res://art/hero.png",
            },
            "checks": [],
            "evidence_refs": [],
        },
        error=None,
    )


def _write_project_file(tmp_path: Path, data: bytes) -> None:
    target = tmp_path / "game" / "art"
    target.mkdir(parents=True, exist_ok=True)
    (target / "hero.png").write_bytes(data)


def _import_service(app, connection) -> GodotImportService:
    return GodotImportService(
        _database(app),
        hub=_FakeHub(connection),
        projects=app.state.services.get("project_registry_service", ProjectRegistryService),
    )


# ----------------------------------------------------------------------
# T11 Godot 导入
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_records_real_uid_and_is_idempotent(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        data = _png()
        version = await _seed_version(
            app, project.project_id, asset.asset_id, data, source_type=SOURCE_AI_GENERATED
        )
        session_id = await _bind_editor(app, project.project_id)
        _write_project_file(tmp_path, data)
        connection = _FakeConnection([_imported()])
        service = _import_service(app, connection)
        request = ImportRequest(
            project_id=project.project_id,
            asset_version_id=version.version_id,
            target_path="res://art/hero.png",
            session_id=session_id,
            created_by="tester",
        )

        view = await service.submit(request)

        assert view.import_status == IMPORT_IMPORTED
        assert view.godot_uid == "uid://e8m5hero"
        assert view.evidence is not None
        assert view.evidence.source_file_hash == hashlib.sha256(data).hexdigest()
        assert view.evidence.godot_version == "4.5.1"
        assert view.evidence.resource_type == "Texture2D"
        assert view.evidence.import_completed_at is not None
        assert connection.calls[0][1]["tool_name"] == "godot.asset.import"

        again = await service.submit(request)
        assert again.created is False
        assert again.import_job_id == view.import_job_id
        assert len(connection.calls) == 1

        jobs = await service.list_for_version(project.project_id, version.version_id)
        assert len(jobs) == 1
        assert jobs[0].import_job_id == view.import_job_id


@pytest.mark.asyncio
async def test_import_without_real_uid_is_failed(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        data = _png()
        version = await _seed_version(
            app, project.project_id, asset.asset_id, data, source_type=SOURCE_AI_GENERATED
        )
        session_id = await _bind_editor(app, project.project_id)
        _write_project_file(tmp_path, data)
        response = EditorCommandResponse(
            success=True,
            data={
                "status": "SUCCEEDED",
                "output": {"phase": "IMPORTED", "imported": True},
                "checks": [],
                "evidence_refs": [],
            },
            error=None,
        )
        service = _import_service(app, _FakeConnection([response]))

        with pytest.raises(AssetImportInvalid):
            await service.submit(
                ImportRequest(
                    project_id=project.project_id,
                    asset_version_id=version.version_id,
                    target_path="res://art/hero.png",
                    session_id=session_id,
                )
            )

        jobs = await service.list_for_version(project.project_id, version.version_id)
        assert jobs[0].import_status == IMPORT_FAILED
        assert jobs[0].godot_uid is None
        assert jobs[0].error_code == "IMPORT_UID_MISSING"


@pytest.mark.asyncio
async def test_import_timeout_marks_unknown_then_refresh_recovers(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        data = _png()
        version = await _seed_version(
            app, project.project_id, asset.asset_id, data, source_type=SOURCE_AI_GENERATED
        )
        session_id = await _bind_editor(app, project.project_id)
        _write_project_file(tmp_path, data)
        connection = _FakeConnection([EditorCommandTimeout("编辑器超时"), _imported()])
        service = _import_service(app, connection)

        with pytest.raises(EditorCommandTimeout):
            await service.submit(
                ImportRequest(
                    project_id=project.project_id,
                    asset_version_id=version.version_id,
                    target_path="res://art/hero.png",
                    session_id=session_id,
                )
            )

        jobs = await service.list_for_version(project.project_id, version.version_id)
        assert jobs[0].import_status == IMPORT_UNKNOWN
        assert jobs[0].evidence is not None

        refreshed = await service.refresh(jobs[0].import_job_id)
        assert refreshed.import_status == IMPORT_IMPORTED
        assert refreshed.godot_uid == "uid://e8m5hero"
        assert connection.calls[-1][1]["tool_name"] == "godot.asset.import_status"


@pytest.mark.asyncio
async def test_import_rejects_file_not_owned_by_version(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(
            app,
            project.project_id,
            asset.asset_id,
            _png(),
            source_type=SOURCE_AI_GENERATED,
        )
        connection = _FakeConnection([])
        service = _import_service(app, connection)
        _write_project_file(tmp_path, b"different-content")

        with pytest.raises(AssetImportInvalid):
            await service.submit(
                ImportRequest(
                    project_id=project.project_id,
                    asset_version_id=version.version_id,
                    target_path="res://art/hero.png",
                )
            )

        assert connection.calls == []
        assert await service.list_for_version(project.project_id, version.version_id) == []


@pytest.mark.asyncio
async def test_import_requires_connected_editor_session(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        data = _png()
        version = await _seed_version(
            app, project.project_id, asset.asset_id, data, source_type=SOURCE_AI_GENERATED
        )
        _write_project_file(tmp_path, data)
        service = _import_service(app, None)

        with pytest.raises(EditorNotConnected):
            await service.submit(
                ImportRequest(
                    project_id=project.project_id,
                    asset_version_id=version.version_id,
                    target_path="res://art/hero.png",
                )
            )


# ----------------------------------------------------------------------
# T12 来源追踪
# ----------------------------------------------------------------------


def _provenance(app) -> ProvenanceService:
    return app.state.services.get("asset_provenance_service", ProvenanceService)


def _license(app) -> LicenseService:
    return app.state.services.get("asset_license_service", LicenseService)


@pytest.mark.asyncio
async def test_provenance_record_is_unique_and_traceable(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(
            app,
            project.project_id,
            asset.asset_id,
            _png(),
            source_type=SOURCE_USER_UPLOADED,
        )
        service = _provenance(app)
        request = ProvenanceRequest(
            project_id=project.project_id,
            asset_id=asset.asset_id,
            asset_version_id=version.version_id,
            source_type=SOURCE_USER_UPLOADED,
            output_hashes=[version.content_hash],
            operator_user_id="designer",
            external_source_reference="local-upload",
        )

        created = await service.record(request)
        assert created.created is True
        assert created.operator_user_id == "designer"

        repeated = await service.record(request)
        assert repeated.created is False
        assert repeated.provenance_id == created.provenance_id

        with pytest.raises(AssetStateInvalid):
            await service.record(
                ProvenanceRequest(
                    project_id=project.project_id,
                    asset_id=asset.asset_id,
                    asset_version_id=version.version_id,
                    source_type=SOURCE_USER_UPLOADED,
                    operator_user_id="someone-else",
                )
            )

        trace = await service.trace(project.project_id, version.version_id)
        assert len(trace) == 1
        assert trace[0].provenance is not None
        assert await service.assert_complete(project.project_id, version.version_id)

        unknown_version = await _seed_version(
            app,
            project.project_id,
            asset.asset_id,
            _png(9, 9),
            source_type=SOURCE_USER_UPLOADED,
            filename="hero2.png",
        )
        await service.record(
            ProvenanceRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                asset_version_id=unknown_version.version_id,
                source_type=SOURCE_UNKNOWN,
            )
        )
        with pytest.raises(AssetStateInvalid):
            await service.assert_complete(project.project_id, unknown_version.version_id)


def _processing_graph() -> dict:
    return {
        "nodes": [
            {"id": "decode", "processor": "image.decode"},
            {
                "id": "resize",
                "processor": "image.resize",
                "depends_on": ["decode"],
                "parameters": {"width": 16, "height": 16, "resample": "nearest"},
            },
        ]
    }


@pytest.mark.asyncio
async def test_processing_version_records_derived_provenance(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(
            app,
            project.project_id,
            asset.asset_id,
            _png(),
            source_type=SOURCE_AI_GENERATED,
        )
        provenance = _provenance(app)
        await provenance.record(
            ProvenanceRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                asset_version_id=version.version_id,
                source_type=SOURCE_AI_GENERATED,
                provider_id="gateway",
                model_id="image-model",
                generation_id="gen_e8m5",
                output_hashes=[version.content_hash],
            )
        )
        pipeline = app.state.services.get("asset_processing_pipeline", ProcessingPipelineService)

        output = await pipeline.submit(
            ProcessingRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                input_version_id=version.version_id,
                graph=_processing_graph(),
                created_by="tester",
            )
        )

        assert output.output_version_id is not None
        derived = await provenance.get(project.project_id, output.output_version_id)
        assert derived is not None
        assert derived.source_type == SOURCE_PROJECT_DERIVED
        assert derived.processing_graph is not None
        assert derived.input_hashes == (version.content_hash,)
        assert derived.processor_versions
        trace = await provenance.trace(project.project_id, output.output_version_id)
        assert len(trace) == 2
        await provenance.assert_complete(project.project_id, output.output_version_id)


# ----------------------------------------------------------------------
# T13 License
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_license_unknown_blocks_delivery_until_manual_verification(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(
            app,
            project.project_id,
            asset.asset_id,
            _png(),
            source_type=SOURCE_USER_UPLOADED,
        )
        service = _license(app)
        license_view = await service.record(
            LicenseRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                asset_version_id=version.version_id,
                license_name="Studio Internal",
                source_type=SOURCE_USER_UPLOADED,
            )
        )
        assert license_view.verification_status == LICENSE_UNKNOWN

        with pytest.raises(AssetDeliveryBlocked):
            await service.check_deliverable(project.project_id, version.version_id)
        with pytest.raises(AssetLicenseInvalid):
            await service.submit_for_review(project.project_id, license_view.license_id)

        pending = await service.add_evidence(
            project.project_id,
            license_view.license_id,
            [
                LicenseEvidenceInput(
                    evidence_type="PURCHASE_RECEIPT",
                    reference="receipt://e8m5",
                    content_hash="a" * 64,
                )
            ],
        )
        assert pending.verification_status == LICENSE_PENDING_REVIEW
        assert len(pending.evidence) == 1

        with pytest.raises(AssetLicenseInvalid):
            await service.verify(
                project.project_id,
                license_view.license_id,
                reviewer_id="",
                commercial_use=True,
                modification_allowed=True,
                redistribution_allowed=True,
            )
        with pytest.raises(AssetLicenseInvalid):
            await service.verify(
                project.project_id,
                license_view.license_id,
                reviewer_id="reviewer",
                commercial_use=True,
                modification_allowed=True,
                redistribution_allowed=True,
                attribution_required=True,
            )

        verified = await service.verify(
            project.project_id,
            license_view.license_id,
            reviewer_id="reviewer",
            commercial_use=True,
            modification_allowed=True,
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text="Studio Internal Assets",
        )
        assert verified.verification_status == LICENSE_VERIFIED
        assert verified.reviewer_id == "reviewer"

        with pytest.raises(AssetDeliveryBlocked):
            await service.check_deliverable(
                project.project_id,
                version.version_id,
                require_redistribution=True,
            )
        delivered = await service.check_deliverable(project.project_id, version.version_id)
        assert delivered.license_id == verified.license_id


@pytest.mark.asyncio
async def test_expired_license_is_marked_and_blocks_delivery(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        asset = await _asset(app, project.project_id)
        version = await _seed_version(
            app,
            project.project_id,
            asset.asset_id,
            _png(),
            source_type=SOURCE_USER_UPLOADED,
        )
        service = _license(app)
        record = await service.record(
            LicenseRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                asset_version_id=version.version_id,
                license_name="Time Limited",
                source_type=SOURCE_USER_UPLOADED,
                evidence_reference="contract://e8m5",
            )
        )
        assert record.verification_status == LICENSE_PENDING_REVIEW
        past = utcnow() - timedelta(days=1)
        verified = await service.verify(
            project.project_id,
            record.license_id,
            reviewer_id="reviewer",
            commercial_use=True,
            modification_allowed=True,
            redistribution_allowed=True,
            expiration_at=past,
        )
        assert verified.verification_status == LICENSE_VERIFIED

        with pytest.raises(AssetDeliveryBlocked):
            await service.check_deliverable(project.project_id, version.version_id)

        expired = await service.get(project.project_id, record.license_id)
        assert expired.verification_status == LICENSE_EXPIRED
