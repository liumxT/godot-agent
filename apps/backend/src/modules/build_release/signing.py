"""签名配置与签名执行（E10-T10）。

安全约束：

- 数据库只保存证书/凭证引用，绝不保存密钥本体；
- 凭证引用中出现疑似明文密钥时直接拒绝；
- 签名失败不得覆盖原制品；
- 签名结果不明确时进入 UNKNOWN，必须核对后再收敛；
- 签名尝试与验证结果都写入发布证据。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from core.errors import NotFoundError, SigningInvalid, SigningUnknown, ValidationFailed
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.artifacts import ArtifactRegistryService, ArtifactView
from modules.build_release.models import (
    ARTIFACT_VERIFIED,
    SIGNING_ACTIVE,
    SIGNING_ATTEMPT_TRANSITIONS,
    SIGNING_DISABLED,
    SIGNING_EXPIRED,
    SIGNING_FAILED,
    SIGNING_PENDING,
    SIGNING_PROFILE_STATUSES,
    SIGNING_SUCCEEDED,
    SIGNING_UNKNOWN,
    SigningAttemptModel,
    SigningProfileModel,
)
from modules.build_release.provenance import BuildProvenanceService
from modules.build_release.repository import (
    SigningAttemptRepository,
    SigningProfileRepository,
)
from modules.build_release.service import _detect_secret, _dump, _load, _new_id


@dataclass(frozen=True, slots=True)
class SigningProfileView:
    signing_profile_id: str
    project_id: str
    platform: str
    signing_method: str
    certificate_reference: str
    credential_reference: str
    allowed_channels: tuple[str, ...]
    expiration: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SigningAttemptView:
    signing_attempt_id: str
    project_id: str
    signing_profile_id: str
    artifact_id: str
    artifact_hash: str
    tool_version: str
    certificate_fingerprint: str
    signature_reference: str
    status: str
    verified: bool
    error_detail: str
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class SigningOutcome:
    status: str
    tool_version: str = ""
    certificate_fingerprint: str = ""
    signature_reference: str = ""
    verified: bool = False
    detail: str = ""


class SigningAdapter(Protocol):
    async def sign(
        self, *, profile: SigningProfileView, artifact: ArtifactView
    ) -> SigningOutcome: ...


class NullSigningAdapter:
    """未配置真实签名工具时的安全默认：结果不明确，绝不伪造成成功。"""

    async def sign(self, *, profile: SigningProfileView, artifact: ArtifactView) -> SigningOutcome:
        return SigningOutcome(
            status=SIGNING_UNKNOWN,
            detail="未配置签名工具，签名结果不明确",
        )


def _profile_view(entity: SigningProfileModel) -> SigningProfileView:
    return SigningProfileView(
        signing_profile_id=entity.signing_profile_id,
        project_id=entity.project_id,
        platform=entity.platform,
        signing_method=entity.signing_method,
        certificate_reference=entity.certificate_reference,
        credential_reference=entity.credential_reference,
        allowed_channels=tuple(_load(entity.allowed_channels_json, [])),
        expiration=entity.expiration,
        status=entity.status,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _attempt_view(entity: SigningAttemptModel) -> SigningAttemptView:
    return SigningAttemptView(
        signing_attempt_id=entity.signing_attempt_id,
        project_id=entity.project_id,
        signing_profile_id=entity.signing_profile_id,
        artifact_id=entity.artifact_id,
        artifact_hash=entity.artifact_hash,
        tool_version=entity.tool_version,
        certificate_fingerprint=entity.certificate_fingerprint,
        signature_reference=entity.signature_reference,
        status=entity.status,
        verified=entity.verified,
        error_detail=entity.error_detail,
        created_at=entity.created_at,
        completed_at=entity.completed_at,
    )


class SigningService:
    """签名配置注册与签名执行。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        artifacts: ArtifactRegistryService,
        provenance: BuildProvenanceService | None = None,
    ) -> None:
        self._database = database
        self._artifacts = artifacts
        self._provenance = provenance

    async def register_profile(
        self,
        *,
        project_id: str,
        platform: str,
        signing_method: str,
        certificate_reference: str = "",
        credential_reference: str = "",
        allowed_channels: list[str] | None = None,
        expiration: datetime | None = None,
    ) -> SigningProfileView:
        if not platform or not signing_method:
            raise ValidationFailed("签名配置必须指定平台与签名方式")
        for reference in (certificate_reference, credential_reference):
            if _detect_secret(reference):
                raise SigningInvalid("签名配置不能包含明文密钥，只能保存引用")
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repo = SigningProfileRepository(session)
            existing = await repo.get_for_scope(project_id, platform, signing_method)
            if existing is not None:
                if existing.status == SIGNING_DISABLED:
                    raise SigningInvalid(
                        "签名配置已禁用，需先创建新的配置",
                        details={"signing_profile_id": existing.signing_profile_id},
                    )
                existing.certificate_reference = certificate_reference
                existing.credential_reference = credential_reference
                existing.allowed_channels_json = _dump(list(allowed_channels or []))
                existing.expiration = expiration
                existing.status = SIGNING_ACTIVE
                existing.updated_at = now
                await session.flush()
                return _profile_view(existing)
            entity = SigningProfileModel(
                signing_profile_id=_new_id("sgn"),
                project_id=project_id,
                platform=platform,
                signing_method=signing_method,
                certificate_reference=certificate_reference,
                credential_reference=credential_reference,
                allowed_channels_json=_dump(list(allowed_channels or [])),
                expiration=expiration,
                status=SIGNING_ACTIVE,
                created_at=now,
                updated_at=now,
            )
            await repo.add(entity)
        return _profile_view(entity)

    async def get_profile(self, signing_profile_id: str) -> SigningProfileView:
        async with self._database.session() as session:
            entity = await SigningProfileRepository(session).get(signing_profile_id)
        if entity is None:
            raise NotFoundError(
                "签名配置不存在", details={"signing_profile_id": signing_profile_id}
            )
        return _profile_view(entity)

    async def list_profiles(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in SIGNING_PROFILE_STATUSES:
            raise ValidationFailed("未知签名配置状态", details={"status": status})
        async with self._database.session() as session:
            page = await SigningProfileRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_profile_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def disable_profile(self, signing_profile_id: str) -> SigningProfileView:
        async with self._database.session() as session, transaction(session):
            entity = await SigningProfileRepository(session).get(signing_profile_id)
            if entity is None:
                raise NotFoundError(
                    "签名配置不存在", details={"signing_profile_id": signing_profile_id}
                )
            entity.status = SIGNING_DISABLED
            entity.updated_at = utcnow()
            await session.flush()
        return await self.get_profile(signing_profile_id)

    async def sign_artifact(
        self,
        *,
        artifact_id: str,
        signing_profile_id: str,
        adapter: SigningAdapter | None = None,
    ) -> SigningAttemptView:
        profile = await self.get_profile(signing_profile_id)
        if profile.status != SIGNING_ACTIVE:
            raise SigningInvalid(
                "签名配置不可用",
                details={"signing_profile_id": signing_profile_id, "status": profile.status},
            )
        if profile.expiration is not None and profile.expiration <= utcnow():
            await self._mark_expired(signing_profile_id)
            raise SigningInvalid(
                "签名配置已过期", details={"signing_profile_id": signing_profile_id}
            )
        artifact = await self._artifacts.get_artifact(artifact_id)
        if artifact.project_id != profile.project_id:
            raise SigningInvalid("签名配置与制品不属于同一项目")
        if artifact.platform != profile.platform:
            raise SigningInvalid(
                "签名配置平台与制品平台不一致",
                details={
                    "profile_platform": profile.platform,
                    "artifact_platform": artifact.platform,
                },
            )
        if artifact.verification_status != ARTIFACT_VERIFIED:
            raise SigningInvalid(
                "制品未通过验证，禁止签名",
                details={"artifact_id": artifact_id, "status": artifact.verification_status},
            )

        async with self._database.session() as session:
            attempts = await SigningAttemptRepository(session).list_for_artifact(artifact_id)
        for attempt in attempts:
            if attempt.signing_profile_id != signing_profile_id:
                continue
            if attempt.status == SIGNING_UNKNOWN:
                raise SigningUnknown(
                    "存在结果不明确的签名尝试，必须先核对",
                    details={"signing_attempt_id": attempt.signing_attempt_id},
                )
            if attempt.status == SIGNING_SUCCEEDED and attempt.verified:
                return _attempt_view(attempt)

        now = utcnow()
        entity = SigningAttemptModel(
            signing_attempt_id=_new_id("sat"),
            project_id=artifact.project_id,
            signing_profile_id=signing_profile_id,
            artifact_id=artifact_id,
            artifact_hash=artifact.content_hash,
            status=SIGNING_PENDING,
            created_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await SigningAttemptRepository(session).add(entity)

        outcome = await (adapter or NullSigningAdapter()).sign(profile=profile, artifact=artifact)
        if outcome.status == SIGNING_SUCCEEDED and not outcome.verified:
            outcome = SigningOutcome(
                status=SIGNING_FAILED,
                tool_version=outcome.tool_version,
                certificate_fingerprint=outcome.certificate_fingerprint,
                signature_reference=outcome.signature_reference,
                verified=False,
                detail="签名结果未通过验证",
            )
        await self._finalize_attempt(entity.signing_attempt_id, outcome)
        if self._provenance is not None:
            await self._provenance.add_evidence(
                project_id=artifact.project_id,
                evidence_type="signing",
                artifact_id=artifact_id,
                reference=entity.signing_attempt_id,
                details={
                    "artifact_hash": artifact.content_hash,
                    "signing_profile_id": signing_profile_id,
                    "tool_version": outcome.tool_version,
                    "certificate_fingerprint": outcome.certificate_fingerprint,
                    "result": outcome.status,
                    "verified": outcome.verified,
                },
            )
        return await self.get_attempt(entity.signing_attempt_id)

    async def reconcile_attempt(
        self,
        signing_attempt_id: str,
        *,
        succeeded: bool,
        certificate_fingerprint: str = "",
        detail: str = "",
    ) -> SigningAttemptView:
        async with self._database.session() as session, transaction(session):
            repo = SigningAttemptRepository(session)
            entity = await repo.get(signing_attempt_id)
            if entity is None:
                raise NotFoundError(
                    "签名尝试不存在", details={"signing_attempt_id": signing_attempt_id}
                )
            if entity.status != SIGNING_UNKNOWN:
                raise SigningInvalid(
                    "只有 UNKNOWN 的签名尝试需要核对",
                    details={"status": entity.status},
                )
            target = SIGNING_SUCCEEDED if succeeded else SIGNING_FAILED
            if target not in SIGNING_ATTEMPT_TRANSITIONS[entity.status]:
                raise SigningInvalid("签名尝试状态迁移非法")
            entity.status = target
            entity.verified = succeeded
            entity.certificate_fingerprint = certificate_fingerprint
            entity.error_detail = detail
            entity.completed_at = utcnow()
            await session.flush()
        return await self.get_attempt(signing_attempt_id)

    async def get_attempt(self, signing_attempt_id: str) -> SigningAttemptView:
        async with self._database.session() as session:
            entity = await SigningAttemptRepository(session).get(signing_attempt_id)
        if entity is None:
            raise NotFoundError(
                "签名尝试不存在", details={"signing_attempt_id": signing_attempt_id}
            )
        return _attempt_view(entity)

    async def list_attempts(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await SigningAttemptRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_attempt_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def require_signed(self, artifact_id: str) -> SigningAttemptView:
        async with self._database.session() as session:
            attempts = await SigningAttemptRepository(session).list_for_artifact(artifact_id)
        for attempt in attempts:
            if attempt.status == SIGNING_SUCCEEDED and attempt.verified:
                return _attempt_view(attempt)
        raise SigningInvalid("制品缺少有效签名", details={"artifact_id": artifact_id})

    # ---- 内部实现 ----

    async def _mark_expired(self, signing_profile_id: str) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await SigningProfileRepository(session).get(signing_profile_id)
            if entity is None:
                return
            entity.status = SIGNING_EXPIRED
            entity.updated_at = utcnow()
            await session.flush()

    async def _finalize_attempt(self, signing_attempt_id: str, outcome: SigningOutcome) -> None:
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            entity = await SigningAttemptRepository(session).get(signing_attempt_id)
            if entity is None:
                raise NotFoundError(
                    "签名尝试不存在", details={"signing_attempt_id": signing_attempt_id}
                )
            entity.status = outcome.status
            entity.tool_version = outcome.tool_version
            entity.certificate_fingerprint = outcome.certificate_fingerprint
            entity.signature_reference = outcome.signature_reference
            entity.verified = outcome.verified
            entity.error_detail = outcome.detail
            entity.completed_at = now
            await session.flush()
