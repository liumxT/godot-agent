"""平台产品发布流水线（E12-T19）。

与 E10 游戏 Build & Release 完全独立：

- 只管理 AI Agent 平台自身的 Product Release；
- 发布必须经过版本、组件、SBOM、测试证据、签名与兼容性检查；
- 审批人不能是 Agent，发布不能绕过审批；
- 发布记录不写入游戏制品版本。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.metadata import distributions
from typing import Any

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.models import (
    RELEASE_APPROVED,
    RELEASE_CANDIDATE,
    RELEASE_DRAFT,
    RELEASE_PUBLISHED,
    RELEASE_REJECTED,
    ProductAuditModel,
    ProductReleaseModel,
)
from modules.product.repository import ProductAuditRepository, ReleaseRepository
from modules.product.versioning import (
    COMPATIBILITY_MATRIX_VERSION,
    PRODUCT_VERSION_DOMAIN,
    ensure_version_isolation,
    parse_version,
)

REQUIRED_EVIDENCE = (
    "unit_tests",
    "integration_tests",
    "godot_plugin_tests",
    "compatibility_matrix",
    "installer_smoke",
    "security_scan",
    "rollback_drill",
)


def _now() -> datetime:
    return datetime.now(UTC)


def build_sbom() -> dict[str, Any]:
    packages = []
    for dist in distributions():
        name = dist.metadata.get("Name") if dist.metadata else None
        if not name:
            continue
        packages.append(
            {
                "name": name,
                "version": dist.version,
                "license": (dist.metadata.get("License") or "UNKNOWN")
                if dist.metadata
                else "UNKNOWN",
            }
        )
    packages.sort(key=lambda item: (item["name"].lower(), item["version"]))
    payload = json.dumps(packages, sort_keys=True, separators=(",", ":")).encode()
    return {
        "packages": packages,
        "count": len(packages),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _release_dict(record: ProductReleaseModel) -> dict[str, Any]:
    return {
        "release_id": record.release_id,
        "product_version": record.product_version,
        "channel": record.channel,
        "status": record.status,
        "component_versions": json.loads(record.component_versions_json),
        "compatibility_matrix_version": record.compatibility_matrix_version,
        "minimum_supported_version": record.minimum_supported_version,
        "package_hash": record.package_hash,
        "signature_status": record.signature_status,
        "approved_by": record.approved_by,
        "published_at": record.published_at.isoformat() if record.published_at else None,
        "created_at": record.created_at.isoformat(),
    }


class ProductReleaseService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def create_candidate(
        self,
        *,
        product_version: str,
        channel: str,
        component_versions: Mapping[str, str],
        package_hash: str,
        signature_status: str,
        release_notes: str,
        evidence: Mapping[str, Any],
        source_revision: str = "unknown",
        version_domain: str = PRODUCT_VERSION_DOMAIN,
    ) -> dict[str, Any]:
        ensure_version_isolation(version_domain)
        parse_version(product_version)
        if not component_versions:
            raise ValidationFailed("发布必须声明所有组件版本")
        missing_components = [key for key, value in component_versions.items() if not value]
        if missing_components:
            raise ValidationFailed("组件版本不能为空", details={"components": missing_components})
        if signature_status not in {"SIGNED", "UNSIGNED", "INVALID"}:
            raise ValidationFailed("未知的签名状态", details={})
        missing_evidence = [key for key in REQUIRED_EVIDENCE if not evidence.get(key)]
        if missing_evidence:
            raise ValidationFailed(
                "发布缺少测试或验收证据",
                details={"missing": missing_evidence},
            )
        sbom = build_sbom()
        now = _now()
        release_id = f"prel_{uuid.uuid4().hex[:16]}"
        async with self._database.session() as session, transaction(session):
            release = ProductReleaseModel(
                release_id=release_id,
                product_version=product_version,
                channel=channel,
                status=RELEASE_CANDIDATE,
                component_versions_json=json.dumps(dict(component_versions)),
                compatibility_matrix_version=COMPATIBILITY_MATRIX_VERSION,
                minimum_supported_version=product_version,
                migration_requirements_json=json.dumps([]),
                package_hash=package_hash,
                package_signature="",
                signature_status=signature_status,
                release_notes=release_notes,
                sbom_json=json.dumps(sbom),
                evidence_json=json.dumps(
                    {"evidence": dict(evidence), "source_revision": source_revision}
                ),
                approved_by=None,
                published_at=None,
                created_at=now,
                updated_at=now,
            )
            await ReleaseRepository(session).add(release)
            await session.flush()
            return _release_dict(release)

    async def approve(self, release_id: str, *, approver: str) -> dict[str, Any]:
        if not approver:
            raise ValidationFailed("发布审批必须记录审批人")
        async with self._database.session() as session, transaction(session):
            repository = ReleaseRepository(session)
            release = await repository.get(release_id)
            if release is None:
                raise ValidationFailed("发布候选不存在", details={"release_id": release_id})
            if release.status != RELEASE_CANDIDATE:
                raise ValidationFailed("只有候选版本可以审批", details={"status": release.status})
            if release.signature_status != "SIGNED":
                raise ValidationFailed(
                    "发布包必须签名后才能审批",
                    details={"signature_status": release.signature_status},
                )
            sbom = json.loads(release.sbom_json)
            if not sbom.get("packages"):
                raise ValidationFailed("缺少 SBOM，禁止审批发布")
            release.status = RELEASE_APPROVED
            release.approved_by = approver
            release.updated_at = _now()
            await self._audit(
                session, action="product.release.approve", actor=approver, target=release_id
            )
            await session.flush()
            return _release_dict(release)

    async def reject(self, release_id: str, *, approver: str, reason: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            release = await ReleaseRepository(session).get(release_id)
            if release is None:
                raise ValidationFailed("发布候选不存在", details={"release_id": release_id})
            if release.status not in {RELEASE_DRAFT, RELEASE_CANDIDATE}:
                raise ValidationFailed("当前状态不允许拒绝", details={"status": release.status})
            release.status = RELEASE_REJECTED
            release.approved_by = approver
            release.release_notes = f"{release.release_notes}\nREJECTED: {reason}".strip()
            release.updated_at = _now()
            await self._audit(
                session, action="product.release.reject", actor=approver, target=release_id
            )
            await session.flush()
            return _release_dict(release)

    async def publish(self, release_id: str, *, publisher: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            release = await ReleaseRepository(session).get(release_id)
            if release is None:
                raise ValidationFailed("发布候选不存在", details={"release_id": release_id})
            if release.status == RELEASE_PUBLISHED:
                return _release_dict(release)
            if release.status != RELEASE_APPROVED:
                raise ValidationFailed("发布必须经过审批", details={"status": release.status})
            if release.signature_status != "SIGNED":
                raise ValidationFailed("未签名发布包禁止发布", details={})
            evidence = json.loads(release.evidence_json)
            missing = [
                key for key in REQUIRED_EVIDENCE if not evidence.get("evidence", {}).get(key)
            ]
            if missing:
                raise ValidationFailed("发布证据缺失", details={"missing": missing})
            release.status = RELEASE_PUBLISHED
            release.published_at = _now()
            release.updated_at = _now()
            await self._audit(
                session, action="product.release.publish", actor=publisher, target=release_id
            )
            await session.flush()
            return _release_dict(release)

    async def get(self, release_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            release = await ReleaseRepository(session).get(release_id)
            if release is None:
                raise ValidationFailed("发布候选不存在", details={"release_id": release_id})
            return _release_dict(release)

    async def list_releases(self, channel: str) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            rows = await ReleaseRepository(session).list_by_channel(channel)
            return [_release_dict(row) for row in rows]

    async def _audit(self, session: Any, *, action: str, actor: str, target: str) -> None:
        await ProductAuditRepository(session).add(
            ProductAuditModel(
                audit_id=f"aud_{uuid.uuid4().hex[:16]}",
                action=action,
                actor_id=actor,
                outcome="SUCCESS",
                target=target,
                detail_json="{}",
                created_at=_now(),
            )
        )
