"""E6-T07–T11 Execution Loop / Plan / Context / Model / Tool Binding 测试。"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from bootstrap.application import create_app
from config.settings import load_settings
from modules.access.service import ProjectAccessService
from modules.agent_runtime.context_binding import AgentContextBindingService
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.execution import AgentExecutionService
from modules.agent_runtime.instance import AgentInstanceService
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.loop import AgentExecutionLoop
from modules.agent_runtime.model_binding import AgentModelBindingService
from modules.agent_runtime.planning import PlanningService
from modules.agent_runtime.service import DefinitionRegistryService
from modules.agent_runtime.tool_binding import AgentToolBindingService
from modules.client.service import ClientService
from modules.model_gateway.registry import CapabilitySetting, ModelRegistryService
from modules.model_gateway.routing import ModelRoutingService
from modules.model_gateway.schemas import ModelResponse
from modules.project_registry.service import ProjectRegistryService
from modules.prompt.service import PromptService
from modules.session.service import SessionService
from modules.task.service import AttemptService, TaskService
from modules.tool.registry import ToolRegistryService

MODEL_CAPABILITIES = ("TEXT_INPUT", "TEXT_OUTPUT", "TOOL_CALLING", "STRUCTURED_OUTPUT")


class _FakeGateway:
    """按脚本返回模型响应的假 Gateway。"""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[Any] = []

    async def generate(self, request: Any) -> ModelResponse:
        self.requests.append(request)
        if not self.script:
            raise AssertionError("FakeGateway 脚本已用尽")
        item = self.script.pop(0)
        status = "SUCCEEDED"
        if isinstance(item, tuple):
            status, item = item
        return ModelResponse(
            request_id=f"mreq_{len(self.requests)}",
            provider_id="mpr_fake",
            model_id="mdl_fake",
            status=status,
            content=item,
            finish_reason="STOP",
        )


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e6loop.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _register_model(app) -> None:
    registry = _service(app, "model_registry_service", ModelRegistryService)
    provider = await registry.register_provider(name="fake-provider", provider_type="OPENAI")
    await registry.register_model(
        provider_id=provider.provider_id,
        model_key="fake-1",
        display_name="Fake Model",
        context_window=16000,
        max_output_tokens=1024,
        capabilities={
            name: CapabilitySetting(
                support_status="SUPPORTED", evidence_source="test-fixture"
            )
            for name in MODEL_CAPABILITIES
        },
    )


async def _session(app) -> tuple[str, str]:
    clients = _service(app, "client_service", ClientService)
    registered = await clients.register(client_type="godot_editor", client_name="Editor")
    issued = await _service(app, "session_service", SessionService).create(
        registered.client_id
    )
    return issued.session.session_id, registered.client_id


async def _prepare(
    app,
    tmp_path: Path,
    *,
    name: str = "generic_agent",
    tools: tuple[str, ...] = ("file.read",),
    risk_ceiling: str = "R2",
    budget: dict[str, int] | None = None,
):
    projects = _service(app, "project_registry_service", ProjectRegistryService)
    prompts = _service(app, "prompt_service", PromptService)
    definitions = _service(
        app, "agent_definition_registry_service", DefinitionRegistryService
    )
    tasks = _service(app, "task_service", TaskService)
    attempts = _service(app, "task_attempt_service", AttemptService)
    instances = _service(app, "agent_instance_service", AgentInstanceService)

    root = tmp_path / f"project_{name}"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    source = root / "src"
    source.mkdir(exist_ok=True)
    (source / "player.gd").write_text("extends Node\n", encoding="utf-8")
    project = await projects.register(project_root=str(root), name=f"E6 {name}")
    await prompts.create(
        name=f"{name}_prompt",
        category="AGENT",
        content="You are a generic game development agent.",
    )
    definition = await definitions.create(
        name=name,
        model_policy_id="default_agent_policy",
        prompt_profile_id=f"{name}_prompt",
        prompt_version=1,
        capabilities=("task_analysis", "planning", "tool_execution", "result_summary"),
        tool_whitelist=tools,
        permission_ceiling=risk_ceiling,
        budget=budget,
    )
    await definitions.publish(definition.definition_id)
    task = await tasks.create(project_id=project.project_id, title="Build a platformer")
    attempt = await attempts.create(task.task_id)
    session_id, client_id = await _session(app)
    await _service(app, "project_access_service", ProjectAccessService).grant(
        project_id=project.project_id,
        session_id=session_id,
        client_id=client_id,
        access_level="editor",
        granted_by="owner_1",
    )
    instance = await instances.create_for_attempt(
        definition_id=definition.definition_id,
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        session_id=session_id,
        client_id=client_id,
    )
    return {
        "project": project,
        "definition": definition,
        "task": task,
        "attempt": attempt,
        "instance": instance,
    }


def _loop(app, gateway) -> AgentExecutionLoop:
    services = app.state.services
    return AgentExecutionLoop(
        instances=services.get("agent_instance_service", AgentInstanceService),
        lifecycle=services.get("agent_lifecycle_service", AgentLifecycleService),
        executions=services.get("agent_execution_service", AgentExecutionService),
        events=services.get("agent_event_service", AgentEventService),
        planning=services.get("agent_planning_service", PlanningService),
        context=services.get(
            "agent_context_binding_service", AgentContextBindingService
        ),
        models=AgentModelBindingService(
            definitions=services.get(
                "agent_definition_registry_service", DefinitionRegistryService
            ),
            routing=services.get("model_routing_service", ModelRoutingService),
            gateway=gateway,
        ),
        tools=services.get(
            "agent_tool_binding_service", AgentToolBindingService
        ),
    )


async def test_loop_plans_executes_tool_and_completes(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path)
        gateway = _FakeGateway(
            [
                json.dumps(
                    {
                        "action": "CREATE_PLAN",
                        "objective": "读取玩家脚本",
                        "steps": [
                            {
                                "type": "TOOL_EXECUTION",
                                "description": "读取 player.gd",
                            }
                        ],
                    }
                ),
                json.dumps(
                    {
                        "action": "EXECUTE_TOOL",
                        "tool": "file.read",
                        "input": {"path": "src/player.gd"},
                    }
                ),
                json.dumps({"action": "COMPLETE_EXECUTION", "summary": "done"}),
            ]
        )
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)

        assert result.status == "COMPLETED", result
        assert result.iterations == 3
        assert len(gateway.requests) == 3
        assert gateway.requests[0].system_instructions.startswith("You are a generic")
        assert gateway.requests[0].tools

        instances = _service(app, "agent_instance_service", AgentInstanceService)
        instance = await instances.get(ctx["instance"].instance_id)
        assert instance.status == "COMPLETED"

        executions = _service(app, "agent_execution_service", AgentExecutionService)
        execution = await executions.latest_for_instance(ctx["instance"].instance_id)
        assert execution is not None
        assert execution.status == "COMPLETED"

        planning = _service(app, "agent_planning_service", PlanningService)
        plans = await planning.list_plans(execution.execution_id)
        assert len(plans) == 1
        assert plans[0].status == "COMPLETED"
        assert plans[0].steps[0].status == "COMPLETED"
        assert plans[0].steps[0].tool_execution_id is not None

        events = _service(app, "agent_event_service", AgentEventService)
        event_types = [
            item.event_type for item in await events.list_after(ctx["instance"].instance_id)
        ]
        for expected in (
            "EXECUTION_STARTED",
            "PLAN_CREATED",
            "STEP_CREATED",
            "STEP_STARTED",
            "TOOL_REQUEST_STARTED",
            "TOOL_REQUEST_COMPLETED",
            "STEP_COMPLETED",
            "EXECUTION_COMPLETED",
        ):
            assert expected in event_types


async def test_loop_fails_on_unstructured_model_output(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path)
        gateway = _FakeGateway(["请帮我修改项目"])
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)

        assert result.status == "FAILED"
        assert result.reason == "AGENT_ACTION_INVALID"
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        assert (await instances.get(ctx["instance"].instance_id)).status == "FAILED"


async def test_loop_waits_for_approval_on_high_risk_tool(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        tools = _service(app, "tool_registry_service", ToolRegistryService)
        await tools.register(
            name="test.write_file",
            category="FILE_SYSTEM",
            description="write file",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
            risk_level="R3",
            required_permissions=("project.write",),
        )
        ctx = await _prepare(
            app,
            tmp_path,
            name="risky_agent",
            tools=("test.write_file",),
            risk_ceiling="R3",
        )
        gateway = _FakeGateway(
            [
                json.dumps(
                    {
                        "action": "EXECUTE_TOOL",
                        "tool": "test.write_file",
                        "input": {"path": "project.godot"},
                        "resource_scope": ["file:res://project.godot"],
                    }
                )
            ]
        )
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)

        assert result.status == "WAITING_APPROVAL"
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        assert (await instances.get(ctx["instance"].instance_id)).status == "WAITING_APPROVAL"
        executions = _service(app, "agent_execution_service", AgentExecutionService)
        execution = await executions.latest_for_instance(ctx["instance"].instance_id)
        assert execution is not None
        assert execution.status == "WAITING_APPROVAL"


async def test_loop_stops_when_iteration_budget_exceeded(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path, name="budget_agent", budget={"max_iterations": 1})
        gateway = _FakeGateway([json.dumps({"action": "ANALYZE", "summary": "thinking"})])
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)

        assert result.status == "FAILED"
        assert result.reason == "BUDGET_EXCEEDED"
        events = _service(app, "agent_event_service", AgentEventService)
        event_types = [
            item.event_type for item in await events.list_after(ctx["instance"].instance_id)
        ]
        assert "BUDGET_EXCEEDED" in event_types
