"""Verification 仓储（E9-T01 / T02 / T03）。

Repository 只读写 verification 自己的表，不提交事务、不修改其他模块状态。
所有按项目查询都必须显式带 ``project_id``。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, update

from infrastructure.database.repository import BaseRepository, Page
from modules.verification.models import (
    EVIDENCE_VALID,
    TEST_CASE_ARCHIVED,
    PhaseReviewDecisionModel,
    PhaseReviewModel,
    QualityGatePolicyModel,
    QualityGateResultModel,
    QualityGateWaiverModel,
    VerificationCampaignModel,
    VerificationCriterionModel,
    VerificationDebuggerErrorModel,
    VerificationDefectModel,
    VerificationEvidenceModel,
    VerificationPlanModel,
    VerificationRegressionPlanModel,
    VerificationResultModel,
    VerificationRunModel,
    VerificationRuntimeEnvironmentModel,
    VerificationTestCaseModel,
    VerificationTestLinkModel,
)


class CampaignRepository(BaseRepository[VerificationCampaignModel]):
    model = VerificationCampaignModel

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        campaign_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[VerificationCampaignModel]:
        filters = [VerificationCampaignModel.project_id == project_id]
        if status is not None:
            filters.append(VerificationCampaignModel.status == status)
        if campaign_type is not None:
            filters.append(VerificationCampaignModel.campaign_type == campaign_type)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_all(self, project_id: str) -> list[VerificationCampaignModel]:
        rows = await self.session.scalars(
            select(VerificationCampaignModel)
            .where(VerificationCampaignModel.project_id == project_id)
            .order_by(VerificationCampaignModel.created_at)
        )
        return list(rows.all())

    async def transition(
        self,
        campaign_id: str,
        *,
        from_statuses: frozenset[str],
        to_status: str,
        expected_version: int,
        now,
        completed_at=None,
    ) -> bool:
        values = {
            "status": to_status,
            "version": VerificationCampaignModel.version + 1,
        }
        if completed_at is not None:
            values["completed_at"] = completed_at
        result = await self.session.execute(
            update(VerificationCampaignModel)
            .where(
                VerificationCampaignModel.campaign_id == campaign_id,
                VerificationCampaignModel.status.in_(tuple(from_statuses)),
                VerificationCampaignModel.version == expected_version,
            )
            .values(**values)
        )
        return bool(result.rowcount)


class PlanRepository(BaseRepository[VerificationPlanModel]):
    model = VerificationPlanModel

    async def get_for_campaign(self, campaign_id: str) -> VerificationPlanModel | None:
        return await self.session.scalar(
            select(VerificationPlanModel)
            .where(VerificationPlanModel.campaign_id == campaign_id)
            .order_by(VerificationPlanModel.created_at.desc())
        )

    async def set_status(
        self, plan_id: str, *, from_statuses: frozenset[str], to_status: str
    ) -> bool:
        result = await self.session.execute(
            update(VerificationPlanModel)
            .where(
                VerificationPlanModel.plan_id == plan_id,
                VerificationPlanModel.status.in_(tuple(from_statuses)),
            )
            .values(status=to_status)
        )
        return bool(result.rowcount)


class TestCaseRepository(BaseRepository[VerificationTestCaseModel]):
    model = VerificationTestCaseModel

    async def get_by_name(self, project_id: str, name: str) -> VerificationTestCaseModel | None:
        return await self.session.scalar(
            select(VerificationTestCaseModel).where(
                VerificationTestCaseModel.project_id == project_id,
                VerificationTestCaseModel.name == name,
            )
        )

    async def list_by_ids(self, test_case_ids: Sequence[str]) -> list[VerificationTestCaseModel]:
        if not test_case_ids:
            return []
        rows = await self.session.scalars(
            select(VerificationTestCaseModel).where(
                VerificationTestCaseModel.test_case_id.in_(tuple(test_case_ids))
            )
        )
        return list(rows.all())

    async def list_page(
        self,
        *,
        project_id: str,
        test_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[VerificationTestCaseModel]:
        filters = [VerificationTestCaseModel.project_id == project_id]
        if test_type is not None:
            filters.append(VerificationTestCaseModel.test_type == test_type)
        if status is not None:
            filters.append(VerificationTestCaseModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_active(self, project_id: str) -> list[VerificationTestCaseModel]:
        """列出项目内未归档测试用例，供影响分析使用。"""

        rows = await self.session.scalars(
            select(VerificationTestCaseModel)
            .where(
                VerificationTestCaseModel.project_id == project_id,
                VerificationTestCaseModel.status != TEST_CASE_ARCHIVED,
            )
            .order_by(VerificationTestCaseModel.name)
        )
        return list(rows.all())

    async def count_active(self, project_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(VerificationTestCaseModel)
                .where(
                    VerificationTestCaseModel.project_id == project_id,
                    VerificationTestCaseModel.status != TEST_CASE_ARCHIVED,
                )
            )
            or 0
        )


class CriterionRepository(BaseRepository[VerificationCriterionModel]):
    model = VerificationCriterionModel

    async def list_for_requirement(self, requirement_id: str) -> list[VerificationCriterionModel]:
        rows = await self.session.scalars(
            select(VerificationCriterionModel)
            .where(VerificationCriterionModel.requirement_id == requirement_id)
            .order_by(VerificationCriterionModel.created_at)
        )
        return list(rows.all())

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        criterion_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[VerificationCriterionModel]:
        filters = [VerificationCriterionModel.project_id == project_id]
        if status is not None:
            filters.append(VerificationCriterionModel.status == status)
        if criterion_type is not None:
            filters.append(VerificationCriterionModel.criterion_type == criterion_type)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def count_active(self, project_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(VerificationCriterionModel)
                .where(
                    VerificationCriterionModel.project_id == project_id,
                    VerificationCriterionModel.status == "ACTIVE",
                )
            )
            or 0
        )

    async def supersede_active(self, requirement_id: str) -> int:
        """需求新版本出现后，旧验收标准必须进入待复核状态。"""

        result = await self.session.execute(
            update(VerificationCriterionModel)
            .where(
                VerificationCriterionModel.requirement_id == requirement_id,
                VerificationCriterionModel.status == "ACTIVE",
            )
            .values(status="SUPERSEDED")
        )
        return int(result.rowcount or 0)


class TestLinkRepository(BaseRepository[VerificationTestLinkModel]):
    model = VerificationTestLinkModel

    async def get_link(
        self, requirement_id: str, test_case_id: str
    ) -> VerificationTestLinkModel | None:
        return await self.session.scalar(
            select(VerificationTestLinkModel).where(
                VerificationTestLinkModel.requirement_id == requirement_id,
                VerificationTestLinkModel.test_case_id == test_case_id,
            )
        )

    async def list_for_requirement(self, requirement_id: str) -> list[VerificationTestLinkModel]:
        rows = await self.session.scalars(
            select(VerificationTestLinkModel)
            .where(VerificationTestLinkModel.requirement_id == requirement_id)
            .order_by(VerificationTestLinkModel.created_at)
        )
        return list(rows.all())

    async def list_for_test_case(self, test_case_id: str) -> list[VerificationTestLinkModel]:
        rows = await self.session.scalars(
            select(VerificationTestLinkModel).where(
                VerificationTestLinkModel.test_case_id == test_case_id
            )
        )
        return list(rows.all())

    async def list_for_project(self, project_id: str) -> list[VerificationTestLinkModel]:
        """列出项目内非归档测试用例的追踪关系，供影响分析使用。"""

        rows = await self.session.scalars(
            select(VerificationTestLinkModel)
            .join(
                VerificationTestCaseModel,
                VerificationTestCaseModel.test_case_id == VerificationTestLinkModel.test_case_id,
            )
            .where(
                VerificationTestCaseModel.project_id == project_id,
                VerificationTestCaseModel.status != TEST_CASE_ARCHIVED,
            )
            .order_by(VerificationTestLinkModel.requirement_id)
        )
        return list(rows.all())

    async def covered_requirement_ids(self, project_id: str) -> set[str]:
        """返回至少拥有一条有效测试追踪的需求 ID。"""

        rows = await self.session.scalars(
            select(VerificationTestLinkModel.requirement_id)
            .join(
                VerificationTestCaseModel,
                VerificationTestCaseModel.test_case_id == VerificationTestLinkModel.test_case_id,
            )
            .where(
                VerificationTestCaseModel.project_id == project_id,
                VerificationTestCaseModel.status != TEST_CASE_ARCHIVED,
            )
            .distinct()
        )
        return set(rows.all())


class RunRepository(BaseRepository[VerificationRunModel]):
    model = VerificationRunModel

    async def list_for_campaign(
        self, campaign_id: str, *, limit: int = 100, offset: int = 0
    ) -> Page[VerificationRunModel]:
        return await self.paginate(
            limit=limit,
            offset=offset,
            filters=[VerificationRunModel.campaign_id == campaign_id],
        )

    async def list_for_campaign_light(self, campaign_id: str) -> list[VerificationRunModel]:
        rows = await self.session.scalars(
            select(VerificationRunModel)
            .where(VerificationRunModel.campaign_id == campaign_id)
            .order_by(VerificationRunModel.created_at)
        )
        return list(rows.all())

    async def list_for_project(
        self, project_id: str, *, limit: int = 50
    ) -> list[VerificationRunModel]:
        rows = await self.session.scalars(
            select(VerificationRunModel)
            .join(
                VerificationCampaignModel,
                VerificationCampaignModel.campaign_id == VerificationRunModel.campaign_id,
            )
            .where(VerificationCampaignModel.project_id == project_id)
            .order_by(VerificationRunModel.created_at.desc())
            .limit(limit)
        )
        return list(rows.all())

    async def transition(
        self,
        run_id: str,
        *,
        from_statuses: frozenset[str],
        to_status: str,
        now,
        started_at=None,
        completed_at=None,
        evidence_ids_json: str | None = None,
        failure_reason: str | None = None,
    ) -> bool:
        values: dict[str, object] = {"execution_status": to_status}
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if evidence_ids_json is not None:
            values["evidence_ids_json"] = evidence_ids_json
        if failure_reason is not None:
            values["failure_reason"] = failure_reason
        result = await self.session.execute(
            update(VerificationRunModel)
            .where(
                VerificationRunModel.run_id == run_id,
                VerificationRunModel.execution_status.in_(tuple(from_statuses)),
            )
            .values(**values)
        )
        return bool(result.rowcount)

    async def set_evidence_ids(self, run_id: str, evidence_ids_json: str) -> bool:
        result = await self.session.execute(
            update(VerificationRunModel)
            .where(VerificationRunModel.run_id == run_id)
            .values(evidence_ids_json=evidence_ids_json)
        )
        return bool(result.rowcount)


class ResultRepository(BaseRepository[VerificationResultModel]):
    model = VerificationResultModel

    async def list_for_campaign(
        self, campaign_id: str, *, limit: int = 200, offset: int = 0
    ) -> Page[VerificationResultModel]:
        return await self.paginate(
            limit=limit,
            offset=offset,
            filters=[VerificationResultModel.campaign_id == campaign_id],
        )

    async def list_all_for_campaign(self, campaign_id: str) -> list[VerificationResultModel]:
        rows = await self.session.scalars(
            select(VerificationResultModel)
            .where(VerificationResultModel.campaign_id == campaign_id)
            .order_by(VerificationResultModel.created_at)
        )
        return list(rows.all())

    async def latest_for_requirement(self, requirement_id: str) -> VerificationResultModel | None:
        return await self.session.scalar(
            select(VerificationResultModel)
            .where(
                VerificationResultModel.requirement_id == requirement_id,
                VerificationResultModel.result_status != "SUPERSEDED",
            )
            .order_by(VerificationResultModel.created_at.desc())
        )

    async def transition(
        self,
        result_id: str,
        *,
        from_statuses: frozenset[str],
        to_status: str,
        superseded_by: str | None = None,
        failure_reason: str | None = None,
    ) -> bool:
        values: dict[str, object] = {"result_status": to_status}
        if superseded_by is not None:
            values["superseded_by"] = superseded_by
        if failure_reason is not None:
            values["failure_reason"] = failure_reason
        result = await self.session.execute(
            update(VerificationResultModel)
            .where(
                VerificationResultModel.result_id == result_id,
                VerificationResultModel.result_status.in_(tuple(from_statuses)),
            )
            .values(**values)
        )
        return bool(result.rowcount)

    async def supersede_for_requirement(self, requirement_id: str) -> int:
        """需求变更后使该需求旧结果进入待复核状态。"""

        result = await self.session.execute(
            update(VerificationResultModel)
            .where(
                VerificationResultModel.requirement_id == requirement_id,
                VerificationResultModel.result_status.notin_(("SUPERSEDED",)),
            )
            .values(result_status="SUPERSEDED")
        )
        return int(result.rowcount or 0)

    async def count_by_status(self, campaign_id: str) -> dict[str, int]:
        rows = await self.session.execute(
            select(
                VerificationResultModel.result_status,
                func.count(),
            )
            .where(VerificationResultModel.campaign_id == campaign_id)
            .group_by(VerificationResultModel.result_status)
        )
        return {str(status): int(count) for status, count in rows.all()}

    async def counts_for_project(self, project_id: str) -> dict[str, int]:
        rows = await self.session.execute(
            select(VerificationResultModel.result_status, func.count())
            .join(
                VerificationCampaignModel,
                VerificationCampaignModel.campaign_id == VerificationResultModel.campaign_id,
            )
            .where(VerificationCampaignModel.project_id == project_id)
            .group_by(VerificationResultModel.result_status)
        )
        return {str(status): int(count) for status, count in rows.all()}


class EvidenceRepository(BaseRepository[VerificationEvidenceModel]):
    model = VerificationEvidenceModel

    async def list_for_run(self, run_id: str) -> list[VerificationEvidenceModel]:
        rows = await self.session.scalars(
            select(VerificationEvidenceModel)
            .where(VerificationEvidenceModel.verification_run_id == run_id)
            .order_by(VerificationEvidenceModel.captured_at)
        )
        return list(rows.all())

    async def list_by_ids(self, evidence_ids: Sequence[str]) -> list[VerificationEvidenceModel]:
        if not evidence_ids:
            return []
        rows = await self.session.scalars(
            select(VerificationEvidenceModel).where(
                VerificationEvidenceModel.evidence_id.in_(tuple(evidence_ids))
            )
        )
        return list(rows.all())

    async def list_all(self, project_id: str) -> list[VerificationEvidenceModel]:
        rows = await self.session.scalars(
            select(VerificationEvidenceModel)
            .where(VerificationEvidenceModel.project_id == project_id)
            .order_by(VerificationEvidenceModel.captured_at)
        )
        return list(rows.all())

    async def list_page(
        self,
        *,
        project_id: str,
        evidence_type: str | None = None,
        validity_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[VerificationEvidenceModel]:
        filters = [VerificationEvidenceModel.project_id == project_id]
        if evidence_type is not None:
            filters.append(VerificationEvidenceModel.evidence_type == evidence_type)
        if validity_status is not None:
            filters.append(VerificationEvidenceModel.validity_status == validity_status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def transition(
        self,
        evidence_id: str,
        *,
        from_statuses: frozenset[str],
        to_status: str,
    ) -> bool:
        result = await self.session.execute(
            update(VerificationEvidenceModel)
            .where(
                VerificationEvidenceModel.evidence_id == evidence_id,
                VerificationEvidenceModel.validity_status.in_(tuple(from_statuses)),
            )
            .values(validity_status=to_status)
        )
        return bool(result.rowcount)

    async def count_valid_for_project(self, project_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(VerificationEvidenceModel)
                .where(
                    VerificationEvidenceModel.project_id == project_id,
                    VerificationEvidenceModel.validity_status == EVIDENCE_VALID,
                )
            )
            or 0
        )


class RuntimeEnvironmentRepository(BaseRepository[VerificationRuntimeEnvironmentModel]):
    model = VerificationRuntimeEnvironmentModel

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[VerificationRuntimeEnvironmentModel]:
        filters = [VerificationRuntimeEnvironmentModel.project_id == project_id]
        if status is not None:
            filters.append(VerificationRuntimeEnvironmentModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def get_by_instance(
        self, runtime_instance_id: str
    ) -> VerificationRuntimeEnvironmentModel | None:
        return await self.session.scalar(
            select(VerificationRuntimeEnvironmentModel).where(
                VerificationRuntimeEnvironmentModel.runtime_instance_id == runtime_instance_id
            )
        )


class DebuggerErrorRepository(BaseRepository[VerificationDebuggerErrorModel]):
    model = VerificationDebuggerErrorModel

    async def get_by_fingerprint(
        self, project_id: str, fingerprint: str
    ) -> VerificationDebuggerErrorModel | None:
        return await self.session.scalar(
            select(VerificationDebuggerErrorModel).where(
                VerificationDebuggerErrorModel.project_id == project_id,
                VerificationDebuggerErrorModel.fingerprint == fingerprint,
            )
        )

    async def list_page(
        self,
        *,
        project_id: str,
        severity: str | None = None,
        status: str | None = None,
        is_baseline: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[VerificationDebuggerErrorModel]:
        filters = [VerificationDebuggerErrorModel.project_id == project_id]
        if severity is not None:
            filters.append(VerificationDebuggerErrorModel.severity == severity)
        if status is not None:
            filters.append(VerificationDebuggerErrorModel.status == status)
        if is_baseline is not None:
            filters.append(VerificationDebuggerErrorModel.is_baseline == is_baseline)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_for_gate(self, project_id: str) -> list[VerificationDebuggerErrorModel]:
        rows = await self.session.scalars(
            select(VerificationDebuggerErrorModel)
            .where(VerificationDebuggerErrorModel.project_id == project_id)
            .order_by(VerificationDebuggerErrorModel.first_seen_at)
        )
        return list(rows.all())


class DefectRepository(BaseRepository[VerificationDefectModel]):
    model = VerificationDefectModel

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[VerificationDefectModel]:
        filters = [VerificationDefectModel.project_id == project_id]
        if status is not None:
            filters.append(VerificationDefectModel.status == status)
        if severity is not None:
            filters.append(VerificationDefectModel.severity == severity)
        if category is not None:
            filters.append(VerificationDefectModel.category == category)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_all(self, project_id: str) -> list[VerificationDefectModel]:
        rows = await self.session.scalars(
            select(VerificationDefectModel)
            .where(VerificationDefectModel.project_id == project_id)
            .order_by(VerificationDefectModel.created_at)
        )
        return list(rows.all())

    async def get_by_source_result(
        self, project_id: str, source_result_id: str
    ) -> VerificationDefectModel | None:
        return await self.session.scalar(
            select(VerificationDefectModel)
            .where(
                VerificationDefectModel.project_id == project_id,
                VerificationDefectModel.source_result_id == source_result_id,
            )
            .order_by(VerificationDefectModel.created_at.desc())
        )


class RegressionPlanRepository(BaseRepository[VerificationRegressionPlanModel]):
    model = VerificationRegressionPlanModel

    async def list_page(
        self,
        *,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[VerificationRegressionPlanModel]:
        return await self.paginate(
            limit=limit,
            offset=offset,
            filters=[VerificationRegressionPlanModel.project_id == project_id],
        )


class QualityGatePolicyRepository(BaseRepository[QualityGatePolicyModel]):
    model = QualityGatePolicyModel

    async def list_for_project(self, project_id: str) -> list[QualityGatePolicyModel]:
        rows = await self.session.scalars(
            select(QualityGatePolicyModel)
            .where(QualityGatePolicyModel.project_id == project_id)
            .order_by(QualityGatePolicyModel.created_at)
        )
        return list(rows.all())


class QualityGateResultRepository(BaseRepository[QualityGateResultModel]):
    model = QualityGateResultModel

    async def list_for_campaign(self, campaign_id: str) -> list[QualityGateResultModel]:
        rows = await self.session.scalars(
            select(QualityGateResultModel)
            .where(QualityGateResultModel.campaign_id == campaign_id)
            .order_by(QualityGateResultModel.evaluated_at)
        )
        return list(rows.all())

    async def latest_for_campaign(self, campaign_id: str) -> list[QualityGateResultModel]:
        """返回每个门禁的最新一次评估结果。"""

        rows = await self.list_for_campaign(campaign_id)
        latest: dict[str, QualityGateResultModel] = {}
        for row in rows:
            latest[row.gate_name] = row
        return list(latest.values())


class QualityGateWaiverRepository(BaseRepository[QualityGateWaiverModel]):
    model = QualityGateWaiverModel

    async def active_for_gate(
        self, campaign_id: str, gate_name: str
    ) -> QualityGateWaiverModel | None:
        return await self.session.scalar(
            select(QualityGateWaiverModel)
            .where(
                QualityGateWaiverModel.campaign_id == campaign_id,
                QualityGateWaiverModel.gate_name == gate_name,
                QualityGateWaiverModel.revoked_at.is_(None),
            )
            .order_by(QualityGateWaiverModel.created_at.desc())
        )


class PhaseReviewRepository(BaseRepository[PhaseReviewModel]):
    model = PhaseReviewModel

    async def list_page(
        self,
        *,
        project_id: str,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[PhaseReviewModel]:
        filters = [PhaseReviewModel.project_id == project_id]
        if workflow_id is not None:
            filters.append(PhaseReviewModel.workflow_id == workflow_id)
        if phase_id is not None:
            filters.append(PhaseReviewModel.phase_id == phase_id)
        if status is not None:
            filters.append(PhaseReviewModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)


class PhaseReviewDecisionRepository(BaseRepository[PhaseReviewDecisionModel]):
    model = PhaseReviewDecisionModel

    async def list_for_review(self, review_id: str) -> list[PhaseReviewDecisionModel]:
        rows = await self.session.scalars(
            select(PhaseReviewDecisionModel)
            .where(PhaseReviewDecisionModel.review_id == review_id)
            .order_by(PhaseReviewDecisionModel.decided_at)
        )
        return list(rows.all())
