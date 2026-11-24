"""E5 工具 Adapter 与工具 API 集成测试（T28–T30）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import EditorCommandTimeout
from infrastructure.database.transaction import transaction
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.editor_command.hub import EditorCommandResponse
from modules.project_registry.service import ProjectRegistryService
from modules.tool.adapters import ToolDispatchContext
from modules.tool.catalog import ensure_builtin_tools
from modules.tool.file_adapter import FileToolAdapter
from modules.tool.godot_adapter import GodotToolAdapter
from modules.tool.models import ToolExecutionModel
from modules.tool.registry import ToolRegistryService
from modules.tool.repository import ToolExecutionRepository


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e5-adapters.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


@asynccontextmanager
async def _running_client(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e5-api.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


def _project_root(tmp_path: Path) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    (root / "project.godot").write_text('[application]\n\nconfig/name="E5"\n', encoding="utf-8")
    (root / "scenes").mkdir()
    (root / "scenes" / "main.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    (root / ".godot").mkdir()
    (root / ".godot" / "cache.bin").write_text("x", encoding="utf-8")
    return root


async def _register_project(app, root: Path):
    projects = app.state.services.get("project_registry_service", ProjectRegistryService)
    return await projects.register(project_root=str(root), name="E5 Adapter")


def _context(
    project_id: str, tool_name: str, data: dict, *, session_id: str | None = "sess_1"
) -> ToolDispatchContext:
    return ToolDispatchContext(
        execution_id="exec_000000000001",
        project_id=project_id,
        tool_id="tool_test",
        tool_name=tool_name,
        tool_version=1,
        input=data,
        session_id=session_id,
        resource_scope=("file:res://main.gd",),
        fencing_token=1,
        timeout_seconds=5.0,
    )


class FakeConnection:
    def __init__(self, response: EditorCommandResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def send_command(self, action: str, payload: dict, *, timeout: float):
        self.calls.append((action, payload))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeHub:
    def __init__(self, connection: FakeConnection | None) -> None:
        self.connection = connection

    def get(self, session_id: str):
        return self.connection


async def test_builtin_tools_are_registered_idempotently(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        registry = app.state.services.get("tool_registry_service", ToolRegistryService)
        assert await ensure_builtin_tools(registry) == (0, 0)
        tool = await registry.get_by_name("file.read")
        assert tool is not None
        assert tool.category == "FILE_SYSTEM"
        assert tool.risk_level == "R0"
        godot_tool = await registry.get_by_name("godot.node.list")
        assert godot_tool is not None
        assert godot_tool.category in ("NODE", "GODOT_EDITOR")


async def test_file_adapter_enforces_project_scope(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    async with _running(tmp_path) as app:
        project = await _register_project(app, root)
        adapter = FileToolAdapter(
            app.state.services.get("project_registry_service", ProjectRegistryService)
        )

        ok = await adapter.execute(
            _context(project.project_id, "file.read", {"path": "res://scenes/main.tscn"})
        )
        assert ok.status == "SUCCEEDED"
        assert ok.output["content"].startswith("[gd_scene")

        for bad_path in (
            "../outside.txt",
            str(root / "project.godot"),
            "project.godot",
            ".godot/cache.bin",
        ):
            denied = await adapter.execute(
                _context(project.project_id, "file.read", {"path": bad_path})
            )
            assert denied.status == "FAILED", bad_path
            assert denied.error_code == "FILE_PATH_DENIED", bad_path


async def test_file_adapter_write_verify_patch_move_delete(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    async with _running(tmp_path) as app:
        project = await _register_project(app, root)
        adapter = FileToolAdapter(
            app.state.services.get("project_registry_service", ProjectRegistryService)
        )

        async def call(tool: str, data: dict):
            return await adapter.execute(_context(project.project_id, tool, data))

        created = await call("file.create", {"path": "src/player.gd", "content": "extends Node\n"})
        assert created.status == "SUCCEEDED"
        assert created.output["created"] is True
        checks = {check.name: check for check in created.checks}
        assert checks["content_verified"].passed is True
        assert checks["import_pending"].passed is None
        assert checks["editor_refresh"].passed is None

        again = await call("file.create", {"path": "src/player.gd", "content": "x"})
        assert again.error_code == "FILE_ALREADY_EXISTS"

        patched = await call(
            "file.patch",
            {
                "path": "src/player.gd",
                "old_text": "extends Node",
                "new_text": "extends CharacterBody2D",
            },
        )
        assert patched.status == "SUCCEEDED"
        assert patched.output["replacements"] == 1

        read = await call("file.read", {"path": "src/player.gd"})
        assert read.output["content"] == "extends CharacterBody2D\n"
        assert read.output["sha256"] == hashlib.sha256(b"extends CharacterBody2D\n").hexdigest()

        stat = await call("file.stat", {"path": "src/player.gd"})
        assert stat.output["is_file"] is True

        listed = await call("file.list", {"path": "src"})
        assert [entry["name"] for entry in listed.output["entries"]] == ["player.gd"]

        searched = await call("file.search", {"path": "src", "pattern": "CharacterBody2D"})
        assert searched.output["matches"][0]["line"] == 1

        renamed = await call("file.rename", {"path": "src/player.gd", "new_name": "hero.gd"})
        assert renamed.status == "SUCCEEDED"
        assert (root / "src" / "hero.gd").is_file()

        moved = await call("file.move", {"path": "src/hero.gd", "destination": "scripts/hero.gd"})
        assert moved.status == "SUCCEEDED"
        assert (root / "scripts" / "hero.gd").is_file()

        deleted = await call("file.delete", {"path": "scripts/hero.gd"})
        assert deleted.status == "SUCCEEDED"
        assert not (root / "scripts" / "hero.gd").exists()


async def test_godot_adapter_requires_connection_and_parses_response(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _register_project(app, _project_root(tmp_path))

        offline = GodotToolAdapter(FakeHub(None))
        missing = await offline.execute(_context(project.project_id, "godot.node.list", {}))
        assert missing.status == "FAILED"
        assert missing.error_code == "EDITOR_NOT_CONNECTED"

        connection = FakeConnection(
            EditorCommandResponse(
                success=True,
                data={
                    "status": "SUCCEEDED",
                    "output": {"nodes": []},
                    "checks": [{"name": "node_list", "passed": True, "detail": "0 nodes"}],
                    "evidence_refs": ["editor://scene/main"],
                },
                error=None,
            )
        )
        adapter = GodotToolAdapter(FakeHub(connection))
        result = await adapter.execute(_context(project.project_id, "godot.node.list", {}))
        assert result.status == "SUCCEEDED"
        assert result.output == {"nodes": []}
        assert result.checks[0].passed is True
        assert result.evidence_refs == ("editor://scene/main",)
        action, payload = connection.calls[0]
        assert action == "editor.command.execute"
        assert payload["phase"] == "EXECUTE"
        assert payload["tool_name"] == "godot.node.list"

        failed = GodotToolAdapter(
            FakeHub(
                FakeConnection(
                    EditorCommandResponse(
                        success=False,
                        data={},
                        error={"code": "TOOL_UNSUPPORTED", "message": "not implemented"},
                    )
                )
            )
        ).execute(_context(project.project_id, "godot.debug.get_errors", {}))
        failed_result = await failed
        assert failed_result.status == "FAILED"
        assert failed_result.error_code == "TOOL_UNSUPPORTED"

        timeout_adapter = GodotToolAdapter(FakeHub(FakeConnection(EditorCommandTimeout("超时"))))
        timeout_result = await timeout_adapter.execute(
            _context(project.project_id, "godot.node.list", {})
        )
        assert timeout_result.status == "UNKNOWN"
        assert timeout_result.error_code == "EDITOR_COMMAND_TIMEOUT"
        assert (
            await timeout_adapter.inspect(_context(project.project_id, "godot.node.list", {}))
            is None
        )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _admin_session(app, client) -> str:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": "admin", "client_name": "E5 admin"},
        headers={"X-Bootstrap-Token": bootstrap},
    )
    body = registered.json()
    challenge = (
        await client.post("/api/v1/auth/challenge", json={"client_id": body["client_id"]})
    ).json()
    verified = await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "client_id": body["client_id"],
            "proof": _proof(
                body["client_secret"], challenge["challenge_id"], challenge["challenge"]
            ),
        },
    )
    issued = await client.post("/api/v1/sessions", headers=_bearer(verified.json()["access_token"]))
    return issued.json()["session_token"]


async def test_tool_api_and_execution_cancel(tmp_path: Path) -> None:
    async with _running_client(tmp_path) as (app, client):
        root = _project_root(tmp_path)
        token = await _admin_session(app, client)
        headers = _bearer(token)
        created = await client.post(
            "/api/v1/projects",
            json={"project_root": str(root), "name": "E5 API"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["project_id"]

        unauthorized = await client.get("/api/v1/tools", params={"project_id": project_id})
        assert unauthorized.status_code == 401

        listed = await client.get(
            "/api/v1/tools",
            params={"project_id": project_id, "category": "FILE_SYSTEM"},
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        names = {item["name"] for item in listed.json()["items"]}
        assert "file.read" in names

        tool_id = next(
            item["tool_id"] for item in listed.json()["items"] if item["name"] == "file.read"
        )
        schema = await client.get(
            f"/api/v1/tools/{tool_id}/schema", params={"project_id": project_id}, headers=headers
        )
        assert schema.status_code == 200
        assert schema.json()["input_schema"]["required"] == ["path"]

        now = datetime.now(UTC)
        database = app.state.services.get("database")
        async with database.session() as session, transaction(session):
            await ToolExecutionRepository(session).add(
                ToolExecutionModel(
                    execution_id="exec_cancel_0001",
                    idempotency_key=None,
                    project_id=project_id,
                    task_id=None,
                    attempt_id=None,
                    agent_instance_id=None,
                    tool_id=tool_id,
                    tool_name="file.read",
                    tool_version=1,
                    risk_level="R0",
                    input_payload='{"path": "res://scenes/main.tscn"}',
                    input_hash=None,
                    changeset_id=None,
                    approval_id=None,
                    session_id=None,
                    client_id=None,
                    actor_id=None,
                    resource_scope="[]",
                    fencing_token=None,
                    status="CREATED",
                    output_payload=None,
                    error_code=None,
                    error_message=None,
                    evidence_refs="[]",
                    verification_status="PENDING",
                    started_at=None,
                    completed_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )

        executions = await client.get(
            "/api/v1/tool-executions", params={"project_id": project_id}, headers=headers
        )
        assert executions.status_code == 200, executions.text
        assert executions.json()["items"][0]["status"] == "CREATED"

        cancelled = await client.post(
            "/api/v1/tool-executions/exec_cancel_0001/cancel",
            json={"reason": "用户取消"},
            headers=headers,
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "CANCELLED"

        audits = await client.get(
            "/api/v1/tool-audits", params={"project_id": project_id}, headers=headers
        )
        assert audits.status_code == 200, audits.text
        assert audits.json()["items"][0]["execution_status"] == "CANCELLED"


async def test_model_api_lists_and_registers_provider(tmp_path: Path) -> None:
    async with _running_client(tmp_path) as (app, client):
        root = _project_root(tmp_path)
        token = await _admin_session(app, client)
        headers = _bearer(token)
        created = await client.post(
            "/api/v1/projects",
            json={"project_root": str(root), "name": "E5 Models"},
            headers=headers,
        )
        project_id = created.json()["project_id"]

        models = await client.get(
            "/api/v1/models", params={"project_id": project_id}, headers=headers
        )
        assert models.status_code == 200, models.text
        assert models.json()["items"] == []

        usage = await client.get(
            "/api/v1/model-usage", params={"project_id": project_id}, headers=headers
        )
        assert usage.status_code == 200
        assert usage.json()["total_tokens"] == 0

        cost = await client.get(
            "/api/v1/model-cost", params={"project_id": project_id}, headers=headers
        )
        assert cost.status_code == 200
        assert float(cost.json()["total_cost"]) == 0.0

        provider = await client.post(
            "/api/v1/providers",
            json={
                "project_id": project_id,
                "name": "OpenAI",
                "provider_type": "OPENAI",
                "endpoint": "https://api.openai.com/v1",
                "credential_ref": "e5_test_key",
                "api_key": "sk-test",
            },
            headers=headers,
        )
        assert provider.status_code == 200, provider.text
        body = provider.json()
        assert body["name"] == "OpenAI"
        assert body["configuration"]["credential_ref"] == "e5_test_key"
        assert "sk-test" not in provider.text

        providers = await client.get(
            "/api/v1/providers", params={"project_id": project_id}, headers=headers
        )
        assert providers.status_code == 200
        assert providers.json()["items"][0]["provider_id"] == body["provider_id"]
