"""E5 工具执行引擎集成测试（T22–T27）。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    PermissionDenied,
    ProjectAccessDenied,
    ResourceLockConflict,
    ToolAdapterMissing,
    ToolInputInvalid,
    ValidationFailed,
)
from core.events.model import Event
from core.events.registry import EventRegistry
from modules.access.service import ProjectAccessService
from modules.client.service import ClientService
from modules.project_registry.service import ProjectRegistryService
from modules.session.service import SessionService
from modules.tool.adapters import (
    AdapterResult,
    ToolAdapterRegistry,
    ToolDispatchContext,
    VerificationCheck,
)
from modules.tool.audit import ToolAuditService
from modules.tool.execution import ToolExecutionRequest, ToolExecutionService
from modules.tool.idempotency import build_idempotency_key
from modules.tool.locks import ResourceLockService
from modules.tool.models import EXECUTION_SUCCEEDED, EXECUTION_TIMEOUT, EXECUTION_UNKNOWN
from modules.tool.registry import ToolRegistryService
from modules.tool.verification import ToolVerificationService

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string", "minLength": 1}},
    "required": ["path"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
}
RESOURCE = "file:res://main.gd"


class FakeAdapter:
    name = "fake"

    def __init__(self) -> None:
        self.executions: list[ToolDispatchContext] = []
        self.inspections: list[ToolDispatchContext] = []
        self.executor = None
        self.inspector = None

    def supports(self, tool) -> bool:
        return tool.category == "CODE"

    async def execute(self, context: ToolDispatchContext) -> AdapterResult:
        self.executions.append(context)
        if self.executor is not None:
            return await self.executor(context)
        return _success_result()

    async def inspect(self, context: ToolDispatchContext) -> AdapterResult | None:
        self.inspections.append(context)
        if self.inspector is not None:
            return await self.inspector(context)
        return None


def _success_result() -> AdapterResult:
    return AdapterResult(
        status=EXECUTION_SUCCEEDED,
        output={"status": "SUCCEEDED"},
        checks=(VerificationCheck("FILE_STATE", True, "res://main.gd"),),
        evidence_refs=("evidence://file/main.gd",),
    )


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e5-exec.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


async def _project(app, tmp_path: Path):
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    projects = app.state.services.get("project_registry_service", ProjectRegistryService)
    return await projects.register(project_root=str(root), name="E5 Execution")


async def _actor(app) -> tuple[str, str]:
    clients = app.state.services.get("client_service", ClientService)
    registered = await clients.register(client_type="godot_editor", client_name="Editor")
    issued = await app.state.services.get("session_service", SessionService).create(
        registered.client_id
    )
    return issued.session.session_id, registered.client_id


async def _grant(app, project_id: str, session_id: str, client_id: str, level: str) -> None:
    access = app.state.services.get("project_access_service", ProjectAccessService)
    await access.grant(
        project_id=project_id,
        session_id=session_id,
        client_id=client_id,
        access_level=level,
        granted_by="owner_1",
    )


async def _register_tool(
    app,
    *,
    name: str = "e5test.write",
    category: str = "CODE",
    risk_level: str = "R1",
    permissions: tuple[str, ...] = ("project.write",),
    idempotency_policy: str = "NONE",
    timeout_seconds: int = 10,
):
    return await app.state.services.get("tool_registry_service", ToolRegistryService).register(
        name=name,
        category=category,
        description="test tool",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        risk_level=risk_level,
        required_permissions=permissions,
        execution_mode="SYNC",
        timeout_seconds=timeout_seconds,
        idempotency_policy=idempotency_policy,
    )


def _adapter(app) -> FakeAdapter:
    adapter = FakeAdapter()
    app.state.services.get("tool_adapter_registry", ToolAdapterRegistry).register(adapter)
    return adapter


def _executor(app) -> ToolExecutionService:
    return app.state.services.get("tool_execution_service", ToolExecutionService)


def _locks(app) -> ResourceLockService:
    return app.state.services.get("tool_lock_service", ResourceLockService)


def _audits(app) -> ToolAuditService:
    return app.state.services.get("tool_audit_service", ToolAuditService)


def _request(project_id: str, tool, session_id: str, client_id: str, **overrides):
    values = {
        "project_id": project_id,
        "tool_id": tool.tool_id,
        "tool_version": tool.version,
        "input": {"path": "res://main.gd"},
        "session_id": session_id,
        "client_id": client_id,
        "actor_id": "user_1",
        "resource_scope": (RESOURCE,),
    }
    values.update(overrides)
    return ToolExecutionRequest(**values)


async def test_execution_success_records_verification_audit_and_event(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        adapter = _adapter(app)
        tool = await _register_tool(app)
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "editor")

        received: list[Event] = []

        async def capture(event: Event) -> None:
            received.append(event)

        app.state.services.get("event_registry", EventRegistry).register(
            "tool.execution.completed", capture, consumer_id="test.capture"
        )

        result = await _executor(app).execute(
            _request(project.project_id, tool, session_id, client_id)
        )

        assert result.status == EXECUTION_SUCCEEDED
        assert result.verification_status == "VERIFIED"
        assert result.output == {"status": "SUCCEEDED"}
        assert "evidence://file/main.gd" in result.evidence_refs
        assert result.reused is False
        assert len(adapter.executions) == 1
        assert adapter.executions[0].fencing_token == 1

        view = await _executor(app).get(result.execution_id)
        assert view.status == EXECUTION_SUCCEEDED
        assert view.completed_at is not None
        assert view.fencing_token == 1

        assert await _locks(app).active_for_resource(project.project_id, RESOURCE) == ()
        audits = await _audits(app).list_for_execution(result.execution_id)
        assert len(audits) == 1
        assert audits[0].execution_status == EXECUTION_SUCCEEDED
        assert audits[0].actor_type == "USER"
        assert "res://main.gd" in audits[0].input_summary
        assert [event.event_type for event in received] == ["tool.execution.completed"]
        assert received[0].payload["execution_id"] == result.execution_id

        verifications = await app.state.services.get(
            "tool_verification_service", ToolVerificationService
        ).history(result.execution_id)
        assert len(verifications) == 1
        assert verifications[0].verification_status == "VERIFIED"


async def test_execution_denied_without_write_permission(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        adapter = _adapter(app)
        tool = await _register_tool(app)
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "viewer")

        with pytest.raises(PermissionDenied):
            await _executor(app).execute(_request(project.project_id, tool, session_id, client_id))

        assert adapter.executions == []
        page = await _executor(app).list_for_project(project.project_id)
        assert page["total"] == 1
        assert page["items"][0].status == "FAILED"
        audits = await _audits(app).list_for_execution(page["items"][0].execution_id)
        assert audits[0].execution_status == "FAILED"
        assert audits[0].failure_reason == "PERMISSION_DENIED"


async def test_invalid_input_and_missing_adapter_fail_closed(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        adapter = _adapter(app)
        tool = await _register_tool(app)
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "editor")

        with pytest.raises(ToolInputInvalid):
            await _executor(app).execute(
                _request(project.project_id, tool, session_id, client_id, input={"path": ""})
            )
        assert adapter.executions == []

        script_tool = await _register_tool(
            app, name="e5test.run", category="EXTERNAL_SERVICE", risk_level="R1"
        )
        with pytest.raises(ToolAdapterMissing):
            await _executor(app).execute(
                _request(project.project_id, script_tool, session_id, client_id)
            )
        page = await _executor(app).list_for_project(project.project_id)
        assert [item.status for item in page["items"]] == ["FAILED", "FAILED"]


async def test_idempotent_replay_reuses_completed_execution(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        adapter = _adapter(app)
        tool = await _register_tool(app, idempotency_policy="KEYED")
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "editor")

        key = build_idempotency_key(
            project_id=project.project_id, tool_id=tool.tool_id, logical_operation_id="op-1"
        )
        request = _request(project.project_id, tool, session_id, client_id, idempotency_key=key)

        first = await _executor(app).execute(request)
        second = await _executor(app).execute(request)

        assert first.reused is False
        assert second.reused is True
        assert second.execution_id == first.execution_id
        assert len(adapter.executions) == 1
        assert second.status == EXECUTION_SUCCEEDED

        with pytest.raises(ValidationFailed):
            await _executor(app).execute(_request(project.project_id, tool, session_id, client_id))


async def test_unknown_execution_is_recovered_by_inspection(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        adapter = _adapter(app)

        async def explode(context: ToolDispatchContext) -> AdapterResult:
            raise RuntimeError("editor disconnected")

        adapter.executor = explode
        adapter.inspector = lambda context: _async_value(_success_result())
        tool = await _register_tool(app, idempotency_policy="KEYED")
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "editor")

        key = build_idempotency_key(
            project_id=project.project_id, tool_id=tool.tool_id, logical_operation_id="op-2"
        )
        request = _request(project.project_id, tool, session_id, client_id, idempotency_key=key)

        first = await _executor(app).execute(request)
        assert first.status == EXECUTION_UNKNOWN
        assert first.verification_status == "UNKNOWN"

        second = await _executor(app).execute(request)
        assert second.reused is True
        assert second.execution_id == first.execution_id
        assert second.status == EXECUTION_SUCCEEDED
        assert second.verification_status == "VERIFIED"
        assert len(adapter.executions) == 1
        assert len(adapter.inspections) == 1


async def test_timeout_marks_execution_unknown_for_recovery(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        adapter = _adapter(app)

        async def slow(context: ToolDispatchContext) -> AdapterResult:
            await asyncio.sleep(1.2)
            return _success_result()

        adapter.executor = slow
        tool = await _register_tool(app, timeout_seconds=1)
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "editor")

        result = await _executor(app).execute(
            _request(project.project_id, tool, session_id, client_id)
        )

        assert result.status == EXECUTION_TIMEOUT
        assert result.verification_status == "UNKNOWN"
        view = await _executor(app).get(result.execution_id)
        assert view.completed_at is not None


async def test_resource_lock_conflict_blocks_execution(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        adapter = _adapter(app)
        tool = await _register_tool(app)
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "editor")
        await _locks(app).acquire(
            project_id=project.project_id,
            resource_key=RESOURCE,
            owner_type="SESSION",
            owner_id="other-session",
            lock_type="WRITE_LOCK",
        )

        with pytest.raises(ResourceLockConflict):
            await _executor(app).execute(_request(project.project_id, tool, session_id, client_id))

        assert adapter.executions == []
        page = await _executor(app).list_for_project(project.project_id)
        assert page["items"][0].status == "FAILED"
        held = await _locks(app).active_for_resource(project.project_id, RESOURCE)
        assert len(held) == 1 and held[0].owner_id == "other-session"


async def test_normal_write_risk_requires_changeset(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        _adapter(app)
        tool = await _register_tool(app, name="e5test.delete", risk_level="R2")
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "editor")

        with pytest.raises(PermissionDenied) as denied:
            await _executor(app).execute(_request(project.project_id, tool, session_id, client_id))
        assert "CHANGESET_REQUIRED" in denied.value.details["reasons"]


async def test_audit_query_requires_project_access(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        _adapter(app)
        tool = await _register_tool(app)
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, session_id, client_id, "editor")
        await _executor(app).execute(_request(project.project_id, tool, session_id, client_id))

        with pytest.raises(ProjectAccessDenied):
            await _audits(app).list_for_project(
                project.project_id,
                access=app.state.services.get("project_access_service", ProjectAccessService),
                session_id=session_id,
                client_id="cli_unknown",
            )

        page = await _audits(app).list_for_project(
            project.project_id,
            access=app.state.services.get("project_access_service", ProjectAccessService),
            session_id=session_id,
            client_id=client_id,
        )
        assert page["total"] == 1


async def _async_value(value):
    return value
