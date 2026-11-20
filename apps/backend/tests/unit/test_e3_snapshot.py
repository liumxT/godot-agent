"""快照服务测试（E3-T11-UT-001…004）。"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import SnapshotUnavailable, ValidationFailed
from infrastructure.database.service import DatabaseService
from modules.client.service import ClientService
from modules.editor_session.service import EditorSessionService
from modules.project.service import ProjectService
from modules.session.service import SessionService
from modules.snapshot.models import SnapshotModel
from modules.snapshot.service import MAX_SNAPSHOT_BYTES, SnapshotService, validate_snapshot


@asynccontextmanager
async def _running(tmp_path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'snapshots.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


@pytest.fixture()
def project_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "project.godot").write_text('config/name="Demo"\n', encoding="utf-8")
    return root


async def _bound(app, project_root) -> tuple[str, str]:
    services = app.state.services
    registered = await services.get("client_service", ClientService).register(
        client_type="godot_editor", client_name="Editor"
    )
    issued = await services.get("session_service", SessionService).create(registered.client_id)
    session_id = issued.session.session_id
    project = await services.get("project_service", ProjectService).resolve(
        project_root=str(project_root), project_name="Demo", godot_version="4.5.1"
    )
    await services.get("editor_session_service", EditorSessionService).bind(
        session_id=session_id,
        editor_instance_id="edi_0123456789ab",
        project_id=project.project_id,
    )
    return session_id, project.project_id


def _snapshot(session_id: str, project_id: str, version: int = 1, **overrides) -> dict:
    snapshot = {
        "snapshot_id": f"snp_{version:012x}",
        "session_id": session_id,
        "project_id": project_id,
        "editor_instance_id": "edi_0123456789ab",
        "snapshot_version": version,
        "last_event_sequence": 0,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "editor_status": "READY",
        "project_status": "READY",
        "active_scene": "res://scenes/main.tscn",
        "current_selection": ["res://scenes/main.tscn"],
        "unsaved_resources": [{"path": "res://scenes/main.tscn", "resource_type": "PackedScene"}],
        "run_status": "STOPPED",
        "import_status": "IDLE",
        "truncated": False,
    }
    snapshot.update(overrides)
    return snapshot


async def test_store_and_latest(tmp_path, project_root) -> None:
    """T11-UT-001：快照入库后可按 Session 读取最新值。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        service = app.state.services.get("snapshot_service", SnapshotService)

        view = await service.store(
            _snapshot(session_id, project_id), session_id=session_id, project_id=project_id
        )
        latest = await service.latest(session_id)

        assert view.snapshot_version == 1
        assert latest.snapshot_id == view.snapshot_id
        assert latest.last_event_sequence == 0


async def test_expired_snapshot_is_unavailable(tmp_path, project_root) -> None:
    """T11-UT-002：超过 TTL 的快照不再用于恢复。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        database = app.state.services.get("database", DatabaseService)
        clock = {"now": datetime(2026, 11, 20, 0, 10, tzinfo=UTC)}
        service = SnapshotService(database, ttl_seconds=900, clock=lambda: clock["now"])

        await service.store(
            _snapshot(session_id, project_id, created_at="2026-11-20T00:00:00Z"),
            session_id=session_id,
            project_id=project_id,
        )
        clock["now"] = clock["now"] + timedelta(seconds=901)

        with pytest.raises(SnapshotUnavailable):
            await service.latest(session_id)


async def test_keep_latest_versions_only(tmp_path, project_root) -> None:
    """T11-UT-003：每个 Session 只保留最近 N 个快照。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        database = app.state.services.get("database", DatabaseService)
        service = SnapshotService(database, keep_per_session=2)

        for version in range(1, 4):
            created_at = (datetime.now(UTC) + timedelta(seconds=version)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            await service.store(
                _snapshot(session_id, project_id, version, created_at=created_at),
                session_id=session_id,
                project_id=project_id,
            )

        async with database.session() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(SnapshotModel)
                .where(SnapshotModel.session_id == session_id)
            )
        assert count == 2
        latest = await service.latest(session_id)
        assert latest.snapshot_version == 3


async def test_oversized_snapshot_is_trimmed(tmp_path, project_root) -> None:
    """T11-UT-004：超过 256 KiB 时裁剪并置 truncated=true。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        service = app.state.services.get("snapshot_service", SnapshotService)
        long_path = "res://" + "a" * 600 + ".tscn"
        snapshot = _snapshot(
            session_id,
            project_id,
            current_selection=["res://" + "b" * 500 + ".tscn"] * 64,
            unsaved_resources=[
                {"path": long_path, "resource_type": "PackedScene"} for _ in range(500)
            ],
        )

        view = await service.store(snapshot, session_id=session_id, project_id=project_id)

        assert view.payload["truncated"] is True
        assert len(view.payload["current_selection"]) <= 8
        assert len(view.payload["unsaved_resources"]) <= 50
        assert len(json.dumps(view.payload, ensure_ascii=False)) < MAX_SNAPSHOT_BYTES


def test_snapshot_validation_rejects_version_regression() -> None:
    """T11-UT-005：未知字段与非正版本必须拒绝。"""

    with pytest.raises(ValidationFailed):
        validate_snapshot(
            _snapshot("ses_000000000001", "prj_1", extra="x"),
            session_id="ses_000000000001",
            project_id="prj_1",
        )
    with pytest.raises(ValidationFailed):
        validate_snapshot(
            _snapshot("ses_000000000001", "prj_1", version=0),
            session_id="ses_000000000001",
            project_id="prj_1",
        )
