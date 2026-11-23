"""E5 验收集成测试（T31）：只读执行、写操作拒绝与中断恢复。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import PermissionDenied
from modules.access.service import ProjectAccessService
from modules.client.service import ClientService
from modules.project_registry.service import ProjectRegistryService
from modules.session.service import SessionService
from modules.tool.adapters import AdapterResult, VerificationCheck
from modules.tool.audit import ToolAuditService
from modules.tool.execution import ToolExecutionRequest, ToolExecutionService
from modules.tool.models import (
    EXECUTION_SUCCEEDED,
    EXECUTION_UNKNOWN,
    VERIFICATION_VERIFIED,
)
from modules.tool.recovery import ToolRecoveryService
from modules.tool.registry import ToolRegistryService

OBJECT_SCHEMA = {"type": "object"}


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e5-acceptance.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


async def _project(app, tmp_path: Path):
    root = tmp_path / "game"
    (root / "scenes").mkdir(parents=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    (root / "scenes" / "main.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    projects = app.state.services.get("project_registry_service", ProjectRegistryService)
    return await projects.register(project_root=str(root), name="E5 Acceptance")


async def _actor(app, project_id: str, level: str) -> tuple[str, str]:
    clients = app.state.services.get("client_service", ClientService)
    registered = await clients.register(client_type="godot_editor", client_name="Acceptance")
    issued = await app.state.services.get("session_service", SessionService).create(
        registered.client_id
    )
    session_id = issued.session.session_id
    access = app.state.services.get("project_access_service", ProjectAccessService)
    await access.grant(
        project_id=project_id,
        session_id=session_id,
        client_id=registered.client_id,
        access_level=level,
        granted_by="owner_1",
    )
    return session_id, registered.client_id


async def test_read_only_tool_runs_end_to_end(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        session_id, client_id = await _actor(app, project.project_id, "viewer")
        registry = app.state.services.get("tool_registry_service", ToolRegistryService)
        tool = await registry.get_by_name("file.read")
        service = app.state.services.get("tool_execution_service", ToolExecutionService)

        result = await service.execute(
            ToolExecutionRequest(
                project_id=project.project_id,
                tool_id=tool.tool_id,
                input={"path": "res://scenes/main.tscn"},
                session_id=session_id,
                client_id=client_id,
                actor_id=client_id,
                resource_scope=("file:res://scenes/main.tscn",),
            )
        )

        assert result.status == EXECUTION_SUCCEEDED
        assert result.verification_status == VERIFICATION_VERIFIED
        assert result.output["content"].startswith("[gd_scene")
        assert result.output["sha256"]
        assert result.evidence_refs

        audits = app.state.services.get("tool_audit_service", ToolAuditService)
        page = await audits.list_for_project(
            project.project_id,
            access=app.state.services.get("project_access_service", ProjectAccessService),
            session_id=session_id,
            client_id=client_id,
        )
        assert page["items"][0]["execution_id"] == result.execution_id
        assert page["items"][0]["execution_status"] == EXECUTION_SUCCEEDED


async def test_project_write_requires_changeset_and_does_not_touch_disk(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        session_id, client_id = await _actor(app, project.project_id, "editor")
        registry = app.state.services.get("tool_registry_service", ToolRegistryService)
        tool = await registry.get_by_name("file.write")
        service = app.state.services.get("tool_execution_service", ToolExecutionService)
        target = Path(project.project_root) / "notes.txt"

        with pytest.raises(PermissionDenied) as exc:
            await service.execute(
                ToolExecutionRequest(
                    project_id=project.project_id,
                    tool_id=tool.tool_id,
                    input={"path": "res://notes.txt", "content": "hello"},
                    session_id=session_id,
                    client_id=client_id,
                    actor_id=client_id,
                    resource_scope=("file:res://notes.txt",),
                )
            )
        assert "CHANGESET_REQUIRED" in exc.value.details["reasons"]
        assert not target.exists()


class _FlakyAdapter:
    """先返回 UNKNOWN，恢复观测时给出可验证结果（模拟编辑器断连后重连）。"""

    name = "e5_acceptance"

    def __init__(self) -> None:
        self.recovered = False

    def supports(self, tool) -> bool:
        return tool.category == "IMPORT"

    async def execute(self, context):
        return AdapterResult(
            status=EXECUTION_UNKNOWN,
            checks=(VerificationCheck("editor_response", None, "连接中断"),),
        )

    async def inspect(self, context):
        self.recovered = True
        return AdapterResult(
            status=EXECUTION_SUCCEEDED,
            output={"nodes": ["Player"]},
            checks=(VerificationCheck("node_list", True, "1 node"),),
            evidence_refs=("editor://scene/main",),
        )


async def test_unknown_execution_recovers_after_editor_reconnect(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        session_id, client_id = await _actor(app, project.project_id, "viewer")
        registry = app.state.services.get("tool_registry_service", ToolRegistryService)
        tool = await registry.register(
            name="e5accept.node.list",
            category="IMPORT",
            description="acceptance node list",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema=OBJECT_SCHEMA,
            risk_level="R0",
            required_permissions=("project.read",),
            execution_mode="SYNC",
            timeout_seconds=5,
            idempotency_policy="NONE",
        )

        adapter = _FlakyAdapter()
        app.state.services.get("tool_adapter_registry").register(adapter)
        service = app.state.services.get("tool_execution_service", ToolExecutionService)

        result = await service.execute(
            ToolExecutionRequest(
                project_id=project.project_id,
                tool_id=tool.tool_id,
                input={},
                session_id=session_id,
                client_id=client_id,
                actor_id=client_id,
            )
        )
        assert result.status == EXECUTION_UNKNOWN

        recovery = app.state.services.get("tool_recovery_service", ToolRecoveryService)
        outcome = await recovery.recover(result.execution_id)
        assert adapter.recovered
        assert outcome.status == EXECUTION_SUCCEEDED
        assert outcome.verification_status == VERIFICATION_VERIFIED
