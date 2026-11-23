"""E5 Tool Registry / Schema / Permission / Risk / Approval 集成测试（T17–T21）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    ApprovalHashMismatch,
    PermissionDenied,
    ToolAlreadyRegistered,
    ToolInputInvalid,
    ToolOutputInvalid,
    ToolSchemaInvalid,
)
from modules.access.service import ProjectAccessService
from modules.approval.service import ApprovalService
from modules.client.service import ClientService
from modules.project_registry.service import ProjectRegistryService
from modules.session.service import SessionService
from modules.task.service import TaskService
from modules.tool.approval import ToolApprovalGate, ToolApprovalScope
from modules.tool.permissions import (
    AgentPolicy,
    ToolPermissionEngine,
    ToolPermissionRequest,
)
from modules.tool.registry import ToolRegistryService
from modules.tool.risk import ToolRiskPolicy

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string", "minLength": 1}},
    "required": ["path"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}, "content": {"type": "string"}},
    "required": ["status"],
}


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e5.db').as_posix()}",
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
    return await projects.register(project_root=str(root), name="E5 Tools")


def _tools(app) -> ToolRegistryService:
    return app.state.services.get("tool_registry_service", ToolRegistryService)


def _engine(app) -> ToolPermissionEngine:
    return app.state.services.get("tool_permission_engine", ToolPermissionEngine)


def _gate(app) -> ToolApprovalGate:
    return app.state.services.get("tool_approval_gate", ToolApprovalGate)


async def _register(
    app,
    *,
    name: str,
    risk_level: str,
    permissions: tuple[str, ...] = ("project.read",),
    capabilities: tuple[str, ...] = (),
):
    return await _tools(app).register(
        name=name,
        category="FILE_SYSTEM",
        description="test tool",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        risk_level=risk_level,
        required_permissions=permissions,
        required_capabilities=capabilities,
    )


async def _actor(app) -> tuple[str, str]:
    clients = app.state.services.get("client_service", ClientService)
    registered = await clients.register(client_type="godot_editor", client_name="Editor")
    issued = await app.state.services.get("session_service", SessionService).create(
        registered.client_id
    )
    return issued.session.session_id, registered.client_id


async def _grant(
    app, project_id: str, level: str, session_id: str, client_id: str
) -> None:
    access = app.state.services.get("project_access_service", ProjectAccessService)
    await access.grant(
        project_id=project_id,
        session_id=session_id,
        client_id=client_id,
        access_level=level,
        granted_by="owner_1",
    )


def _request(
    project_id: str, tool, session_id: str, client_id: str, **overrides
) -> ToolPermissionRequest:
    values = {
        "user_id": "user_1",
        "project_id": project_id,
        "session_id": session_id,
        "client_id": client_id,
        "tool_id": tool.tool_id,
        "resource_scope": ("file:res://main.gd",),
    }
    values.update(overrides)
    return ToolPermissionRequest(**values)


async def test_tool_registration_enforces_schema_and_versions(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        tools = _tools(app)

        with pytest.raises(ToolSchemaInvalid):
            await tools.register(
                name="bad.tool",
                category="FILE_SYSTEM",
                description="bad",
                input_schema={"type": "array"},
                output_schema=OUTPUT_SCHEMA,
                risk_level="R0",
            )

        first = await _register(app, name="e5test.read", risk_level="R0")
        assert first.version == 1
        with pytest.raises(ToolAlreadyRegistered):
            await _register(app, name="e5test.read", risk_level="R0")

        second = await tools.register_version(
            "e5test.read",
            description="read a file",
            input_schema=INPUT_SCHEMA,
            output_schema=OUTPUT_SCHEMA,
            risk_level="R0",
        )
        assert second.version == 2
        assert second.category == "FILE_SYSTEM"

        latest = await tools.get_by_name("e5test.read")
        assert latest.tool_id == second.tool_id
        assert latest.version == 2
        assert latest.category == "FILE_SYSTEM"
        await tools.validate_input(second, {"path": "res://main.gd"})
        with pytest.raises(ToolInputInvalid):
            await tools.validate_input(second, {"path": ""})
        await tools.validate_output(second, {"status": "SUCCEEDED"})
        with pytest.raises(ToolOutputInvalid):
            await tools.validate_output(second, {"content": "missing status"})

        disabled = await tools.set_enabled(second.tool_id, False)
        assert disabled.enabled is False


async def test_risk_policy_only_allows_raising_risk(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        policy = ToolRiskPolicy()
        normal = await _register(app, name="e5test.write", risk_level="R2")
        high = await _register(app, name="e5test.delete", risk_level="R3")

        assert policy.assess(normal).changeset_required is True
        assert policy.assess(normal).approval_required is False

        lowered = policy.assess(high, requested_level="R0")
        assert lowered.level == "R3"
        assert "RISK_DOWNGRADE_IGNORED" in lowered.warnings
        assert lowered.approval_required is True

        raised = policy.assess(normal, requested_level="R4")
        assert raised.level == "R4"
        assert raised.strong_approval_required is True
        assert raised.approval_required is True


async def test_permission_engine_enforces_project_access_and_tool_permissions(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        tool = await _register(
            app,
            name="e5test.write",
            risk_level="R2",
            permissions=("project.write",),
            capabilities=("PROJECT_WRITE",),
        )
        engine = _engine(app)
        session_id, client_id = await _actor(app)

        await _grant(app, project.project_id, "viewer", session_id, client_id)
        viewer = await engine.check(_request(project.project_id, tool, session_id, client_id))
        assert viewer.allowed is False
        assert "MISSING_TOOL_PERMISSION" in viewer.reasons
        assert viewer.access_level == "viewer"

        await _grant(app, project.project_id, "editor", session_id, client_id)
        editor = await engine.check(_request(project.project_id, tool, session_id, client_id))
        assert editor.allowed is True
        assert editor.risk is not None and editor.risk.changeset_required is True

        no_session = await engine.check(
            _request(project.project_id, tool, "", client_id)
        )
        assert "SESSION_REQUIRED" in no_session.reasons

        wrong_client = await engine.check(
            _request(project.project_id, tool, session_id, "cli_x")
        )
        assert "PROJECT_ACCESS_DENIED" in wrong_client.reasons

        no_scope = await engine.check(
            _request(project.project_id, tool, session_id, client_id, resource_scope=())
        )
        assert "RESOURCE_SCOPE_REQUIRED" in no_scope.reasons

        with pytest.raises(PermissionDenied):
            await engine.require(
                _request(project.project_id, tool, session_id, client_id, resource_scope=())
            )


async def test_permission_engine_checks_task_and_agent_limits(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        tasks = app.state.services.get("task_service", TaskService)
        task = await tasks.create(project_id=project.project_id, title="Read files")
        tool = await _register(
            app, name="e5test.read", risk_level="R1", capabilities=("PROJECT_READ",)
        )
        engine = _engine(app)
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, "editor", session_id, client_id)

        allowed = await engine.check(
            _request(project.project_id, tool, session_id, client_id, task_id=task.task_id)
        )
        assert allowed.allowed is True

        await tasks.cancel(task.task_id, actor_id="owner_1")
        cancelled = await engine.check(
            _request(project.project_id, tool, session_id, client_id, task_id=task.task_id)
        )
        assert "TASK_TERMINAL" in cancelled.reasons

        denied_by_agent = await engine.check(
            _request(project.project_id, tool, session_id, client_id),
            agent_policy=AgentPolicy(
                definition_id="agt_1",
                allowed_tool_ids=frozenset(),
                allowed_capabilities=frozenset({"PROJECT_READ"}),
            ),
        )
        assert "AGENT_TOOL_NOT_ALLOWED" in denied_by_agent.reasons

        risk_denied = await engine.check(
            _request(project.project_id, tool, session_id, client_id),
            agent_policy=AgentPolicy(
                definition_id="agt_1",
                allowed_tool_ids=frozenset({tool.tool_id}),
                allowed_capabilities=frozenset({"PROJECT_READ"}),
                max_risk_level="R0",
            ),
        )
        assert "AGENT_RISK_EXCEEDED" in risk_denied.reasons


async def test_high_risk_tool_requires_approval_bound_to_content(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        tool = await _register(
            app,
            name="e5test.delete",
            risk_level="R3",
            permissions=("project.admin",),
        )
        engine = _engine(app)
        gate = _gate(app)
        approvals = app.state.services.get("approval_service", ApprovalService)
        session_id, client_id = await _actor(app)
        await _grant(app, project.project_id, "owner", session_id, client_id)

        payload = {"path": "res://scenes/boss.tscn"}
        scope_ref = ("file:res://scenes/boss.tscn",)
        missing = await engine.check(
            _request(
                project.project_id,
                tool,
                session_id,
                client_id,
                input_payload=payload,
                resource_scope=scope_ref,
            )
        )
        assert missing.allowed is False
        assert "APPROVAL_REQUIRED" in missing.reasons

        scope = ToolApprovalScope(
            project_id=project.project_id,
            tool_id=tool.tool_id,
            tool_version=tool.version,
            input_payload=payload,
            resource_scope=("file:res://scenes/boss.tscn",),
        )
        approval = await gate.request(scope, requested_by="user_1")

        pending = await engine.check(
            _request(
                project.project_id,
                tool,
                session_id,
                client_id,
                input_payload=payload,
                resource_scope=scope_ref,
                approval_id=approval.approval_id,
            )
        )
        assert pending.allowed is False
        assert any(reason.startswith("APPROVAL_INVALID:") for reason in pending.reasons)

        await approvals.approve(approval.approval_id, actor_id="owner_1")
        approved = await engine.check(
            _request(
                project.project_id,
                tool,
                session_id,
                client_id,
                input_payload=payload,
                resource_scope=scope_ref,
                approval_id=approval.approval_id,
            )
        )
        assert approved.allowed is True
        assert approved.approval is not None

        with pytest.raises(ApprovalHashMismatch):
            await gate.ensure_approved(
                approval.approval_id,
                ToolApprovalScope(
                    project_id=project.project_id,
                    tool_id=tool.tool_id,
                    tool_version=tool.version,
                    input_payload={"path": "res://scenes/player.tscn"},
                    resource_scope=("file:res://scenes/player.tscn",),
                ),
            )
