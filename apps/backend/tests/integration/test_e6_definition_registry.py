"""E6-T01/T02 Agent Definition Registry 集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    AgentCapabilityUnsupported,
    AgentDefinitionInvalid,
    AgentVersionImmutable,
    NotFoundError,
)
from modules.agent_runtime.service import DefinitionRegistryService
from modules.prompt.service import PromptService
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


def _registry(app) -> DefinitionRegistryService:
    return app.state.services.get("agent_definition_registry_service", DefinitionRegistryService)


def _tools(app) -> ToolRegistryService:
    return app.state.services.get("tool_registry_service", ToolRegistryService)


async def _prepare(app) -> None:
    prompts = app.state.services.get("prompt_service", PromptService)
    await prompts.create(
        name="generic_agent_prompt",
        category="AGENT",
        content="You are a generic game development agent.",
    )


async def _create(registry: DefinitionRegistryService, **overrides):
    payload = {
        "name": "generic_agent",
        "model_policy_id": "default_agent_policy",
        "prompt_profile_id": "generic_agent_prompt",
        "prompt_version": 1,
        "capabilities": ("task_analysis", "planning", "tool_execution", "result_summary"),
        "tool_whitelist": ("file.read", "godot.project.get_info"),
        "permission_ceiling": "R2",
    }
    payload.update(overrides)
    return await registry.create(**payload)


async def test_create_publish_and_immutability(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _prepare(app)
        registry = _registry(app)
        tools = _tools(app)

        view = await _create(registry)
        assert view.status == "DRAFT"
        assert view.current_version is None
        assert view.capabilities == (
            "task_analysis",
            "planning",
            "tool_execution",
            "result_summary",
        )
        assert view.budget["max_iterations"] == 30
        assert len(view.tool_whitelist) == 2
        # 白名单解析为稳定的 tool_id
        first = await tools.get_by_name("file.read", version=1)
        assert first.tool_id in view.tool_whitelist

        version = await registry.publish(view.definition_id, published_by="tester")
        assert version.version == "1.0.0"
        assert len(version.content_hash) == 64
        assert version.definition["agent"]["name"] == "generic_agent"
        assert version.definition["tools"]["allowed"] == list(view.tool_whitelist)
        assert version.definition["permissions"]["maximum_risk_level"] == "R2"

        published = await registry.get(view.definition_id)
        assert published.status == "ACTIVE"
        assert published.current_version == "1.0.0"

        # 发布后不可原地修改
        with pytest.raises(AgentVersionImmutable):
            await registry.update(view.definition_id, description="changed")

        # 同一版本不能重复发布
        with pytest.raises(AgentVersionImmutable):
            await registry.publish(view.definition_id, version="1.0.0")

        next_version = await registry.publish(view.definition_id)
        assert next_version.version == "1.0.1"
        versions = await registry.list_versions(view.definition_id)
        assert [item.version for item in versions] == ["1.0.0", "1.0.1"]
        # 旧版本内容保持不变
        assert versions[0].definition["agent"]["version"] == "1.0.0"


async def test_draft_update_changes_payload_and_version(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _prepare(app)
        registry = _registry(app)
        view = await _create(registry)

        updated = await registry.update(
            view.definition_id,
            description="操作项目文件",
            capabilities=("task_analysis", "planning"),
            expected_version=view.version,
        )
        assert updated.description == "操作项目文件"
        assert updated.capabilities == ("task_analysis", "planning")
        assert updated.version == view.version + 1

        published = await registry.publish(view.definition_id)
        assert published.definition["capabilities"] == ["task_analysis", "planning"]

        # 乐观锁冲突
        with pytest.raises(Exception) as exc_info:
            await registry.update(view.definition_id, expected_version=1)
        assert getattr(exc_info.value, "code", "") in {
            "VERSION_CONFLICT",
            "AGENT_VERSION_IMMUTABLE",
        }


async def test_validation_is_fail_closed(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _prepare(app)
        registry = _registry(app)

        with pytest.raises(AgentCapabilityUnsupported):
            await _create(registry, name="cap_agent", capabilities=("telepathy",))

        with pytest.raises(AgentDefinitionInvalid) as unknown_tool:
            await _create(registry, name="tool_agent", tool_whitelist=("file.unknown",))
        assert unknown_tool.value.details["reasons"] == ["UNKNOWN_TOOL"]

        with pytest.raises(AgentDefinitionInvalid) as ceiling:
            await _create(
                registry,
                name="ceiling_agent",
                tool_whitelist=("file.write",),
                permission_ceiling="R0",
            )
        assert ceiling.value.details["reasons"] == ["TOOL_EXCEEDS_CEILING"]

        with pytest.raises(AgentDefinitionInvalid) as policy:
            await _create(registry, name="policy_agent", model_policy_id="missing_policy")
        assert policy.value.details["reasons"] == ["UNKNOWN_MODEL_POLICY"]

        with pytest.raises(AgentDefinitionInvalid) as prompt:
            await _create(registry, name="prompt_agent", prompt_profile_id="missing_prompt")
        assert prompt.value.details["reasons"] == ["UNKNOWN_PROMPT"]

        with pytest.raises(AgentDefinitionInvalid) as context:
            await _create(registry, name="context_agent", context_profile_id="missing_profile")
        assert context.value.details["reasons"] == ["UNKNOWN_CONTEXT_PROFILE"]

        with pytest.raises(AgentDefinitionInvalid) as budget:
            await _create(registry, name="budget_agent", budget={"max_robots": 1})
        assert budget.value.details["reasons"] == ["UNKNOWN_BUDGET_FIELD"]

        # 失败输入不会留下半成品 Definition
        assert (await registry.list())["total"] == 0


async def test_duplicate_name_and_deactivate(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _prepare(app)
        registry = _registry(app)
        view = await _create(registry)

        with pytest.raises(AgentDefinitionInvalid) as duplicate:
            await _create(registry, model_policy_id="default_agent_policy")
        assert duplicate.value.details["reasons"] == ["DUPLICATE_NAME"]

        disabled = await registry.deactivate(view.definition_id)
        assert disabled.status == "DISABLED"
        with pytest.raises(AgentDefinitionInvalid):
            await registry.publish(view.definition_id)

        with pytest.raises(NotFoundError):
            await registry.get("agdef_missing")


async def test_list_filters_by_status(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _prepare(app)
        registry = _registry(app)
        first = await _create(registry)
        await _create(registry, name="second_agent")

        draft_page = await registry.list(status="DRAFT")
        assert draft_page["total"] == 2

        await registry.publish(first.definition_id)
        active_page = await registry.list(status="ACTIVE")
        assert active_page["total"] == 1
        assert active_page["items"][0].definition_id == first.definition_id
