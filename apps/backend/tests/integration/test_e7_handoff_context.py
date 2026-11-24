"""E7-T07 / T08 / T09 / T12 集成测试：交接、共享 Context、消息与 Lead。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    AgentConflictInvalid,
    AgentContextInvalid,
    AgentContextStale,
    AgentHandoffInvalid,
    AgentMessageInvalid,
    AgentOrchestrationUnauthorized,
    AgentResourceConflict,
    AgentResourceLockInvalid,
)
from modules.agent_runtime.service import DefinitionRegistryService
from modules.multi_agent.communication import MessageService
from modules.multi_agent.conflicts import ConflictService
from modules.multi_agent.context import SharedContextService
from modules.multi_agent.decomposition import DecompositionPlan, SubtaskSpec
from modules.multi_agent.lead import IntegrationService, LeadAgentService
from modules.multi_agent.orchestrator import OrchestratorService
from modules.multi_agent.resources import (
    ParallelExecutionManager,
    ResourceCoordinatorService,
    ResourceRequest,
)
from modules.multi_agent.service import (
    AgentTeamService,
    AssignmentService,
    HandoffPayload,
    HandoffService,
)
from modules.project_registry.service import ProjectRegistryService
from modules.prompt.service import PromptService
from modules.task.service import AttemptService, TaskService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e7context.db').as_posix()}",
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
    project = await projects.register(project_root=str(root), name="E7 Context")
    await prompts.create(
        name="e7_context_prompt",
        category="AGENT",
        content="You are a specialized game development agent.",
    )

    async def make(name: str, capabilities: tuple[str, ...], tools: tuple[str, ...], ceiling: str):
        definition = await definitions.create(
            name=name,
            model_policy_id="default_agent_policy",
            prompt_profile_id="e7_context_prompt",
            prompt_version=1,
            capabilities=capabilities,
            tool_whitelist=tools,
            permission_ceiling=ceiling,
        )
        return await definitions.publish(definition.definition_id)

    designer = await make("e7c_designer", ("gameplay_design", "level_design"), ("file.read",), "R2")
    programmer = await make(
        "e7c_programmer",
        ("gameplay_programming", "game_system_programming"),
        ("file.read", "file.write"),
        "R2",
    )
    backup = await make(
        "e7c_backup_programmer",
        ("gameplay_programming", "game_system_programming"),
        ("file.read", "file.write"),
        "R2",
    )
    qa = await make("e7c_qa", ("qa_testing", "test_automation"), ("file.read",), "R1")

    task = await tasks.create(
        project_id=project.project_id,
        title="2D 平台跳跃游戏",
        description="移动、跳跃、HUD 与敌人",
    )
    attempt = await attempts.create(task.task_id)
    return {
        "project": project,
        "definitions": {
            "designer": designer,
            "programmer": programmer,
            "backup": backup,
            "qa": qa,
        },
        "task": task,
        "attempt": attempt,
    }


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


async def _orchestrate(app, ctx: dict, plan: DecompositionPlan):
    return await _service(app, "orchestrator_service", OrchestratorService).orchestrate(
        task_id=ctx["task"].task_id,
        attempt_id=ctx["attempt"].attempt_id,
        plan=plan,
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


def _handoff_payload(context_id: str | None = None) -> HandoffPayload:
    return HandoffPayload(
        original_objective="实现玩家移动与跳跃",
        current_scope="Player 场景与输入映射",
        completed_work=("移动已完成",),
        remaining_work=("跳跃未完成",),
        next_steps=("完成跳跃并补测试",),
        acceptance_criteria=("玩家可以跳跃",),
        context_snapshot_id=context_id,
    )


async def test_handoff_execution_creates_replacement_assignment(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _single_plan())
        source = result.assignments[0].assignment
        contexts = _service(app, "shared_context_service", SharedContextService)
        handoffs = _service(app, "handoff_service", HandoffService)
        teams = _service(app, "agent_team_service", AgentTeamService)

        context = await contexts.publish(
            result.team.team_id,
            content_reference="context://team/interface/1",
            content={"interface": "jump"},
            created_by_assignment_id=source.assignment_id,
        )
        handoff = await handoffs.request(
            source_assignment_id=source.assignment_id,
            target_agent_definition_id=ctx["definitions"]["backup"].definition_id,
            handoff_type="TASK_HANDOFF",
            payload=_handoff_payload(context.context_id),
        )
        execution = await _service(
            app, "orchestrator_service", OrchestratorService
        ).execute_handoff(handoff.handoff_id)

        assert execution.handoff.status == "COMPLETED"
        assert execution.handoff.target_assignment_id == execution.assignment.assignment_id
        assert execution.assignment.status == "READY"
        assert execution.assignment.parent_assignment_id == source.assignment_id
        assert execution.assignment.input_reference == context.context_id
        members = await teams.get_members(result.team.team_id)
        assert execution.assignment.assignment_id in {m.assignment_id for m in members}


async def test_handoff_rejects_target_without_capability(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _single_plan())
        source = result.assignments[0].assignment
        handoffs = _service(app, "handoff_service", HandoffService)
        handoff = await handoffs.request(
            source_assignment_id=source.assignment_id,
            target_agent_definition_id=ctx["definitions"]["designer"].definition_id,
            handoff_type="ROLE_HANDOFF",
            payload=_handoff_payload(),
        )
        with pytest.raises(AgentHandoffInvalid) as exc_info:
            await _service(app, "orchestrator_service", OrchestratorService).execute_handoff(
                handoff.handoff_id
            )
        assert "CAPABILITY_MISMATCH" in exc_info.value.details["reasons"]
        failed = await handoffs.get(handoff.handoff_id)
        assert failed.status == "FAILED"


async def test_handoff_requires_task_system_authorization(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _single_plan())
        source = result.assignments[0].assignment
        handoff = await _service(app, "handoff_service", HandoffService).request(
            source_assignment_id=source.assignment_id,
            target_agent_definition_id=ctx["definitions"]["backup"].definition_id,
            handoff_type="TASK_HANDOFF",
            payload=_handoff_payload(),
        )
        with pytest.raises(AgentOrchestrationUnauthorized):
            await _service(app, "orchestrator_service", OrchestratorService).execute_handoff(
                handoff.handoff_id, authorized_by="AGENT_INSTANCE"
            )


async def test_shared_context_versions_and_stale_policy(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _single_plan())
        contexts = _service(app, "shared_context_service", SharedContextService)
        team_id = result.team.team_id

        first = await contexts.publish(
            team_id, content_reference="context://team/1", content={"stage": 1}
        )
        same = await contexts.publish(
            team_id, content_reference="context://team/1", content={"stage": 1}
        )
        assert same.context_id == first.context_id

        second = await contexts.publish(
            team_id,
            content_reference="context://team/2",
            content={"stage": 2},
            expected_version=1,
        )
        assert second.context_version == 2
        old = await contexts.get(first.context_id)
        assert old.status == "SUPERSEDED"
        assert old.superseded_by == second.context_id

        fresh = await contexts.check(team_id, 2)
        assert fresh.stale is False
        accepted = await contexts.check(team_id, 1, policy="ACCEPT")
        assert accepted.stale is True
        with pytest.raises(AgentContextStale):
            await contexts.check(team_id, 1, policy="PAUSE")


async def test_shared_context_rejects_private_scope(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _single_plan())
        contexts = _service(app, "shared_context_service", SharedContextService)
        with pytest.raises(AgentContextInvalid) as exc_info:
            await contexts.publish(
                result.team.team_id,
                content_reference="context://private/1",
                scope="PRIVATE",
            )
        assert exc_info.value.details["reasons"] == ["SCOPE_NOT_SHARABLE"]


async def test_messages_are_team_scoped_and_consumed_once(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        messages = _service(app, "message_service", MessageService)

        message = await messages.send(
            team_id=result.team.team_id,
            source_assignment_id=by_key["design"].assignment_id,
            target_assignment_id=by_key["code"].assignment_id,
            message_type="TASK_UPDATE",
            payload_reference="context://message/1",
        )
        assert message.sequence_number == 1
        consumed = await messages.consume(
            message.message_id, consumer_assignment_id=by_key["code"].assignment_id
        )
        assert consumed.consumed_at is not None
        again = await messages.consume(
            message.message_id, consumer_assignment_id=by_key["code"].assignment_id
        )
        assert again.consumed_at == consumed.consumed_at
        with pytest.raises(AgentMessageInvalid):
            await messages.consume(
                message.message_id, consumer_assignment_id=by_key["design"].assignment_id
            )
        with pytest.raises(AgentMessageInvalid):
            await messages.send(
                team_id=result.team.team_id,
                source_assignment_id=by_key["design"].assignment_id,
                target_assignment_id=by_key["code"].assignment_id,
                message_type="UNKNOWN",
                payload_reference="context://message/2",
            )


async def test_lead_status_conflicts_and_integration_plan(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        assignments = _service(app, "assignment_service", AssignmentService)
        lead = _service(app, "lead_agent_service", LeadAgentService)
        teams = _service(app, "agent_team_service", AgentTeamService)
        integrations = _service(app, "integration_service", IntegrationService)
        team_id = result.team.team_id

        design = await _run_to_completion(
            assignments,
            by_key["design"],
            agent_instance_id="instance_design",
            output_reference="context://result/shared",
        )
        code_ready = await assignments.transition(
            by_key["code"].assignment_id, "READY", expected_version=by_key["code"].version
        )
        code = await _run_to_completion(
            assignments,
            code_ready,
            agent_instance_id="instance_code",
            output_reference="context://result/shared",
        )
        assert design.status == "COMPLETED" and code.status == "COMPLETED"

        hud_ready = await assignments.transition(
            by_key["hud"].assignment_id, "READY", expected_version=by_key["hud"].version
        )
        hud_claimed = await assignments.claim(
            hud_ready.assignment_id, "instance_lead", expected_version=hud_ready.version
        )
        team = await lead.designate_lead(team_id, hud_claimed.assignment_id)
        assert team.lead_agent_instance_id == "instance_lead"
        roles = await teams.get_members(team_id)
        assert any(m.role == "LEAD" and m.assignment_id == hud_claimed.assignment_id for m in roles)

        board = await lead.status_board(team_id)
        assert len(board.assignments) == 4
        assert hud_claimed.assignment_id in board.missing_outputs

        conflicts = await lead.detect_interface_conflicts(team_id)
        assert len(conflicts) == 1
        assert set(conflicts[0].assignment_ids) == {design.assignment_id, code.assignment_id}

        integration = await lead.build_integration_plan(
            team_id,
            owner_assignment_id=hud_claimed.assignment_id,
            plan="合并移动与 HUD 输出",
        )
        assert integration.status == "READY"
        assert set(integration.source_assignment_ids) == {
            design.assignment_id,
            code.assignment_id,
        }
        assert len(await integrations.list_for_team(team_id)) == 1

        summary = await lead.final_summary(team_id)
        assert summary.completed_assignments == 2
        assert len(summary.results) == 2
        assert len(summary.conflicts) == 1


async def test_resource_write_locks_are_exclusive_and_fenced(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        coordinator = _service(app, "resource_coordinator_service", ResourceCoordinatorService)
        scene = ResourceRequest(resource_type="SCENE", resource_key="res://player.tscn")

        first = await coordinator.acquire(
            team_id=result.team.team_id,
            assignment_id=by_key["code"].assignment_id,
            resources=[scene],
        )
        assert first.locks[0].mode == "WRITE"
        with pytest.raises(AgentResourceConflict) as exc_info:
            await coordinator.acquire(
                team_id=result.team.team_id,
                assignment_id=by_key["hud"].assignment_id,
                resources=[scene],
            )
        assert exc_info.value.details["reasons"] == ["LOCK_CONFLICT"]

        lock = first.locks[0]
        with pytest.raises(AgentResourceLockInvalid):
            await coordinator.release(lock.lock_id, fencing_token=lock.fencing_token + 1)
        released = await coordinator.release(lock.lock_id, fencing_token=lock.fencing_token)
        assert released.status == "RELEASED"

        second = await coordinator.acquire(
            team_id=result.team.team_id,
            assignment_id=by_key["hud"].assignment_id,
            resources=[scene],
        )
        assert second.locks[0].fencing_token > lock.fencing_token
        with pytest.raises(AgentResourceLockInvalid):
            await coordinator.assert_valid(lock.lock_id, fencing_token=lock.fencing_token)


async def test_read_locks_allow_parallel_but_block_writers(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        coordinator = _service(app, "resource_coordinator_service", ResourceCoordinatorService)
        script = "res://scripts/player.gd"

        reader_one = await coordinator.acquire(
            team_id=result.team.team_id,
            assignment_id=by_key["design"].assignment_id,
            resources=[ResourceRequest("SCRIPT", script, "READ")],
        )
        reader_two = await coordinator.acquire(
            team_id=result.team.team_id,
            assignment_id=by_key["code"].assignment_id,
            resources=[ResourceRequest("SCRIPT", script, "READ")],
        )
        assert len(reader_one.locks) == len(reader_two.locks) == 1

        with pytest.raises(AgentResourceConflict):
            await coordinator.acquire(
                team_id=result.team.team_id,
                assignment_id=by_key["hud"].assignment_id,
                resources=[ResourceRequest("SCRIPT", script, "WRITE")],
            )

        for grant in (reader_one, reader_two):
            lock = grant.locks[0]
            await coordinator.release(lock.lock_id, fencing_token=lock.fencing_token)
        writer = await coordinator.acquire(
            team_id=result.team.team_id,
            assignment_id=by_key["hud"].assignment_id,
            resources=[ResourceRequest("SCRIPT", script, "WRITE")],
        )
        assert writer.locks[0].mode == "WRITE"


async def test_parallel_plan_respects_limit_and_resources(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        assignments = _service(app, "assignment_service", AssignmentService)
        manager = _service(app, "parallel_execution_manager", ParallelExecutionManager)

        for key in ("code", "hud"):
            await assignments.transition(
                by_key[key].assignment_id, "READY", expected_version=by_key[key].version
            )

        bounded = await manager.plan_batches(result.team.team_id, max_parallel=2)
        assert [len(batch.assignments) for batch in bounded.batches] == [2, 1]

        resource_map = {
            by_key["design"].assignment_id: {"scene"},
            by_key["code"].assignment_id: {"scene"},
            by_key["hud"].assignment_id: {"ui"},
        }
        planned = await manager.plan_batches(
            result.team.team_id,
            resources_by_assignment=resource_map,
            max_parallel=4,
        )
        assert [
            {item.assignment_id for item in batch.assignments} for batch in planned.batches
        ] == [
            {by_key["design"].assignment_id},
            {by_key["code"].assignment_id, by_key["hud"].assignment_id},
        ]


async def test_refresh_readiness_unblocks_after_dependencies_complete(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        assignments = _service(app, "assignment_service", AssignmentService)
        manager = _service(app, "parallel_execution_manager", ParallelExecutionManager)

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
            output_reference="context://result/code",
        )
        hud_ready = await assignments.transition(
            by_key["hud"].assignment_id, "READY", expected_version=by_key["hud"].version
        )
        hud = await _run_to_completion(
            assignments,
            hud_ready,
            agent_instance_id="instance_hud",
            output_reference="context://result/hud",
        )
        assert design.status == code.status == hud.status == "COMPLETED"

        promoted = await manager.refresh_readiness(result.team.team_id)
        assert [item.assignment_id for item in promoted] == [by_key["qa"].assignment_id]
        assert promoted[0].status == "READY"


async def test_failure_isolation_blocks_only_dependents(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        assignments = _service(app, "assignment_service", AssignmentService)
        manager = _service(app, "parallel_execution_manager", ParallelExecutionManager)

        impact = await manager.handle_failure(
            by_key["design"].assignment_id,
            expected_version=by_key["design"].version,
            failure_reason="设计无法满足跳跃需求",
        )
        assert set(impact.blocked_assignment_ids) == {
            by_key["code"].assignment_id,
            by_key["hud"].assignment_id,
        }
        assert impact.unaffected_assignments == 1
        assert (await assignments.get(by_key["design"].assignment_id)).status == "FAILED"
        assert (await assignments.get(by_key["code"].assignment_id)).status == "BLOCKED"
        assert (await assignments.get(by_key["qa"].assignment_id)).status == "BLOCKED"


async def test_conflict_report_pauses_and_escalates(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        ctx = await _prepare(app, tmp_path)
        result = await _orchestrate(app, ctx, _platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        assignments = _service(app, "assignment_service", AssignmentService)
        conflicts = _service(app, "conflict_service", ConflictService)
        team_id = result.team.team_id
        participants = [by_key["design"].assignment_id, by_key["code"].assignment_id]

        reported = await conflicts.report(
            team_id=team_id,
            conflict_type="WRITE_WRITE",
            conflicting_assignment_ids=participants,
            severity="HIGH",
            resource_id="SCENE:res://player.tscn",
        )
        assert reported.conflict.resolution_status == "DETECTED"
        assert (await assignments.get(by_key["design"].assignment_id)).status == "BLOCKED"
        assert reported.paused_assignments

        with pytest.raises(AgentConflictInvalid) as exc_info:
            await conflicts.resolve(
                reported.conflict.conflict_id,
                strategy="LAST_WRITE_WINS",
                resolution_reference="resolution://last-write",
                resolved_by="ORCHESTRATOR",
            )
        assert exc_info.value.details["reasons"] == ["UNKNOWN_STRATEGY"]

        resolved = await conflicts.resolve(
            reported.conflict.conflict_id,
            strategy="SEQUENTIAL_EXECUTION",
            resolution_reference="resolution://serialize/1",
            resolved_by="ORCHESTRATOR",
        )
        assert resolved.resolution_status == "RESOLVED"
        assert resolved.resolution_strategy == "SEQUENTIAL_EXECUTION"

        escalated = await conflicts.report(
            team_id=team_id,
            conflict_type="INTERFACE_CONFLICT",
            conflicting_assignment_ids=participants,
            severity="HIGH",
            affects_user_goal=True,
            pause=False,
        )
        assert escalated.conflict.resolution_status == "ESCALATED"
        with pytest.raises(AgentConflictInvalid) as exc_info:
            await conflicts.resolve(
                escalated.conflict.conflict_id,
                strategy="MERGE_PROPOSAL",
                resolution_reference="resolution://merge/1",
                resolved_by="ORCHESTRATOR",
            )
        assert exc_info.value.details["reasons"] == ["USER_DECISION_REQUIRED"]
        user_choice = await conflicts.resolve(
            escalated.conflict.conflict_id,
            strategy="USER_DECISION",
            resolution_reference="resolution://user/1",
            resolved_by="USER",
        )
        assert user_choice.resolution_status == "RESOLVED"
