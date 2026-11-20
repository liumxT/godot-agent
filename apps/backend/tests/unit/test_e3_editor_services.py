"""Editor 绑定与租约服务测试（E3-T07-UT / T08-UT）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import FencingTokenStale, LeaseExpired, LeaseRevoked, ValidationFailed
from infrastructure.database.service import DatabaseService
from modules.audit.service import AuditService
from modules.client.service import ClientService
from modules.editor_session.service import EditorSessionService
from modules.lease.service import LeaseService
from modules.project.service import ProjectService
from modules.session.service import SessionService


@asynccontextmanager
async def _running(tmp_path, **overrides):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e3.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
        **overrides,
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


async def _new_session(app, *, register_client: bool = True) -> tuple[str, str]:
    services = app.state.services
    client_id = "cli_e3test00001"
    if register_client:
        registered = await services.get("client_service", ClientService).register(
            client_type="godot_editor", client_name="Editor", client_id=client_id
        )
        client_id = registered.client_id
    issued = await services.get("session_service", SessionService).create(client_id)
    return client_id, issued.session.session_id


async def _resolved_project(app, project_root) -> str:
    project = await app.state.services.get("project_service", ProjectService).resolve(
        project_root=str(project_root), project_name="Demo", godot_version="4.5.1"
    )
    return project.project_id


async def _bind_session(app, session_id: str, project_id: str) -> None:
    await app.state.services.get("editor_session_service", EditorSessionService).bind(
        session_id=session_id,
        editor_instance_id="edi_0123456789ab",
        project_id=project_id,
    )


async def _bound_session(app, project_root, *, register_client: bool = True):
    _, session_id = await _new_session(app, register_client=register_client)
    project_id = await _resolved_project(app, project_root)
    await _bind_session(app, session_id, project_id)
    return session_id, project_id


async def test_binding_lifecycle(tmp_path, project_root) -> None:
    """T07-UT-001：绑定进入 CONNECTED，断开后转 DISCONNECTED，可重新连接。"""

    async with _running(tmp_path) as app:
        _, session_id = await _new_session(app)
        project_id = await _resolved_project(app, project_root)
        service = app.state.services.get("editor_session_service", EditorSessionService)

        bound = await service.bind(
            session_id=session_id,
            editor_instance_id="edi_0123456789ab",
            project_id=project_id,
            godot_version="4.5.1",
            plugin_version="0.1.0",
        )
        assert bound.binding_status == "CONNECTED"
        assert bound.transport == "websocket"

        disconnected = await service.mark_disconnected(session_id)
        assert disconnected is not None
        assert disconnected.binding_status == "DISCONNECTED"
        assert disconnected.disconnected_at is not None

        rebound = await service.bind(
            session_id=session_id,
            editor_instance_id="edi_0123456789ab",
            project_id=project_id,
        )
        assert rebound.binding_status == "CONNECTED"
        assert rebound.disconnected_at is None

        recovering = await service.mark_recovering(session_id)
        assert recovering is not None
        assert recovering.binding_status == "RECOVERING"
        recovered = await service.mark_connected(session_id)
        assert recovered is not None
        assert recovered.binding_status == "CONNECTED"


async def test_editor_instance_id_is_normalized(tmp_path, project_root) -> None:
    """T07-UT-002：非契约格式的实例 ID 规范化为 edi_ + 12 位。"""

    async with _running(tmp_path) as app:
        _, session_id = await _new_session(app)
        project_id = await _resolved_project(app, project_root)
        service = app.state.services.get("editor_session_service", EditorSessionService)

        bound = await service.bind(
            session_id=session_id,
            editor_instance_id="6F5C1D8E-AAAA-BBBB-CCCC-1234567890AB",
            project_id=project_id,
        )
        assert bound.editor_instance_id.startswith("edi_")
        assert len(bound.editor_instance_id) == 16


async def test_same_session_cannot_switch_project(tmp_path, project_root) -> None:
    """T07-UT-004：同一 Session 不允许切换项目。"""

    async with _running(tmp_path) as app:
        _, session_id = await _new_session(app)
        project_id = await _resolved_project(app, project_root)
        service = app.state.services.get("editor_session_service", EditorSessionService)
        await service.bind(
            session_id=session_id,
            editor_instance_id="edi_0123456789ab",
            project_id=project_id,
        )

        with pytest.raises(ValidationFailed):
            await service.bind(
                session_id=session_id,
                editor_instance_id="edi_0123456789ab",
                project_id="prj_other",
            )


async def test_closed_binding_cannot_reopen(tmp_path, project_root) -> None:
    """T07-UT-003：CLOSED 绑定不可复用。"""

    async with _running(tmp_path) as app:
        _, session_id = await _new_session(app)
        project_id = await _resolved_project(app, project_root)
        service = app.state.services.get("editor_session_service", EditorSessionService)
        await service.bind(
            session_id=session_id,
            editor_instance_id="edi_0123456789ab",
            project_id=project_id,
        )
        await service.mark_closed(session_id)

        with pytest.raises(ValidationFailed):
            await service.bind(
                session_id=session_id,
                editor_instance_id="edi_0123456789ab",
                project_id=project_id,
            )


async def test_lease_fencing_token_is_monotonic(tmp_path, project_root) -> None:
    """T08-UT-001 / T08-UT-006：Fencing Token 按项目单调递增，旧令牌被拒绝。"""

    async with _running(tmp_path) as app:
        _, first_session = await _new_session(app)
        _, second_session = await _new_session(app, register_client=False)
        project_id = await _resolved_project(app, project_root)
        await _bind_session(app, first_session, project_id)
        await _bind_session(app, second_session, project_id)
        service = app.state.services.get("lease_service", LeaseService)

        first = await service.issue(session_id=first_session, project_id=project_id)
        second = await service.issue(session_id=second_session, project_id=project_id)

        assert first.fencing_token == 1
        assert second.fencing_token == 2
        assert second.status == "ACTIVE"

        with pytest.raises(FencingTokenStale):
            await service.validate(
                session_id=first_session,
                project_id=project_id,
                fencing_token=first.fencing_token,
            )


async def test_lease_renew_and_revoke(tmp_path, project_root) -> None:
    """T08-UT-002 / T08-UT-004：续期刷新时间，撤销后拒绝。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound_session(app, project_root)
        service = app.state.services.get("lease_service", LeaseService)

        lease = await service.issue(session_id=session_id, project_id=project_id)
        renewed = await service.renew(lease.lease_id)
        assert renewed.renewed_at is not None
        assert renewed.expires_at >= lease.expires_at

        revoked = await service.revoke(lease.lease_id, reason="user")
        assert revoked is not None
        assert revoked.status == "REVOKED"
        with pytest.raises(LeaseRevoked):
            await service.renew(lease.lease_id)


async def test_expired_lease_is_rejected(tmp_path, project_root) -> None:
    """T08-UT-003 / T08-UT-005：过期租约不通过校验，不提供受保护操作。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound_session(app, project_root)
        services = app.state.services
        database = services.get("database", DatabaseService)
        fixed = datetime(2026, 11, 20, 9, 0, 0, tzinfo=UTC)
        service = LeaseService(
            database,
            ttl_seconds=0,
            audit=services.get("audit_service", AuditService),
            clock=lambda: fixed,
        )

        lease = await service.issue(session_id=session_id, project_id=project_id)
        assert lease.status == "ACTIVE"
        with pytest.raises(LeaseExpired):
            await service.validate(session_id=session_id, project_id=project_id)
        assert await service.expire_stale() == 0


async def test_reissue_revokes_previous_lease_for_session(tmp_path, project_root) -> None:
    """T08-UT-005：同一 Session 重新握手后旧租约立即失效。"""

    async with _running(tmp_path) as app:
        session_id, project_id = await _bound_session(app, project_root)
        service = app.state.services.get("lease_service", LeaseService)

        first = await service.issue(session_id=session_id, project_id=project_id)
        second = await service.issue(session_id=session_id, project_id=project_id)

        with pytest.raises(FencingTokenStale):
            await service.validate(
                session_id=session_id,
                project_id=project_id,
                fencing_token=first.fencing_token,
            )
        current = await service.validate(
            session_id=session_id,
            project_id=project_id,
            fencing_token=second.fencing_token,
        )
        assert current.lease_id == second.lease_id


async def test_project_identity_is_stable(tmp_path, project_root) -> None:
    """T14 前置：同一路径解析出相同 project_id，指纹不可为空。"""

    async with _running(tmp_path) as app:
        first = await _resolved_project(app, project_root)
        second = await _resolved_project(app, project_root)

        assert first == second
        assert first.startswith("prj_")


async def test_invalid_project_root_is_rejected(tmp_path) -> None:
    async with _running(tmp_path) as app:
        service = app.state.services.get("project_service", ProjectService)
        with pytest.raises(ValidationFailed):
            await service.resolve(project_root=str(tmp_path / "missing"))
