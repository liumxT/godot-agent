"""E9-T13 证据管理与完整性集成测试。"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from modules.project_registry.service import ProjectRegistryService
from modules.verification.service import VerificationService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9evidence.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app) -> VerificationService:
    return app.state.services.get("verification_service", VerificationService)


async def _project(app, tmp_path: Path) -> str:
    registry = app.state.services.get("project_registry_service", ProjectRegistryService)
    root = tmp_path / "game"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name="Game")
    return project.project_id


@pytest.mark.asyncio
async def test_file_evidence_integrity_and_staleness(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        service = _service(app)
        project_id = await _project(app, tmp_path)
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"fake-png-bytes")
        digest = hashlib.sha256(shot.read_bytes()).hexdigest()

        await service.record_evidence(
            project_id=project_id,
            evidence_type="SCREENSHOT",
            source_type="GODOT_RUNTIME",
            source_reference=f"file:///{shot.as_posix()}",
            content_hash=digest,
            metadata={"project_revision": "rev-1", "runtime_instance_id": "inst_1"},
        )

        summary = await service.evidence_summary(project_id)
        assert summary["total"] == 1
        assert summary["by_type"] == {"SCREENSHOT": 1}

        integrity = await service.check_evidence_integrity(project_id)
        assert integrity["valid"] is True
        assert integrity["checked"] == 1

        stale = await service.mark_stale_evidence(project_id, project_revision="rev-2")
        assert stale["stale"] == 1

        page = await service.list_evidence(project_id, validity_status="STALE")
        assert page["total"] == 1
        # 失效证据不再参与完整性通过判定
        assert (await service.check_evidence_integrity(project_id))["checked"] == 0


@pytest.mark.asyncio
async def test_evidence_without_context_or_file_is_reported(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        service = _service(app)
        project_id = await _project(app, tmp_path)

        await service.record_evidence(
            project_id=project_id,
            evidence_type="RUNTIME_TRACE",
            source_type="GODOT_RUNTIME",
            source_reference="runtime://inst_1/t1",
            content_hash="a" * 64,
            metadata={},
        )
        await service.record_evidence(
            project_id=project_id,
            evidence_type="SCREENSHOT",
            source_type="GODOT_RUNTIME",
            source_reference=f"file:///{(tmp_path / 'missing.png').as_posix()}",
            content_hash="b" * 64,
            metadata={"project_revision": "rev-1", "runtime_instance_id": "inst_1"},
        )

        integrity = await service.check_evidence_integrity(project_id)
        assert integrity["valid"] is False
        problems = [item["problem"] for item in integrity["problems"]]
        assert any("project_revision" in item for item in problems)
        assert any("runtime_instance_id" in item for item in problems)
        assert any("不存在" in item for item in problems)
