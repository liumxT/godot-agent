"""E9-T05 验证编排器集成测试。"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import VerificationPlanInvalid
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.project_registry.service import ProjectRegistryService
from modules.requirement.models import REQUIREMENT_ACTIVE, RequirementModel
from modules.verification.models import (
    LAYER_RUNTIME,
    LAYER_STATIC,
    METHOD_RUNTIME_TEST,
    METHOD_STATIC_ANALYSIS,
)
from modules.verification.orchestrator import (
    EvidenceDraft,
    LayerOutcome,
    VerificationOrchestrator,
)
from modules.verification.service import VerificationService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9orchestrator.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _get(app, name: str, expected):
    return app.state.services.get(name, expected)


def _draft(layer: str) -> EvidenceDraft:
    return EvidenceDraft(
        evidence_type="TEST_REPORT",
        source_type="TEST_RUNNER",
        source_reference=f"runner://{layer}/report",
        content_hash=hashlib.sha256(layer.encode()).hexdigest(),
        metadata={"layer": layer},
    )


class _PassExecutor:
    def __init__(self, layer: str) -> None:
        self.layer = layer

    async def __call__(self, context):
        return LayerOutcome(
            execution_status="COMPLETED",
            result_status="PASSED",
            evidence=(_draft(self.layer),),
        )


class _FailExecutor:
    async def __call__(self, context):
        return LayerOutcome(
            execution_status="FAILED",
            result_status="FAILED",
            failure_reason="玩家无法跳跃",
        )


class _UnknownExecutor:
    async def __call__(self, context):
        return LayerOutcome(execution_status="UNKNOWN", result_status="UNKNOWN")


class _NoEvidenceExecutor:
    async def __call__(self, context):
        return LayerOutcome(execution_status="COMPLETED", result_status="PASSED")


async def _project(app, tmp_path: Path, name: str) -> str:
    registry = _get(app, "project_registry_service", ProjectRegistryService)
    root = tmp_path / name.lower()
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name=name)
    return project.project_id


async def _requirement(app, project_id: str) -> str:
    database = _get(app, "database", DatabaseService)
    requirement_id = "req_jump"
    now = utcnow()
    async with database.session() as session:
        session.add(
            RequirementModel(
                requirement_id=requirement_id,
                project_id=project_id,
                requirement_key="REQ-JUMP",
                title="玩家可以跳跃",
                description="按下跳跃键完成跳跃",
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


async def _trace(verification: VerificationService, project_id: str, requirement_id: str) -> None:
    static_case = await verification.register_test_case(
        project_id=project_id,
        name="静态检查",
        test_type="STATIC",
        execution_method="static_analyzer",
        automation_level="AUTOMATED",
    )
    runtime_case = await verification.register_test_case(
        project_id=project_id,
        name="运行时跳跃",
        test_type="RUNTIME",
        execution_method="godot_headless",
        automation_level="AUTOMATED",
    )
    static_criterion = await verification.register_criterion(
        project_id=project_id,
        requirement_id=requirement_id,
        criterion_type="STRUCTURAL",
        statement="Player 场景包含 CharacterBody2D",
        verification_method=METHOD_STATIC_ANALYSIS,
    )
    runtime_criterion = await verification.register_criterion(
        project_id=project_id,
        requirement_id=requirement_id,
        criterion_type="FUNCTIONAL",
        statement="玩家运行时可以跳跃",
        verification_method=METHOD_RUNTIME_TEST,
    )
    await verification.link_test(
        requirement_id=requirement_id,
        test_case_id=static_case.test_case_id,
        criterion_id=static_criterion.criterion_id,
    )
    await verification.link_test(
        requirement_id=requirement_id,
        test_case_id=runtime_case.test_case_id,
        criterion_id=runtime_criterion.criterion_id,
    )


async def _prepare(app, tmp_path: Path, name: str = "Orchestrated"):
    verification = _get(app, "verification_service", VerificationService)
    orchestrator = _get(app, "verification_orchestrator", VerificationOrchestrator)
    project_id = await _project(app, tmp_path, name)
    requirement_id = await _requirement(app, project_id)
    await _trace(verification, project_id, requirement_id)
    prepared = await orchestrator.prepare(
        project_id=project_id,
        campaign_type="TASK",
        requirement_ids=(requirement_id,),
        target_platforms=("windows",),
        environment_profile="local",
    )
    return verification, orchestrator, prepared


@pytest.mark.asyncio
async def test_orchestrator_runs_layers_and_completes_campaign(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification, orchestrator, prepared = await _prepare(app, tmp_path)
        assert prepared.proposal.ready is True
        assert prepared.proposal.verification_layers == (LAYER_STATIC, LAYER_RUNTIME)
        assert prepared.campaign.status == "READY"
        orchestrator.register_executor(LAYER_STATIC, _PassExecutor(LAYER_STATIC))
        orchestrator.register_executor(LAYER_RUNTIME, _PassExecutor(LAYER_RUNTIME))

        report = await orchestrator.run_plan(prepared.campaign.campaign_id)

        assert report.blocking is False
        assert report.campaign_status == "COMPLETED"
        assert report.plan_status == "COMPLETED"
        assert report.summary["PASSED"] == 2
        assert [layer.layer for layer in report.layers] == [LAYER_STATIC, LAYER_RUNTIME]
        for layer in report.layers:
            assert layer.execution_status == "COMPLETED"
            assert layer.evidence_ids

        campaign = await verification.get_campaign(prepared.campaign.campaign_id)
        assert campaign.completed_at is not None
        results = await verification.list_results(prepared.campaign.campaign_id)
        assert {item.result_status for item in results["items"]} == {"PASSED"}


@pytest.mark.asyncio
async def test_executor_failure_marks_campaign_failed(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        _verification, orchestrator, prepared = await _prepare(app, tmp_path, "Failed")
        orchestrator.register_executor(LAYER_STATIC, _PassExecutor(LAYER_STATIC))
        orchestrator.register_executor(LAYER_RUNTIME, _FailExecutor())

        report = await orchestrator.run_plan(prepared.campaign.campaign_id)

        assert report.blocking is True
        assert report.campaign_status == "FAILED"
        assert report.summary["FAILED"] == 1
        failed_layer = report.layers[-1]
        assert failed_layer.failure_reason == "玩家无法跳跃"


@pytest.mark.asyncio
async def test_unknown_is_not_downgraded_to_failed(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification, orchestrator, prepared = await _prepare(app, tmp_path, "Unknown")
        orchestrator.register_executor(LAYER_STATIC, _PassExecutor(LAYER_STATIC))
        orchestrator.register_executor(LAYER_RUNTIME, _UnknownExecutor())

        report = await orchestrator.run_plan(prepared.campaign.campaign_id)

        assert report.blocking is True
        assert report.campaign_status == "RUNNING"
        assert report.summary["UNKNOWN"] == 1
        results = await verification.list_results(prepared.campaign.campaign_id)
        statuses = {item.result_status for item in results["items"]}
        assert statuses == {"PASSED", "UNKNOWN"}


@pytest.mark.asyncio
async def test_missing_executor_is_not_run(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification, orchestrator, prepared = await _prepare(app, tmp_path, "Missing")
        orchestrator.register_executor(LAYER_STATIC, _PassExecutor(LAYER_STATIC))

        report = await orchestrator.run_plan(prepared.campaign.campaign_id)

        assert report.blocking is True
        assert report.campaign_status == "RUNNING"
        assert report.summary["NOT_RUN"] == 1
        runs = await verification.list_runs(prepared.campaign.campaign_id)
        assert {item.execution_status for item in runs["items"]} == {"COMPLETED", "SKIPPED"}


@pytest.mark.asyncio
async def test_pass_without_evidence_is_rejected(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        _verification, orchestrator, prepared = await _prepare(app, tmp_path, "NoEvidence")
        orchestrator.register_executor(LAYER_STATIC, _NoEvidenceExecutor())
        orchestrator.register_executor(LAYER_RUNTIME, _PassExecutor(LAYER_RUNTIME))

        report = await orchestrator.run_plan(prepared.campaign.campaign_id)

        assert report.campaign_status == "FAILED"
        failed_layer = report.layers[0]
        assert failed_layer.execution_status == "FAILED"
        assert "证据" in (failed_layer.failure_reason or "")


@pytest.mark.asyncio
async def test_prepare_blocks_on_coverage_gap(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        orchestrator = _get(app, "verification_orchestrator", VerificationOrchestrator)
        project_id = await _project(app, tmp_path, "Gap")
        requirement_id = await _requirement(app, project_id)

        with pytest.raises(VerificationPlanInvalid) as exc_info:
            await orchestrator.prepare(
                project_id=project_id,
                campaign_type="TASK",
                requirement_ids=(requirement_id,),
            )
        gaps = exc_info.value.details["gaps"]
        assert {gap["kind"] for gap in gaps} == {"missing_criteria", "uncovered_requirement"}
