"""E7-M7 端到端验收：Platformer 多 Agent 全流程、恢复、幂等与安全检查。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from pathlib import Path

import httpx
import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    AgentAssignmentInvalid,
    AgentHandoffInvalid,
    AgentOrchestrationInvalid,
    AgentResourceConflict,
    VersionConflict,
)
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.agent_runtime.service import DefinitionRegistryService
from modules.multi_agent.conflicts import ConflictService
from modules.multi_agent.context import SharedContextService
from modules.multi_agent.decomposition import DecompositionPlan, SubtaskSpec
from modules.multi_agent.lead import IntegrationService
from modules.multi_agent.models import RESOLUTION_SEQUENTIAL
from modules.multi_agent.observability import TeamObservabilityService
from modules.multi_agent.orchestrator import OrchestratorService
from modules.multi_agent.resources import ResourceCoordinatorService, ResourceRequest
from modules.multi_agent.review import ReviewService
from modules.multi_agent.service import (
    AgentTeamService,
    AssignmentService,
    HandoffService,
)
from modules.project_registry.service import ProjectRegistryService
from modules.prompt.service import PromptService
from modules.task.service import AttemptService, TaskService


def _settings(tmp_path: Path, name: str = "e7e2e"):
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / f'{name}.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _setup_fixture(app, tmp_path: Path, name: str = "project"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await _service(app, "project_registry_service", ProjectRegistryService).register(
        project_root=str(root), name="E7 E2E"
    )
    await _service(app, "prompt_service", PromptService).create(
        name="e7e2e_prompt", category="AGENT", content="You are a game development agent."
    )
    definitions = _service(
        app, "agent_definition_registry_service", DefinitionRegistryService
    )

    async def make(name: str, capabilities, tools, ceiling: str = "R2"):
        definition = await definitions.create(
            name=name,
            model_policy_id="default_agent_policy",
            prompt_profile_id="e7e2e_prompt",
            prompt_version=1,
            capabilities=capabilities,
            tool_whitelist=tools,
            permission_ceiling=ceiling,
        )
        return await definitions.publish(definition.definition_id)

    await make("e2e_designer", ("gameplay_design",), ("file.read",), "R1")
    await make(
        "e2e_tilemap",
        ("tilemap_development",),
        ("godot.tilemap.get_cells", "godot.tilemap.set_cells"),
    )
    programmer = await make(
        "e2e_programmer",
        ("gameplay_programming", "gameplay_design"),
        ("file.read", "file.write"),
    )
    await make("e2e_planner", ("project_planning",), (), "R0")
    task = await _service(app, "task_service", TaskService).create(
        project_id=project.project_id,
        title="2D 平台跳跃游戏",
        description="移动、跳跃、敌人、关卡、生命与 HUD",
    )
    attempt = await _service(app, "task_attempt_service", AttemptService).create(
        task.task_id
    )
    return project, task, attempt, programmer


def _e2e_plan() -> DecompositionPlan:
    return DecompositionPlan(
        task_objective="创建 2D 平台跳跃游戏",
        acceptance_criteria=("设计完成", "关卡完成", "玩法实现", "集成验证通过"),
        subtasks=(
            SubtaskSpec(
                key="design",
                objective="设计玩法与生命系统",
                capabilities=("gameplay_design",),
                acceptance_criteria=("设计完成",),
                required_tools=("file.read",),
                risk_level="R1",
            ),
            SubtaskSpec(
                key="level",
                objective="搭建 TileMap 关卡",
                capabilities=("tilemap_development",),
                acceptance_criteria=("关卡完成",),
                required_tools=("godot.tilemap.set_cells",),
            ),
            SubtaskSpec(
                key="player",
                objective="实现玩家控制",
                capabilities=("gameplay_programming",),
                acceptance_criteria=("玩法实现",),
                required_tools=("file.write",),
                dependencies=("design",),
            ),
            SubtaskSpec(
                key="integration",
                objective="整合并准备验收材料",
                capabilities=("project_planning",),
                acceptance_criteria=("集成验证通过",),
                dependencies=("level", "player"),
                risk_level="R0",
            ),
        ),
    )


async def _claim(app, assignment, instance: str):
    assignments = _service(app, "assignment_service", AssignmentService)
    claimed = await assignments.claim(
        assignment.assignment_id, instance, expected_version=assignment.version
    )
    starting = await assignments.transition(
        claimed.assignment_id, "STARTING", expected_version=claimed.version
    )
    return await assignments.transition(
        starting.assignment_id, "RUNNING", expected_version=starting.version
    )


async def _finish(app, assignment, output: str, instance: str = "instance_e2e"):
    assignments = _service(app, "assignment_service", AssignmentService)
    if assignment.status == "READY":
        assignment = await _claim(app, assignment, instance)
    elif assignment.status == "BLOCKED":
        assignment = await assignments.transition(
            assignment.assignment_id, "READY", expected_version=assignment.version
        )
        assignment = await _claim(app, assignment, instance)
    elif assignment.status == "COMPLETED":
        return assignment
    return await assignments.complete(
        assignment.assignment_id, output_reference=output, expected_version=assignment.version
    )


async def test_platformer_multi_agent_end_to_end(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    async with app.state.lifecycle.lifespan(app):
        project, task, attempt, programmer = await _setup_fixture(app, tmp_path)
        assert project.project_id
        orchestrator = _service(app, "orchestrator_service", OrchestratorService)
        result = await orchestrator.orchestrate(
            task_id=task.task_id, attempt_id=attempt.attempt_id, plan=_e2e_plan()
        )
        by_key = {item.key: item.assignment for item in result.assignments}
        assert result.team.status == "READY"
        assert by_key["design"].status == "READY"
        assert by_key["level"].status == "READY"
        assert by_key["player"].status == "BLOCKED"
        assert by_key["integration"].status == "BLOCKED"

        # 6. 并行执行独立子任务
        design, level = await asyncio.gather(
            _claim(app, by_key["design"], "instance_design"),
            _claim(app, by_key["level"], "instance_level"),
        )
        assert design.status == level.status == "RUNNING"

        # 9. 资源冲突：同一资源写入被拒绝，冲突可解决
        resources = _service(
            app, "resource_coordinator_service", ResourceCoordinatorService
        )
        await resources.acquire(
            team_id=result.team.team_id,
            assignment_id=design.assignment_id,
            resources=(ResourceRequest("SCENE", "godot://scene/main", "WRITE"),),
        )
        with pytest.raises(AgentResourceConflict):
            await resources.acquire(
                team_id=result.team.team_id,
                assignment_id=level.assignment_id,
                resources=(ResourceRequest("SCENE", "godot://scene/main", "WRITE"),),
            )
        conflicts = _service(app, "conflict_service", ConflictService)
        detected = await conflicts.report(
            team_id=result.team.team_id,
            conflict_type="RESOURCE_LOCK_CONFLICT",
            conflicting_assignment_ids=(design.assignment_id, level.assignment_id),
            resource_id="godot://scene/main",
            pause=False,
        )
        resolved = await conflicts.resolve(
            detected.conflict.conflict_id,
            strategy=RESOLUTION_SEQUENTIAL,
            resolution_reference="plan://serialized-main-scene",
            resolved_by="lead_agent",
        )
        assert resolved.resolution_status == "RESOLVED"
        await resources.release_for_assignment(design.assignment_id)

        # 5. Context 共享与版本化
        contexts = _service(app, "shared_context_service", SharedContextService)
        published = await contexts.publish(
            result.team.team_id,
            content_reference="context://interface/player-health",
            content={"fact": "HUD 读取 player.health", "kind": "FACT"},
            created_by_assignment_id=design.assignment_id,
        )
        assert (await contexts.get(published.context_id)).context_version == 1

        # 7. Handoff：由 Orchestrator 执行并创建目标 Assignment
        handoffs = _service(app, "handoff_service", HandoffService)
        requested = await handoffs.request(
            source_assignment_id=design.assignment_id,
            target_agent_definition_id=programmer.definition_id,
            handoff_type="TASK_HANDOFF",
            handoff_payload_reference="handoff://e2e/player-control",
            context_snapshot_id=published.context_id,
        )
        execution = await orchestrator.execute_handoff(requested.handoff_id)
        assert execution.handoff.status == "COMPLETED"
        assert execution.assignment.status == "READY"

        design = await _finish(app, design, "context://result/design")
        level = await _finish(app, level, "context://result/level")
        handoff_target = await _finish(
            app, execution.assignment, "context://result/handoff-player"
        )
        player = await _finish(app, by_key["player"], "context://result/player")
        integration_assignment = await _finish(
            app, by_key["integration"], "context://result/integration"
        )

        # 16. 独立评审（不替代 Verification）
        reviews = _service(app, "review_service", ReviewService)
        review = await reviews.request(
            team_id=result.team.team_id,
            target_assignment_id=design.assignment_id,
            review_type="DESIGN_REVIEW",
            reviewer_assignment_id=integration_assignment.assignment_id,
        )
        await reviews.start(review.review_id)
        completed_review = await reviews.complete(
            review.review_id,
            findings=("设计与生命值接口一致",),
            severity="LOW",
            acceptance_status="ACCEPTED",
            evidence_reference="evidence://review/design",
        )
        assert completed_review.requires_verification is True

        # 8/10. Lead 集成 + 项目集成
        integrations = _service(app, "integration_service", IntegrationService)
        preparation = await integrations.prepare(
            team_id=result.team.team_id, plan="按依赖顺序合并设计、关卡、玩法与 HUD"
        )
        assert len(preparation.sources) == 5
        applying = await integrations.start_apply(
            preparation.integration.integration_id,
            expected_version=preparation.integration.version,
        )
        verifying = await integrations.start_verification(
            applying.integration_id, expected_version=applying.version
        )
        integrated = await integrations.submit_verification(
            verifying.integration_id,
            verification_reference="verification://e2e/run-1",
            expected_version=verifying.version,
        )

        # 11/12. 提交 Verification，Task System 接收
        tasks = _service(app, "task_service", TaskService)
        queued = await tasks.transition(task.task_id, "QUEUED", actor_id="task_system")
        running = await tasks.transition(
            task.task_id, "RUNNING", actor_id="task_system", expected_version=queued.version
        )
        assert running.status == "RUNNING"
        reviewed = await tasks.request_review(task.task_id, actor_id="verification_system")
        assert integrated.status == "COMPLETED"
        assert reviewed.status == "REVIEW_PENDING"
        assert level.assignment_id != handoff_target.assignment_id
        assert player.status == "COMPLETED"

        observability = _service(
            app, "team_observability_service", TeamObservabilityService
        )
        dashboard = await observability.team_dashboard(result.team.team_id)
        assert dashboard["assignment_counts"]["COMPLETED"] == 5


async def test_team_recovers_after_restart_and_rejects_duplicates(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "restart")
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        _, task, attempt, _ = await _setup_fixture(app, tmp_path, "restart_project")
        orchestrator = _service(app, "orchestrator_service", OrchestratorService)
        result = await orchestrator.orchestrate(
            task_id=task.task_id, attempt_id=attempt.attempt_id, plan=_e2e_plan()
        )
        team_id = result.team.team_id
        with pytest.raises(AgentOrchestrationInvalid) as exc_info:
            await orchestrator.orchestrate(
                task_id=task.task_id, attempt_id=attempt.attempt_id, plan=_e2e_plan()
            )
        assert exc_info.value.details["reasons"] == ["TEAM_ALREADY_EXISTS"]

        design = next(
            item.assignment for item in result.assignments if item.key == "design"
        )
        assignments = _service(app, "assignment_service", AssignmentService)
        claimed = await assignments.claim(
            design.assignment_id, "instance_a", expected_version=design.version
        )
        started = await assignments.transition(
            claimed.assignment_id, "STARTING", expected_version=claimed.version
        )
        running = await assignments.transition(
            started.assignment_id, "RUNNING", expected_version=started.version
        )
        assert running.status == "RUNNING"
        with pytest.raises((AgentAssignmentInvalid, VersionConflict)):
            await assignments.claim(
                design.assignment_id, "instance_b", expected_version=design.version
            )

    restarted = create_app(settings)
    async with restarted.state.lifecycle.lifespan(restarted):
        teams = _service(restarted, "agent_team_service", AgentTeamService)
        team = await teams.get(team_id)
        assert team.status == "READY"
        assignments = _service(restarted, "assignment_service", AssignmentService)
        recovered = await assignments.get(claimed.assignment_id)
        assert recovered.status == "RUNNING"
        assert recovered.agent_instance_id == "instance_a"
        assert len(await assignments.list_for_team(team_id)) == 4


async def test_handoff_is_not_executed_after_source_cancelled(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, "handoff_cancel"))
    async with app.state.lifecycle.lifespan(app):
        _, task, attempt, programmer = await _setup_fixture(app, tmp_path, "handoff_project")
        orchestrator = _service(app, "orchestrator_service", OrchestratorService)
        result = await orchestrator.orchestrate(
            task_id=task.task_id, attempt_id=attempt.attempt_id, plan=_e2e_plan()
        )
        design = next(item.assignment for item in result.assignments if item.key == "design")
        handoffs = _service(app, "handoff_service", HandoffService)
        requested = await handoffs.request(
            source_assignment_id=design.assignment_id,
            target_agent_definition_id=programmer.definition_id,
            handoff_type="TASK_HANDOFF",
            handoff_payload_reference="handoff://e2e/interrupted",
        )
        assignments = _service(app, "assignment_service", AssignmentService)
        await assignments.transition(
            design.assignment_id, "CANCELLED", expected_version=design.version
        )
        with pytest.raises(AgentHandoffInvalid) as exc_info:
            await orchestrator.execute_handoff(requested.handoff_id)
        assert exc_info.value.details["reasons"] == ["SOURCE_TERMINAL"]
        failed = await handoffs.get(requested.handoff_id)
        assert failed.status == "FAILED"
        assert len(await assignments.list_for_team(result.team.team_id)) == 4


async def test_user_without_project_access_is_forbidden(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "security")
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token

            async def session(client_type: str) -> str:
                registered = await client.post(
                    "/api/v1/clients",
                    json={"client_type": client_type, "client_name": f"E7 {client_type}"},
                    headers={"X-Bootstrap-Token": bootstrap},
                )
                body = registered.json()
                challenge = (
                    await client.post(
                        "/api/v1/auth/challenge", json={"client_id": body["client_id"]}
                    )
                ).json()
                verified = await client.post(
                    "/api/v1/auth/verify",
                    json={
                        "challenge_id": challenge["challenge_id"],
                        "client_id": body["client_id"],
                        "proof": _proof(
                            body["client_secret"],
                            challenge["challenge_id"],
                            challenge["challenge"],
                        ),
                    },
                )
                issued = await client.post(
                    "/api/v1/sessions",
                    headers=_bearer(verified.json()["access_token"]),
                )
                return issued.json()["session_token"]

            admin = await session("admin")
            identity = await session("godot_editor")
            root = tmp_path / "sec_project"
            root.mkdir(exist_ok=True)
            (root / "project.godot").write_text("[application]\n", encoding="utf-8")
            created = await client.post(
                "/api/v1/projects",
                json={"project_root": str(root), "name": "security"},
                headers=_bearer(admin),
            )
            project_id = created.json()["project_id"]
            forbidden = await client.get(
                f"/api/v1/agent-teams?project_id={project_id}", headers=_bearer(identity)
            )
            assert forbidden.status_code == 403
