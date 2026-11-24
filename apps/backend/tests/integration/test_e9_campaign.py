"""E9-T01 / T02 / T03 验证活动集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    VerificationEvidenceStale,
    VerificationPlanInvalid,
    VerificationResultInvalid,
    VerificationStateInvalid,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.project_registry.service import ProjectRegistryService
from modules.requirement.models import REQUIREMENT_ACTIVE, RequirementModel
from modules.verification.service import VerificationService

HASH_A = "a" * 64


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9verification.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _project(app, tmp_path: Path, name: str) -> str:
    registry = _service(app, "project_registry_service", ProjectRegistryService)
    root = tmp_path / name.lower().replace(" ", "_")
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name=name)
    return project.project_id


async def _requirement(app, project_id: str, key: str = "REQ-JUMP") -> str:
    database = _service(app, "database", DatabaseService)
    requirement_id = "req_" + key.lower().replace("-", "_")
    now = utcnow()
    async with database.session() as session:
        session.add(
            RequirementModel(
                requirement_id=requirement_id,
                project_id=project_id,
                requirement_key=key,
                title="玩家可以跳跃",
                description="玩家按下跳跃键后完成一次跳跃",
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
async def test_campaign_plan_run_result_and_traceability(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id = await _project(app, tmp_path, "Verify")
        requirement_id = await _requirement(app, project_id)

        campaign = await verification.create_campaign(
            project_id=project_id, campaign_type="PHASE", created_by="agent:qa"
        )
        assert campaign.status == "DRAFT"

        plan = await verification.create_plan(
            campaign.campaign_id,
            requirement_ids=(requirement_id,),
            verification_layers=("STATIC", "RUNTIME"),
            target_platforms=("windows",),
        )
        assert plan.verification_layers == ("STATIC", "RUNTIME")
        assert (await verification.get_campaign(campaign.campaign_id)).status == "READY"

        test_case = await verification.register_test_case(
            project_id=project_id,
            name="玩家跳跃",
            test_type="RUNTIME",
            execution_method="godot_headless",
            automation_level="AUTOMATED",
        )
        criterion = await verification.register_criterion(
            project_id=project_id,
            requirement_id=requirement_id,
            criterion_type="FUNCTIONAL",
            statement="玩家可以完成一次跳跃",
            verification_method="FUNCTIONAL_TEST",
            required_evidence=("RUNTIME_TRACE",),
        )
        link = await verification.link_test(
            requirement_id=requirement_id,
            test_case_id=test_case.test_case_id,
            criterion_id=criterion.criterion_id,
        )
        assert link.requirement_id == requirement_id

        coverage = await verification.coverage(project_id)
        assert coverage["total_testable_requirements"] == 1
        assert coverage["covered_requirements"] == 1
        assert coverage["coverage_rate"] == 100.0
        assert coverage["untraceable_requirement_ids"] == []

        run = await verification.start_run(campaign.campaign_id, test_suite_id="suite_jump")
        assert run.execution_status == "RUNNING"
        evidence = await verification.record_evidence(
            project_id=project_id,
            evidence_type="RUNTIME_TRACE",
            source_type="GODOT_RUNTIME",
            source_reference="runtime://session/jump/trace-01",
            content_hash=HASH_A,
            run_id=run.run_id,
        )
        completed = await verification.complete_run(
            run.run_id, execution_status="COMPLETED", evidence_ids=(evidence.evidence_id,)
        )
        assert completed.execution_status == "COMPLETED"
        assert evidence.evidence_id in completed.evidence_ids

        result = await verification.record_result(
            campaign_id=campaign.campaign_id,
            result_status="PASSED",
            run_id=run.run_id,
            requirement_id=requirement_id,
            criterion_id=criterion.criterion_id,
            test_case_id=test_case.test_case_id,
            evidence_ids=(evidence.evidence_id,),
            confidence_level="HIGH",
        )
        assert result.result_status == "PASSED"
        assert result.verified_at is not None

        after = await verification.coverage(project_id)
        assert after["executed_tests"] == 1
        assert after["pass_rate"] == 100.0

        trace = await verification.trace_requirement(requirement_id)
        assert trace["latest_result"] is not None
        assert trace["latest_result"].result_status == "PASSED"

        counts = await verification.invalidate_requirement(requirement_id, reason="需求变更")
        assert counts["criteria_superseded"] == 1
        assert counts["results_superseded"] == 1
        assert (await verification.get_result(result.result_id)).result_status == "SUPERSEDED"


@pytest.mark.asyncio
async def test_evidence_rules_and_waiver(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id = await _project(app, tmp_path, "Evidence")
        requirement_id = await _requirement(app, project_id, key="REQ-ATTACK")
        campaign = await verification.create_campaign(project_id=project_id, campaign_type="TASK")

        with pytest.raises(VerificationStateInvalid):
            await verification.start_run(campaign.campaign_id)

        with pytest.raises(VerificationStateInvalid):
            await verification.transition_campaign(campaign.campaign_id, "COMPLETED")

        with pytest.raises(VerificationPlanInvalid):
            await verification.create_plan(campaign.campaign_id, verification_layers=("UNKNOWN",))

        await verification.create_plan(campaign.campaign_id, verification_layers=("RUNTIME",))

        run = await verification.start_run(campaign.campaign_id)

        with pytest.raises(VerificationResultInvalid):
            await verification.record_result(
                campaign_id=campaign.campaign_id,
                result_status="PASSED",
                run_id=run.run_id,
                requirement_id=requirement_id,
            )

        with pytest.raises(VerificationResultInvalid):
            await verification.record_result(
                campaign_id=campaign.campaign_id,
                result_status="FAILED",
                run_id=run.run_id,
                requirement_id=requirement_id,
            )

        evidence = await verification.record_evidence(
            project_id=project_id,
            evidence_type="LOG",
            source_type="GODOT_RUNTIME",
            source_reference="runtime://session/log-01",
            content_hash=HASH_A,
        )
        await verification.invalidate_evidence(evidence.evidence_id)
        with pytest.raises(VerificationEvidenceStale):
            await verification.record_result(
                campaign_id=campaign.campaign_id,
                result_status="PASSED",
                run_id=run.run_id,
                requirement_id=requirement_id,
                evidence_ids=(evidence.evidence_id,),
            )

        failed = await verification.record_result(
            campaign_id=campaign.campaign_id,
            result_status="FAILED",
            run_id=run.run_id,
            requirement_id=requirement_id,
            failure_reason="玩家攻击没有造成伤害",
        )
        waived = await verification.waive_result(
            failed.result_id, reason="确认属于已知外部问题", waived_by="user:owner"
        )
        assert waived.result_status == "WAIVED"
        assert "waived_by=user:owner" in (waived.failure_reason or "")
