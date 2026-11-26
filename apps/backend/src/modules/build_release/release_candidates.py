"""发布候选管理（E10-T11）。

候选把制品、交付包与验证活动绑定为不可变清单，验证通过后进入
READY_FOR_APPROVAL，供 T12 发布审批使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import (
    NotFoundError,
    ReleaseCandidateInvalid,
    ReleaseStateInvalid,
    ValidationFailed,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.models import (
    ARTIFACT_VERIFIED,
    PACKAGE_VERIFIED,
    RC_APPROVED,
    RC_DRAFT,
    RC_INVALIDATED,
    RC_READY_FOR_APPROVAL,
    RC_REJECTED,
    RC_SUPERSEDED,
    RC_TRANSITIONS,
    RC_VALIDATING,
    ReleaseCandidateModel,
)
from modules.build_release.packaging import PackagingService
from modules.build_release.repository import (
    ReleaseCandidateRepository,
    ReleaseEvidenceRepository,
    SmokeTestResultRepository,
)
from modules.build_release.service import _dump, _hash_payload, _load, _new_id


def _ensure_rc_transition(current: str, target: str) -> None:
    if target not in RC_TRANSITIONS.get(current, frozenset()):
        raise ReleaseStateInvalid("发布候选状态迁移非法", details={"from": current, "to": target})


@dataclass(frozen=True, slots=True)
class ReleaseCandidateView:
    release_candidate_id: str
    project_id: str
    version: str
    artifact_id: str
    package_id: str | None
    verification_campaign_id: str | None
    candidate_manifest_hash: str
    status: str
    created_by: str | None
    superseded_by: str | None
    created_at: datetime
    updated_at: datetime
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CandidateValidationView:
    release_candidate_id: str
    ready: bool
    status: str
    problems: list[str]


def _candidate_view(entity: ReleaseCandidateModel) -> ReleaseCandidateView:
    return ReleaseCandidateView(
        release_candidate_id=entity.release_candidate_id,
        project_id=entity.project_id,
        version=entity.version,
        artifact_id=entity.artifact_id,
        package_id=entity.package_id,
        verification_campaign_id=entity.verification_campaign_id,
        candidate_manifest_hash=entity.candidate_manifest_hash,
        status=entity.status,
        created_by=entity.created_by,
        superseded_by=entity.superseded_by,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        manifest=_load(entity.candidate_manifest_json, {}),
    )


class ReleaseCandidateService:
    """发布候选创建与校验。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        artifacts: ArtifactRegistryService,
        packages: PackagingService,
    ) -> None:
        self._database = database
        self._artifacts = artifacts
        self._packages = packages

    async def create_candidate(
        self,
        *,
        project_id: str,
        version: str,
        artifact_id: str,
        package_id: str | None = None,
        verification_campaign_id: str | None = None,
        created_by: str | None = None,
    ) -> ReleaseCandidateView:
        if not version.strip():
            raise ValidationFailed("发布候选版本号不能为空")
        artifact = await self._artifacts.get_artifact(artifact_id)
        if artifact.project_id != project_id:
            raise ReleaseCandidateInvalid("制品不属于该项目", details={"artifact_id": artifact_id})
        if artifact.verification_status != ARTIFACT_VERIFIED:
            raise ReleaseCandidateInvalid(
                "制品未通过验证，不能创建发布候选",
                details={"artifact_id": artifact_id, "status": artifact.verification_status},
            )
        package = None
        if package_id:
            package = await self._packages.get_package(package_id)
            if package.project_id != project_id:
                raise ReleaseCandidateInvalid(
                    "交付包不属于该项目", details={"package_id": package_id}
                )
            if package.status != PACKAGE_VERIFIED:
                raise ReleaseCandidateInvalid(
                    "交付包未通过校验，不能创建发布候选",
                    details={"package_id": package_id, "status": package.status},
                )
            if package.artifact_id != artifact_id:
                raise ReleaseCandidateInvalid(
                    "交付包与制品不匹配", details={"package_id": package_id}
                )

        manifest = {
            "project_id": project_id,
            "version": version,
            "artifact_id": artifact.artifact_id,
            "artifact_version": artifact.artifact_version,
            "artifact_content_hash": artifact.content_hash,
            "platform": artifact.platform,
            "architecture": artifact.architecture,
            "package_id": package.package_id if package else None,
            "package_manifest_hash": package.manifest_hash if package else None,
            "package_hash": package.package_hash if package else None,
            "verification_campaign_id": verification_campaign_id,
        }
        manifest_hash = _hash_payload(manifest)
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repo = ReleaseCandidateRepository(session)
            for existing in await repo.list_by_version(project_id, version):
                if (
                    existing.candidate_manifest_hash == manifest_hash
                    and existing.status != RC_SUPERSEDED
                ):
                    return _candidate_view(existing)
            entity = ReleaseCandidateModel(
                release_candidate_id=_new_id("rc"),
                project_id=project_id,
                version=version,
                artifact_id=artifact_id,
                package_id=package_id,
                verification_campaign_id=verification_campaign_id,
                candidate_manifest_json=_dump(manifest),
                candidate_manifest_hash=manifest_hash,
                status=RC_DRAFT,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            await repo.add(entity)
        return _candidate_view(entity)

    async def get_candidate(self, release_candidate_id: str) -> ReleaseCandidateView:
        async with self._database.session() as session:
            entity = await ReleaseCandidateRepository(session).get(release_candidate_id)
        if entity is None:
            raise NotFoundError(
                "发布候选不存在", details={"release_candidate_id": release_candidate_id}
            )
        return _candidate_view(entity)

    async def list_candidates(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await ReleaseCandidateRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_candidate_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def validate_candidate(self, release_candidate_id: str) -> CandidateValidationView:
        candidate = await self.get_candidate(release_candidate_id)
        if candidate.status not in {RC_DRAFT, RC_VALIDATING}:
            raise ReleaseStateInvalid(
                "当前候选状态不可校验",
                details={"release_candidate_id": release_candidate_id, "status": candidate.status},
            )
        if candidate.status == RC_DRAFT:
            await self._transition(candidate, RC_VALIDATING)

        problems = await self._collect_problems(candidate)
        target = RC_READY_FOR_APPROVAL if not problems else RC_REJECTED
        updated = await self._transition(candidate, target)
        return CandidateValidationView(
            release_candidate_id=release_candidate_id,
            ready=not problems,
            status=updated.status,
            problems=problems,
        )

    async def reject_candidate(self, release_candidate_id: str) -> ReleaseCandidateView:
        candidate = await self.get_candidate(release_candidate_id)
        return await self._transition(candidate, RC_REJECTED)

    async def mark_approved(self, release_candidate_id: str) -> ReleaseCandidateView:
        candidate = await self.get_candidate(release_candidate_id)
        if candidate.status == RC_APPROVED:
            return candidate
        return await self._transition(candidate, RC_APPROVED)

    async def supersede_candidate(
        self, release_candidate_id: str, *, superseded_by: str | None = None
    ) -> ReleaseCandidateView:
        candidate = await self.get_candidate(release_candidate_id)
        if superseded_by:
            async with self._database.session() as session, transaction(session):
                entity = await ReleaseCandidateRepository(session).get(release_candidate_id)
                assert entity is not None
                _ensure_rc_transition(entity.status, RC_SUPERSEDED)
                entity.status = RC_SUPERSEDED
                entity.superseded_by = superseded_by
                entity.updated_at = utcnow()
                await session.flush()
            return await self.get_candidate(release_candidate_id)
        return await self._transition(candidate, RC_SUPERSEDED)

    async def invalidate_candidate(self, release_candidate_id: str) -> ReleaseCandidateView:
        candidate = await self.get_candidate(release_candidate_id)
        if candidate.status == RC_APPROVED:
            raise ReleaseStateInvalid(
                "已批准候选不可直接失效，请创建新的候选版本",
                details={"release_candidate_id": release_candidate_id},
            )
        return await self._transition(candidate, RC_INVALIDATED)

    async def require_ready(self, release_candidate_id: str) -> ReleaseCandidateView:
        candidate = await self.get_candidate(release_candidate_id)
        if candidate.status != RC_READY_FOR_APPROVAL:
            raise ReleaseStateInvalid(
                "发布候选尚未就绪",
                details={"release_candidate_id": release_candidate_id, "status": candidate.status},
            )
        return candidate

    # ---- 内部实现 ----

    async def _transition(
        self, candidate: ReleaseCandidateView, target: str
    ) -> ReleaseCandidateView:
        async with self._database.session() as session, transaction(session):
            entity = await ReleaseCandidateRepository(session).get(candidate.release_candidate_id)
            if entity is None:
                raise NotFoundError(
                    "发布候选不存在",
                    details={"release_candidate_id": candidate.release_candidate_id},
                )
            _ensure_rc_transition(entity.status, target)
            entity.status = target
            entity.updated_at = utcnow()
            await session.flush()
        return await self.get_candidate(candidate.release_candidate_id)

    async def _collect_problems(self, candidate: ReleaseCandidateView) -> list[str]:
        problems: list[str] = []
        manifest = candidate.manifest
        if _hash_payload(manifest) != candidate.candidate_manifest_hash:
            problems.append("候选清单哈希与内容不一致")
        artifact = await self._artifacts.get_artifact(candidate.artifact_id)
        if artifact.verification_status != ARTIFACT_VERIFIED:
            problems.append(f"制品未通过验证: {artifact.verification_status}")
        if manifest.get("artifact_content_hash") != artifact.content_hash:
            problems.append("制品内容已变化，候选清单失效")
        if candidate.package_id:
            package = await self._packages.get_package(candidate.package_id)
            if package.status != PACKAGE_VERIFIED:
                problems.append(f"交付包未通过校验: {package.status}")
            if package.manifest.get("artifact_content_hash") != artifact.content_hash:
                problems.append("交付包绑定的制品内容已变化")
        async with self._database.session() as session:
            if not await SmokeTestResultRepository(session).has_passed_for_artifact(
                candidate.artifact_id
            ):
                problems.append("缺少通过的冒烟测试记录")
            if candidate.verification_campaign_id:
                evidence = await ReleaseEvidenceRepository(session).find_by_reference(
                    candidate.project_id, "verification", candidate.verification_campaign_id
                )
                if evidence is None:
                    problems.append(f"缺少验证活动证据: {candidate.verification_campaign_id}")
        return problems
