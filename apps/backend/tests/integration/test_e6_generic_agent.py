"""E6-T19 内置通用 Agent 测试：幂等创建并完成一次真实任务。"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from bootstrap.application import create_app
from config.settings import load_settings
from modules.access.service import ProjectAccessService
from modules.agent_runtime.budget import BudgetManager
from modules.agent_runtime.checkpoint import CheckpointService
from modules.agent_runtime.context_binding import AgentContextBindingService
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.execution import AgentExecutionService
from modules.agent_runtime.generic import (
    GENERIC_AGENT_NAME,
    GENERIC_AGENT_TOOLS,
    GenericAgentService,
)
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
from modules.session.service import SessionService
from modules.task.service import AttemptService, TaskService
from modules.tool.registry import ToolRegistryService

MODEL_CAPABILITIES = ("TEXT_INPUT", "TEXT_OUTPUT", "TOOL_CALLING", "STRUCTURED_OUTPUT")


class _FakeGateway:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[Any] = []

    async def generate(self, request: Any) -> ModelResponse:
        self.requests.append(request)
        item = self.script.pop(0)
        return ModelResponse(
            request_id=f"mreq_{len(self.requests)}",
            provider_id="mpr_fake",
            model_id="mdl_fake",
            status="SUCCEEDED",
            content=item,
            finish_reason="STOP",
        )


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e6generic.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _session(app) -> tuple[str, str]:
    clients = _service(app, "client_service", ClientService)
    registered = await clients.register(client_type="godot_editor", client_name="Editor")
    issued = await _service(app, "session_service", SessionService).create(registered.client_id)
    return issued.session.session_id, registered.client_id


async def test_generic_agent_is_idempotent_and_completes_task(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        registry = _service(app, "model_registry_service", ModelRegistryService)
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

        definitions = _service(app, "agent_definition_registry_service", DefinitionRegistryService)
        generic = _service(app, "generic_agent_service", GenericAgentService)
        first = await generic.ensure()
        second = await generic.ensure()
        assert first.definition_id == second.definition_id
        assert second.name == GENERIC_AGENT_NAME
        assert second.status == "ACTIVE"
        assert second.current_version == "1.0.0"
        tools = _service(app, "tool_registry_service", ToolRegistryService)
        resolved = [await tools.get(tool_id) for tool_id in second.tool_whitelist]
        assert {tool.name for tool in resolved} == set(GENERIC_AGENT_TOOLS)
        assert second.budget["on_exceed"] == "PAUSE"

        projects = _service(app, "project_registry_service", ProjectRegistryService)
        root = tmp_path / "generic_project"
        root.mkdir(parents=True, exist_ok=True)
        (root / "project.godot").write_text("[application]\n", encoding="utf-8")
        source = root / "src"
        source.mkdir(exist_ok=True)
        (source / "player.gd").write_text("extends Node\n", encoding="utf-8")
        project = await projects.register(project_root=str(root), name="Generic Project")
        tasks = _service(app, "task_service", TaskService)
        attempts = _service(app, "task_attempt_service", AttemptService)
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        task = await tasks.create(project_id=project.project_id, title="Analyze player")
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
            definition_id=second.definition_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            session_id=session_id,
            client_id=client_id,
        )

        gateway = _FakeGateway(
            [
                json.dumps(
                    {
                        "action": "CREATE_PLAN",
                        "objective": "读取并总结玩家脚本",
                        "steps": [{"type": "TOOL_EXECUTION", "description": "读取 player.gd"}],
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
        services = app.state.services
        loop = AgentExecutionLoop(
            instances=instances,
            lifecycle=services.get("agent_lifecycle_service", AgentLifecycleService),
            executions=services.get("agent_execution_service", AgentExecutionService),
            events=services.get("agent_event_service", AgentEventService),
            planning=services.get("agent_planning_service", PlanningService),
            context=services.get("agent_context_binding_service", AgentContextBindingService),
            models=AgentModelBindingService(
                definitions=definitions,
                routing=services.get("model_routing_service", ModelRoutingService),
                gateway=gateway,
            ),
            tools=services.get("agent_tool_binding_service", AgentToolBindingService),
            budget=services.get("agent_budget_manager", BudgetManager),
            checkpoints=services.get("agent_checkpoint_service", CheckpointService),
        )
        result = await loop.run(instance.instance_id)
        assert result.status == "COMPLETED", result
        assert result.iterations == 3

        latest = await services.get(
            "agent_execution_service", AgentExecutionService
        ).latest_for_instance(instance.instance_id)
        assert latest is not None
        assert latest.status == "COMPLETED"
