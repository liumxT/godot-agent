"""发布审批与审批绑定（E10-T12）。

规则：

- 审批必须绑定候选清单哈希、制品哈希与交付包哈希；
- 任一关键内容变化使原审批立即失效；
- 只有用户可批准，Agent 不得自行批准或修改审批结果；
- 审批结果写入发布证据。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import (
    NotFoundError,
    ReleaseApprovalMismatch,
    ReleaseApprovalRequired,
    ReleaseStateInvalid,
    ValidationFailed,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.models import (
    APPROVAL_APPROVED,
    APPROVAL_INVALIDATED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_STATUSES,
    APPROVAL_TRANSITIONS,
    DISTRIBUTION_CHANNELS,
    RC_READY_FOR_APPROVAL,
    ReleaseApprovalModel,
)
from modules.build_release.packaging import PackagingService
from modules.build_release.provenance import BuildProvenanceService
from modules.build_release.release_candidates import (
    ReleaseCandidateService,
    ReleaseCandidateView,
)
from modules.build_release.repository import ReleaseApprovalRepository
from modules.build_release.service import _new_id


@dataclass(frozen=True, slots=True)
class ReleaseApprovalView:
    approval_id: str
    project_id: str
    release_candidate_id: str
    artifact_hash: str
    package_hash: str
    manifest_hash: str
    target_platform: str
    distribution_channel: str
    release_version: str
    policy_version: str
    status: str
    requested_by: str | None
    approved_by: str | None
    requested_at: datetime
    approved_at: datetime | None
    invalidated_reason: str


def _approval_view(entity: ReleaseApprovalModel) -> ReleaseApprovalView:
    return ReleaseApprovalView(
        approval_id=entity.approval_id,
        project_id=entity.project_id,
        release_candidate_id=entity.release_candidate_id,
        artifact_hash=entity.artifact_hash,
        package_hash=entity.package_hash,
        manifest_hash=entity.manifest_hash,
        target_platform=entity.target_platform,
        distribution_channel=entity.distribution_channel,
        release_version=entity.release_version,
        policy_version=entity.policy_version,
        status=entity.status,
        requested_by=entity.requested_by,
        approved_by=entity.approved_by,
        requested_at=entity.requested_at,
        approved_at=entity.approved_at,
        invalidated_reason=entity.invalidated_reason,
    )


def _ensure_approval_transition(current: str, target: str) -> None:
    if target not in APPROVAL_TRANSITIONS.get(current, frozenset()):
        raise ReleaseStateInvalid("发布审批状态迁移非法", details={"from": current, "to": target})


class ReleaseApprovalService:
    """发布审批请求、批准与绑定校验。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        candidates: ReleaseCandidateService,
        artifacts: ArtifactRegistryService,
        packages: PackagingService,
        provenance: BuildProvenanceService | None = None,
    ) -> None:
        self._database = database
        self._candidates = candidates
        self._artifacts = artifacts
        self._packages = packages
        self._provenance = provenance

    async def request_approval(
        self,
        *,
        release_candidate_id: str,
        distribution_channel: str,
        policy_version: str = "",
        requested_by: str | None = None,
    ) -> ReleaseApprovalView:
        if distribution_channel not in DISTRIBUTION_CHANNELS:
            raise ValidationFailed("未知发布渠道", details={"channel": distribution_channel})
        candidate = await self._candidates.get_candidate(release_candidate_id)
        if candidate.status != RC_READY_FOR_APPROVAL:
            raise ReleaseStateInvalid(
                "发布候选尚未就绪，不能请求审批",
                details={"release_candidate_id": release_candidate_id, "status": candidate.status},
            )
        manifest = candidate.manifest
        binding = {
            "artifact_hash": str(manifest.get("artifact_content_hash", "")),
            "package_hash": str(manifest.get("package_hash") or ""),
            "manifest_hash": candidate.candidate_manifest_hash,
            "target_platform": str(manifest.get("platform", "")),
            "distribution_channel": distribution_channel,
            "release_version": candidate.version,
            "policy_version": policy_version,
        }
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repo = ReleaseApprovalRepository(session)
            for existing in await repo.list_for_candidate(release_candidate_id):
                if (
                    existing.status == APPROVAL_PENDING
                    and existing.distribution_channel == distribution_channel
                    and existing.manifest_hash == binding["manifest_hash"]
                ):
                    return _approval_view(existing)
            entity = ReleaseApprovalModel(
                approval_id=_new_id("apr"),
                project_id=candidate.project_id,
                release_candidate_id=release_candidate_id,
                artifact_hash=binding["artifact_hash"],
                package_hash=binding["package_hash"],
                manifest_hash=binding["manifest_hash"],
                target_platform=binding["target_platform"],
                distribution_channel=distribution_channel,
                release_version=binding["release_version"],
                policy_version=binding["policy_version"],
                status=APPROVAL_PENDING,
                requested_by=requested_by,
                requested_at=now,
                updated_at=now,
            )
            await repo.add(entity)
        return _approval_view(entity)

    async def approve(self, approval_id: str, *, approved_by: str) -> ReleaseApprovalView:
        if not approved_by:
            raise ReleaseApprovalRequired("必须指定审批人")
        approval = await self.get_approval(approval_id)
        if approval.status != APPROVAL_PENDING:
            raise ReleaseStateInvalid("当前审批状态不可批准", details={"status": approval.status})
        candidate = await self._candidates.get_candidate(approval.release_candidate_id)
        await self.assert_binding(approval, candidate)
        if candidate.status != RC_READY_FOR_APPROVAL:
            raise ReleaseStateInvalid(
                "发布候选状态已变化，不能批准",
                details={"status": candidate.status},
            )
        await self._transition(approval, APPROVAL_APPROVED, approved_by=approved_by)
        await self._candidates.mark_approved(approval.release_candidate_id)
        await self._record_evidence(approval, "approved", approved_by)
        return await self.get_approval(approval_id)

    async def reject(self, approval_id: str, *, rejected_by: str) -> ReleaseApprovalView:
        if not rejected_by:
            raise ReleaseApprovalRequired("必须指定审批人")
        approval = await self.get_approval(approval_id)
        if approval.status != APPROVAL_PENDING:
            raise ReleaseStateInvalid("当前审批状态不可驳回", details={"status": approval.status})
        await self._transition(approval, APPROVAL_REJECTED, approved_by=rejected_by)
        await self._record_evidence(approval, "rejected", rejected_by)
        return await self.get_approval(approval_id)

    async def invalidate(self, approval_id: str, *, reason: str = "") -> ReleaseApprovalView:
        await self.get_approval(approval_id)
        async with self._database.session() as session, transaction(session):
            entity = await ReleaseApprovalRepository(session).get(approval_id)
            assert entity is not None
            _ensure_approval_transition(entity.status, APPROVAL_INVALIDATED)
            entity.status = APPROVAL_INVALIDATED
            entity.invalidated_reason = reason
            entity.updated_at = utcnow()
            await session.flush()
        return await self.get_approval(approval_id)

    async def assert_binding(
        self,
        approval: ReleaseApprovalView,
        candidate: ReleaseCandidateView | None = None,
    ) -> None:
        current = candidate or await self._candidates.get_candidate(approval.release_candidate_id)
        problems: list[str] = []
        if current.candidate_manifest_hash != approval.manifest_hash:
            problems.append("候选清单已变化")
        if str(current.manifest.get("artifact_content_hash", "")) != approval.artifact_hash:
            problems.append("制品内容已变化")
        if str(current.manifest.get("package_hash") or "") != approval.package_hash:
            problems.append("交付包内容已变化")
        if problems:
            if approval.status == APPROVAL_APPROVED:
                await self.invalidate(approval.approval_id, reason="; ".join(problems))
            raise ReleaseApprovalMismatch(
                "审批绑定内容已失效，必须重新审批",
                details={"approval_id": approval.approval_id, "problems": problems},
            )

    async def require_approved(self, approval_id: str) -> ReleaseApprovalView:
        approval = await self.get_approval(approval_id)
        if approval.status != APPROVAL_APPROVED:
            raise ReleaseApprovalRequired(
                "尚未获得有效的发布审批",
                details={"approval_id": approval_id, "status": approval.status},
            )
        await self.assert_binding(approval)
        return approval

    async def get_approved_for_candidate(
        self, release_candidate_id: str
    ) -> ReleaseApprovalView | None:
        async with self._database.session() as session:
            entity = await ReleaseApprovalRepository(session).find_approved(release_candidate_id)
        return _approval_view(entity) if entity is not None else None

    async def get_approval(self, approval_id: str) -> ReleaseApprovalView:
        async with self._database.session() as session:
            entity = await ReleaseApprovalRepository(session).get(approval_id)
        if entity is None:
            raise NotFoundError("发布审批不存在", details={"approval_id": approval_id})
        return _approval_view(entity)

    async def list_approvals(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in APPROVAL_STATUSES:
            raise ValidationFailed("未知审批状态", details={"status": status})
        async with self._database.session() as session:
            page = await ReleaseApprovalRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_approval_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def list_for_candidate(self, release_candidate_id: str) -> list[ReleaseApprovalView]:
        async with self._database.session() as session:
            rows = await ReleaseApprovalRepository(session).list_for_candidate(release_candidate_id)
        return [_approval_view(row) for row in rows]

    # ---- 内部实现 ----

    async def _transition(
        self,
        approval: ReleaseApprovalView,
        target: str,
        *,
        approved_by: str | None = None,
    ) -> None:
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            entity = await ReleaseApprovalRepository(session).get(approval.approval_id)
            if entity is None:
                raise NotFoundError("发布审批不存在", details={"approval_id": approval.approval_id})
            _ensure_approval_transition(entity.status, target)
            entity.status = target
            if target == APPROVAL_APPROVED or target == APPROVAL_REJECTED:
                entity.approved_by = approved_by
                entity.approved_at = now
            entity.updated_at = now
            await session.flush()

    async def _record_evidence(
        self, approval: ReleaseApprovalView, result: str, actor: str
    ) -> None:
        if self._provenance is None:
            return
        await self._provenance.add_evidence(
            project_id=approval.project_id,
            evidence_type="approval",
            release_candidate_id=approval.release_candidate_id,
            reference=approval.approval_id,
            details={
                "result": result,
                "approved_by": actor,
                "artifact_hash": approval.artifact_hash,
                "package_hash": approval.package_hash,
                "manifest_hash": approval.manifest_hash,
                "distribution_channel": approval.distribution_channel,
            },
        )
