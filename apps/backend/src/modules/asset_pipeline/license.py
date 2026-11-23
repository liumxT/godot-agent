"""资产授权与使用权审查（E8-T13）。

原则：

- License 是独立门禁，绝不根据来源类型自动推导商业使用权；
- 新记录只有在存在授权凭证时才进入 ``PENDING_REVIEW``，否则保持 ``UNKNOWN``；
- 只有人工核验才能进入 ``VERIFIED``，且必须提供审核人、完整权限字段与署名文本；
- 过期授权自动标记 ``EXPIRED`` 并阻止交付；``UNKNOWN`` / ``PENDING_REVIEW`` /
  ``REJECTED`` / ``RESTRICTED`` 一律不能正式交付；
- 审核证据可追加，已核验结论不允许被静默覆盖。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    AssetDeliveryBlocked,
    AssetLicenseInvalid,
    NotFoundError,
)
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    LICENSE_EXPIRED,
    LICENSE_PENDING_REVIEW,
    LICENSE_REJECTED,
    LICENSE_TRANSITIONS,
    LICENSE_UNKNOWN,
    LICENSE_VERIFIED,
    SOURCE_TYPES,
    AssetLicenseEvidenceModel,
    AssetLicenseModel,
)
from modules.asset_pipeline.repository import (
    AssetLicenseEvidenceRepository,
    AssetLicenseRepository,
    AssetRepository,
    AssetVersionRepository,
)

__all__ = [
    "LicenseEvidenceInput",
    "LicenseEvidenceView",
    "LicenseRequest",
    "LicenseService",
    "LicenseView",
]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@dataclass(frozen=True, slots=True)
class LicenseEvidenceInput:
    evidence_type: str
    reference: str
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_type.strip():
            raise AssetLicenseInvalid("授权证据缺少类型")
        if not self.reference.strip():
            raise AssetLicenseInvalid("授权证据缺少引用")


@dataclass(frozen=True, slots=True)
class LicenseRequest:
    project_id: str
    asset_id: str
    asset_version_id: str
    license_name: str
    source_type: str
    license_family: str | None = None
    source_reference: str | None = None
    commercial_use: bool | None = None
    modification_allowed: bool | None = None
    redistribution_allowed: bool | None = None
    attribution_required: bool | None = None
    attribution_text: str | None = None
    expiration_policy: str | None = None
    expiration_at: datetime | None = None
    territory: str | None = None
    evidence_reference: str | None = None
    verification_method: str | None = None
    evidence: Sequence[LicenseEvidenceInput] = ()
    created_by: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise AssetLicenseInvalid("缺少项目 ID")
        if not self.asset_id.strip():
            raise AssetLicenseInvalid("缺少资产 ID")
        if not self.asset_version_id.strip():
            raise AssetLicenseInvalid("缺少资产版本 ID")
        if not self.license_name.strip():
            raise AssetLicenseInvalid("缺少授权名称")
        if self.source_type not in SOURCE_TYPES:
            raise AssetLicenseInvalid(
                "未知资产来源类型", details={"source_type": self.source_type}
            )
        if not all(isinstance(item, LicenseEvidenceInput) for item in self.evidence):
            raise AssetLicenseInvalid("授权证据必须是 LicenseEvidenceInput")


@dataclass(frozen=True, slots=True)
class LicenseEvidenceView:
    evidence_id: str
    evidence_type: str
    reference: str
    content_hash: str | None
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LicenseView:
    license_id: str
    asset_id: str
    asset_version_id: str
    license_name: str
    license_family: str | None
    source_type: str
    source_reference: str | None
    commercial_use: bool | None
    modification_allowed: bool | None
    redistribution_allowed: bool | None
    attribution_required: bool | None
    attribution_text: str | None
    expiration_policy: str | None
    expiration_at: datetime | None
    territory: str | None
    evidence_reference: str | None
    verification_method: str | None
    verification_status: str
    reviewer_id: str | None
    reviewed_at: datetime | None
    created_at: datetime
    evidence: tuple[LicenseEvidenceView, ...]
    created: bool = True


def _evidence_view(entity: AssetLicenseEvidenceModel) -> LicenseEvidenceView:
    return LicenseEvidenceView(
        evidence_id=entity.evidence_id,
        evidence_type=entity.evidence_type,
        reference=entity.reference,
        content_hash=entity.content_hash,
        metadata=_load(entity.metadata_json, {}),
        created_at=entity.created_at,
    )


def _license_view(
    entity: AssetLicenseModel,
    evidence: Sequence[AssetLicenseEvidenceModel],
    *,
    created: bool,
) -> LicenseView:
    return LicenseView(
        license_id=entity.license_id,
        asset_id=entity.asset_id,
        asset_version_id=entity.asset_version_id,
        license_name=entity.license_name,
        license_family=entity.license_family,
        source_type=entity.source_type,
        source_reference=entity.source_reference,
        commercial_use=entity.commercial_use,
        modification_allowed=entity.modification_allowed,
        redistribution_allowed=entity.redistribution_allowed,
        attribution_required=entity.attribution_required,
        attribution_text=entity.attribution_text,
        expiration_policy=entity.expiration_policy,
        expiration_at=entity.expiration_at,
        territory=entity.territory,
        evidence_reference=entity.evidence_reference,
        verification_method=entity.verification_method,
        verification_status=entity.verification_status,
        reviewer_id=entity.reviewer_id,
        reviewed_at=entity.reviewed_at,
        created_at=entity.created_at,
        evidence=tuple(_evidence_view(item) for item in evidence),
        created=created,
    )


class LicenseService:
    """资产授权记录、审核与交付门禁。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        events: EventBus | None = None,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._events = events
        self._clock = clock
        self._logger = get_logger("backend.asset.license")

    async def record(self, request: LicenseRequest) -> LicenseView:
        await self._validate_ownership(
            request.project_id, request.asset_id, request.asset_version_id
        )
        has_evidence = bool(request.evidence_reference) or bool(request.evidence)
        status = LICENSE_PENDING_REVIEW if has_evidence else LICENSE_UNKNOWN
        now = self._clock()
        entity = AssetLicenseModel(
            license_id="alic_" + uuid4().hex[:12],
            asset_id=request.asset_id,
            asset_version_id=request.asset_version_id,
            license_name=request.license_name.strip(),
            license_family=request.license_family,
            source_type=request.source_type,
            source_reference=request.source_reference,
            commercial_use=request.commercial_use,
            modification_allowed=request.modification_allowed,
            redistribution_allowed=request.redistribution_allowed,
            attribution_required=request.attribution_required,
            attribution_text=request.attribution_text,
            expiration_policy=request.expiration_policy,
            expiration_at=request.expiration_at,
            territory=request.territory,
            evidence_reference=request.evidence_reference,
            verification_method=request.verification_method,
            verification_status=status,
            reviewer_id=None,
            reviewed_at=None,
            created_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await AssetLicenseRepository(session).add(entity)
            await self._add_evidence_rows(session, entity.license_id, request.evidence, now)
        await self._publish(
            "asset.license.recorded",
            {
                "license_id": entity.license_id,
                "asset_version_id": request.asset_version_id,
                "status": status,
            },
            project_id=request.project_id,
        )
        return await self.get(request.project_id, entity.license_id)

    async def add_evidence(
        self,
        project_id: str,
        license_id: str,
        evidence: Sequence[LicenseEvidenceInput],
    ) -> LicenseView:
        if not evidence:
            raise AssetLicenseInvalid("至少需要一条授权证据")
        await self._load_license(project_id, license_id)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            stored = await AssetLicenseRepository(session).get(license_id)
            await self._add_evidence_rows(session, license_id, evidence, now)
            if stored.verification_status == LICENSE_UNKNOWN:
                stored.verification_status = LICENSE_PENDING_REVIEW
            await session.flush()
        await self._publish(
            "asset.license.evidence_added",
            {"license_id": license_id, "count": len(evidence)},
            project_id=project_id,
        )
        return await self.get(project_id, license_id)

    async def submit_for_review(self, project_id: str, license_id: str) -> LicenseView:
        entity = await self._load_license(project_id, license_id)
        if entity.verification_status == LICENSE_PENDING_REVIEW:
            return await self.get(project_id, license_id)
        await self._require_evidence(entity)
        self._assert_transition(entity, LICENSE_PENDING_REVIEW)
        async with self._database.session() as session, transaction(session):
            stored = await AssetLicenseRepository(session).get(license_id)
            stored.verification_status = LICENSE_PENDING_REVIEW
            await session.flush()
        await self._publish(
            "asset.license.review_requested",
            {"license_id": license_id},
            project_id=project_id,
        )
        return await self.get(project_id, license_id)

    async def verify(
        self,
        project_id: str,
        license_id: str,
        *,
        reviewer_id: str,
        commercial_use: bool,
        modification_allowed: bool,
        redistribution_allowed: bool,
        attribution_required: bool = False,
        attribution_text: str | None = None,
        expiration_at: datetime | None = None,
        territory: str | None = None,
        verification_method: str | None = None,
    ) -> LicenseView:
        if not reviewer_id.strip():
            raise AssetLicenseInvalid("核验授权必须提供审核人")
        for name, value in (
            ("commercial_use", commercial_use),
            ("modification_allowed", modification_allowed),
            ("redistribution_allowed", redistribution_allowed),
        ):
            if not isinstance(value, bool):
                raise AssetLicenseInvalid(
                    "授权核验必须明确权限字段", details={"field": name}
                )
        if attribution_required and not (attribution_text or "").strip():
            raise AssetLicenseInvalid("要求署名时必须提供署名文本")
        entity = await self._load_license(project_id, license_id)
        if entity.verification_status == LICENSE_VERIFIED:
            raise AssetLicenseInvalid(
                "授权已核验，不能重复覆盖", details={"license_id": license_id}
            )
        await self._require_evidence(entity)
        self._assert_transition(entity, LICENSE_VERIFIED)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            stored = await AssetLicenseRepository(session).get(license_id)
            stored.commercial_use = commercial_use
            stored.modification_allowed = modification_allowed
            stored.redistribution_allowed = redistribution_allowed
            stored.attribution_required = attribution_required
            if attribution_text is not None:
                stored.attribution_text = attribution_text
            if expiration_at is not None:
                stored.expiration_at = expiration_at
            if territory is not None:
                stored.territory = territory
            if verification_method is not None:
                stored.verification_method = verification_method
            stored.verification_status = LICENSE_VERIFIED
            stored.reviewer_id = reviewer_id
            stored.reviewed_at = now
            await session.flush()
        await self._publish(
            "asset.license.verified",
            {"license_id": license_id, "reviewer_id": reviewer_id},
            project_id=project_id,
        )
        return await self.get(project_id, license_id)

    async def reject(
        self,
        project_id: str,
        license_id: str,
        *,
        reviewer_id: str,
        reason: str,
    ) -> LicenseView:
        if not reviewer_id.strip():
            raise AssetLicenseInvalid("驳回授权必须提供审核人")
        if not reason.strip():
            raise AssetLicenseInvalid("驳回授权必须提供原因")
        entity = await self._load_license(project_id, license_id)
        self._assert_transition(entity, LICENSE_REJECTED)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            stored = await AssetLicenseRepository(session).get(license_id)
            stored.verification_status = LICENSE_REJECTED
            stored.reviewer_id = reviewer_id
            stored.reviewed_at = now
            await self._add_evidence_rows(
                session,
                license_id,
                [
                    LicenseEvidenceInput(
                        evidence_type="REVIEW_NOTE",
                        reference=reason,
                        metadata={"reviewer_id": reviewer_id, "decision": "REJECTED"},
                    )
                ],
                now,
            )
            await session.flush()
        await self._publish(
            "asset.license.rejected",
            {"license_id": license_id, "reviewer_id": reviewer_id},
            project_id=project_id,
        )
        return await self.get(project_id, license_id)

    async def get(self, project_id: str, license_id: str) -> LicenseView:
        entity = await self._load_license(project_id, license_id)
        async with self._database.session() as session:
            evidence = await AssetLicenseEvidenceRepository(session).list_for_license(
                license_id
            )
            return _license_view(entity, [item for item in evidence], created=False)

    async def latest_for_version(
        self, project_id: str, asset_version_id: str
    ) -> LicenseView | None:
        await self._validate_ownership(project_id, None, asset_version_id)
        async with self._database.session() as session:
            entity = await AssetLicenseRepository(session).latest_for_version(
                asset_version_id
            )
            if entity is None:
                return None
            evidence = await AssetLicenseEvidenceRepository(session).list_for_license(
                entity.license_id
            )
            session.expunge(entity)
        return _license_view(entity, evidence, created=False)

    async def list_for_version(
        self, project_id: str, asset_version_id: str
    ) -> list[LicenseView]:
        await self._validate_ownership(project_id, None, asset_version_id)
        async with self._database.session() as session:
            entities = await AssetLicenseRepository(session).list_for_version(
                asset_version_id
            )
            evidence_repository = AssetLicenseEvidenceRepository(session)
            views: list[LicenseView] = []
            for entity in entities:
                evidence = await evidence_repository.list_for_license(entity.license_id)
                views.append(_license_view(entity, evidence, created=False))
            return views

    async def check_deliverable(
        self,
        project_id: str,
        asset_version_id: str,
        *,
        require_commercial_use: bool = True,
        require_redistribution: bool = False,
    ) -> LicenseView:
        view = await self.latest_for_version(project_id, asset_version_id)
        if view is None:
            raise AssetDeliveryBlocked(
                "资产版本没有授权记录",
                details={"asset_version_id": asset_version_id},
            )
        now = self._clock()
        if view.expiration_at is not None and ensure_utc(view.expiration_at) <= now:
            if view.verification_status != LICENSE_EXPIRED:
                self._assert_transition_from(view.verification_status, LICENSE_EXPIRED)
                async with self._database.session() as session, transaction(session):
                    stored = await AssetLicenseRepository(session).get(view.license_id)
                    stored.verification_status = LICENSE_EXPIRED
                    await session.flush()
                await self._publish(
                    "asset.license.expired",
                    {"license_id": view.license_id},
                    project_id=project_id,
                )
            raise AssetDeliveryBlocked(
                "授权已过期，不能正式交付",
                details={"license_id": view.license_id},
            )
        if view.verification_status != LICENSE_VERIFIED:
            raise AssetDeliveryBlocked(
                "授权未核验，不能正式交付",
                details={
                    "license_id": view.license_id,
                    "status": view.verification_status,
                },
            )
        if require_commercial_use and view.commercial_use is not True:
            raise AssetDeliveryBlocked(
                "授权不允许商业使用",
                details={"license_id": view.license_id},
            )
        if require_redistribution and view.redistribution_allowed is not True:
            raise AssetDeliveryBlocked(
                "授权不允许再分发",
                details={"license_id": view.license_id},
            )
        return view

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _validate_ownership(
        self, project_id: str, asset_id: str | None, asset_version_id: str
    ) -> None:
        async with self._database.session() as session:
            version = await AssetVersionRepository(session).get(asset_version_id)
            if version is None:
                raise NotFoundError(
                    "资产版本不存在", details={"asset_version_id": asset_version_id}
                )
            if asset_id is not None and version.asset_id != asset_id:
                raise NotFoundError(
                    "资产版本不属于该资产",
                    details={"asset_id": asset_id, "asset_version_id": asset_version_id},
                )
            asset = await AssetRepository(session).get(version.asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产版本不属于该项目",
                    details={
                        "project_id": project_id,
                        "asset_version_id": asset_version_id,
                    },
                )

    async def _load_license(
        self, project_id: str, license_id: str
    ) -> AssetLicenseModel:
        async with self._database.session() as session:
            entity = await AssetLicenseRepository(session).get(license_id)
            if entity is None:
                raise NotFoundError(
                    "授权记录不存在", details={"license_id": license_id}
                )
            asset = await AssetRepository(session).get(entity.asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "授权记录不属于该项目",
                    details={"project_id": project_id, "license_id": license_id},
                )
            session.expunge(entity)
            return entity

    async def _add_evidence_rows(
        self,
        session,
        license_id: str,
        evidence: Sequence[LicenseEvidenceInput],
        now: datetime,
    ) -> None:
        repository = AssetLicenseEvidenceRepository(session)
        for item in evidence:
            await repository.add(
                AssetLicenseEvidenceModel(
                    evidence_id="alev_" + uuid4().hex[:12],
                    license_id=license_id,
                    evidence_type=item.evidence_type.strip(),
                    reference=item.reference.strip(),
                    content_hash=item.content_hash,
                    metadata_json=_dump(item.metadata),
                    created_at=now,
                )
            )

    async def _require_evidence(self, entity: AssetLicenseModel) -> None:
        async with self._database.session() as session:
            evidence = await AssetLicenseEvidenceRepository(session).list_for_license(
                entity.license_id
            )
        if not evidence and not entity.evidence_reference:
            raise AssetLicenseInvalid(
                "授权缺少审核证据", details={"license_id": entity.license_id}
            )

    def _assert_transition(self, entity: AssetLicenseModel, target: str) -> None:
        self._assert_transition_from(entity.verification_status, target)

    def _assert_transition_from(self, current: str, target: str) -> None:
        if target == current:
            return
        if target not in LICENSE_TRANSITIONS.get(current, frozenset()):
            raise AssetLicenseInvalid(
                "授权状态迁移非法", details={"from": current, "to": target}
            )

    async def _publish(
        self, event_type: str, payload: dict[str, Any], *, project_id: str
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(
                Event.create(event_type, payload, project_id=project_id)
            )
        except Exception:  # noqa: BLE001 - 事件失败不阻断授权记录
            log_event(
                self._logger,
                logging.WARNING,
                "asset.license.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )
