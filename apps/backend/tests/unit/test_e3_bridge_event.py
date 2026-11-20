"""Bridge 事件流服务测试（E3-T10-UT-001…005）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from modules.bridge_event.models import DIRECTION_PLUGIN_TO_BACKEND
from modules.bridge_event.service import BridgeEventService
from modules.client.service import ClientService
from modules.editor_session.service import EditorSessionService
from modules.project.service import ProjectService
from modules.session.service import SessionService


@asynccontextmanager
async def _running(tmp_path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'events.db').as_posix()}",
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


def _event(event_id: str, event_type: str = "project.opened", **payload) -> dict:
    return {
        "protocol_version": "1.0",
        "event_id": event_id,
        "event_type": event_type,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "plugin",
        "payload": payload,
    }


async def test_publish_assigns_monotonic_sequence(tmp_path, project_root) -> None:
    """T10-UT-001：sequence 按 session+direction 单调递增，并写入 payload。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        service = app.state.services.get("bridge_event_service", BridgeEventService)

        first = await service.publish(
            session_id=session_id, project_id=project_id, events=[_event("evt_a")]
        )
        second = await service.publish(
            session_id=session_id,
            project_id=project_id,
            events=[_event("evt_b"), _event("evt_c")],
        )

        assert first.latest_sequence == 1
        assert second.accepted == ["evt_b", "evt_c"]
        assert second.latest_sequence == 3
        result = await service.since(session_id=session_id, direction=DIRECTION_PLUGIN_TO_BACKEND)
        assert [event["event_id"] for event in result.events] == ["evt_a", "evt_b", "evt_c"]
        assert [event["payload"]["sequence"] for event in result.events] == [1, 2, 3]
        assert all(event["payload"]["event_version"] == 1 for event in result.events)


async def test_duplicate_event_is_idempotent(tmp_path, project_root) -> None:
    """T10-UT-002：重复 event_id 只确认，不重复分配 sequence。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        service = app.state.services.get("bridge_event_service", BridgeEventService)

        await service.publish(
            session_id=session_id, project_id=project_id, events=[_event("evt_dup")]
        )
        again = await service.publish(
            session_id=session_id, project_id=project_id, events=[_event("evt_dup")]
        )

        assert again.accepted == ["evt_dup"]
        assert again.persisted == 0
        assert again.latest_sequence == 1


async def test_ephemeral_event_is_not_persisted(tmp_path, project_root) -> None:
    """T10-UT-003：EPHEMERAL 事件只确认不落库。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        service = app.state.services.get("bridge_event_service", BridgeEventService)

        result = await service.publish(
            session_id=session_id,
            project_id=project_id,
            events=[_event("evt_sel", "editor.selection_changed", persistence="EPHEMERAL")],
        )
        since = await service.since(session_id=session_id, direction=DIRECTION_PLUGIN_TO_BACKEND)

        assert result.accepted == ["evt_sel"]
        assert result.persisted == 0
        assert since.events == []


async def test_ack_marks_events(tmp_path, project_root) -> None:
    """T10-UT-004：ack 写入 acked_at，重复确认不报错。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        service = app.state.services.get("bridge_event_service", BridgeEventService)
        await service.publish(
            session_id=session_id,
            project_id=project_id,
            events=[_event("evt_x"), _event("evt_y")],
        )

        acked = await service.ack(
            session_id=session_id,
            event_ids=["evt_x"],
            direction=DIRECTION_PLUGIN_TO_BACKEND,
        )
        by_sequence = await service.ack(
            session_id=session_id,
            last_sequence=5,
            direction=DIRECTION_PLUGIN_TO_BACKEND,
        )
        repeated = await service.ack(
            session_id=session_id,
            event_ids=["evt_x"],
            direction=DIRECTION_PLUGIN_TO_BACKEND,
        )

        assert acked == 1
        assert by_sequence == 1
        assert repeated == 0


async def test_since_limit_and_retention_gap(tmp_path, project_root) -> None:
    """T10-UT-005：since 上限与保留清理后的 snapshot_required。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        database = app.state.services.get("database", DatabaseService)
        clock = {"now": datetime(2026, 11, 1, tzinfo=UTC)}
        service = BridgeEventService(database, retention_days=7, clock=lambda: clock["now"])

        await service.publish(
            session_id=session_id, project_id=project_id, events=[_event("evt_old")]
        )
        clock["now"] = clock["now"] + timedelta(days=10)
        await service.publish(
            session_id=session_id,
            project_id=project_id,
            events=[_event("evt_new1"), _event("evt_new2")],
        )

        limited = await service.since(
            session_id=session_id,
            after_sequence=1,
            limit=1,
            direction=DIRECTION_PLUGIN_TO_BACKEND,
        )
        assert [event["event_id"] for event in limited.events] == ["evt_new1"]

        removed = await service.prune()
        gap = await service.since(
            session_id=session_id,
            after_sequence=0,
            direction=DIRECTION_PLUGIN_TO_BACKEND,
        )

        assert removed == 1
        assert gap.snapshot_required is True
        assert [event["event_id"] for event in gap.events] == ["evt_new1", "evt_new2"]


async def test_invalid_event_is_rejected(tmp_path, project_root) -> None:
    """T10-UT-006：source/session 不匹配的事件必须拒绝。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound(app, project_root)
        service = app.state.services.get("bridge_event_service", BridgeEventService)

        backend_event = _event("evt_backend")
        backend_event["source"] = "backend"
        with pytest.raises(ValidationFailed):
            await service.publish(
                session_id=session_id, project_id=project_id, events=[backend_event]
            )

        wrong_session = _event("evt_wrong")
        wrong_session["session_id"] = "ses_000000000000"
        with pytest.raises(ValidationFailed):
            await service.publish(
                session_id=session_id, project_id=project_id, events=[wrong_session]
            )
