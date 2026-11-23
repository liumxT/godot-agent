"""E6-T12–T15 Budget / Checkpoint / Control / Recovery 测试。"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AgentRecoveryRequired
from modules.access.service import ProjectAccessService
from modules.agent_runtime.budget import BudgetManager
from modules.agent_runtime.checkpoint import CheckpointService
from modules.agent_runtime.context_binding import AgentContextBindingService
from modules.agent_runtime.control import AgentControlService
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.execution import AgentExecutionService
from modules.agent_runtime.instance import AgentInstanceService
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.loop import AgentExecutionLoop
from modules.agent_runtime.model_binding import AgentModelBindingService
from modules.agent_runtime.planning import PlanningService
from modules.agent_runtime.recovery import RecoveryCoordinator
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
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e6control.db').as_posix()}",
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


async def _prepare(
    app,
    tmp_path: Path,
    *,
    name: str = "generic_agent",
    tools: tuple[str, ...] = ("file.read",),
    risk_ceiling: str = "R2",
    budget: dict[str, Any] | None = None,
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
        tools=services.get("agent_tool_binding_service", AgentToolBindingService),
        budget=services.get("agent_budget_manager", BudgetManager),
        checkpoints=services.get("agent_checkpoint_service", CheckpointService),
    )


async def _start_running(app, ctx):
    """初始化 Instance 并创建一条 RUNNING Execution（不经过 Loop）。"""

    instances = _service(app, "agent_instance_service", AgentInstanceService)
    lifecycle = _service(app, "agent_lifecycle_service", AgentLifecycleService)
    executions = _service(app, "agent_execution_service", AgentExecutionService)
    instance = await instances.get(ctx["instance"].instance_id)
    instance = await lifecycle.initialize(instance.instance_id)
    instance = await lifecycle.start(instance.instance_id)
    execution = await executions.start_execution(instance)
    return instance, execution


async def test_budget_usage_and_checkpoints_are_persisted(tmp_path: Path) -> None:
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
                            {"type": "TOOL_EXECUTION", "description": "读取 player.gd"}
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

        executions = _service(app, "agent_execution_service", AgentExecutionService)
        execution = await executions.latest_for_instance(ctx["instance"].instance_id)
        assert execution is not None
        assert execution.budget_usage["iterations"] == 3
        assert execution.budget_usage["model_calls"] == 3
        assert execution.budget_usage["tool_calls"] == 1

        checkpoints = _service(app, "agent_checkpoint_service", CheckpointService)
        latest = await checkpoints.latest(ctx["instance"].instance_id)
        assert latest is not None
        assert latest.state["trigger"] == "COMPLETED"
        events = _service(app, "agent_event_service", AgentEventService)
        assert latest.last_event_sequence == await events.last_sequence(
            ctx["instance"].instance_id
        ) - 1

        event_types = [
            item.event_type for item in await events.list_after(ctx["instance"].instance_id)
        ]
        assert "CHECKPOINT_CREATED" in event_types


async def test_budget_exceeded_pause_policy_pauses_instance(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(
            app,
            tmp_path,
            name="pause_budget_agent",
            budget={"max_iterations": 1, "on_exceed": "PAUSE"},
        )
        gateway = _FakeGateway([json.dumps({"action": "ANALYZE", "summary": "thinking"})])
        result = await _loop(app, gateway).run(ctx["instance"].instance_id)

        assert result.status == "PAUSED"
        assert result.reason == "BUDGET_EXCEEDED"

        instances = _service(app, "agent_instance_service", AgentInstanceService)
        assert (await instances.get(ctx["instance"].instance_id)).status == "PAUSED"
        executions = _service(app, "agent_execution_service", AgentExecutionService)
        execution = await executions.latest_for_instance(ctx["instance"].instance_id)
        assert execution is not None
        assert execution.status == "PAUSED"

        checkpoints = _service(app, "agent_checkpoint_service", CheckpointService)
        latest = await checkpoints.latest(ctx["instance"].instance_id)
        assert latest is not None
        assert latest.state["trigger"] == "BUDGET_EXCEEDED"

        events = _service(app, "agent_event_service", AgentEventService)
        event_types = [
            item.event_type for item in await events.list_after(ctx["instance"].instance_id)
        ]
        assert "BUDGET_EXCEEDED" in event_types
        assert "PAUSED" in event_types


async def test_pause_then_resume_round_trip(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path)
        instance, execution = await _start_running(app, ctx)

        control = _service(app, "agent_control_service", AgentControlService)
        paused = await control.pause(instance.instance_id, reason="USER")
        assert paused.status == "PAUSED"

        executions = _service(app, "agent_execution_service", AgentExecutionService)
        assert (
            await executions.latest_for_instance(instance.instance_id)
        ).status == "PAUSED"
        checkpoints = _service(app, "agent_checkpoint_service", CheckpointService)
        latest = await checkpoints.latest(instance.instance_id)
        assert latest is not None
        assert latest.state["trigger"] == "PAUSE_REQUESTED"
        assert latest.execution_id == execution.execution_id

        check = await control.validate_resume(instance.instance_id)
        assert check.ok, check.reasons

        resumed = await control.resume(instance.instance_id, actor="tester")
        assert resumed.status == "RUNNING"
        assert (
            await executions.latest_for_instance(instance.instance_id)
        ).status == "RUNNING"

        events = _service(app, "agent_event_service", AgentEventService)
        event_types = [
            item.event_type
            for item in await events.list_after(ctx["instance"].instance_id)
        ]
        for expected in ("PAUSE_REQUESTED", "PAUSED", "RESUME_REQUESTED", "RESUMED"):
            assert expected in event_types


async def test_resume_rejected_when_task_is_cancelled(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path)
        instance, _ = await _start_running(app, ctx)

        control = _service(app, "agent_control_service", AgentControlService)
        await control.pause(instance.instance_id, reason="USER")
        tasks = _service(app, "task_service", TaskService)
        await tasks.cancel(ctx["task"].task_id)

        check = await control.validate_resume(instance.instance_id)
        assert not check.ok
        assert "TASK_BINDING_INVALID" in check.reasons

        with pytest.raises(AgentRecoveryRequired) as exc_info:
            await control.resume(instance.instance_id)
        assert "TASK_BINDING_INVALID" in exc_info.value.details["reasons"]

        instances = _service(app, "agent_instance_service", AgentInstanceService)
        assert (await instances.get(instance.instance_id)).status == "PAUSED"


async def test_cancel_abandons_plan_and_stops_instance(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path)
        instance, execution = await _start_running(app, ctx)

        planning = _service(app, "agent_planning_service", PlanningService)
        plan = await planning.create_plan(
            instance_id=instance.instance_id,
            execution_id=execution.execution_id,
            objective="读取玩家脚本",
            steps=[{"type": "TOOL_EXECUTION", "description": "读取 player.gd"}],
        )

        control = _service(app, "agent_control_service", AgentControlService)
        stopped = await control.cancel(instance.instance_id, reason="USER_CANCEL")
        assert stopped.status == "STOPPED"

        plans = await planning.list_plans(execution.execution_id)
        assert plans[0].plan_id == plan.plan_id
        assert plans[0].status == "ABANDONED"
        assert plans[0].steps[0].status == "SKIPPED"

        executions = _service(app, "agent_execution_service", AgentExecutionService)
        latest_execution = await executions.get(execution.execution_id)
        assert latest_execution.status == "STOPPED"

        events = _service(app, "agent_event_service", AgentEventService)
        event_types = [
            item.event_type for item in await events.list_after(instance.instance_id)
        ]
        assert "CANCEL_REQUESTED" in event_types
        assert "STOPPED" in event_types


async def test_approval_pending_action_survives_pause(tmp_path: Path) -> None:
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
            name="approval_agent",
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

        checkpoints = _service(app, "agent_checkpoint_service", CheckpointService)
        waiting = await checkpoints.latest(ctx["instance"].instance_id)
        assert waiting is not None
        assert waiting.state["trigger"] == "WAITING_APPROVAL"
        assert waiting.state["pending_action"]["input"] == {"path": "project.godot"}

        control = _service(app, "agent_control_service", AgentControlService)
        paused = await control.pause(ctx["instance"].instance_id, reason="USER")
        assert paused.status == "PAUSED"
        latest = await checkpoints.latest(ctx["instance"].instance_id)
        assert latest is not None
        assert latest.state["trigger"] == "PAUSE_REQUESTED"
        assert latest.state["pending_action"]["input"] == {"path": "project.godot"}

        check = await control.validate_resume(ctx["instance"].instance_id)
        assert not check.ok
        assert "APPROVAL_REQUIRED" in check.reasons
        with pytest.raises(AgentRecoveryRequired):
            await control.resume(ctx["instance"].instance_id)


async def test_recovery_pauses_instance_with_valid_checkpoint(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path)
        instance, execution = await _start_running(app, ctx)
        checkpoints = _service(app, "agent_checkpoint_service", CheckpointService)
        await checkpoints.create(
            instance_id=instance.instance_id,
            execution_id=execution.execution_id,
            trigger="MANUAL",
        )

        recovery = _service(app, "agent_recovery_coordinator", RecoveryCoordinator)
        result = await recovery.recover(instance.instance_id)
        assert result.decision == "PAUSED"
        assert result.status == "PAUSED"

        instances = _service(app, "agent_instance_service", AgentInstanceService)
        assert (await instances.get(instance.instance_id)).status == "PAUSED"
        executions = _service(app, "agent_execution_service", AgentExecutionService)
        assert (
            await executions.latest_for_instance(instance.instance_id)
        ).status == "PAUSED"
        latest = await checkpoints.latest(instance.instance_id)
        assert latest is not None
        assert latest.state["trigger"] == "RECOVERY"

        events = _service(app, "agent_event_service", AgentEventService)
        event_types = [
            item.event_type for item in await events.list_after(instance.instance_id)
        ]
        assert "RECOVERY_STARTED" in event_types
        assert "RECOVERY_COMPLETED" in event_types


async def test_recovery_marks_unknown_without_checkpoint(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path)
        instance, _ = await _start_running(app, ctx)

        recovery = _service(app, "agent_recovery_coordinator", RecoveryCoordinator)
        result = await recovery.recover(instance.instance_id)
        assert result.decision == "UNKNOWN"
        assert "CHECKPOINT_MISSING" in result.reasons
        assert result.status == "UNKNOWN"

        instances = _service(app, "agent_instance_service", AgentInstanceService)
        assert (await instances.get(instance.instance_id)).status == "UNKNOWN"
        executions = _service(app, "agent_execution_service", AgentExecutionService)
        assert (
            await executions.latest_for_instance(instance.instance_id)
        ).status == "UNKNOWN"


async def test_recovery_skips_ready_instance(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _register_model(app)
        ctx = await _prepare(app, tmp_path)
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        lifecycle = _service(app, "agent_lifecycle_service", AgentLifecycleService)
        await lifecycle.initialize(ctx["instance"].instance_id)

        recovery = _service(app, "agent_recovery_coordinator", RecoveryCoordinator)
        result = await recovery.recover(ctx["instance"].instance_id)
        assert result.decision == "SKIPPED"
        assert result.status == "READY"
        assert (await instances.get(ctx["instance"].instance_id)).status == "READY"

        results = await recovery.recover_all()
        matched = [item for item in results if item.instance_id == ctx["instance"].instance_id]
        assert matched and matched[0].decision == "SKIPPED"
