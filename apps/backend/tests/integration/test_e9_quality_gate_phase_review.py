"""E9-T16/T17/T18 质量门禁、Phase Review 与看板集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ValidationFailed
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.project_registry.service import ProjectRegistryService
from modules.requirement.models import REQUIREMENT_ACTIVE, RequirementModel
from modules.verification.models import GATE_EVIDENCE, GATE_WAIVED
from modules.verification.service import VerificationService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9gate.db').as_posix()}",
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
    root = tmp_path / "qa_project"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name="QA")
    return project.project_id


async def _requirement(app, project_id: str) -> str:
    database = _service(app, "database", DatabaseService)
    requirement_id = "req_gate_jump"
    now = utcnow()
    async with database.session() as session:
        session.add(
            RequirementModel(
                requirement_id=requirement_id,
                project_id=project_id,
                requirement_key="REQ-GATE-JUMP",
                title="玩家可以跳跃",
                description="按下跳跃键完成一次跳跃",
                category="FUNCTIONAL",
                priority="HIGH",
                status=REQUIREMENT_ACTIVE,
                source="USER",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    return requirement_id


@pytest.mark.asyncio
async def test_quality_gate_evaluate_and_waive(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id = await _project(app, tmp_path)
        requirement_id = await _requirement(app, project_id)

        campaign = await verification.create_campaign(project_id=project_id, campaign_type="TASK")
        await verification.create_plan(
            campaign.campaign_id,
            requirement_ids=(requirement_id,),
            verification_layers=("STATIC", "RUNTIME"),
        )
        case = await verification.register_test_case(
            project_id=project_id,
            name="test_player_jump",
            test_type="FUNCTIONAL",
            execution_method="GODOT_TEST",
        )
        await verification.link_test(requirement_id=requirement_id, test_case_id=case.test_case_id)

        evaluation = await verification.evaluate_quality_gate(
            project_id, campaign_id=campaign.campaign_id
        )
        # 没有实际执行结果时绝不能 PASSED；证据缺失为 UNKNOWN。
        assert evaluation.decision["status"] == "UNKNOWN"
        assert len(evaluation.gates) == 10
        by_gate = {item.gate_name: item for item in evaluation.gates}
        assert by_gate["GATE-1_REQUIREMENT_COMPLETENESS"].status == "PASSED"
        assert by_gate["GATE-2_STATIC_VALIDATION"].status == "PENDING"
        assert by_gate["GATE-6_EVIDENCE_COMPLETENESS"].status == "UNKNOWN"
        assert by_gate["GATE-7_DEFECT_STATUS"].status == "PASSED"

        latest = await verification.list_gate_results(project_id, campaign_id=campaign.campaign_id)
        assert len(latest) == 10

        evidence_result = next(item for item in latest if item.gate_name == GATE_EVIDENCE)
        with pytest.raises(ValidationFailed):
            await verification.waive_gate_result(
                evidence_result.gate_result_id,
                authorized_by="user:owner",
                reason="暂无截图",
                risk_statement="可能遗漏视觉问题",
                scope="phase-1",
                expires_at=utcnow() - timedelta(days=1),
            )

        policy = await verification.create_gate_policy(
            project_id=project_id,
            name="仅证据门禁",
            gates=[GATE_EVIDENCE],
            waivers_allowed=True,
        )
        policy_eval = await verification.evaluate_quality_gate(
            project_id, campaign_id=campaign.campaign_id, policy_id=policy.gate_policy_id
        )
        assert policy_eval.decision["status"] == "UNKNOWN"
        target = next(item for item in policy_eval.gates if item.gate_name == GATE_EVIDENCE)
        waived = await verification.waive_gate_result(
            target.gate_result_id,
            authorized_by="user:owner",
            reason="暂无截图，接受风险",
            risk_statement="可能遗漏视觉问题",
            scope="phase-1",
            expires_at=utcnow() + timedelta(days=3),
        )
        assert waived.status == GATE_WAIVED
        assert waived.waiver is not None
        assert waived.waiver["authorized_by"] == "user:owner"

        after = await verification.evaluate_quality_gate(
            project_id, campaign_id=campaign.campaign_id, policy_id=policy.gate_policy_id
        )
        waived_gate = next(item for item in after.gates if item.gate_name == GATE_EVIDENCE)
        assert waived_gate.status == GATE_WAIVED
        assert after.decision["status"] == "PASSED"

        policies = await verification.list_gate_policies(project_id)
        assert len(policies) == 1


@pytest.mark.asyncio
async def test_phase_review_flow_and_dashboards(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id = await _project(app, tmp_path)
        requirement_id = await _requirement(app, project_id)
        campaign = await verification.create_campaign(project_id=project_id, campaign_type="PHASE")
        await verification.create_plan(
            campaign.campaign_id,
            requirement_ids=(requirement_id,),
            verification_layers=("STATIC",),
        )
        await verification.register_test_case(
            project_id=project_id,
            name="test_player_jump",
            test_type="FUNCTIONAL",
            execution_method="GODOT_TEST",
        )

        review = await verification.create_phase_review(
            project_id,
            workflow_id="wf_demo",
            phase_id="ph_1",
            campaign_id=campaign.campaign_id,
            goals=["完成玩家移动与跳跃"],
            completed=["移动"],
            incomplete=["跳跃音效"],
        )
        assert review.status == "DRAFT"
        assert review.recommendation == "REQUEST_REVISION"
        assert review.summary["defects"]["total"] == 0
        assert review.summary["verification"]["passed"] == 0

        submitted = await verification.submit_phase_review(
            review.review_id, submitted_by="agent:qa"
        )
        assert submitted.status == "SUBMITTED"

        decided = await verification.decide_phase_review(
            review.review_id,
            decision="ACCEPT",
            actor_id="user:owner",
            comment="接受当前风险",
        )
        assert decided.status == "ACCEPTED"
        assert len(decided.decisions) == 1
        assert decided.decisions[0]["decision"] == "ACCEPT"

        reviewed = await verification.get_phase_review(review.review_id)
        assert reviewed.decided_by == "user:owner"

        listed = await verification.list_phase_reviews(project_id)
        assert listed["total"] == 1

        with pytest.raises(ValidationFailed):
            await verification.decide_phase_review(
                review.review_id, decision="NOT_A_DECISION", actor_id="user:owner"
            )

        overview = await verification.verification_overview(project_id)
        assert overview["campaigns"]["total"] == 1
        assert overview["results"]["executed"] == 0
        assert overview["results"]["pass_rate"] == 0.0
        assert overview["test_cases"] == 1

        requirements = await verification.requirement_dashboard(project_id)
        assert requirements["total_requirements"] == 1
        assert "coverage" in requirements

        tests = await verification.test_dashboard(project_id)
        assert tests["test_case_count"] == 1
        assert tests["test_case_by_type"]["FUNCTIONAL"] == 1
        assert tests["recent_runs"] == []

        evidence = await verification.evidence_dashboard(project_id)
        assert evidence["project_id"] == project_id
        assert evidence["items"] == []
