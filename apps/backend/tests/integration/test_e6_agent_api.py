"""E6-T17 Agent API 测试：定义、实例、控制、执行、事件、指标、追踪与越权。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from bootstrap.application import create_app
from config.settings import load_settings
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.agent_runtime.execution import AgentExecutionService
from modules.agent_runtime.instance import AgentInstanceService
from modules.model_gateway.registry import CapabilitySetting, ModelRegistryService
from modules.prompt.service import PromptService
from modules.task.service import AttemptService, TaskService

MODEL_CAPABILITIES = ("TEXT_INPUT", "TEXT_OUTPUT", "TOOL_CALLING", "STRUCTURED_OUTPUT")


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e6api.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _session_for(app, client, client_type: str) -> str:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": client_type, "client_name": f"E6 {client_type}"},
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


async def _register_model(app) -> None:
    registry = app.state.services.get("model_registry_service", ModelRegistryService)
    provider = await registry.register_provider(name="fake-provider", provider_type="OPENAI")
    await registry.register_model(
        provider_id=provider.provider_id,
        model_key="fake-1",
        display_name="Fake Model",
        context_window=16000,
        max_output_tokens=1024,
        capabilities={
            name: CapabilitySetting(support_status="SUPPORTED", evidence_source="test-fixture")
            for name in MODEL_CAPABILITIES
        },
    )


async def _project_and_task(app, client, headers, tmp_path: Path) -> tuple[str, str, str]:
    root = tmp_path / "agent_api_project"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    created = await client.post(
        "/api/v1/projects",
        json={"project_root": str(root), "name": "E6 API"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["project_id"]

    prompts = app.state.services.get("prompt_service", PromptService)
    await prompts.create(name="e6_api_prompt", category="AGENT", content="You are an E6 API agent.")
    tasks = app.state.services.get("task_service", TaskService)
    attempts = app.state.services.get("task_attempt_service", AttemptService)
    task = await tasks.create(project_id=project_id, title="Agent API task")
    attempt = await attempts.create(task.task_id)
    return project_id, task.task_id, attempt.attempt_id


async def test_agent_api_lifecycle_and_observability(tmp_path: Path) -> None:
    async with _running(tmp_path) as (app, client):
        await _register_model(app)
        token = await _session_for(app, client, "admin")
        headers = _bearer(token)
        project_id, task_id, attempt_id = await _project_and_task(app, client, headers, tmp_path)

        definition = await client.post(
            "/api/v1/agents/definitions",
            json={
                "name": "api_agent",
                "prompt_profile_id": "e6_api_prompt",
                "capabilities": ["task_analysis"],
                "tool_whitelist": [],
                "permission_ceiling": "R0",
                "budget": {"max_iterations": 8},
            },
            headers=headers,
        )
        assert definition.status_code == 200, definition.text
        definition_id = definition.json()["definition_id"]
        assert definition.json()["status"] == "DRAFT"

        published = await client.post(
            f"/api/v1/agents/definitions/{definition_id}/publish", headers=headers
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "ACTIVE"

        listed = await client.get("/api/v1/agents/definitions", headers=headers)
        assert listed.status_code == 200
        assert any(item["definition_id"] == definition_id for item in listed.json()["items"])

        versions = await client.get(
            f"/api/v1/agents/definitions/{definition_id}/versions", headers=headers
        )
        assert versions.status_code == 200
        assert versions.json()["items"][0]["version"] == "1.0.0"

        created = await client.post(
            "/api/v1/agents/instances",
            json={
                "definition_id": definition_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        instance_id = created.json()["instance_id"]
        assert created.json()["status"] == "CREATED"

        started = await client.post(
            f"/api/v1/agents/instances/{instance_id}/start", headers=headers
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "RUNNING"

        executions = app.state.services.get("agent_execution_service", AgentExecutionService)
        instances = app.state.services.get("agent_instance_service", AgentInstanceService)
        execution = await executions.start_execution(await instances.get(instance_id))

        paused = await client.post(
            f"/api/v1/agents/instances/{instance_id}/pause",
            json={"reason": "USER"},
            headers=headers,
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()["status"] == "PAUSED"

        resumed = await client.post(
            f"/api/v1/agents/instances/{instance_id}/resume",
            json={},
            headers=headers,
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "RUNNING"

        execution_list = await client.get(
            f"/api/v1/agents/instances/{instance_id}/executions", headers=headers
        )
        assert execution_list.status_code == 200
        assert execution_list.json()["items"][0]["execution_id"] == execution.execution_id

        fetched = await client.get(
            f"/api/v1/agents/executions/{execution.execution_id}", headers=headers
        )
        assert fetched.status_code == 200
        assert fetched.json()["budget_usage"] == {}

        missing_plan = await client.get(
            f"/api/v1/agents/executions/{execution.execution_id}/plan", headers=headers
        )
        assert missing_plan.status_code == 404
        assert missing_plan.json()["error"]["code"] == "NOT_FOUND"

        steps = await client.get(
            f"/api/v1/agents/executions/{execution.execution_id}/steps", headers=headers
        )
        assert steps.status_code == 200
        assert steps.json()["items"] == []

        events = await client.get(f"/api/v1/agents/instances/{instance_id}/events", headers=headers)
        assert events.status_code == 200
        event_types = [item["event_type"] for item in events.json()["items"]]
        assert "RESUME_REQUESTED" in event_types

        metrics = await client.get(
            f"/api/v1/agents/metrics?project_id={project_id}", headers=headers
        )
        assert metrics.status_code == 200, metrics.text
        assert metrics.json()["agent_instance_count"] == 1
        assert metrics.json()["running_execution_count"] == 1

        trace = await client.get(
            f"/api/v1/agents/executions/{execution.execution_id}/trace", headers=headers
        )
        assert trace.status_code == 200, trace.text
        body = trace.json()
        assert body["instance"]["instance_id"] == instance_id
        assert body["execution"]["execution_id"] == execution.execution_id
        assert body["task"]["task_id"] == task_id
        assert body["attempt"]["attempt_id"] == attempt_id

        stopped = await client.post(
            f"/api/v1/agents/instances/{instance_id}/stop",
            json={"reason": "USER_CANCEL"},
            headers=headers,
        )
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "STOPPED"


async def test_agent_instance_requires_project_access(tmp_path: Path) -> None:
    async with _running(tmp_path) as (app, client):
        await _register_model(app)
        admin_token = await _session_for(app, client, "admin")
        admin_headers = _bearer(admin_token)
        project_id, task_id, attempt_id = await _project_and_task(
            app, client, admin_headers, tmp_path
        )
        definition = await client.post(
            "/api/v1/agents/definitions",
            json={
                "name": "deny_agent",
                "prompt_profile_id": "e6_api_prompt",
                "capabilities": ["task_analysis"],
            },
            headers=admin_headers,
        )
        definition_id = definition.json()["definition_id"]
        await client.post(
            f"/api/v1/agents/definitions/{definition_id}/publish", headers=admin_headers
        )
        created = await client.post(
            "/api/v1/agents/instances",
            json={
                "definition_id": definition_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
            },
            headers=admin_headers,
        )
        assert created.status_code == 200, created.text
        instance_id = created.json()["instance_id"]

        editor_token = await _session_for(app, client, "godot_editor")
        editor_headers = _bearer(editor_token)
        denied = await client.get(f"/api/v1/agents/instances/{instance_id}", headers=editor_headers)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PROJECT_ACCESS_DENIED"

        listing_denied = await client.get(
            f"/api/v1/agents/instances?project_id={project_id}", headers=editor_headers
        )
        assert listing_denied.status_code == 403


async def test_management_page_exposes_agent_monitoring(tmp_path: Path) -> None:
    async with _running(tmp_path) as (_, client):
        page = await client.get("/api/v1/manage")
        assert page.status_code == 200
        for marker in ("Agent 概览", "Agent 实例", "Agent 预算", "恢复监控"):
            assert marker in page.text
