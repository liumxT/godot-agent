"""E7-T18 团队预算测试：分配、上限、重新分配原因与用量失败关闭。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AgentBudgetExceeded, AgentTeamInvalid
from modules.multi_agent.budget import TeamBudgetService
from modules.multi_agent.models import TEAM_BUDGET_EXHAUSTED
from modules.multi_agent.service import AgentTeamService
from modules.project_registry.service import ProjectRegistryService
from modules.task.service import AttemptService, TaskService

BUDGET = {
    "max_model_calls": 20,
    "max_tool_calls": 40,
    "max_input_tokens": 1000,
    "max_output_tokens": 1000,
    "max_cost": 1.5,
    "max_execution_seconds": 600,
}


async def _service(tmp_path: Path) -> tuple[TeamBudgetService, str, object]:
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e7budget.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    stack = app.state.lifecycle.lifespan(app)
    await stack.__aenter__()
    services = app.state.services
    root = tmp_path / "budget_project"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await services.get(
        "project_registry_service", ProjectRegistryService
    ).register(project_root=str(root), name="budget")
    task = await services.get("task_service", TaskService).create(
        project_id=project.project_id, title="预算测试任务"
    )
    attempt = await services.get("task_attempt_service", AttemptService).create(
        task.task_id
    )
    team = await services.get("agent_team_service", AgentTeamService).create(
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        project_id=project.project_id,
    )
    service = services.get("team_budget_service", TeamBudgetService)
    return service, team.team_id, stack


async def test_allocate_reallocate_and_usage(tmp_path: Path) -> None:
    service, team_id, stack = await _service(tmp_path)
    try:
        created = await service.allocate(team_id=team_id, budget=BUDGET)
        assert created.status == "ACTIVE"
        assert created.version == 1
        assert len(created.allocation_log) == 1
        assert created.remaining["tool_calls"] == 40

        updated = await service.allocate(
            team_id=team_id,
            budget={**BUDGET, "max_tool_calls": 80},
            reason="QA 阶段需要更多工具调用",
            expected_version=1,
        )
        assert updated.version == 2
        assert updated.budget["max_tool_calls"] == 80
        assert updated.allocation_log[-1]["reason"] == "QA 阶段需要更多工具调用"

        with pytest.raises(AgentTeamInvalid) as exc_info:
            await service.allocate(
                team_id=team_id,
                budget={**BUDGET, "max_tool_calls": 120},
                reason=" ",
                expected_version=2,
            )
        assert exc_info.value.details["reasons"] == ["REASON_REQUIRED"]

        used = await service.record_usage(team_id, dimension="tool_calls", amount=30)
        assert used.usage["tool_calls"] == 30
        assert used.remaining["tool_calls"] == 50

        with pytest.raises(AgentBudgetExceeded) as exc_info:
            await service.record_usage(team_id, dimension="tool_calls", amount=60)
        assert exc_info.value.details["limit"] == 80
        exhausted = await service.get(team_id)
        assert exhausted.status == TEAM_BUDGET_EXHAUSTED

        with pytest.raises(AgentTeamInvalid):
            await service.record_usage(team_id, dimension="unknown", amount=1)
    finally:
        await stack.__aexit__(None, None, None)


async def test_budget_must_stay_within_task_and_orchestrator(tmp_path: Path) -> None:
    service, team_id, stack = await _service(tmp_path)
    try:
        with pytest.raises(AgentTeamInvalid) as exc_info:
            await service.allocate(
                team_id=team_id,
                budget={**BUDGET, "max_cost": 5},
                task_budget={**BUDGET, "max_cost": 2},
            )
        assert exc_info.value.details["reasons"] == ["TASK_BUDGET_EXCEEDED"]

        with pytest.raises(AgentTeamInvalid) as exc_info:
            await service.allocate(
                team_id=team_id, budget=BUDGET, authorized_by="AGENT"
            )
        assert exc_info.value.details["reasons"] == ["UNAUTHORIZED_BUDGET_CHANGE"]

        with pytest.raises(AgentTeamInvalid) as exc_info:
            await service.allocate(team_id=team_id, budget={"max_cost": 1})
        assert exc_info.value.details["reasons"] == ["MISSING_BUDGET_KEYS"]

        with pytest.raises(AgentTeamInvalid):
            await service.allocate(
                team_id=team_id,
                budget={**BUDGET, "on_exceed": "SILENT"},
            )
    finally:
        await stack.__aexit__(None, None, None)
