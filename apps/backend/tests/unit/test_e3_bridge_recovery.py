"""Bridge 恢复、项目切换与诊断摘要单元测试（E3-T12 / T13 / T14）。"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest

from app.api.diagnostics import _bridge_summary
from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import FencingTokenStale, ValidationFailed
from modules.bridge_metrics import BridgeMetrics
from modules.client.service import ClientService
from modules.editor_session.service import EditorSessionService
from modules.lease.service import LeaseService
from modules.project.service import ProjectService
from modules.session.service import SessionService


@asynccontextmanager
async def _running(tmp_path, **overrides):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'm5.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
        **overrides,
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _project(tmp_path, name: str):
    root = tmp_path / name
    root.mkdir()
    (root / "project.godot").write_text(f'config/name="{name}"\n', encoding="utf-8")
    return root


async def _session_token(app, project_root) -> tuple[str, str]:
    services = app.state.services
    registered = await services.get("client_service", ClientService).register(
        client_type="godot_editor", client_name="Editor"
    )
    issued = await services.get("session_service", SessionService).create(registered.client_id)
    project = await services.get("project_service", ProjectService).resolve(
        project_root=str(project_root), project_name="Demo", godot_version="4.5.1"
    )
    await services.get("editor_session_service", EditorSessionService).bind(
        session_id=issued.session.session_id,
        editor_instance_id="edi_0123456789ab",
        project_id=project.project_id,
    )
    return issued.session.session_id, issued.session_token


def test_metrics_snapshot_tracks_counters() -> None:
    """T12-UT-001：诊断计数器只增减自身，不产生负值。"""

    metrics = BridgeMetrics()
    metrics.connection_opened()
    metrics.connection_opened()
    metrics.connection_closed()
    metrics.recovery_succeeded()
    metrics.recovery_failed_count()
    metrics.fencing_rejected()
    metrics.connection_closed()
    metrics.connection_closed()

    assert metrics.snapshot() == {
        "connections": 0,
        "recovery_success": 1,
        "recovery_failed": 1,
        "fencing_rejections": 1,
    }


async def test_project_switch_requires_recovering_state(tmp_path) -> None:
    """T14-UT-001：同一 Session 仅在 RECOVERING 时允许切换项目。"""

    first_root = _project(tmp_path, "first")
    second_root = _project(tmp_path, "second")
    async with _running(tmp_path) as app:
        services = app.state.services
        sessions = await services.get("client_service", ClientService).register(
            client_type="godot_editor", client_name="Editor"
        )
        issued = await services.get("session_service", SessionService).create(sessions.client_id)
        project_service = services.get("project_service", ProjectService)
        first = await project_service.resolve(project_root=str(first_root))
        second = await project_service.resolve(project_root=str(second_root))
        service = services.get("editor_session_service", EditorSessionService)

        await service.bind(
            session_id=issued.session.session_id,
            editor_instance_id="edi_0123456789ab",
            project_id=first.project_id,
        )
        with pytest.raises(ValidationFailed):
            await service.bind(
                session_id=issued.session.session_id,
                editor_instance_id="edi_0123456789ab",
                project_id=second.project_id,
            )

        await service.mark_recovering(issued.session.session_id)
        switched = await service.bind(
            session_id=issued.session.session_id,
            editor_instance_id="edi_0123456789ab",
            project_id=second.project_id,
        )
        assert switched.project_id == second.project_id
        assert switched.binding_status == "CONNECTED"
        assert await service.count_connected() == 1


async def test_bridge_status_returns_binding_and_active_lease(tmp_path) -> None:
    """T13-UT-002：/bridge/status 返回绑定、租约与项目身份。"""

    root = _project(tmp_path, "status")
    async with _running(tmp_path) as app:
        session_id, token = await _session_token(app, root)
        lease = await app.state.services.get("lease_service", LeaseService).issue(
            session_id=session_id,
            project_id=(
                await app.state.services.get("project_service", ProjectService).resolve(
                    project_root=str(root)
                )
            ).project_id,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1/bridge/status",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["session_id"] == session_id
        assert body["binding"]["binding_status"] == "CONNECTED"
        assert body["lease"]["lease_id"] == lease.lease_id
        assert body["project"]["project_root"].endswith("status")
        assert body["events_pending_ack"] == 0


async def test_bridge_status_without_binding_is_not_found(tmp_path) -> None:
    """T13-UT-003：无 Editor 绑定的 Session 查询状态返回 404。"""

    _project(tmp_path, "unbound")
    async with _running(tmp_path) as app:
        registered = await app.state.services.get("client_service", ClientService).register(
            client_type="godot_editor", client_name="Editor"
        )
        issued = await app.state.services.get("session_service", SessionService).create(
            registered.client_id
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1/bridge/status",
                headers={"Authorization": f"Bearer {issued.session_token}"},
            )
        assert response.status_code == 404


async def test_stale_fencing_token_is_rejected(tmp_path) -> None:
    """T18-IT-013：旧 fencing token 无法执行受保护操作。"""

    root = _project(tmp_path, "fencing")
    async with _running(tmp_path) as app:
        session_id, _ = await _session_token(app, root)
        project = await app.state.services.get("project_service", ProjectService).resolve(
            project_root=str(root)
        )
        leases = app.state.services.get("lease_service", LeaseService)
        first = await leases.issue(session_id=session_id, project_id=project.project_id)
        second = await leases.issue(session_id=session_id, project_id=project.project_id)
        assert second.fencing_token > first.fencing_token

        with pytest.raises(FencingTokenStale):
            await leases.validate(
                session_id=session_id,
                project_id=project.project_id,
                fencing_token=first.fencing_token,
            )
        valid = await leases.validate(
            session_id=session_id,
            project_id=project.project_id,
            fencing_token=second.fencing_token,
        )
        assert valid.lease_id == second.lease_id


async def test_diagnostics_bridge_block_contains_expected_keys(tmp_path) -> None:
    """T13-UT-004：诊断摘要 bridge 块字段齐全，且不依赖连接也存在。"""

    async with _running(tmp_path) as app:
        summary = await _bridge_summary(app.state.services)
        assert set(summary) == {
            "connections",
            "sessions_active",
            "leases_active",
            "events_pending_ack",
            "recovery_success",
            "recovery_failed",
            "fencing_rejections",
        }
        assert all(value >= 0 for value in summary.values())
