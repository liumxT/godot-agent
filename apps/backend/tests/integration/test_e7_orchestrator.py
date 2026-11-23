"""E7-T03/T04/T06 Orchestrator、Team Manager 与 Assignment 集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    AgentAssignmentInvalid,
    AgentOrchestrationInvalid,
    AgentOrchestrationUnauthorized,
    AgentTeamInvalid,
)
from modules.agent_runtime.service import DefinitionRegistryService
from modules.multi_agent.decomposition import (
    COMPLEXITY_COMPLEX,
    COMPLEXITY_SIMPLE,
    DecompositionPlan,
    SubtaskSpec,
)
from modules.multi_agent.orchestrator import OrchestratorService
from modules.multi_agent.service import AgentTeamService, AssignmentService
from modules.project_registry.service import ProjectRegistryService
from modules.prompt.service import PromptService
from modules.task.service import AttemptService, TaskService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e7orchestrator.db').as_posix()}",
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
    project = await projects.register(project_root=str(root), name="E7 Orchestrator")
    await prompts.create(
        name="e7_orchestration_prompt",
        category="AGENT",
        content="You are a specialized game development agent.",
    )

    async def make(name: str, capabilities: tuple[str, ...], tools: tuple[str, ...], ceiling: str):
        definition = await definitions.create(
            name=name,
            model_policy_id="default_agent_policy",
            prompt_profile_id="e7_orchestration_prompt",
            prompt_version=1,
            capabilities=capabilities,
            tool_whitelist=tools,
            permission_ceiling=ceiling,
        )
        return await definitions.publish(definition.definition_id)

    designer = await make(
        "e7_designer", ("gameplay_design", "level_design"), ("file.read",), "R2"
    )
    programmer = await make(
        "e7_programmer",
        ("gameplay_programming", "game_system_programming"),
        ("file.read", "file.write"),
        "R2",
    )
    qa = await make("e7_qa", ("qa_testing", "test_automation"), ("file.read",), "R1")

    task = await tasks.create(
        project_id=project.project_id,
        title="2D 平台跳跃游戏",
        description="移动、跳跃、HUD 与敌人",
    )
    attempt = await attempts.create(task.task_id)
    return {
        "project": project,
        "definitions": {"designer": designer, "programmer": programmer, "qa": qa},
        "task": task,
        "attempt": attempt,
    }


def _platformer_plan() -> DecompositionPlan:
    return DecompositionPlan(
        task_objective="创建 2D 平台跳跃游戏",
        acceptance_criteria=("玩家可以移动并跳跃", "HUD 显示生命值", "敌人可以伤害玩家"),
        subtasks=(
            SubtaskSpec(
                key="design",
                objective="设计移动、跳跃与关卡规则",
                capabilities=("gameplay_design",),
                acceptance_criteria=("设计通过评审",),
                covers=("玩家可以移动并跳跃",),
                required_tools=("file.read",),
                risk_level="R1",
            ),
            SubtaskSpec(
                key="code",
                objective="实现玩家移动与跳跃",
                capabilities=("gameplay_programming",),
                acceptance_criteria=("移动与跳跃测试通过",),
                covers=("玩家可以移动并跳跃",),
                required_tools=("file.write",),
                dependencies=("design",),
            ),
            SubtaskSpec(
                key="hud",
                objective="实现 HUD 生命值显示",
                capabilities=("gameplay_programming",),
                acceptance_criteria=("HUD 显示生命值",),
                covers=("HUD 显示生命值",),
                required_tools=("file.write",),
                dependencies=("design",),
            ),
            SubtaskSpec(
                key="qa",
                objective="验证移动、HUD 与敌人伤害",
                capabilities=("qa_testing",),
                acceptance_criteria=("QA 报告通过",),
                covers=("敌人可以伤害玩家",),
                required_tools=("file.read",),
                dependencies=("code", "hud"),
                risk_level="R1",
            ),
        ),
    )


def _single_plan() -> DecompositionPlan:
    return DecompositionPlan(
        task_objective="只实现玩家移动",
        acceptance_criteria=("玩家可以移动",),
        subtasks=(
            SubtaskSpec(
                key="move",
                objective="实现玩家移动",
                capabilities=("gameplay_programming",),
                acceptance_criteria=("玩家可以移动",),
                required_tools=("file.write",),
            ),
        ),
    )


async def _orchestrate(app, ctx: dict, plan: DecompositionPlan):
    return await _service(app, "orchestrator_service", OrchestratorService).orchestrate(
        task_id=ctx["task"].task_id,
        attempt_id=ctx["attempt"].attempt_id,
        plan=plan,
    )


async def test_orchestrator_creates_team_assignments_and_dependencies(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())

        assert result.team.status == "READY"
        assert result.complexity.level == COMPLEXITY_COMPLEX
        assert result.single_agent is False
        by_key = {item.key: item.assignment for item in result.assignments}
        assert set(by_key) == {"design", "code", "hud", "qa"}
        assert by_key["design"].status == "READY"
        assert by_key["code"].status == "BLOCKED"
        assert by_key["hud"].status == "BLOCKED"
        assert by_key["qa"].status == "BLOCKED"
        assert by_key["design"].agent_definition_id == ctx["definitions"]["designer"].definition_id
        assert by_key["code"].agent_definition_id == ctx["definitions"]["programmer"].definition_id
        assert by_key["qa"].agent_definition_id == ctx["definitions"]["qa"].definition_id
        assert by_key["code"].dependencies == (by_key["design"].assignment_id,)
        assert set(by_key["qa"].dependencies) == {
            by_key["code"].assignment_id,
            by_key["hud"].assignment_id,
        }
        members = await _service(app, "agent_team_service", AgentTeamService).get_members(
            result.team.team_id
        )
        assert {member.assignment_id for member in members} == {
            item.assignment.assignment_id for item in result.assignments
        }


async def test_single_subtask_uses_one_assignment(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _single_plan())
        assert result.complexity.level == COMPLEXITY_SIMPLE
        assert result.single_agent is True
        assert len(result.assignments) == 1
        assert result.assignments[0].assignment.status == "READY"


async def test_orchestrator_requires_task_system_authorization(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        orchestrator = _service(app, "orchestrator_service", OrchestratorService)
        with pytest.raises(AgentOrchestrationUnauthorized):
            await orchestrator.orchestrate(
                task_id=ctx["task"].task_id,
                attempt_id=ctx["attempt"].attempt_id,
                plan=_single_plan(),
                authorized_by="AGENT_INSTANCE",
            )


async def test_orchestrator_rejects_second_active_team(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        await _orchestrate(app, ctx, _single_plan())
        with pytest.raises(AgentOrchestrationInvalid) as exc_info:
            await _orchestrate(app, ctx, _single_plan())
        assert "TEAM_ALREADY_EXISTS" in exc_info.value.details["reasons"]


async def test_no_candidate_creates_no_team(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        plan = DecompositionPlan(
            task_objective="高权限任务",
            acceptance_criteria=(),
            subtasks=(
                SubtaskSpec(
                    key="danger",
                    objective="需要 R4 权限",
                    capabilities=("scene_development",),
                    acceptance_criteria=("删除场景",),
                    risk_level="R4",
                ),
            ),
        )
        with pytest.raises(AgentOrchestrationInvalid) as exc_info:
            await _orchestrate(app, ctx, plan)
        assert "NO_CANDIDATE" in exc_info.value.details["reasons"]
        teams = await _service(app, "agent_team_service", AgentTeamService).list(
            task_id=ctx["task"].task_id
        )
        assert teams["total"] == 0


async def test_assignment_claim_and_team_close(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _single_plan())
        assignment = result.assignments[0].assignment
        assignments = _service(app, "assignment_service", AssignmentService)
        teams = _service(app, "agent_team_service", AgentTeamService)

        claimed = await assignments.claim(
            assignment.assignment_id, "instance_1", expected_version=assignment.version
        )
        assert claimed.status == "ASSIGNED"
        assert claimed.agent_instance_id == "instance_1"
        with pytest.raises(AgentAssignmentInvalid):
            await assignments.claim(
                assignment.assignment_id, "instance_2", expected_version=claimed.version
            )

        team = await teams.get(result.team.team_id)
        with pytest.raises(AgentTeamInvalid):
            await teams.close(team.team_id, expected_version=team.version)

        await assignments.transition(
            assignment.assignment_id, "CANCELLED", expected_version=claimed.version
        )
        team = await teams.get(team.team_id)
        closed = await teams.close(team.team_id, expected_version=team.version)
        assert closed.status == "COMPLETED"
        assert closed.completed_at is not None


async def test_assignment_replace_preserves_old_record(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _single_plan())
        assignment = result.assignments[0].assignment
        assignments = _service(app, "assignment_service", AssignmentService)
        designer = ctx["definitions"]["designer"]

        replacement = await assignments.replace(
            assignment.assignment_id,
            agent_definition_id=designer.definition_id,
            agent_definition_version="1.0.0",
            expected_version=assignment.version,
        )
        assert replacement.parent_assignment_id == assignment.assignment_id
        assert replacement.status == "READY"
        assert replacement.assigned_objective == assignment.assigned_objective
        old = await assignments.get(assignment.assignment_id)
        assert old.status == "FAILED"
