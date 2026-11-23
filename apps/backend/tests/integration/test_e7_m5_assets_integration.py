"""E7-T13 / T14 / T15 / T16 集成测试：专用 Agent、工作流、集成与评审。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AgentReviewInvalid, AgentTeamInvalid
from modules.agent_runtime.service import DefinitionRegistryService
from modules.multi_agent.decomposition import DecompositionPlan, SubtaskSpec
from modules.multi_agent.lead import IntegrationService
from modules.multi_agent.orchestrator import OrchestratorService
from modules.multi_agent.review import ReviewService
from modules.multi_agent.service import AssignmentService
from modules.multi_agent.specialized import (
    PRIORITY_P0,
    SpecializedAgentCatalog,
)
from modules.multi_agent.workflows import GameWorkflowService
from modules.project_registry.service import ProjectRegistryService
from modules.prompt.service import PromptService
from modules.task.service import AttemptService, TaskService
from modules.workflow.service import WorkflowInstanceService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e7m5.db').as_posix()}",
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
    project = await projects.register(project_root=str(root), name="E7 M5")
    await prompts.create(
        name="e7m5_prompt",
        category="AGENT",
        content="You are a specialized game development agent.",
    )

    async def make(name: str, capabilities: tuple[str, ...], tools: tuple[str, ...], ceiling: str):
        definition = await definitions.create(
            name=name,
            model_policy_id="default_agent_policy",
            prompt_profile_id="e7m5_prompt",
            prompt_version=1,
            capabilities=capabilities,
            tool_whitelist=tools,
            permission_ceiling=ceiling,
        )
        return await definitions.publish(definition.definition_id)

    designer = await make("e7m5_designer", ("gameplay_design",), ("file.read",), "R1")
    programmer = await make(
        "e7m5_programmer",
        ("gameplay_programming",),
        ("file.read", "file.write"),
        "R2",
    )
    task = await tasks.create(
        project_id=project.project_id,
        title="2D 平台跳跃游戏",
        description="移动、跳跃与 HUD",
    )
    attempt = await attempts.create(task.task_id)
    return {
        "project": project,
        "definitions": {"designer": designer, "programmer": programmer},
        "task": task,
        "attempt": attempt,
    }


def _plan() -> DecompositionPlan:
    return DecompositionPlan(
        task_objective="创建 2D 平台跳跃游戏",
        acceptance_criteria=("设计完成", "实现完成"),
        subtasks=(
            SubtaskSpec(
                key="design",
                objective="设计移动与跳跃规则",
                capabilities=("gameplay_design",),
                acceptance_criteria=("设计完成",),
                required_tools=("file.read",),
                risk_level="R1",
            ),
            SubtaskSpec(
                key="code",
                objective="实现移动与跳跃",
                capabilities=("gameplay_programming",),
                acceptance_criteria=("实现完成",),
                required_tools=("file.write",),
                dependencies=("design",),
            ),
        ),
    )


async def _orchestrate(app, ctx: dict):
    return await _service(app, "orchestrator_service", OrchestratorService).orchestrate(
        task_id=ctx["task"].task_id,
        attempt_id=ctx["attempt"].attempt_id,
        plan=_plan(),
    )


async def _run_to_completion(
    assignments: AssignmentService,
    assignment,
    *,
    agent_instance_id: str,
    output_reference: str,
):
    claimed = await assignments.claim(
        assignment.assignment_id, agent_instance_id, expected_version=assignment.version
    )
    starting = await assignments.transition(
        claimed.assignment_id, "STARTING", expected_version=claimed.version
    )
    running = await assignments.transition(
        starting.assignment_id, "RUNNING", expected_version=starting.version
    )
    return await assignments.complete(
        running.assignment_id,
        output_reference=output_reference,
        expected_version=running.version,
    )


async def _complete_both(app, result, *, code_output: str = "context://result/code"):
    assignments = _service(app, "assignment_service", AssignmentService)
    by_key = {item.key: item.assignment for item in result.assignments}
    design = await _run_to_completion(
        assignments,
        by_key["design"],
        agent_instance_id="instance_design",
        output_reference="context://result/design",
    )
    code_ready = await assignments.transition(
        by_key["code"].assignment_id, "READY", expected_version=by_key["code"].version
    )
    code = await _run_to_completion(
        assignments,
        code_ready,
        agent_instance_id="instance_code",
        output_reference=code_output,
    )
    return design, code


async def test_specialized_catalog_publishes_executable_definitions(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        await _prepare(app, tmp_path)
        catalog = _service(app, "specialized_agent_catalog", SpecializedAgentCatalog)

        first = await catalog.ensure_definition("game_designer")
        assert first.status == "ACTIVE"
        assert first.current_version is not None
        assert first.capabilities == ("game_concept_design",)

        again = await catalog.ensure_definition("game_designer")
        assert again.definition_id == first.definition_id

        published = await catalog.ensure_all(priorities=(PRIORITY_P0,))
        assert len(published) == 15
        assert all(item.status == "ACTIVE" for item in published.values())
        assert "game_designer" in published and "qa_engineer" in published


async def test_game_workflow_definition_and_instance(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        workflows = _service(app, "game_workflow_service", GameWorkflowService)
        instances = _service(app, "workflow_instance_service", WorkflowInstanceService)

        definition = await workflows.ensure_definition("core_gameplay_development")
        assert definition.category == "GAME_DEVELOPMENT"
        assert len(definition.nodes) == 6
        assert len(definition.phases) == 6
        same = await workflows.ensure_definition("core_gameplay_development")
        assert same.definition_id == definition.definition_id

        instance = await workflows.instantiate(
            "core_gameplay_development",
            project_id=ctx["project"].project_id,
            task_id=ctx["task"].task_id,
        )
        assert instance.status == "READY"
        assert instance.definition_id == definition.definition_id
        assert (await instances.get(instance.instance_id)).instance_id == instance.instance_id


async def test_integration_requires_all_results_and_verification(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx)
        integrations = _service(app, "integration_service", IntegrationService)
        team_id = result.team.team_id

        with pytest.raises(AgentTeamInvalid) as exc_info:
            await integrations.prepare(team_id=team_id)
        assert "MISSING_RESULTS" in exc_info.value.details["reasons"]

        design, code = await _complete_both(app, result)
        preparation = await integrations.prepare(
            team_id=team_id, plan="按依赖顺序合并玩法与设计输出"
        )
        assert preparation.integration.status == "READY"
        assert {item.assignment_id for item in preparation.sources} == {
            design.assignment_id,
            code.assignment_id,
        }

        applying = await integrations.start_apply(
            preparation.integration.integration_id,
            expected_version=preparation.integration.version,
        )
        verifying = await integrations.start_verification(
            applying.integration_id, expected_version=applying.version
        )
        completed = await integrations.submit_verification(
            verifying.integration_id,
            verification_reference="verification://run/1",
            expected_version=verifying.version,
        )
        assert completed.status == "COMPLETED"
        assert completed.verification_reference == "verification://run/1"
        assert completed.completed_at is not None


async def test_integration_rejects_duplicate_outputs(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx)
        integrations = _service(app, "integration_service", IntegrationService)
        await _complete_both(app, result, code_output="context://result/design")

        with pytest.raises(AgentTeamInvalid) as exc_info:
            await integrations.prepare(team_id=result.team.team_id)
        assert "INTERFACE_CONFLICT" in exc_info.value.details["reasons"]


async def test_review_requires_independent_reviewer_and_evidence(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx)
        design, code = await _complete_both(app, result)
        reviews = _service(app, "review_service", ReviewService)
        team_id = result.team.team_id

        with pytest.raises(AgentReviewInvalid) as exc_info:
            await reviews.request(
                team_id=team_id,
                target_assignment_id=design.assignment_id,
                review_type="CODE_REVIEW",
                reviewer_assignment_id=design.assignment_id,
            )
        assert exc_info.value.details["reasons"] == ["INDEPENDENT_REVIEWER_REQUIRED"]

        with pytest.raises(AgentReviewInvalid):
            await reviews.request(
                team_id=team_id,
                target_assignment_id=design.assignment_id,
                review_type="UNKNOWN_REVIEW",
            )

        review = await reviews.request(
            team_id=team_id,
            target_assignment_id=design.assignment_id,
            review_type="DESIGN_REVIEW",
            reviewer_assignment_id=code.assignment_id,
        )
        assert review.status == "PENDING"
        assert review.requires_verification is True

        with pytest.raises(AgentReviewInvalid):
            await reviews.complete(
                review.review_id,
                findings=(),
                severity="MEDIUM",
                acceptance_status="ACCEPTED",
                evidence_reference="evidence://review/1",
            )

        started = await reviews.start(review.review_id)
        assert started.status == "IN_PROGRESS"
        with pytest.raises(AgentReviewInvalid) as exc_info:
            await reviews.complete(
                review.review_id,
                findings=(),
                severity="MEDIUM",
                acceptance_status="NEEDS_REVISION",
                evidence_reference="evidence://review/1",
            )
        assert exc_info.value.details["reasons"] == ["FINDINGS_REQUIRED"]

        completed = await reviews.complete(
            review.review_id,
            findings=("规则覆盖移动、跳跃与失败状态",),
            severity="LOW",
            acceptance_status="ACCEPTED",
            evidence_reference="evidence://review/1",
        )
        assert completed.status == "COMPLETED"
        assert completed.acceptance_status == "ACCEPTED"
        assert completed.completed_at is not None
        assert len(await reviews.list_for_target(design.assignment_id)) == 1
        assert len(await reviews.list_for_team(team_id)) == 1
