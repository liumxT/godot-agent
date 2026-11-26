"""发布生命周期管理（E10-T15）。

规则：

- 发布前必须先获得有效审批，审批绑定内容变化即失效；
- 本地交付与线上发布严格区分；
- 分发必须幂等，重复请求返回既有操作状态；
- 结果不明确进入 UNKNOWN，禁止仅凭客户端超时重复发布；
- 回滚只在本渠道能力范围内执行，不伪造历史。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.errors import (
    DistributionInvalid,
    NotFoundError,
    ReleaseApprovalMismatch,
    ReleaseCandidateInvalid,
    ReleaseStateInvalid,
    ValidationFailed,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.distribution import (
    DistributionAdapterRegistry,
    build_default_registry,
)
from modules.build_release.models import (
    ARTIFACT_VERIFIED,
    CHANNEL_LOCAL,
    CHANNEL_LOCAL_EXPORT,
    CHANNEL_USER_DOWNLOAD,
    CHANNEL_USER_OUTPUT_DIR,
    DIST_FAILED,
    DIST_PENDING,
    DIST_SUCCEEDED,
    DISTRIBUTION_CHANNELS,
    RC_APPROVED,
    RELEASE_AUTHORIZED,
    RELEASE_COMPLETED,
    RELEASE_DISTRIBUTING,
    RELEASE_FAILED,
    RELEASE_PENDING,
    RELEASE_POST_VERIFYING,
    RELEASE_PUBLISHED,
    RELEASE_ROLLED_BACK,
    RELEASE_STATUSES,
    RELEASE_TRANSITIONS,
    RELEASE_UNKNOWN,
    RELEASE_WITHDRAWN,
    DistributionOperationModel,
    ReleaseModel,
)
from modules.build_release.packaging import PackagingService
from modules.build_release.provenance import BuildProvenanceService
from modules.build_release.release_approvals import ReleaseApprovalService
from modules.build_release.release_candidates import ReleaseCandidateService
from modules.build_release.repository import (
    DistributionOperationRepository,
    ReleaseRepository,
)
from modules.build_release.service import _dump, _load, _new_id

_LOCAL_CHANNELS = frozenset(
    {CHANNEL_LOCAL, CHANNEL_LOCAL_EXPORT, CHANNEL_USER_DOWNLOAD, CHANNEL_USER_OUTPUT_DIR}
)
_TERMINAL_RELEASE_STATUSES = frozenset({RELEASE_FAILED, RELEASE_WITHDRAWN, RELEASE_ROLLED_BACK})


@dataclass(frozen=True, slots=True)
class ReleaseView:
    release_id: str
    project_id: str
    release_candidate_id: str
    approval_id: str
    channel: str
    version: str
    status: str
    approved_by: str | None
    distribution_reference: str
    external_operation_id: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DistributionOperationView:
    operation_id: str
    project_id: str
    release_id: str | None
    channel: str
    operation_status: str
    idempotency_key: str
    external_operation_id: str | None
    target_reference: str
    details: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None


def _release_view(entity: ReleaseModel) -> ReleaseView:
    return ReleaseView(
        release_id=entity.release_id,
        project_id=entity.project_id,
        release_candidate_id=entity.release_candidate_id,
        approval_id=entity.approval_id,
        channel=entity.channel,
        version=entity.version,
        status=entity.status,
        approved_by=entity.approved_by,
        distribution_reference=entity.distribution_reference,
        external_operation_id=entity.external_operation_id,
        published_at=entity.published_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _operation_view(entity: DistributionOperationModel) -> DistributionOperationView:
    return DistributionOperationView(
        operation_id=entity.operation_id,
        project_id=entity.project_id,
        release_id=entity.release_id,
        channel=entity.channel,
        operation_status=entity.operation_status,
        idempotency_key=entity.idempotency_key,
        external_operation_id=entity.external_operation_id,
        target_reference=entity.target_reference,
        details=_load(entity.details_json, {}),
        started_at=entity.started_at,
        completed_at=entity.completed_at,
    )


def _ensure_release_transition(current: str, target: str) -> None:
    if target not in RELEASE_TRANSITIONS.get(current, frozenset()):
        raise ReleaseStateInvalid("发布状态迁移非法", details={"from": current, "to": target})


class ReleaseManagerService:
    """发布创建、授权、分发、验证与撤回。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        approvals: ReleaseApprovalService,
        candidates: ReleaseCandidateService,
        artifacts: ArtifactRegistryService,
        packages: PackagingService,
        registry: DistributionAdapterRegistry | None = None,
        projects: Any = None,
        provenance: BuildProvenanceService | None = None,
    ) -> None:
        self._database = database
        self._approvals = approvals
        self._candidates = candidates
        self._artifacts = artifacts
        self._packages = packages
        self._registry = registry or build_default_registry()
        self._projects = projects
        self._provenance = provenance

    async def create_release(
        self,
        *,
        release_candidate_id: str,
        approval_id: str,
        channel: str,
        created_by: str | None = None,
    ) -> ReleaseView:
        if channel not in DISTRIBUTION_CHANNELS:
            raise DistributionInvalid("未知发布渠道", details={"channel": channel})
        candidate = await self._candidates.get_candidate(release_candidate_id)
        approval = await self._approvals.get_approval(approval_id)
        if approval.release_candidate_id != release_candidate_id:
            raise ReleaseApprovalMismatch("审批不属于该发布候选")
        if approval.distribution_channel != channel:
            raise ReleaseApprovalMismatch(
                "发布渠道与审批绑定渠道不一致",
                details={
                    "approval_channel": approval.distribution_channel,
                    "channel": channel,
                },
            )
        await self._approvals.require_approved(approval_id)
        if candidate.status != RC_APPROVED:
            raise ReleaseCandidateInvalid("发布候选未获批准", details={"status": candidate.status})

        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repo = ReleaseRepository(session)
            for existing in await repo.list_for_candidate(release_candidate_id):
                if (
                    existing.approval_id == approval_id
                    and existing.channel == channel
                    and existing.status not in _TERMINAL_RELEASE_STATUSES
                ):
                    return _release_view(existing)
            entity = ReleaseModel(
                release_id=_new_id("rel"),
                project_id=candidate.project_id,
                release_candidate_id=release_candidate_id,
                approval_id=approval_id,
                channel=channel,
                version=candidate.version,
                status=RELEASE_PENDING,
                approved_by=approval.approved_by,
                created_at=now,
                updated_at=now,
            )
            await repo.add(entity)
        return _release_view(entity)

    async def authorize_release(self, release_id: str) -> ReleaseView:
        release = await self.get_release(release_id)
        await self._approvals.require_approved(release.approval_id)
        return await self._transition(release, RELEASE_AUTHORIZED)

    async def start_release(
        self,
        release_id: str,
        *,
        target_reference: str = "",
        idempotency_key: str | None = None,
    ) -> ReleaseView:
        release = await self.get_release(release_id)
        if not target_reference:
            raise DistributionInvalid("本地交付必须指定目标位置")
        key = idempotency_key or f"{release_id}:{release.channel}:{target_reference}"
        async with self._database.session() as session:
            existing = await DistributionOperationRepository(session).find_by_idempotency_key(key)
        if existing is not None:
            if existing.release_id != release_id:
                raise DistributionInvalid(
                    "幂等键已被其他发布占用", details={"idempotency_key": key}
                )
            return release
        if release.status != RELEASE_AUTHORIZED:
            raise ReleaseStateInvalid(
                "发布未授权，禁止开始分发",
                details={"release_id": release_id, "status": release.status},
            )
        candidate = await self._candidates.get_candidate(release.release_candidate_id)
        artifact = await self._artifacts.get_artifact(candidate.artifact_id)
        if artifact.verification_status != ARTIFACT_VERIFIED:
            raise ReleaseCandidateInvalid(
                "制品未通过验证，禁止发布",
                details={"artifact_id": artifact.artifact_id},
            )
        if candidate.package_id:
            await self._packages.require_verified(candidate.package_id)

        adapter = self._registry.get(release.channel)
        await adapter.prepare_distribution(target_reference=target_reference)

        source_path = await self._resolve_source(release.project_id, candidate)
        await self._transition(release, RELEASE_DISTRIBUTING)
        operation = await self._create_operation(
            release=release,
            channel=release.channel,
            idempotency_key=key,
            target_reference=target_reference,
        )
        result = await adapter.submit_release(
            source_path=source_path,
            target_reference=target_reference,
            version=release.version,
        )
        await self._finalize_operation(operation.operation_id, result)
        if result.status == DIST_SUCCEEDED:
            current = await self.get_release(release_id)
            current = await self._transition(current, RELEASE_PUBLISHED)
            await self._set_distribution_reference(
                release_id,
                reference=result.reference,
                external_operation_id=result.external_operation_id or None,
            )
            current = await self.get_release(release_id)
            await self._record_evidence(current, "published", result)
            return current
        if result.status == DIST_FAILED:
            return await self._transition(await self.get_release(release_id), RELEASE_FAILED)
        return await self._transition(await self.get_release(release_id), RELEASE_UNKNOWN)

    async def verify_release(self, release_id: str) -> ReleaseView:
        release = await self.get_release(release_id)
        if release.status != RELEASE_PUBLISHED:
            raise ReleaseStateInvalid(
                "只有已发布的版本可以执行发布后验证",
                details={"status": release.status},
            )
        current = await self._transition(release, RELEASE_POST_VERIFYING)
        adapter = self._registry.get(current.channel)
        operation = await self._latest_succeeded_operation(release_id)
        if operation is None:
            return await self._transition(current, RELEASE_FAILED)
        ok = await adapter.verify_distribution(
            reference=operation.target_reference,
            expected_digest=str(operation.details.get("digest", "")),
        )
        target = RELEASE_COMPLETED if ok else RELEASE_FAILED
        current = await self._transition(current, target)
        await self._record_evidence(current, "verified" if ok else "verify_failed", None)
        return current

    async def withdraw_release(self, release_id: str) -> ReleaseView:
        release = await self.get_release(release_id)
        operation = await self._latest_succeeded_operation(release_id)
        if operation is not None:
            adapter = self._registry.get(release.channel)
            result = await adapter.withdraw_release(reference=operation.target_reference)
            if result.status != DIST_SUCCEEDED:
                raise DistributionInvalid("撤回交付失败", details={"detail": result.detail})
        current = await self._transition(release, RELEASE_WITHDRAWN)
        await self._record_evidence(current, "withdrawn", None)
        return current

    async def rollback_release(self, release_id: str) -> ReleaseView:
        release = await self.get_release(release_id)
        if release.status != RELEASE_COMPLETED:
            raise ReleaseStateInvalid(
                "只有已完成的本地发布可以标记回滚",
                details={"status": release.status},
            )
        if release.channel not in _LOCAL_CHANNELS:
            raise DistributionInvalid("线上渠道回滚需要真实渠道接口")
        return await self._transition(release, RELEASE_ROLLED_BACK)

    async def reconcile_release(
        self,
        release_id: str,
        *,
        status: str,
        external_operation_id: str = "",
    ) -> ReleaseView:
        if status not in RELEASE_STATUSES:
            raise ValidationFailed("未知发布状态", details={"status": status})
        release = await self.get_release(release_id)
        if release.status != RELEASE_UNKNOWN:
            raise ReleaseStateInvalid(
                "只有 UNKNOWN 的发布需要核对", details={"status": release.status}
            )
        reconciled = await self._transition(release, status)
        if external_operation_id:
            await self._set_distribution_reference(
                release_id,
                reference=reconciled.distribution_reference,
                external_operation_id=external_operation_id,
            )
            reconciled = await self.get_release(release_id)
        return reconciled

    async def get_release(self, release_id: str) -> ReleaseView:
        async with self._database.session() as session:
            entity = await ReleaseRepository(session).get(release_id)
        if entity is None:
            raise NotFoundError("发布不存在", details={"release_id": release_id})
        return _release_view(entity)

    async def list_releases(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in RELEASE_STATUSES:
            raise ValidationFailed("未知发布状态", details={"status": status})
        async with self._database.session() as session:
            page = await ReleaseRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_release_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def list_operations(self, release_id: str) -> list[DistributionOperationView]:
        async with self._database.session() as session:
            rows = await DistributionOperationRepository(session).list_for_release(release_id)
        return [_operation_view(row) for row in rows]

    # ---- 内部实现 ----

    async def _transition(self, release: ReleaseView, target: str) -> ReleaseView:
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            entity = await ReleaseRepository(session).get(release.release_id)
            if entity is None:
                raise NotFoundError("发布不存在", details={"release_id": release.release_id})
            _ensure_release_transition(entity.status, target)
            entity.status = target
            if target == RELEASE_PUBLISHED:
                entity.published_at = now
            entity.updated_at = now
            await session.flush()
        return await self.get_release(release.release_id)

    async def _resolve_source(self, project_id: str, candidate: Any) -> Path:
        artifact = await self._artifacts.get_artifact(candidate.artifact_id)
        reference = artifact.storage_reference
        if candidate.package_id:
            package = await self._packages.get_package(candidate.package_id)
            reference = package.storage_reference or reference
        path = Path(reference)
        if not path.is_absolute():
            if self._projects is None:
                raise DistributionInvalid(
                    "无法解析交付源路径", details={"storage_reference": reference}
                )
            view = await self._projects.get(project_id)
            root = getattr(view, "project_root", "")
            if not root:
                raise DistributionInvalid("项目路径缺失", details={"project_id": project_id})
            path = Path(root) / reference
        if not path.exists():
            raise DistributionInvalid("交付源文件不存在", details={"path": str(path)})
        return path

    async def _create_operation(
        self,
        *,
        release: ReleaseView,
        channel: str,
        idempotency_key: str,
        target_reference: str,
    ) -> DistributionOperationView:
        now = utcnow()
        entity = DistributionOperationModel(
            operation_id=_new_id("dop"),
            project_id=release.project_id,
            release_id=release.release_id,
            channel=channel,
            operation_status=DIST_PENDING,
            idempotency_key=idempotency_key,
            target_reference=target_reference,
            started_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await DistributionOperationRepository(session).add(entity)
        return _operation_view(entity)

    async def _finalize_operation(
        self, operation_id: str, result: Any
    ) -> DistributionOperationView:
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            entity = await DistributionOperationRepository(session).get(operation_id)
            if entity is None:
                raise NotFoundError("分发操作不存在", details={"operation_id": operation_id})
            entity.operation_status = result.status
            entity.target_reference = result.reference or entity.target_reference
            entity.external_operation_id = result.external_operation_id or None
            entity.details_json = _dump({"digest": result.digest, "detail": result.detail})
            entity.completed_at = now
            await session.flush()
        return _operation_view(entity)

    async def _set_distribution_reference(
        self, release_id: str, *, reference: str, external_operation_id: str | None
    ) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await ReleaseRepository(session).get(release_id)
            if entity is None:
                raise NotFoundError("发布不存在", details={"release_id": release_id})
            entity.distribution_reference = reference
            entity.external_operation_id = external_operation_id
            entity.updated_at = utcnow()
            await session.flush()

    async def _latest_succeeded_operation(
        self, release_id: str
    ) -> DistributionOperationView | None:
        operations = await self.list_operations(release_id)
        for operation in reversed(operations):
            if operation.operation_status == DIST_SUCCEEDED:
                return operation
        return None

    async def _record_evidence(self, release: ReleaseView, result: str, detail: Any) -> None:
        if self._provenance is None:
            return
        await self._provenance.add_evidence(
            project_id=release.project_id,
            evidence_type="distribution",
            release_candidate_id=release.release_candidate_id,
            reference=release.release_id,
            details={
                "result": result,
                "channel": release.channel,
                "version": release.version,
                "distribution_reference": release.distribution_reference,
                "digest": getattr(detail, "digest", ""),
            },
        )
