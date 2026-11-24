"""验证编排器（E9-T05）。

职责：

- 从需求生成 Campaign + VerificationPlan；
- 按计划层次顺序执行已注册的 LayerExecutor；
- 每层独立 Run，结果必须带证据，失败必须带原因；
- 执行器异常按 FAILED 处理，未注册执行器按 NOT_RUN/SKIPPED 处理；
- UNKNOWN 保留为 UNKNOWN，不自动降级为 FAILED；
- 只推进 Verification 自己的状态，绝不修改 Task / Workflow / ChangeSet 状态。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.errors import (
    VerificationPlanInvalid,
    VerificationResultInvalid,
    VerificationStateInvalid,
)
from modules.verification.models import (
    CAMPAIGN_COMPLETED,
    CAMPAIGN_FAILED,
    CAMPAIGN_READY,
    CAMPAIGN_RUNNING,
    PLAN_ACTIVE,
    PLAN_COMPLETED,
    PLAN_READY,
    RESULT_FAILED,
    RESULT_NOT_RUN,
    RESULT_PASSED,
    RESULT_STATUSES,
    RESULT_UNKNOWN,
    RUN_FAILED,
    RUN_SKIPPED,
    RUN_STATUSES,
    VERIFICATION_LAYERS,
)
from modules.verification.planner import PlanProposal
from modules.verification.service import (
    CampaignView,
    PlanView,
    VerificationService,
)

_ALLOWED_EXECUTION_STATUSES = frozenset(
    {"COMPLETED", "FAILED", "UNKNOWN", "SKIPPED", "CANCELLED"}
)
_NON_PASS_EXECUTION = frozenset({"FAILED", "UNKNOWN", "SKIPPED", "CANCELLED"})


@dataclass(frozen=True, slots=True)
class EvidenceDraft:
    evidence_type: str
    source_type: str
    source_reference: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LayerOutcome:
    """执行器返回的层结果。执行器不能直接写库，也不能声明 Task 成功。"""

    execution_status: str
    result_status: str
    evidence: tuple[EvidenceDraft, ...] = ()
    failure_reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerificationContext:
    campaign_id: str
    project_id: str
    plan: PlanView
    layer: str
    requirement_ids: tuple[str, ...]
    environment_profile: str | None
    target_platforms: tuple[str, ...]
    acceptance_policy: dict[str, Any]


class LayerExecutor(Protocol):
    async def __call__(self, context: VerificationContext) -> LayerOutcome: ...


@dataclass(frozen=True, slots=True)
class LayerReport:
    layer: str
    run_id: str
    execution_status: str
    result_status: str
    result_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    failure_reason: str | None


@dataclass(frozen=True, slots=True)
class OrchestrationReport:
    campaign_id: str
    campaign_status: str
    plan_id: str
    plan_status: str
    layers: tuple[LayerReport, ...]
    summary: dict[str, int]
    blocking: bool


@dataclass(frozen=True, slots=True)
class PreparedVerification:
    proposal: PlanProposal
    campaign: CampaignView
    plan: PlanView


class VerificationOrchestrator:
    def __init__(self, verification: VerificationService) -> None:
        self._verification = verification
        self._executors: dict[str, LayerExecutor] = {}

    def register_executor(self, layer: str, executor: LayerExecutor) -> None:
        if layer not in VERIFICATION_LAYERS:
            raise VerificationPlanInvalid("未知验证层次", details={"layer": layer})
        self._executors[layer] = executor

    def registered_layers(self) -> tuple[str, ...]:
        return tuple(sorted(self._executors))

    async def prepare(
        self,
        *,
        project_id: str,
        campaign_type: str,
        requirement_ids: Sequence[str],
        workflow_id: str | None = None,
        phase_id: str | None = None,
        task_id: str | None = None,
        changeset_id: str | None = None,
        target_platforms: Sequence[str] = (),
        environment_profile: str | None = None,
        acceptance_policy: dict[str, Any] | None = None,
        allow_gaps: bool = False,
        created_by: str | None = None,
    ) -> PreparedVerification:
        proposal = await self._verification.propose_plan(
            project_id,
            tuple(requirement_ids),
            target_platforms=tuple(target_platforms),
            environment_profile=environment_profile,
            acceptance_policy=acceptance_policy,
        )
        if not proposal.ready and not allow_gaps:
            raise VerificationPlanInvalid(
                "验证计划存在覆盖缺口，禁止执行",
                details={
                    "gaps": [
                        {
                            "kind": gap.kind,
                            "requirement_id": gap.requirement_id,
                            "criterion_id": gap.criterion_id,
                            "message": gap.message,
                        }
                        for gap in proposal.gaps
                    ]
                },
            )
        campaign = await self._verification.create_campaign(
            project_id=project_id,
            campaign_type=campaign_type,
            workflow_id=workflow_id,
            phase_id=phase_id,
            task_id=task_id,
            changeset_id=changeset_id,
            created_by=created_by,
        )
        plan = await self._verification.create_plan(
            campaign.campaign_id,
            requirement_ids=proposal.requirement_ids,
            test_suite_ids=proposal.test_case_ids,
            verification_layers=proposal.verification_layers,
            environment_profile=proposal.environment_profile,
            target_platforms=proposal.target_platforms,
            acceptance_policy=proposal.acceptance_policy,
        )
        campaign = await self._verification.get_campaign(campaign.campaign_id)
        return PreparedVerification(proposal=proposal, campaign=campaign, plan=plan)

    async def run_plan(
        self, campaign_id: str, *, executor_id: str | None = None
    ) -> OrchestrationReport:
        campaign = await self._verification.get_campaign(campaign_id)
        if campaign.status not in {CAMPAIGN_READY, CAMPAIGN_RUNNING}:
            raise VerificationStateInvalid(
                "验证活动尚未就绪，不能编排执行", details={"status": campaign.status}
            )
        plan = await self._verification.latest_plan(campaign_id)
        if plan is None:
            raise VerificationPlanInvalid("验证活动缺少验证计划")
        if plan.status not in {PLAN_READY, PLAN_ACTIVE}:
            raise VerificationPlanInvalid(
                "验证计划状态不允许执行", details={"status": plan.status}
            )
        if not plan.requirement_ids:
            raise VerificationPlanInvalid("验证计划必须关联需求才能记录结果")
        unknown_layers = sorted(set(plan.verification_layers) - set(VERIFICATION_LAYERS))
        if unknown_layers:
            raise VerificationPlanInvalid(
                "验证计划包含未知层次", details={"layers": unknown_layers}
            )
        if plan.status == PLAN_READY:
            plan = await self._verification.transition_plan(plan.plan_id, PLAN_ACTIVE)

        reports: list[LayerReport] = []
        for layer in plan.verification_layers:
            reports.append(
                await self._run_layer(campaign_id, plan, layer, executor_id=executor_id)
            )

        plan_status = PLAN_ACTIVE
        counts = _summarize(reports)
        expected = len(plan.requirement_ids) * len(plan.verification_layers)
        blocking = counts[RESULT_PASSED] < expected
        target = _campaign_target(counts, expected)
        if target is not None:
            campaign = await self._verification.transition_campaign(campaign_id, target)
            plan = await self._verification.transition_plan(plan.plan_id, PLAN_COMPLETED)
            plan_status = plan.status
        else:
            campaign = await self._verification.get_campaign(campaign_id)
        return OrchestrationReport(
            campaign_id=campaign_id,
            campaign_status=campaign.status,
            plan_id=plan.plan_id,
            plan_status=plan_status,
            layers=tuple(reports),
            summary=counts,
            blocking=blocking,
        )

    async def _run_layer(
        self,
        campaign_id: str,
        plan: PlanView,
        layer: str,
        *,
        executor_id: str | None,
    ) -> LayerReport:
        campaign = await self._verification.get_campaign(campaign_id)
        run = await self._verification.start_run(
            campaign_id,
            plan_id=plan.plan_id,
            test_suite_id=layer,
            environment_id=plan.environment_profile,
            executor_id=executor_id,
        )
        executor = self._executors.get(layer)
        if executor is None:
            completed = await self._verification.complete_run(
                run.run_id,
                execution_status=RUN_SKIPPED,
                failure_reason="未注册该验证层次的执行器",
            )
            result_ids = await self._record(
                campaign_id=campaign_id,
                plan=plan,
                run_id=run.run_id,
                result_status=RESULT_NOT_RUN,
                failure_reason="未执行：缺少执行器",
            )
            return LayerReport(
                layer=layer,
                run_id=run.run_id,
                execution_status=completed.execution_status,
                result_status=RESULT_NOT_RUN,
                result_ids=result_ids,
                evidence_ids=(),
                failure_reason=completed.failure_reason,
            )

        context = VerificationContext(
            campaign_id=campaign_id,
            project_id=campaign.project_id,
            plan=plan,
            layer=layer,
            requirement_ids=plan.requirement_ids,
            environment_profile=plan.environment_profile,
            target_platforms=plan.target_platforms,
            acceptance_policy=plan.acceptance_policy,
        )
        try:
            outcome = await executor(context)
            _validate_outcome(outcome)
            evidence_ids: list[str] = []
            for draft in outcome.evidence:
                evidence = await self._verification.record_evidence(
                    project_id=campaign.project_id,
                    evidence_type=draft.evidence_type,
                    source_type=draft.source_type,
                    source_reference=draft.source_reference,
                    content_hash=draft.content_hash,
                    run_id=run.run_id,
                    metadata=draft.metadata,
                )
                evidence_ids.append(evidence.evidence_id)
            completed = await self._verification.complete_run(
                run.run_id,
                execution_status=outcome.execution_status,
                evidence_ids=tuple(evidence_ids),
                failure_reason=outcome.failure_reason,
            )
        except Exception as exc:  # noqa: BLE001 - 执行器异常必须落为失败证据
            completed = await self._verification.complete_run(
                run.run_id,
                execution_status=RUN_FAILED,
                failure_reason=_reason(exc),
            )
            result_ids = await self._record(
                campaign_id=campaign_id,
                plan=plan,
                run_id=run.run_id,
                result_status=RESULT_FAILED,
                failure_reason=_reason(exc),
            )
            return LayerReport(
                layer=layer,
                run_id=run.run_id,
                execution_status=completed.execution_status,
                result_status=RESULT_FAILED,
                result_ids=result_ids,
                evidence_ids=(),
                failure_reason=completed.failure_reason,
            )

        result_ids = await self._record(
            campaign_id=campaign_id,
            plan=plan,
            run_id=run.run_id,
            result_status=outcome.result_status,
            evidence_ids=tuple(evidence_ids),
            failure_reason=outcome.failure_reason,
        )
        return LayerReport(
            layer=layer,
            run_id=run.run_id,
            execution_status=completed.execution_status,
            result_status=outcome.result_status,
            result_ids=result_ids,
            evidence_ids=tuple(evidence_ids),
            failure_reason=completed.failure_reason,
        )

    async def _record(
        self,
        *,
        campaign_id: str,
        plan: PlanView,
        run_id: str,
        result_status: str,
        evidence_ids: tuple[str, ...] = (),
        failure_reason: str | None = None,
    ) -> tuple[str, ...]:
        result_ids: list[str] = []
        for requirement_id in plan.requirement_ids:
            result = await self._verification.record_result(
                campaign_id=campaign_id,
                result_status=result_status,
                run_id=run_id,
                requirement_id=requirement_id,
                evidence_ids=evidence_ids,
                failure_reason=failure_reason,
            )
            result_ids.append(result.result_id)
        return tuple(result_ids)


def _validate_outcome(outcome: LayerOutcome) -> None:
    if outcome.execution_status not in RUN_STATUSES:
        raise VerificationResultInvalid(
            "执行器返回了未知执行状态", details={"execution_status": outcome.execution_status}
        )
    if outcome.execution_status not in _ALLOWED_EXECUTION_STATUSES:
        raise VerificationResultInvalid(
            "执行器必须返回终态", details={"execution_status": outcome.execution_status}
        )
    if outcome.result_status not in RESULT_STATUSES:
        raise VerificationResultInvalid(
            "执行器返回了未知结果状态", details={"result_status": outcome.result_status}
        )
    if outcome.result_status == RESULT_PASSED and not outcome.evidence:
        raise VerificationResultInvalid("通过结果必须提供证据，执行器不能自行宣布成功")
    if outcome.result_status == RESULT_PASSED and outcome.execution_status in _NON_PASS_EXECUTION:
        raise VerificationResultInvalid(
            "未成功执行不能产生通过结果",
            details={
                "execution_status": outcome.execution_status,
                "result_status": outcome.result_status,
            },
        )
    if outcome.result_status == RESULT_FAILED and not (outcome.failure_reason or "").strip():
        raise VerificationResultInvalid("失败结果必须给出失败原因")
    if outcome.result_status == RESULT_UNKNOWN and outcome.execution_status == "COMPLETED":
        raise VerificationResultInvalid("UNKNOWN 结果不能标记为执行完成")

    for draft in outcome.evidence:
        if not draft.source_reference.strip():
            raise VerificationResultInvalid("证据缺少来源引用")


def _reason(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _summarize(reports: Sequence[LayerReport]) -> dict[str, int]:
    counts = {status: 0 for status in RESULT_STATUSES}
    for report in reports:
        counts[report.result_status] += len(report.result_ids)
    counts["TOTAL"] = sum(len(report.result_ids) for report in reports)
    return counts


def _campaign_target(counts: dict[str, int], expected: int) -> str | None:
    if expected > 0 and counts.get(RESULT_PASSED, 0) == expected:
        return CAMPAIGN_COMPLETED
    if counts.get(RESULT_FAILED, 0) > 0:
        return CAMPAIGN_FAILED
    return None


__all__ = [
    "EvidenceDraft",
    "LayerExecutor",
    "LayerOutcome",
    "LayerReport",
    "OrchestrationReport",
    "PreparedVerification",
    "VerificationContext",
    "VerificationOrchestrator",
]
