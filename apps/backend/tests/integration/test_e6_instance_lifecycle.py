"""E6-T03/T04/T05/T06 Instance、Lifecycle、Scheduler 与 Task 绑定测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AgentDefinitionInvalid, AgentStateInvalid
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.instance import AgentInstanceService
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.scheduler import AgentScheduler
from modules.agent_runtime.service import DefinitionRegistryService
from modules.project_registry.service import ProjectRegistryService
from modules.prompt.service import PromptService
from modules.task.service import AttemptService, TaskService
from modules.tool.registry import ToolRegistryService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e6.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _prepare(app, tmp_path: Path):
    projects = _service(app, "project_registry_service", ProjectRegistryService)
    prompts = _service(app, "prompt_service", PromptService)
    definitions = _service(app, "agent_definition_registry_service", DefinitionRegistryService)
    tasks = _service(app, "task_service", TaskService)
    attempts = _service(app, "task_attempt_service", AttemptService)

    root = tmp_path / "demo_project"
    root.mkdir()
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await projects.register(project_root=str(root), name="E6 Demo")
    await prompts.create(
        name="generic_agent_prompt",
        category="AGENT",
        content="You are a generic game development agent.",
    )
    definition = await definitions.create(
        name="generic_agent",
        model_policy_id="default_agent_policy",
        prompt_profile_id="generic_agent_prompt",
        prompt_version=1,
        capabilities=("task_analysis", "planning", "tool_execution", "result_summary"),
        tool_whitelist=("file.read",),
        permission_ceiling="R2",
    )
    await definitions.publish(definition.definition_id)
    task = await tasks.create(project_id=project.project_id, title="Build a platformer")
    attempt = await attempts.create(task.task_id)
    return {
        "project": project,
        "definition": definition,
        "task": task,
        "attempt": attempt,
        "definitions": definitions,
        "tasks": tasks,
        "attempts": attempts,
    }


async def test_create_instance_freezes_config_and_is_idempotent(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        events = _service(app, "agent_event_service", AgentEventService)

        instance = await instances.create_for_attempt(
            definition_id=ctx["definition"].definition_id,
            task_id=ctx["task"].task_id,
            attempt_id=ctx["attempt"].attempt_id,
            session_id="ses_test",
            model_id="model-x",
        )
        assert instance.status == "CREATED"
        assert instance.agent_version == "1.0.0"
        assert instance.project_id == ctx["project"].project_id
        assert instance.started_at is None

        snapshot = await instances.get_snapshot(instance.instance_id)
        assert snapshot.agent_version == "1.0.0"
        assert snapshot.model_policy_id == "default_agent_policy"
        assert snapshot.model_id == "model-x"
        assert snapshot.prompt_profile_id == "generic_agent_prompt"
        assert snapshot.prompt_version == 1
        assert snapshot.context_profile_id == "project_context_default"
        assert len(snapshot.tool_whitelist) == 1
        assert snapshot.permission_ceiling == "R2"
        assert snapshot.budget["max_iterations"] == 30
        assert len(snapshot.content_hash) == 64

        again = await instances.create_for_attempt(
            definition_id=ctx["definition"].definition_id,
            task_id=ctx["task"].task_id,
            attempt_id=ctx["attempt"].attempt_id,
            session_id="ses_test",
        )
        assert again.instance_id == instance.instance_id

        recorded = await events.list_after(instance.instance_id)
        assert [item.event_type for item in recorded] == ["INSTANCE_CREATED"]
        assert recorded[0].sequence_number == 1


async def test_create_rejects_invalid_binding(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        definitions = ctx["definitions"]
        tasks = ctx["tasks"]
        attempts = ctx["attempts"]

        draft = await definitions.create(
            name="draft_agent",
            model_policy_id="default_agent_policy",
            prompt_profile_id="generic_agent_prompt",
            prompt_version=1,
            capabilities=("task_analysis",),
            tool_whitelist=(),
            permission_ceiling="R0",
        )
        with pytest.raises(AgentDefinitionInvalid):
            await instances.create_for_attempt(
                definition_id=draft.definition_id,
                task_id=ctx["task"].task_id,
                attempt_id=ctx["attempt"].attempt_id,
            )

        other_task = await tasks.create(
            project_id=ctx["project"].project_id, title="Other task"
        )
        other_attempt = await attempts.create(other_task.task_id)
        with pytest.raises(AgentStateInvalid) as mismatch:
            await instances.create_for_attempt(
                definition_id=ctx["definition"].definition_id,
                task_id=ctx["task"].task_id,
                attempt_id=other_attempt.attempt_id,
            )
        assert mismatch.value.code == "AGENT_STATE_INVALID"

        await attempts.cancel(ctx["attempt"].attempt_id)
        with pytest.raises(AgentStateInvalid):
            await instances.create_for_attempt(
                definition_id=ctx["definition"].definition_id,
                task_id=ctx["task"].task_id,
                attempt_id=ctx["attempt"].attempt_id,
            )

        await tasks.cancel(other_task.task_id)
        with pytest.raises(AgentStateInvalid):
            await instances.create_for_attempt(
                definition_id=ctx["definition"].definition_id,
                task_id=other_task.task_id,
                attempt_id=other_attempt.attempt_id,
            )


async def test_lifecycle_transitions_and_events(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        lifecycle = _service(app, "agent_lifecycle_service", AgentLifecycleService)
        events = _service(app, "agent_event_service", AgentEventService)

        instance = await instances.create_for_attempt(
            definition_id=ctx["definition"].definition_id,
            task_id=ctx["task"].task_id,
            attempt_id=ctx["attempt"].attempt_id,
        )

        initialized = await lifecycle.initialize(instance.instance_id)
        assert initialized.status == "READY"
        assert initialized.version == instance.version + 2

        running = await lifecycle.start(instance.instance_id)
        assert running.status == "RUNNING"
        assert running.started_at is not None

        paused = await lifecycle.pause(instance.instance_id)
        assert paused.status == "PAUSED"
        resumed = await lifecycle.resume(instance.instance_id)
        assert resumed.status == "RUNNING"

        completed = await lifecycle.complete(instance.instance_id, reason="DONE")
        assert completed.status == "COMPLETED"
        assert completed.completed_at is not None
        assert completed.termination_reason == "DONE"

        # 终态不可再次启动
        with pytest.raises(AgentStateInvalid):
            await lifecycle.start(instance.instance_id)

        event_types = [item.event_type for item in await events.list_after(instance.instance_id)]
        assert event_types == [
            "INSTANCE_CREATED",
            "INSTANCE_INITIALIZED",
            "EXECUTION_STARTED",
            "PAUSE_REQUESTED",
            "PAUSED",
            "RESUME_REQUESTED",
            "RESUMED",
            "EXECUTION_COMPLETED",
        ]


async def test_initialize_fails_when_frozen_tool_disabled(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        lifecycle = _service(app, "agent_lifecycle_service", AgentLifecycleService)
        tools = _service(app, "tool_registry_service", ToolRegistryService)

        instance = await instances.create_for_attempt(
            definition_id=ctx["definition"].definition_id,
            task_id=ctx["task"].task_id,
            attempt_id=ctx["attempt"].attempt_id,
        )
        snapshot = await instances.get_snapshot(instance.instance_id)
        tool = await tools.get(snapshot.tool_whitelist[0])
        await tools.set_enabled(tool.tool_id, False)

        with pytest.raises(AgentStateInvalid):
            await lifecycle.initialize(instance.instance_id)

        failed = await instances.get(instance.instance_id)
        assert failed.status == "FAILED"
        assert failed.termination_reason == "INITIALIZATION_FAILED"


async def test_scheduler_claims_ready_instance(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        instances = _service(app, "agent_instance_service", AgentInstanceService)
        lifecycle = _service(app, "agent_lifecycle_service", AgentLifecycleService)
        scheduler = _service(app, "agent_scheduler", AgentScheduler)

        instance = await instances.create_for_attempt(
            definition_id=ctx["definition"].definition_id,
            task_id=ctx["task"].task_id,
            attempt_id=ctx["attempt"].attempt_id,
        )
        await lifecycle.initialize(instance.instance_id)

        claimed = await scheduler.claim_next()
        assert claimed is not None
        assert claimed.instance_id == instance.instance_id
        assert claimed.status == "RUNNING"
        assert await scheduler.claim_next() is None
