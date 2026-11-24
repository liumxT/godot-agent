"""E9-T19 Agent 验证集成与预算控制集成测试。"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AgentBudgetExceeded, ValidationFailed
from modules.project_registry.service import ProjectRegistryService
from modules.verification.agent_policy import VerificationBudgetLimits
from modules.verification.service import VerificationService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9agent.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _project(app, tmp_path: Path) -> str:
    registry = _service(app, "project_registry_service", ProjectRegistryService)
    root = tmp_path / "platformer"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name="Platformer Demo")
    return project.project_id


async def _ready_campaign(verification: VerificationService, project_id: str):
    campaign = await verification.agent_request_verification(
        project_id=project_id, campaign_type="TASK", actor_id="agent_gameplay"
    )
    await verification.transition_campaign(campaign.campaign_id, "PLANNING")
    return await verification.transition_campaign(campaign.campaign_id, "READY")


async def _test_case(verification: VerificationService, project_id: str, name: str) -> str:
    view = await verification.register_test_case(
        project_id=project_id,
        name=name,
        test_type="RUNTIME",
        execution_method="MANUAL",
    )
    return view.test_case_id


@pytest.mark.asyncio
async def test_agent_policy_matrix_and_request_verification(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id = await _project(app, tmp_path)

        policy = await verification.agent_verification_policy()
        assert "REQUEST_VERIFICATION" in policy["allowed_actions"]
        assert "REQUEST_RUN" in policy["allowed_actions"]
        assert "SELF_WAIVE_GATE" in policy["forbidden_actions"]
        assert set(policy["budgets"]) == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

        campaign = await verification.agent_request_verification(
            project_id=project_id, campaign_type="TASK", actor_id="agent_gameplay"
        )
        assert campaign.created_by == "agent_gameplay"
        assert campaign.status == "DRAFT"

        with pytest.raises(ValidationFailed):
            await verification.agent_request_verification(
                project_id=project_id, campaign_type="TASK", actor_id="  "
            )


@pytest.mark.asyncio
async def test_agent_run_budget_blocks_repeated_execution(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id = await _project(app, tmp_path)
        campaign = await _ready_campaign(verification, project_id)

        limits = VerificationBudgetLimits(test_runs=1, retries=0, screenshots=4)
        case_id = await _test_case(verification, project_id, "VT-跳跃")
        other_case_id = await _test_case(verification, project_id, "VT-攻击")
        run = await verification.agent_request_run(
            campaign.campaign_id, limits=limits, test_case_id=case_id
        )
        assert run.execution_status == "RUNNING"
        await verification.complete_run(run.run_id, execution_status="COMPLETED")

        budget = await verification.verification_budget(campaign.campaign_id, limits=limits)
        assert budget["usage"]["test_runs"] == 1
        assert budget["usage"]["retries"] == 0
        assert "test_runs" in budget["exhausted"]

        with pytest.raises(AgentBudgetExceeded):
            await verification.agent_request_run(
                campaign.campaign_id, limits=limits, test_case_id=other_case_id
            )

        with pytest.raises(ValidationFailed):
            await verification.ensure_verification_budget(
                campaign.campaign_id, dimension="NOT_A_DIMENSION"
            )


@pytest.mark.asyncio
async def test_retry_budget_and_evidence_usage(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id = await _project(app, tmp_path)
        campaign = await _ready_campaign(verification, project_id)

        # 首次执行不消耗 retry 预算
        limits = VerificationBudgetLimits(test_runs=5, retries=1, screenshots=2)
        case_id = await _test_case(verification, project_id, "VT-移动")
        first = await verification.agent_request_run(
            campaign.campaign_id, limits=limits, test_case_id=case_id
        )
        await verification.complete_run(first.run_id, execution_status="COMPLETED")

        screenshot = tmp_path / "jump.png"
        screenshot.write_bytes(b"png-bytes")
        evidence = await verification.record_evidence(
            project_id=project_id,
            evidence_type="SCREENSHOT",
            source_type="GODOT_RUNTIME",
            source_reference=f"file://{screenshot.as_posix()}",
            content_hash=hashlib.sha256(screenshot.read_bytes()).hexdigest(),
            run_id=first.run_id,
            metadata={"project_revision": "rev-1", "runtime_instance_id": "rt-1"},
        )
        assert evidence.evidence_type == "SCREENSHOT"

        # 第二次尝试同一测试用例属于重试，消耗 retry 预算
        retry = await verification.agent_request_run(
            campaign.campaign_id, limits=limits, test_case_id=case_id
        )
        await verification.complete_run(retry.run_id, execution_status="COMPLETED")

        budget = await verification.verification_budget(campaign.campaign_id, limits=limits)
        assert budget["usage"]["retries"] == 1
        assert budget["usage"]["screenshots"] == 1
        assert "retries" in budget["exhausted"]

        with pytest.raises(AgentBudgetExceeded):
            await verification.agent_request_run(
                campaign.campaign_id, limits=limits, test_case_id=case_id
            )


@pytest.mark.asyncio
async def test_unknown_risk_level_is_rejected(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id = await _project(app, tmp_path)
        campaign = await verification.agent_request_verification(
            project_id=project_id, campaign_type="TASK", actor_id="agent_gameplay"
        )
        with pytest.raises(ValidationFailed):
            await verification.verification_budget(campaign.campaign_id, risk_level="UNKNOWN")
