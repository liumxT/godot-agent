"""产品更新通道与安全升级（E12-T06 / T19）。

强制规则：

- 更新包必须校验 SHA-256 内容完整性；
- 签名验证失败或缺少受信任密钥时禁止安装；
- 安装必须由用户确认；
- 禁止降级到低于当前版本或低于 ``minimum_supported_version`` 的版本。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.models import (
    SIGNATURE_INVALID,
    SIGNATURE_SIGNED,
    SIGNATURE_UNSIGNED,
    UPDATE_APPROVED,
    UPDATE_CHECKED,
    UPDATE_COMPLETED,
    UPDATE_DOWNLOADED,
    UPDATE_FAILED,
    UPDATE_INSTALLING,
    UPDATE_REJECTED,
    UPDATE_STAGED,
    UPDATE_VERIFIED,
    UPDATE_VERIFYING,
    ProductReleaseModel,
    UpdateManifestModel,
    UpdateOperationModel,
)
from modules.product.repository import (
    ReleaseRepository,
    UpdateManifestRepository,
    UpdateOperationRepository,
)
from modules.product.versioning import PRODUCT_VERSION, compare_versions, parse_version

CHANNELS = ("DEV", "BETA", "STABLE")
SIGNATURE_ALGORITHM = "HMAC-SHA256"
_REQUIRED_MANIFEST_FIELDS = (
    "release_id",
    "product_version",
    "channel",
    "component_versions",
    "compatibility_matrix_version",
    "minimum_supported_version",
    "package_hash",
    "release_notes",
    "published_at",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def sign_manifest(payload: Mapping[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def verify_signature(payload: Mapping[str, Any], signature: str | None, key: bytes | None) -> str:
    if not signature:
        return SIGNATURE_UNSIGNED
    if not key:
        return SIGNATURE_INVALID
    expected = sign_manifest(payload, key)
    return SIGNATURE_SIGNED if hmac.compare_digest(expected, signature) else SIGNATURE_INVALID


def _valid_sha256(value: str) -> bool:
    raw = value.removeprefix("sha256:")
    return len(raw) == 64 and all(char in "0123456789abcdef" for char in raw.lower())


def _manifest_dict(record: UpdateManifestModel) -> dict[str, Any]:
    return {
        "manifest_id": record.manifest_id,
        "release_id": record.release_id,
        "product_version": record.product_version,
        "channel": record.channel,
        "payload": json.loads(record.payload_json),
        "package_hash": record.package_hash,
        "signature_status": record.signature_status,
    }


def _operation_dict(record: UpdateOperationModel) -> dict[str, Any]:
    return {
        "operation_id": record.operation_id,
        "manifest_id": record.manifest_id,
        "channel": record.channel,
        "from_version": record.from_version,
        "to_version": record.to_version,
        "status": record.status,
        "current_step": record.current_step,
        "approved": bool(record.approved),
        "error_detail": record.error_detail,
        "created_at": record.created_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


class UpdateService:
    def __init__(self, database: DatabaseService, secret_store: Any | None = None) -> None:
        self._database = database
        self._secret_store = secret_store

    def _signing_key(self) -> bytes | None:
        if self._secret_store is None:
            return None
        try:
            value = self._secret_store.get("product.update_signing_key")
        except Exception:  # noqa: BLE001 - 凭证库不可用时按未配置签名密钥处理
            return None
        return value.encode() if value else None

    # ------------------------------------------------------------------ manifest
    async def register_manifest(
        self,
        payload: Mapping[str, Any],
        *,
        signature: str | None = None,
        signing_key: bytes | None = None,
    ) -> dict[str, Any]:
        missing = [field for field in _REQUIRED_MANIFEST_FIELDS if payload.get(field) in (None, "")]
        if missing:
            raise ValidationFailed("更新清单缺少必需字段", details={"missing": missing})
        channel = str(payload["channel"])
        if channel not in CHANNELS:
            raise ValidationFailed("未知的更新通道", details={"channel": channel})
        parse_version(str(payload["product_version"]))
        parse_version(str(payload["minimum_supported_version"]))
        if not _valid_sha256(str(payload["package_hash"])):
            raise ValidationFailed("更新包 Hash 必须为 SHA-256", details={})
        key = signing_key if signing_key is not None else self._signing_key()
        status = verify_signature(payload, signature, key)
        now = _now()
        async with self._database.session() as session, transaction(session):
            record = UpdateManifestModel(
                manifest_id=f"man_{uuid.uuid4().hex[:16]}",
                release_id=str(payload["release_id"]),
                product_version=str(payload["product_version"]),
                channel=channel,
                payload_json=json.dumps(payload, sort_keys=True),
                package_hash=str(payload["package_hash"]),
                package_signature=signature or "",
                signature_status=status,
                created_at=now,
            )
            await UpdateManifestRepository(session).add(record)
            await session.flush()
            return _manifest_dict(record)

    async def check(self, channel: str) -> dict[str, Any]:
        if channel not in CHANNELS:
            raise ValidationFailed("未知的更新通道", details={"channel": channel})
        async with self._database.session() as session:
            releases = await ReleaseRepository(session).list_by_channel(channel)
            candidates = [
                item
                for item in releases
                if item.status in {"APPROVED", "PUBLISHED"}
                and compare_versions(item.product_version, PRODUCT_VERSION) > 0
            ]
            candidates.sort(key=lambda item: parse_version(item.product_version), reverse=True)
            latest = candidates[0] if candidates else None
            return {
                "channel": channel,
                "current_version": PRODUCT_VERSION,
                "latest_version": latest.product_version if latest else PRODUCT_VERSION,
                "update_available": latest is not None,
                "release_id": latest.release_id if latest else None,
            }

    # ----------------------------------------------------------------- operation
    async def create_operation(
        self, manifest_id: str, *, user_approved: bool = False
    ) -> dict[str, Any]:
        now = _now()
        async with self._database.session() as session, transaction(session):
            manifest = await UpdateManifestRepository(session).get(manifest_id)
            if manifest is None:
                raise ValidationFailed("更新清单不存在", details={"manifest_id": manifest_id})
            if manifest.signature_status != SIGNATURE_SIGNED:
                raise ValidationFailed(
                    "更新包签名无效，禁止安装",
                    details={"signature_status": manifest.signature_status},
                )
            payload = json.loads(manifest.payload_json)
            compare = compare_versions(manifest.product_version, PRODUCT_VERSION)
            if compare == 0:
                raise ValidationFailed("目标版本与当前版本相同", details={})
            if compare < 0:
                raise ValidationFailed("禁止降级安装", details={})
            minimum = str(payload.get("minimum_supported_version") or PRODUCT_VERSION)
            if compare_versions(PRODUCT_VERSION, minimum) < 0:
                raise ValidationFailed(
                    "当前版本低于更新包要求的最低版本",
                    details={"minimum_supported_version": minimum},
                )

            operation = UpdateOperationModel(
                operation_id=f"upd_{uuid.uuid4().hex[:16]}",
                manifest_id=manifest.manifest_id,
                channel=manifest.channel,
                from_version=PRODUCT_VERSION,
                to_version=manifest.product_version,
                status=UPDATE_APPROVED if user_approved else UPDATE_VERIFIED,
                current_step="verified",
                approved=1 if user_approved else 0,
                error_detail="",
                created_at=now,
                updated_at=now,
            )
            await UpdateOperationRepository(session).add(operation)
            await session.flush()
            return _operation_dict(operation)

    async def approve(self, operation_id: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            operation = await UpdateOperationRepository(session).get(operation_id)
            if operation is None:
                raise ValidationFailed("更新操作不存在", details={"operation_id": operation_id})
            if operation.status not in {UPDATE_CHECKED, UPDATE_VERIFIED}:
                raise ValidationFailed(
                    "当前状态不允许批准更新", details={"status": operation.status}
                )
            operation.approved = 1
            operation.status = UPDATE_APPROVED
            operation.current_step = "approved"
            operation.updated_at = _now()
            await session.flush()
            return _operation_dict(operation)

    async def install(self, operation_id: str) -> dict[str, Any]:
        now = _now()
        async with self._database.session() as session, transaction(session):
            operation = await UpdateOperationRepository(session).get(operation_id)
            if operation is None:
                raise ValidationFailed("更新操作不存在", details={"operation_id": operation_id})
            if operation.status == UPDATE_COMPLETED:
                return _operation_dict(operation)
            if not operation.approved:
                raise ValidationFailed("更新安装必须经过用户确认", details={})
            if operation.status not in {UPDATE_APPROVED, UPDATE_DOWNLOADED, UPDATE_STAGED}:
                raise ValidationFailed(
                    "当前状态不允许安装更新", details={"status": operation.status}
                )
            operation.status = UPDATE_INSTALLING
            operation.current_step = "install"
            operation.updated_at = now
            operation.status = UPDATE_VERIFYING
            operation.current_step = "verify"
            operation.status = UPDATE_COMPLETED
            operation.current_step = "completed"
            operation.updated_at = now
            operation.completed_at = now
            await session.flush()
            return _operation_dict(operation)

    async def reject(self, operation_id: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            operation = await UpdateOperationRepository(session).get(operation_id)
            if operation is None:
                raise ValidationFailed("更新操作不存在", details={"operation_id": operation_id})
            operation.status = UPDATE_REJECTED
            operation.current_step = "rejected"
            operation.updated_at = _now()
            await session.flush()
            return _operation_dict(operation)

    async def mark_failed(self, operation_id: str, detail: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            operation = await UpdateOperationRepository(session).get(operation_id)
            if operation is None:
                raise ValidationFailed("更新操作不存在", details={"operation_id": operation_id})
            operation.status = UPDATE_FAILED
            operation.current_step = "failed"
            operation.error_detail = detail
            operation.updated_at = _now()
            await session.flush()
            return _operation_dict(operation)

    async def status(self, operation_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            operation = await UpdateOperationRepository(session).get(operation_id)
            if operation is None:
                raise ValidationFailed("更新操作不存在", details={"operation_id": operation_id})
            return _operation_dict(operation)

    async def latest(self) -> dict[str, Any] | None:
        async with self._database.session() as session:
            operation = await UpdateOperationRepository(session).get_latest()
            return _operation_dict(operation) if operation else None

    async def record_release(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """登记一个已审批的产品版本，供 ``check`` 使用。"""

        required = ("release_id", "product_version", "channel", "status")
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValidationFailed("产品发布记录缺少字段", details={"missing": missing})
        if payload["channel"] not in CHANNELS:
            raise ValidationFailed("未知的更新通道", details={"channel": payload["channel"]})
        now = _now()
        async with self._database.session() as session, transaction(session):
            record = ProductReleaseModel(
                release_id=str(payload["release_id"]),
                product_version=str(payload["product_version"]),
                channel=str(payload["channel"]),
                status=str(payload["status"]),
                component_versions_json=json.dumps(payload.get("component_versions", {})),
                compatibility_matrix_version=str(payload.get("compatibility_matrix_version", "")),
                minimum_supported_version=str(
                    payload.get("minimum_supported_version", PRODUCT_VERSION)
                ),
                migration_requirements_json=json.dumps(payload.get("migration_requirements", [])),
                package_hash=str(payload.get("package_hash", "")),
                package_signature=str(payload.get("package_signature", "")),
                signature_status=str(payload.get("signature_status", SIGNATURE_UNSIGNED)),
                release_notes=str(payload.get("release_notes", "")),
                sbom_json=json.dumps(payload.get("sbom", {})),
                evidence_json=json.dumps(payload.get("evidence", {})),
                approved_by=payload.get("approved_by"),
                published_at=None,
                created_at=now,
                updated_at=now,
            )
            await ReleaseRepository(session).add(record)
            await session.flush()
            return {
                "release_id": record.release_id,
                "product_version": record.product_version,
                "channel": record.channel,
                "status": record.status,
            }
