"""E8-M4 集成测试：处理流水线与质量审核。"""

from __future__ import annotations

import hashlib
import io
import struct
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AssetProcessingInvalid, AssetQualityInvalid
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    PROCESSING_FAILED,
    PROCESSING_SUCCEEDED,
    QUALITY_HUMAN_APPROVED,
    QUALITY_HUMAN_REQUIRED,
    QUALITY_MACHINE_FAILED,
    QUALITY_MACHINE_PASSED,
    REVIEW_TYPE_HUMAN,
    REVIEW_TYPE_MACHINE,
    SOURCE_AI_GENERATED,
    SOURCE_USER_UPLOADED,
    STORAGE_GENERATED,
    AssetStorageObjectModel,
)
from modules.asset_pipeline.processing import (
    ProcessingPipelineService,
    ProcessingRequest,
)
from modules.asset_pipeline.quality import QualityControlService
from modules.asset_pipeline.service import AssetService
from modules.asset_pipeline.storage import AssetStorage
from modules.asset_pipeline.versioning import AssetVersionService
from modules.project_registry.service import ProjectRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8proc.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _database(app) -> DatabaseService:
    return app.state.services.get("database", DatabaseService)


def _pipeline(app) -> ProcessingPipelineService:
    return app.state.services.get(
        "asset_processing_pipeline", ProcessingPipelineService
    )


def _quality(app) -> QualityControlService:
    return app.state.services.get("asset_quality_control", QualityControlService)


def _png(width: int = 8, height: int = 8) -> bytes:
    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([1, 1, width - 2, height - 2], fill=(10, 20, 30, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _wav(sample_rate: int = 8000) -> bytes:
    samples = [1000, -1000] * 40
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buffer.getvalue()


async def _project(app, tmp_path: Path):
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    projects = app.state.services.get(
        "project_registry_service", ProjectRegistryService
    )
    return await projects.register(project_root=str(root), name="E8 Processing")


async def _seed_version(
    app,
    project_id: str,
    asset_id: str,
    *,
    filename: str,
    data: bytes,
    source_type: str,
    mime_type: str,
):
    storage = app.state.services.get("asset_storage", AssetStorage)
    versions = app.state.services.get(
        "asset_version_service", AssetVersionService
    )
    relative_path = f"{asset_id}/{filename}"
    written = storage.write_bytes(
        project_id, STORAGE_GENERATED, relative_path, data
    )
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
                mime_type=mime_type,
                created_at=version.created_at,
            )
        )
    return version


async def _seed_image_asset(app, tmp_path: Path):
    project = await _project(app, tmp_path)
    assets = app.state.services.get("asset_service", AssetService)
    asset = await assets.create(
        project_id=project.project_id,
        name="hero",
        category="IMAGE",
        asset_type="CHARACTER",
    )
    version = await _seed_version(
        app,
        project.project_id,
        asset.asset_id,
        filename="hero.png",
        data=_png(),
        source_type=SOURCE_AI_GENERATED,
        mime_type="image/png",
    )
    return project, asset, version


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "decode", "processor": "image.decode"},
            {
                "id": "remove_bg",
                "processor": "image.background_remove",
                "depends_on": ["decode"],
                "parameters": {"tolerance": 8},
            },
            {
                "id": "resize",
                "processor": "image.resize",
                "depends_on": ["remove_bg"],
                "parameters": {"width": 16, "height": 16, "resample": "nearest"},
            },
            {
                "id": "meta",
                "processor": "image.metadata_extract",
                "depends_on": ["resize"],
            },
        ]
    }


@pytest.mark.asyncio
async def test_processing_pipeline_creates_new_version_and_step_records(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _seed_image_asset(app, tmp_path)
        pipeline = _pipeline(app)
        storage = app.state.services.get("asset_storage", AssetStorage)
        assets = app.state.services.get("asset_service", AssetService)

        view = await pipeline.submit(
            ProcessingRequest(
                project_id=project.project_id,
                asset_id=asset.asset_id,
                input_version_id=version.version_id,
                graph=_graph(),
                created_by="tester",
            )
        )

        assert view.status == PROCESSING_SUCCEEDED
        assert view.output_version_id is not None
        assert view.output_version_id != version.version_id
        assert len(view.steps) == 4
        assert all(item.execution_status == "SUCCEEDED" for item in view.steps)
        assert all(len(item.input_hash) == 64 for item in view.steps)
        assert {item.node_id for item in view.steps} == {
            "decode",
            "remove_bg",
            "resize",
            "meta",
        }
        assert len(view.outputs) == 1

        output = view.outputs[0]
        data = storage.read_bytes(
            project.project_id, output.storage_area, output.reference
        )
        image = Image.open(io.BytesIO(data))
        assert image.size == (16, 16)
        assert image.getpixel((0, 0))[3] == 0

        current = await assets.get(asset.asset_id)
        assert current.current_version_id == view.output_version_id

        listing = await pipeline.list_for_asset(
            project.project_id, asset.asset_id
        )
        assert [item.job_id for item in listing] == [view.job_id]


@pytest.mark.asyncio
async def test_processing_idempotency_and_conflict(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _seed_image_asset(app, tmp_path)
        pipeline = _pipeline(app)
        request = ProcessingRequest(
            project_id=project.project_id,
            asset_id=asset.asset_id,
            input_version_id=version.version_id,
            graph=_graph(),
            idempotency_key="process-hero",
        )

        first = await pipeline.submit(request)
        second = await pipeline.submit(request)

        assert first.job_id == second.job_id
        assert second.created is False

        conflicting = ProcessingRequest(
            project_id=project.project_id,
            asset_id=asset.asset_id,
            input_version_id=version.version_id,
            graph={
                "nodes": [
                    {
                        "id": "resize",
                        "processor": "image.resize",
                        "parameters": {"width": 4, "height": 4},
                    }
                ]
            },
            idempotency_key="process-hero",
        )
        with pytest.raises(AssetProcessingInvalid):
            await pipeline.submit(conflicting)


@pytest.mark.asyncio
async def test_processing_failure_marks_job_failed_and_keeps_version(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _seed_image_asset(app, tmp_path)
        pipeline = _pipeline(app)
        assets = app.state.services.get("asset_service", AssetService)

        with pytest.raises(AssetProcessingInvalid):
            await pipeline.submit(
                ProcessingRequest(
                    project_id=project.project_id,
                    asset_id=asset.asset_id,
                    input_version_id=version.version_id,
                    graph={
                        "nodes": [
                            {
                                "id": "crop",
                                "processor": "image.crop",
                                "parameters": {"box": [0, 0, 100, 100]},
                            }
                        ]
                    },
                )
            )

        listing = await pipeline.list_for_asset(
            project.project_id, asset.asset_id
        )
        assert len(listing) == 1
        failed = listing[0]
        assert failed.status == PROCESSING_FAILED
        assert failed.error_code == "ASSET_PROCESSING_INVALID"
        assert failed.steps[0].execution_status == "FAILED"
        assert failed.steps[0].resource_usage["error_code"] == "ASSET_PROCESSING_INVALID"

        current = await assets.get(asset.asset_id)
        assert current.current_version_id == version.version_id


@pytest.mark.asyncio
async def test_processing_rejects_unregistered_processor_before_job(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _seed_image_asset(app, tmp_path)
        pipeline = _pipeline(app)

        with pytest.raises(AssetProcessingInvalid):
            await pipeline.submit(
                ProcessingRequest(
                    project_id=project.project_id,
                    asset_id=asset.asset_id,
                    input_version_id=version.version_id,
                    graph={
                        "nodes": [
                            {"id": "convert", "processor": "model3d.format_convert"}
                        ]
                    },
                )
            )
        assert await pipeline.list_for_asset(
            project.project_id, asset.asset_id
        ) == []


@pytest.mark.asyncio
async def test_machine_review_passes_and_returns_structured_findings(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _seed_image_asset(app, tmp_path)
        quality = _quality(app)

        review = await quality.run_machine_review(
            project.project_id,
            asset.asset_id,
            version.version_id,
            rules={
                "expected_width": 8,
                "expected_height": 8,
                "expected_format": "png",
                "require_alpha": True,
            },
            reviewer_id="qc-bot",
        )

        assert review.review_type == REVIEW_TYPE_MACHINE
        assert review.review_status == QUALITY_MACHINE_PASSED
        assert review.findings
        assert all(item["evidence"] for item in review.findings)
        assert review.machine_result["summary"]["failed"] == 0
        rules = {item["rule_id"] for item in review.findings}
        assert {"image.decodable", "image.width", "image.height", "image.alpha"} <= rules

        listing = await quality.list_for_version(
            project.project_id, asset.asset_id, version.version_id
        )
        assert [item.review_id for item in listing] == [review.review_id]


@pytest.mark.asyncio
async def test_machine_review_fails_for_corrupt_image_and_audio_mismatch(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        assets = app.state.services.get("asset_service", AssetService)
        quality = _quality(app)

        broken = await assets.create(
            project_id=project.project_id,
            name="broken",
            category="IMAGE",
            asset_type="UI",
        )
        broken_version = await _seed_version(
            app,
            project.project_id,
            broken.asset_id,
            filename="broken.png",
            data=b"not-an-image",
            source_type=SOURCE_USER_UPLOADED,
            mime_type="image/png",
        )
        review = await quality.run_machine_review(
            project.project_id, broken.asset_id, broken_version.version_id
        )
        assert review.review_status == QUALITY_MACHINE_FAILED
        decoded = [item for item in review.findings if item["rule_id"] == "image.decodable"]
        assert decoded and decoded[0]["status"] == "FAILED"

        audio = await assets.create(
            project_id=project.project_id,
            name="jump",
            category="AUDIO",
            asset_type="SFX",
        )
        audio_version = await _seed_version(
            app,
            project.project_id,
            audio.asset_id,
            filename="jump.wav",
            data=_wav(sample_rate=8000),
            source_type=SOURCE_USER_UPLOADED,
            mime_type="audio/wav",
        )
        audio_review = await quality.run_machine_review(
            project.project_id,
            audio.asset_id,
            audio_version.version_id,
            rules={"expected_sample_rate": 44100},
        )
        assert audio_review.review_status == QUALITY_MACHINE_FAILED
        assert any(
            item["rule_id"] == "audio.sample_rate" and item["status"] == "FAILED"
            for item in audio_review.findings
        )


@pytest.mark.asyncio
async def test_human_review_requires_machine_review_and_is_immutable(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _seed_image_asset(app, tmp_path)
        quality = _quality(app)

        with pytest.raises(AssetQualityInvalid):
            await quality.request_human_review(
                project.project_id, asset.asset_id, version.version_id
            )

        await quality.run_machine_review(
            project.project_id, asset.asset_id, version.version_id
        )
        requested = await quality.request_human_review(
            project.project_id,
            asset.asset_id,
            version.version_id,
            notes="请美术确认",
            reviewer_id="art-lead",
        )
        assert requested.review_type == REVIEW_TYPE_HUMAN
        assert requested.review_status == QUALITY_HUMAN_REQUIRED
        assert requested.completed_at is None

        decided = await quality.record_human_decision(
            project.project_id,
            asset.asset_id,
            requested.review_id,
            approved=True,
            reviewer_id="art-lead",
            notes="通过",
        )
        assert decided.review_status == QUALITY_HUMAN_APPROVED
        assert decided.human_result["approved"] is True
        assert decided.completed_at is not None

        with pytest.raises(AssetQualityInvalid):
            await quality.record_human_decision(
                project.project_id,
                asset.asset_id,
                requested.review_id,
                approved=False,
                reviewer_id="art-lead",
            )


@pytest.mark.asyncio
async def test_quality_reviews_are_isolated_per_version(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project, asset, version = await _seed_image_asset(app, tmp_path)
        quality = _quality(app)
        versions = app.state.services.get(
            "asset_version_service", AssetVersionService
        )
        storage = app.state.services.get("asset_storage", AssetStorage)

        await quality.run_machine_review(
            project.project_id, asset.asset_id, version.version_id
        )

        payload = _png(4, 4)
        relative_path = f"{asset.asset_id}/hero_v2.png"
        written = storage.write_bytes(
            project.project_id, STORAGE_GENERATED, relative_path, payload
        )
        second = await versions.create_version(
            asset.asset_id,
            content_hash=hashlib.sha256(payload).hexdigest(),
            source_type=SOURCE_USER_UPLOADED,
            change_reason="manual_revision",
            parent_version_id=version.version_id,
        )
        assert str(written["content_hash"]) == second.content_hash
        async with _database(app).session() as session, transaction(session):
            session.add(
                AssetStorageObjectModel(
                    object_id="asob_" + uuid4().hex[:12],
                    project_id=project.project_id,
                    asset_version_id=second.version_id,
                    storage_area=STORAGE_GENERATED,
                    relative_path=relative_path,
                    content_hash=second.content_hash,
                    size_bytes=len(payload),
                    mime_type="image/png",
                    created_at=second.created_at,
                )
            )

        second_review = await quality.run_machine_review(
            project.project_id, asset.asset_id, second.version_id
        )
        assert second_review.asset_version_id == second.version_id

        first_reviews = await quality.list_for_version(
            project.project_id, asset.asset_id, version.version_id
        )
        second_reviews = await quality.list_for_version(
            project.project_id, asset.asset_id, second.version_id
        )
        assert len(first_reviews) == 1
        assert len(second_reviews) == 1
        assert first_reviews[0].review_id != second_reviews[0].review_id
