"""E5 Prompt 版本化与 Context 装配集成测试（T15 / T16）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ContextSourceMissing, PromptVariableInvalid, ValidationFailed
from modules.context.models import LAYER_PROJECT, LAYER_SYSTEM, LAYER_TASK
from modules.context.service import (
    ContextAssemblyRequest,
    ContextAssemblyService,
    ContextLayer,
)
from modules.project_registry.service import ProjectRegistryService
from modules.prompt.service import PromptService
from modules.task.service import TaskService

SCHEMA = {
    "type": "object",
    "properties": {
        "task_title": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["task_title"],
    "additionalProperties": False,
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
    return await projects.register(project_root=str(root), name="E5 Context")


async def test_prompt_versions_are_immutable_and_activation_is_explicit(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        prompts = app.state.services.get("prompt_service", PromptService)

        first = await prompts.create(
            name="planner",
            category="TASK",
            content="Plan: {{ task_title }}",
            variables_schema=SCHEMA,
        )
        assert first.version == 1
        assert first.status == "DRAFT"

        second = await prompts.create_version(
            "planner",
            content="Plan v2: {{ task_title }} / {{ steps }}",
            variables_schema=SCHEMA,
        )
        assert second.version == 2
        assert second.category == "TASK"
        assert [item.version for item in await prompts.list_versions("planner")] == [2, 1]

        activated = await prompts.activate(first.prompt_id)
        assert activated.status == "ACTIVE"
        activated = await prompts.activate(second.prompt_id)
        assert activated.status == "ACTIVE"
        assert (await prompts.get_active("planner")).prompt_id == second.prompt_id
        assert (await prompts.get(first.prompt_id)).status == "ARCHIVED"
        assert (await prompts.get(first.prompt_id)).content == "Plan: {{ task_title }}"


async def test_prompt_render_validates_declared_variables(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        prompts = app.state.services.get("prompt_service", PromptService)
        prompt = await prompts.create(
            name="planner",
            category="AGENT",
            content="Plan: {{ task_title }} / {{ steps }}",
            variables_schema=SCHEMA,
        )

        rendered = await prompts.render(
            prompt.prompt_id, {"task_title": "Boss", "steps": ["a", "b"]}
        )
        assert '["a", "b"]' in rendered.content
        assert rendered.untrusted_variables == ("steps", "task_title")

        trusted = await prompts.render(
            prompt.prompt_id,
            {"task_title": "Boss", "steps": ["a"]},
            trusted_variables=("task_title",),
        )
        assert trusted.untrusted_variables == ("steps",)

        with pytest.raises(PromptVariableInvalid):
            await prompts.render(prompt.prompt_id, {"task_title": 1, "steps": []})
        with pytest.raises(PromptVariableInvalid):
            await prompts.render(prompt.prompt_id, {})
        with pytest.raises(ValidationFailed):
            await prompts.create(
                name="unsafe",
                category="SYSTEM",
                content="Try to override: {{ user_instruction }}",
            )


async def test_prompt_test_results_are_traceable(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        prompts = app.state.services.get("prompt_service", PromptService)
        prompt = await prompts.create(
            name="reviewer", category="REVIEW", content="Review the supplied change."
        )

        record = await prompts.record_test(
            prompt.prompt_id, "PASSED", summary="looks good", metadata={"score": 1}
        )
        assert record.status == "PASSED"
        assert (await prompts.list_tests(prompt.prompt_id))[0].test_id == record.test_id

        with pytest.raises(ValidationFailed):
            await prompts.record_test(prompt.prompt_id, "UNKNOWN")


async def test_context_assembly_records_layers_and_versions(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        tasks = app.state.services.get("task_service", TaskService)
        task = await tasks.create(project_id=project.project_id, title="Build boss")
        contexts = app.state.services.get("context_assembly_service", ContextAssemblyService)

        result = await contexts.assemble(
            ContextAssemblyRequest(
                project_id=project.project_id,
                task_id=task.task_id,
                required_sources=(LAYER_PROJECT, LAYER_TASK),
            )
        )

        assert [layer.layer for layer in result.layers] == [
            LAYER_PROJECT,
            LAYER_TASK,
            "POLICY",
        ]
        assert f"project:{project.project_id}" in result.source_refs
        assert f"task:{task.task_id}" in result.source_refs
        assert result.token_estimate > 0
        assert result.budget_exceeded is False
        assert result.context_version == 1

        loaded = await contexts.get(result.context_id)
        assert loaded.context_version == 1
        assert loaded.project_id == project.project_id
        assert loaded.layers[0].layer == LAYER_PROJECT

        second = await contexts.assemble(ContextAssemblyRequest(project_id=project.project_id))
        assert second.context_version == 2
        assert len(await contexts.list_for_project(project.project_id)) == 2


async def test_context_reports_budget_and_keeps_fixed_layers(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        contexts = app.state.services.get("context_assembly_service", ContextAssemblyService)

        result = await contexts.assemble(
            ContextAssemblyRequest(
                project_id=project.project_id,
                token_budget=1,
                fixed_context_refs=(f"project:{project.project_id}",),
            )
        )

        assert result.budget_exceeded is True
        assert result.token_estimate > 1
        assert "CONTEXT_BUDGET_EXCEEDED" in result.warnings
        assert [layer.layer for layer in result.layers] == [LAYER_PROJECT, "POLICY"]

        with pytest.raises(ContextSourceMissing):
            await contexts.assemble(
                ContextAssemblyRequest(
                    project_id=project.project_id,
                    fixed_context_refs=("file:main.gd",),
                )
            )
        with pytest.raises(ContextSourceMissing):
            await contexts.assemble(
                ContextAssemblyRequest(
                    project_id=project.project_id, required_sources=("WORKFLOW",)
                )
            )


async def test_context_accepts_caller_layers_but_not_system_ones(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        project = await _project(app, tmp_path)
        contexts = app.state.services.get("context_assembly_service", ContextAssemblyService)

        system = ContextLayer(
            layer=LAYER_SYSTEM,
            content={"instructions": "You are a Godot assistant."},
            source_refs=("prompt:system",),
            origin="FACT",
        )
        result = await contexts.assemble(
            ContextAssemblyRequest(
                project_id=project.project_id,
                required_sources=(LAYER_SYSTEM,),
            ),
            layers=(system,),
        )
        assert result.layers[0].layer == LAYER_SYSTEM

        with pytest.raises(ValidationFailed):
            await contexts.assemble(
                ContextAssemblyRequest(project_id=project.project_id),
                layers=(ContextLayer(layer=LAYER_PROJECT, content={"x": 1}),),
            )
        with pytest.raises(ValidationFailed):
            await contexts.assemble(
                ContextAssemblyRequest(project_id=project.project_id),
                layers=(
                    ContextLayer(layer=LAYER_SYSTEM, content={"a": 1}),
                    ContextLayer(layer=LAYER_SYSTEM, content={"b": 2}),
                ),
            )
