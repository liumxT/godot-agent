"""E7-T19/T20/T22 集成测试：可观测性、API 与 Platformer Demo 编排。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from bootstrap.application import create_app
from config.settings import load_settings
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.agent_runtime.service import DefinitionRegistryService
from modules.multi_agent.decomposition import DecompositionPlan, SubtaskSpec
from modules.multi_agent.demo import build_platformer_plan
from modules.multi_agent.observability import TeamObservabilityService
from modules.multi_agent.orchestrator import OrchestratorService
from modules.multi_agent.service import AssignmentService, HandoffService
from modules.prompt.service import PromptService
from modules.task.service import AttemptService, TaskService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e7m6.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _session_for(app, client, client_type: str) -> str:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": client_type, "client_name": f"E7 {client_type}"},
        headers={"X-Bootstrap-Token": bootstrap},
    )
    body = registered.json()
    challenge = (
        await client.post("/api/v1/auth/challenge", json={"client_id": body["client_id"]})
    ).json()
    verified = await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "client_id": body["client_id"],
            "proof": _proof(
                body["client_secret"], challenge["challenge_id"], challenge["challenge"]
            ),
        },
    )
    issued = await client.post("/api/v1/sessions", headers=_bearer(verified.json()["access_token"]))
    return issued.json()["session_token"]


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _project_prompt_task(app, client, headers, tmp_path: Path, name: str):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    created = await client.post(
        "/api/v1/projects",
        json={"project_root": str(root), "name": name},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["project_id"]
    await _service(app, "prompt_service", PromptService).create(
        name="e7m6_prompt", category="AGENT", content="You are an E7 multi-agent fixture."
    )
    task = await _service(app, "task_service", TaskService).create(
        project_id=project_id, title="2D 平台跳跃游戏"
    )
    attempt = await _service(app, "task_attempt_service", AttemptService).create(task.task_id)
    return project_id, task, attempt


async def _make_definition(app, name: str, capabilities, tools, ceiling: str = "R2"):
    definitions = _service(app, "agent_definition_registry_service", DefinitionRegistryService)
    definition = await definitions.create(
        name=name,
        model_policy_id="default_agent_policy",
        prompt_profile_id="e7m6_prompt",
        prompt_version=1,
        capabilities=capabilities,
        tool_whitelist=tools,
        permission_ceiling=ceiling,
    )
    return await definitions.publish(definition.definition_id)


def _two_step_plan() -> DecompositionPlan:
    return DecompositionPlan(
        task_objective="创建 2D 平台跳跃游戏",
        acceptance_criteria=("设计完成", "实现完成"),
        subtasks=(
            SubtaskSpec(
                key="design",
                objective="设计移动与跳跃",
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


async def _orchestrate(app, task, attempt, plan):
    return await _service(app, "orchestrator_service", OrchestratorService).orchestrate(
        task_id=task.task_id, attempt_id=attempt.attempt_id, plan=plan
    )


async def _complete(assignments: AssignmentService, assignment, output: str):
    claimed = await assignments.claim(
        assignment.assignment_id, "instance_m6", expected_version=assignment.version
    )
    starting = await assignments.transition(
        claimed.assignment_id, "STARTING", expected_version=claimed.version
    )
    running = await assignments.transition(
        starting.assignment_id, "RUNNING", expected_version=starting.version
    )
    return await assignments.complete(
        running.assignment_id, output_reference=output, expected_version=running.version
    )


async def test_observability_dashboards(tmp_path: Path) -> None:
    async with _running(tmp_path) as (app, client):
        token = await _session_for(app, client, "admin")
        project_id, task, attempt = await _project_prompt_task(
            app, client, _bearer(token), tmp_path, "obs"
        )
        await _make_definition(app, "m6_designer", ("gameplay_design",), ("file.read",), "R1")
        await _make_definition(app, "m6_programmer", ("gameplay_programming",), ("file.write",))
        result = await _orchestrate(app, task, attempt, _two_step_plan())

        observability = _service(app, "team_observability_service", TeamObservabilityService)
        dashboard = await observability.team_dashboard(result.team.team_id)
        assert dashboard["assignment_counts"] == {"READY": 1, "BLOCKED": 1}
        assert len(dashboard["graph"]["nodes"]) == 2
        assert len(dashboard["graph"]["edges"]) == 1
        assert dashboard["budget"] is None

        design_id = next(
            item.assignment.assignment_id for item in result.assignments if item.key == "design"
        )
        detail = await observability.assignment_dashboard(design_id)
        assert detail["assignment"]["status"] == "READY"
        assert detail["blocked"] == [] and detail["dependencies"] == []

        overview = await observability.overview(project_id)
        assert overview["teams"][0]["assignment_count"] == 2
        assert await observability.team_events(result.team.team_id) == []


async def test_multi_agent_api_and_handoff(tmp_path: Path) -> None:
    async with _running(tmp_path) as (app, client):
        token = await _session_for(app, client, "admin")
        headers = _bearer(token)
        project_id, task, attempt = await _project_prompt_task(
            app, client, headers, tmp_path, "api"
        )
        await _make_definition(app, "m6_designer", ("gameplay_design",), ("file.read",), "R1")
        await _make_definition(app, "m6_programmer", ("gameplay_programming",), ("file.write",))
        helper = await _make_definition(
            app,
            "m6_helper",
            ("gameplay_design", "gameplay_programming"),
            ("file.read", "file.write"),
        )

        created = await client.post(
            "/api/v1/agent-teams",
            json={
                "task_id": task.task_id,
                "attempt_id": attempt.attempt_id,
                "subtasks": [
                    {
                        "key": "design",
                        "objective": "设计移动与跳跃",
                        "capabilities": ["gameplay_design"],
                        "acceptance_criteria": ["设计完成"],
                        "required_tools": ["file.read"],
                    },
                    {
                        "key": "code",
                        "objective": "实现移动与跳跃",
                        "capabilities": ["gameplay_programming"],
                        "acceptance_criteria": ["实现完成"],
                        "required_tools": ["file.write"],
                        "dependencies": ["design"],
                    },
                ],
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        body = created.json()
        team_id = body["team"]["team_id"]
        design = body["assignments"][0]
        assert design["assignment"]["status"] == "READY"

        listed = await client.get(f"/api/v1/agent-teams?project_id={project_id}", headers=headers)
        assert listed.status_code == 200 and len(listed.json()["items"]) == 1
        graph = await client.get(f"/api/v1/agent-teams/{team_id}/graph", headers=headers)
        assert len(graph.json()["edges"]) == 1

        pending = await client.get(
            f"/api/v1/agent-assignments/{design['assignment']['assignment_id']}/result",
            headers=headers,
        )
        assert pending.status_code == 409

        assignments = _service(app, "assignment_service", AssignmentService)
        completed = await _complete(
            assignments,
            await assignments.get(design["assignment"]["assignment_id"]),
            "context://result/design",
        )
        result = await client.get(
            f"/api/v1/agent-assignments/{completed.assignment_id}/result",
            headers=headers,
        )
        assert result.status_code == 200
        assert result.json()["output_reference"] == "context://result/design"

        handoffs = _service(app, "handoff_service", HandoffService)
        code_assignment = body["assignments"][1]["assignment"]
        requested = await handoffs.request(
            source_assignment_id=code_assignment["assignment_id"],
            target_agent_definition_id=helper.definition_id,
            handoff_type="TASK_HANDOFF",
            handoff_payload_reference="handoff://e7m6/accept",
        )
        accepted = await client.post(
            f"/api/v1/agent-handoffs/{requested.handoff_id}/accept",
            json={"expected_version": 1},
            headers=headers,
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["handoff"]["status"] == "COMPLETED"
        assert accepted.json()["assignment"]["status"] == "READY"
        again = await client.post(
            f"/api/v1/agent-handoffs/{requested.handoff_id}/accept",
            json={"expected_version": 1},
            headers=headers,
        )
        assert again.status_code == 200 and "assignment" not in again.json()

        rejected_source = await handoffs.request(
            source_assignment_id=accepted.json()["assignment"]["assignment_id"],
            target_agent_definition_id=helper.definition_id,
            handoff_type="TASK_HANDOFF",
            handoff_payload_reference="handoff://e7m6/reject",
        )
        rejected = await client.post(
            f"/api/v1/agent-handoffs/{rejected_source.handoff_id}/reject",
            json={"reason": "目标 Agent 能力不匹配", "expected_version": 1},
            headers=headers,
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "REJECTED"
        assert rejected.json()["rejection_reason"] == "目标 Agent 能力不匹配"

        unauthenticated = await client.get(f"/api/v1/agent-teams?project_id={project_id}")
        assert unauthenticated.status_code == 401


async def test_platformer_demo_orchestration(tmp_path: Path) -> None:
    async with _running(tmp_path) as (app, client):
        token = await _session_for(app, client, "admin")
        _, task, attempt = await _project_prompt_task(app, client, _bearer(token), tmp_path, "demo")
        await _make_definition(app, "demo_designer", ("gameplay_design",), ("file.read",), "R1")
        await _make_definition(
            app, "demo_gameplay", ("gameplay_programming",), ("file.read", "file.write")
        )
        await _make_definition(
            app,
            "demo_tilemap",
            ("tilemap_development",),
            ("godot.tilemap.get_cells", "godot.tilemap.set_cells"),
        )
        await _make_definition(
            app,
            "demo_ui",
            ("ui_programming",),
            ("godot.scene.create", "godot.node.create"),
        )
        await _make_definition(app, "demo_planner", ("project_planning",), (), "R0")

        result = await _orchestrate(app, task, attempt, build_platformer_plan())
        by_key = {item.key: item.assignment for item in result.assignments}
        assert set(by_key) == {
            "design",
            "player_controller",
            "tilemap_level",
            "hud",
            "integration",
        }
        assert by_key["design"].status == "READY"
        assert by_key["player_controller"].status == "BLOCKED"
        assert by_key["tilemap_level"].status == "BLOCKED"
        assert by_key["hud"].status == "BLOCKED"
        assert by_key["integration"].status == "BLOCKED"
        assert result.complexity.requires_multi_agent is True
