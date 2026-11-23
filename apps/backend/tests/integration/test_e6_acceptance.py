"""E6-T20 验收：E2E 边界、安全与恢复关键场景。

补充已有 E6 测试未覆盖的验收点：
- Agent 完成后不得直接改变 Task 最终状态，Task 仍只能由 Task System 驱动；
- 模型请求白名单外工具必须被拒绝且不产生工具执行；
- 隐藏推理/思维链不得落库或出现在事件、追踪中；
- 模型请求 UNKNOWN 必须显式进入 UNKNOWN，禁止盲目自动重试。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import InvalidStateTransition
from modules.access.service import ProjectAccessService
from modules.agent_runtime.budget import BudgetManager
from modules.agent_runtime.checkpoint import CheckpointService
from modules.agent_runtime.context_binding import AgentContextBindingService
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.execution import AgentExecutionService
from modules.agent_runtime.instance import AgentInstanceService
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.loop import AgentExecutionLoop
from modules.agent_runtime.model_binding import AgentModelBindingService
from modules.agent_runtime.observability import AgentObservabilityService
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
from modules.tool.execution import ToolExecutionService

MODEL_CAPABILITIES = ("TEXT_INPUT", "TEXT_OUTPUT", "TOOL_CALLING", "STRUCTURED_OUTPUT")


class _FakeGateway:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[Any] = []

    async def generate(self, request: Any) -> ModelResponse:
        self.requests.append(request)
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
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e6accept.db').as_posix()}",
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
            name: CapabilitySetting(support_status="SUPPORTED", evidence_source="test-fixture")
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


async def _prepare(app, tmp_path: Path, *, name: str, tools: tuple[str, ...]):
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
        content="You are an acceptance test agent.",
    )
    definition = await definitions.create(
        name=name,
        model_policy_id="default_agent_policy",
        prompt_profile_id=f"{name}_prompt",
        prompt_version=1,
        capabilities=("task_analysis", "planning", "tool_execution", "result_summary"),
        tool_whitelist=tools,
        permission_ceiling="R2",
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
    return {"project": project, "task": task, "attempt": attempt, "instance": instance}


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
        tools=services.get("agent_tool_binding_service", AgentToolBindingService),
        budget=services.get("agent_budget_manager", BudgetManager),
        checkpoints=services.get("agent_checkpoint_service", CheckpointService),
    )


async def test_agent_completion_does_not_mutate_task_status(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path, name="e2e_agent", tools=("file.read",))
        tasks = _service(app, "task_service", TaskService)
        gateway = _FakeGateway(
            [
                json.dumps(
                    {
                        "action": "CREATE_PLAN",
                        "objective": "读取玩家脚本",
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
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)
        assert result.status == "COMPLETED"

        # Agent Runtime 只完成自己的执行，Task 状态保持由 Task System 决定。
        assert (await tasks.get(ctx["task"].task_id)).status == "READY"
        with pytest.raises(InvalidStateTransition):
            await tasks.accept(ctx["task"].task_id)

        # 工具调用必须留下 Tool System 的执行记录。
        execution = await _service(
            app, "agent_execution_service", AgentExecutionService
        ).latest_for_instance(ctx["instance"].instance_id)
        assert execution is not None
        plans = await _service(app, "agent_planning_service", PlanningService).list_plans(
            execution.execution_id
        )
        tool_id = plans[0].steps[0].tool_execution_id
        assert tool_id is not None
        assert (
            await _service(app, "tool_execution_service", ToolExecutionService).get(tool_id)
        ).status == "SUCCEEDED"

        # 只有经由 Task System 的合法路径才能推进最终状态。
        for target in ("QUEUED", "RUNNING"):
            await tasks.transition(ctx["task"].task_id, target, actor_type="SYSTEM")
        await tasks.request_review(ctx["task"].task_id)
        assert (await tasks.accept(ctx["task"].task_id)).status == "COMPLETED"


async def test_tool_outside_whitelist_is_rejected_without_execution(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path, name="deny_agent", tools=("file.read",))
        gateway = _FakeGateway(
            [
                json.dumps(
                    {
                        "action": "EXECUTE_TOOL",
                        "tool": "file.write",
                        "input": {"path": "src/player.gd", "content": "x"},
                    }
                )
            ]
        )
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)

        assert result.status == "FAILED"
        assert result.reason == "AGENT_PERMISSION_DENIED"
        instance = await _service(
            app, "agent_instance_service", AgentInstanceService
        ).get(ctx["instance"].instance_id)
        assert instance.status == "FAILED"
        events = await _service(app, "agent_event_service", AgentEventService).list_after(
            ctx["instance"].instance_id
        )
        assert "TOOL_REQUEST_STARTED" not in {event.event_type for event in events}


async def test_hidden_reasoning_is_not_persisted(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path, name="reasoning_agent", tools=("file.read",))
        gateway = _FakeGateway(
            [
                json.dumps(
                    {
                        "action": "COMPLETE_EXECUTION",
                        "summary": "done",
                        "reasoning": "SECRET_CHAIN",
                        "chain_of_thought": "SECRET_CHAIN",
                    }
                )
            ]
        )
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)
        assert result.status == "COMPLETED"

        events = await _service(app, "agent_event_service", AgentEventService).list_after(
            ctx["instance"].instance_id
        )
        event_dump = json.dumps(
            [event.payload for event in events], ensure_ascii=False, default=str
        )
        assert "SECRET_CHAIN" not in event_dump

        trace = await _service(
            app, "agent_observability_service", AgentObservabilityService
        ).trace(result.execution_id)
        assert "SECRET_CHAIN" not in json.dumps(trace, ensure_ascii=False, default=str)


async def test_model_unknown_marks_unknown_without_retry(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path, name="unknown_agent", tools=("file.read",))
        gateway = _FakeGateway([("UNKNOWN", "")])
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)

        assert result.status == "UNKNOWN"
        assert result.reason == "MODEL_REQUEST_UNKNOWN"
        assert len(gateway.requests) == 1
        instance = await _service(
            app, "agent_instance_service", AgentInstanceService
        ).get(ctx["instance"].instance_id)
        assert instance.status == "UNKNOWN"
