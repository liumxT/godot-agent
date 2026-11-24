"""E7-T01 Multi-Agent Domain 集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    AgentAssignmentInvalid,
    AgentAssignmentUnauthorized,
    AgentCapabilityUnsupported,
    AgentTeamInvalid,
)
from modules.agent_runtime.service import DefinitionRegistryService
from modules.multi_agent.capabilities import CapabilityRequirement
from modules.multi_agent.models import AUTHORITY_ORCHESTRATOR
from modules.multi_agent.service import (
    AgentTeamService,
    AssignmentService,
    CapabilityRegistryService,
    CollaborationService,
    HandoffService,
)
from modules.project_registry.service import ProjectRegistryService
from modules.prompt.service import PromptService
from modules.task.service import AttemptService, TaskService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e7domain.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _prepare(app, tmp_path: Path) -> dict:
    projects = _service(app, "project_registry_service", ProjectRegistryService)
    prompts = _service(app, "prompt_service", PromptService)
    definitions = _service(app, "agent_definition_registry_service", DefinitionRegistryService)
    tasks = _service(app, "task_service", TaskService)
    attempts = _service(app, "task_attempt_service", AttemptService)

    root = tmp_path / "project"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await projects.register(project_root=str(root), name="E7 Domain")
    await prompts.create(
        name="e7_prompt",
        category="AGENT",
        content="You are a game development agent.",
    )
    definition = await definitions.create(
        name="e7_generic_agent",
        model_policy_id="default_agent_policy",
        prompt_profile_id="e7_prompt",
        prompt_version=1,
        capabilities=("task_analysis", "planning"),
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
    }


async def _team(app, ctx: dict) -> str:
    team = await _service(app, "agent_team_service", AgentTeamService).create(
        task_id=ctx["task"].task_id,
        attempt_id=ctx["attempt"].attempt_id,
        project_id=ctx["project"].project_id,
    )
    return team.team_id


async def _assignment(app, ctx: dict, team_id: str, objective: str) -> str:
    assignment = await _service(app, "assignment_service", AssignmentService).create(
        team_id=team_id,
        agent_definition_id=ctx["definition"].definition_id,
        agent_definition_version="1.0.0",
        task_id=ctx["task"].task_id,
        attempt_id=ctx["attempt"].attempt_id,
        assigned_objective=objective,
        authorized_by=AUTHORITY_ORCHESTRATOR,
        acceptance_criteria=("can run",),
        required_capabilities=("gameplay_design",),
    )
    return assignment.assignment_id


async def test_capability_registry_seeds_builtins_and_matches(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        registry = _service(app, "capability_registry_service", CapabilityRegistryService)
        capability = await registry.get_by_name("gameplay_programming")
        assert capability.category == "PROGRAMMING"
        assert capability.enabled is True
        listed = await registry.list(limit=200)
        assert listed["total"] >= 30
        assert await registry.ensure_builtin_capabilities() == 0

        with pytest.raises(AgentCapabilityUnsupported):
            await registry.match(CapabilityRequirement(capabilities=("not_a_capability",)), [])


async def test_team_assignment_handoff_and_collaboration_persist(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        team_id = await _team(app, ctx)
        first = await _assignment(app, ctx, team_id, "实现玩家移动")
        second = await _assignment(app, ctx, team_id, "实现 HUD")

        assignments = await _service(app, "assignment_service", AssignmentService).list_for_team(
            team_id
        )
        assert {item.assignment_id for item in assignments} == {first, second}
        assert assignments[0].dependencies == ()
        assert assignments[0].assigned_by == AUTHORITY_ORCHESTRATOR

        handoff = await _service(app, "handoff_service", HandoffService).request(
            source_assignment_id=first,
            target_agent_definition_id=ctx["definition"].definition_id,
            handoff_type="ROLE_HANDOFF",
            handoff_payload_reference="artifact://handoff/1",
        )
        assert handoff.status == "REQUESTED"
        assert handoff.target_assignment_id is None

        collaboration = await _service(app, "collaboration_service", CollaborationService).create(
            team_id=team_id,
            objective="联调移动与 HUD",
            participant_assignments=(first, second),
        )
        assert collaboration.participant_assignments == (first, second)
        assert collaboration.status == "ACTIVE"


async def test_assignment_requires_orchestrator_authorization(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        team_id = await _team(app, ctx)
        with pytest.raises(AgentAssignmentUnauthorized):
            await _service(app, "assignment_service", AssignmentService).create(
                team_id=team_id,
                agent_definition_id=ctx["definition"].definition_id,
                agent_definition_version="1.0.0",
                task_id=ctx["task"].task_id,
                attempt_id=ctx["attempt"].attempt_id,
                assigned_objective="越权分配",
                authorized_by="agent_instance_1",
            )


async def test_assignment_scope_must_match_team(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        team_id = await _team(app, ctx)
        other = await _service(app, "task_service", TaskService).create(
            project_id=ctx["project"].project_id, title="Other task"
        )
        other_attempt = await _service(app, "task_attempt_service", AttemptService).create(
            other.task_id
        )
        with pytest.raises(AgentAssignmentInvalid):
            await _service(app, "assignment_service", AssignmentService).create(
                team_id=team_id,
                agent_definition_id=ctx["definition"].definition_id,
                agent_definition_version="1.0.0",
                task_id=other.task_id,
                attempt_id=other_attempt.attempt_id,
                assigned_objective="跨任务分配",
                authorized_by=AUTHORITY_ORCHESTRATOR,
            )


async def test_assignment_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        team_id = await _team(app, ctx)
        service = _service(app, "assignment_service", AssignmentService)
        first = await _assignment(app, ctx, team_id, "第一项")
        await service.create(
            team_id=team_id,
            agent_definition_id=ctx["definition"].definition_id,
            agent_definition_version="1.0.0",
            task_id=ctx["task"].task_id,
            attempt_id=ctx["attempt"].attempt_id,
            assigned_objective="第二项",
            authorized_by=AUTHORITY_ORCHESTRATOR,
            dependencies=(first,),
        )
        third = await _assignment(app, ctx, team_id, "第三项")
        updated = await service.add_dependency(first, third, expected_version=1)
        assert third in updated.dependencies
        with pytest.raises(AgentAssignmentInvalid):
            await service.add_dependency(third, first, expected_version=1)


async def test_duplicate_active_team_is_rejected(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        await _team(app, ctx)
        with pytest.raises(AgentTeamInvalid):
            await _team(app, ctx)
