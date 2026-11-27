"""License / Entitlement 抽象（E12-T05）。

首期提供：

- 完全本地运行的 Development License；
- LOCAL / ONLINE / ENTERPRISE / SUBSCRIPTION 模式的统一状态机；
- 离线宽限、时钟异常检测与功能使用权。

授权失效只影响商业功能，不删除任何用户数据与项目。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.models import (
    LICENSE_ACTIVE,
    LICENSE_CLOCK_ANOMALY,
    LICENSE_EXPIRED,
    LICENSE_GRACE,
    LICENSE_MODE_DEVELOPMENT,
    LICENSE_MODES,
    LICENSE_REVOKED,
    LICENSE_UNKNOWN,
    ProductEntitlementModel,
    ProductLicenseModel,
)
from modules.product.repository import (
    EntitlementRepository,
    FeatureFlagRepository,
    LicenseRepository,
)

FEATURES = (
    "development_assistant",
    "autonomous_development",
    "multi_agent",
    "asset_pipeline",
    "verification",
    "build_release",
    "product_recovery",
)

CLOCK_SKEW_TOLERANCE = timedelta(days=1)
ENTITLEMENT_ACTIVE = "ACTIVE"
ENTITLEMENT_REVOKED = "REVOKED"


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class LicenseService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def ensure_development_license(self) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            licenses = LicenseRepository(session)
            license = await licenses.get_latest()
            if license is None:
                now = _now()
                license = ProductLicenseModel(
                    license_id=f"lic_{uuid.uuid4().hex[:16]}",
                    license_mode=LICENSE_MODE_DEVELOPMENT,
                    status=LICENSE_ACTIVE,
                    license_reference="development",
                    issued_at=now,
                    expires_at=None,
                    offline_grace_days=0,
                    device_reference="local",
                    created_at=now,
                    updated_at=now,
                )
                await licenses.add(license)
                entitlements = EntitlementRepository(session)
                for feature in FEATURES:
                    await entitlements.add(
                        ProductEntitlementModel(
                            entitlement_id=f"ent_{uuid.uuid4().hex[:16]}",
                            license_id=license.license_id,
                            feature_key=feature,
                            status=ENTITLEMENT_ACTIVE,
                            source="DEVELOPMENT",
                            created_at=now,
                        )
                    )
                await session.flush()
            return {"license_id": license.license_id, "license_mode": license.license_mode}

    async def register(
        self,
        *,
        license_mode: str,
        license_reference: str,
        issued_at: datetime,
        expires_at: datetime | None = None,
        offline_grace_days: int = 7,
        device_reference: str = "local",
        features: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if license_mode not in LICENSE_MODES:
            raise ValidationFailed("未知的授权模式", details={"license_mode": license_mode})
        if not license_reference:
            raise ValidationFailed("授权必须提供只保存引用，不保存密钥本体")
        now = _now()
        async with self._database.session() as session, transaction(session):
            license = ProductLicenseModel(
                license_id=f"lic_{uuid.uuid4().hex[:16]}",
                license_mode=license_mode,
                status=LICENSE_ACTIVE,
                license_reference=license_reference,
                issued_at=_ensure_aware(issued_at),
                expires_at=_ensure_aware(expires_at) if expires_at else None,
                offline_grace_days=max(0, offline_grace_days),
                device_reference=device_reference,
                created_at=now,
                updated_at=now,
            )
            await LicenseRepository(session).add(license)
            entitlements = EntitlementRepository(session)
            for feature in features or FEATURES:
                await entitlements.add(
                    ProductEntitlementModel(
                        entitlement_id=f"ent_{uuid.uuid4().hex[:16]}",
                        license_id=license.license_id,
                        feature_key=feature,
                        status=ENTITLEMENT_ACTIVE,
                        source=license_mode,
                        created_at=now,
                    )
                )
            await session.flush()
            return {"license_id": license.license_id, "license_mode": license_mode}

    async def grant(
        self, license_id: str, feature_key: str, source: str = "MANUAL"
    ) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            entitlements = EntitlementRepository(session)
            record = await entitlements.get_by_feature(license_id, feature_key)
            if record is None:
                record = ProductEntitlementModel(
                    entitlement_id=f"ent_{uuid.uuid4().hex[:16]}",
                    license_id=license_id,
                    feature_key=feature_key,
                    status=ENTITLEMENT_ACTIVE,
                    source=source,
                    created_at=_now(),
                )
                await entitlements.add(record)
            else:
                record.status = ENTITLEMENT_ACTIVE
                record.revoked_at = None
                record.source = source
            await session.flush()
            return {"license_id": license_id, "feature_key": feature_key, "status": record.status}

    async def revoke(self, license_id: str, feature_key: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            entitlements = EntitlementRepository(session)
            record = await entitlements.get_by_feature(license_id, feature_key)
            if record is None:
                raise ValidationFailed("功能使用权不存在", details={"feature_key": feature_key})
            record.status = ENTITLEMENT_REVOKED
            record.revoked_at = _now()
            await session.flush()
            return {"license_id": license_id, "feature_key": feature_key, "status": record.status}

    async def evaluate(self, now: datetime | None = None) -> dict[str, Any]:
        check_time = _ensure_aware(now or _now())
        async with self._database.session() as session, transaction(session):
            licenses = LicenseRepository(session)
            license = await licenses.get_latest()
            if license is None:
                return {
                    "status": LICENSE_UNKNOWN,
                    "valid": False,
                    "mode": "UNKNOWN",
                    "features": [],
                    "message": "尚未登记授权，仅可使用受限开发能力",
                }

            status = LICENSE_ACTIVE
            message = ""
            issued_at = _ensure_aware(license.issued_at)
            if check_time < issued_at - CLOCK_SKEW_TOLERANCE:
                status = LICENSE_CLOCK_ANOMALY
                message = "系统时间早于授权签发时间，可能存在时钟异常"
            elif license.expires_at is not None:
                expires_at = _ensure_aware(license.expires_at)
                if check_time > expires_at:
                    grace_end = expires_at + timedelta(days=license.offline_grace_days)
                    if license.offline_grace_days and check_time <= grace_end:
                        status = LICENSE_GRACE
                        message = "授权已过期，处于离线宽限期"
                    else:
                        status = LICENSE_EXPIRED
                        message = "授权已过期"
            if status != license.status:
                license.status = status
                license.updated_at = _now()

            entitlements = await EntitlementRepository(session).list_by_license(license.license_id)
            features = sorted(
                item.feature_key
                for item in entitlements
                if item.status == ENTITLEMENT_ACTIVE and item.revoked_at is None
            )
            valid = status in {LICENSE_ACTIVE, LICENSE_GRACE}
            return {
                "status": status,
                "valid": valid,
                "mode": license.license_mode,
                "features": features,
                "message": message,
                "license_id": license.license_id,
            }

    async def mark_revoked(self, license_id: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            licenses = LicenseRepository(session)
            license = await licenses.get(license_id)
            if license is None:
                raise ValidationFailed("授权不存在", details={"license_id": license_id})
            license.status = LICENSE_REVOKED
            license.updated_at = _now()
            await session.flush()
            return {"license_id": license_id, "status": license.status}

    async def has_feature(self, feature_key: str) -> bool:
        """功能开关只能显式开启；未知功能默认拒绝。"""

        async with self._database.session() as session:
            flag = await FeatureFlagRepository(session).get(feature_key)
            if flag is not None and flag.enabled:
                return True
        evaluation = await self.evaluate()
        return feature_key in evaluation["features"]
