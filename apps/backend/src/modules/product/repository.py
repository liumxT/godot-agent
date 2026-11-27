"""E12 产品域仓储。

产品域 Repository 只操作 ``product_*`` / ``update_*`` / ``recovery_*`` 表，
不导入其他模块的 Repository。
"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository
from modules.product.models import (
    CompatibilityResultModel,
    CrashReportModel,
    ProductAuditModel,
    ProductComponentModel,
    ProductConfigurationModel,
    ProductEntitlementModel,
    ProductFeatureFlagModel,
    ProductInstallationModel,
    ProductInstallationStepModel,
    ProductLicenseModel,
    ProductMigrationModel,
    ProductMigrationRunModel,
    ProductPolicyModel,
    ProductReleaseModel,
    RecoveryOperationModel,
    RecoveryPointModel,
    SupportBundleModel,
    TelemetryConsentModel,
    UpdateManifestModel,
    UpdateOperationModel,
)


class InstallationRepository(BaseRepository[ProductInstallationModel]):
    model = ProductInstallationModel

    async def get_latest(self) -> ProductInstallationModel | None:
        return await self.session.scalar(
            select(ProductInstallationModel).order_by(ProductInstallationModel.created_at.desc())
        )


class InstallationStepRepository(BaseRepository[ProductInstallationStepModel]):
    model = ProductInstallationStepModel

    async def list_by_installation(
        self, installation_id: str
    ) -> list[ProductInstallationStepModel]:
        rows = await self.session.scalars(
            select(ProductInstallationStepModel)
            .where(ProductInstallationStepModel.installation_id == installation_id)
            .order_by(ProductInstallationStepModel.created_at)
        )
        return list(rows.all())

    async def get_by_name(
        self, installation_id: str, step_name: str
    ) -> ProductInstallationStepModel | None:
        return await self.session.scalar(
            select(ProductInstallationStepModel).where(
                ProductInstallationStepModel.installation_id == installation_id,
                ProductInstallationStepModel.step_name == step_name,
            )
        )


class ComponentRepository(BaseRepository[ProductComponentModel]):
    model = ProductComponentModel

    async def list_all(self) -> list[ProductComponentModel]:
        rows = await self.session.scalars(
            select(ProductComponentModel).order_by(ProductComponentModel.component_id)
        )
        return list(rows.all())


class ReleaseRepository(BaseRepository[ProductReleaseModel]):
    model = ProductReleaseModel

    async def get_by_version_channel(
        self, product_version: str, channel: str
    ) -> ProductReleaseModel | None:
        return await self.session.scalar(
            select(ProductReleaseModel).where(
                ProductReleaseModel.product_version == product_version,
                ProductReleaseModel.channel == channel,
            )
        )

    async def list_by_channel(self, channel: str) -> list[ProductReleaseModel]:
        rows = await self.session.scalars(
            select(ProductReleaseModel)
            .where(ProductReleaseModel.channel == channel)
            .order_by(ProductReleaseModel.created_at.desc())
        )
        return list(rows.all())


class ConfigurationRepository(BaseRepository[ProductConfigurationModel]):
    model = ProductConfigurationModel

    async def get_by_name_scope(
        self, profile_name: str, scope: str
    ) -> ProductConfigurationModel | None:
        return await self.session.scalar(
            select(ProductConfigurationModel).where(
                ProductConfigurationModel.profile_name == profile_name,
                ProductConfigurationModel.scope == scope,
            )
        )

    async def list_by_scope(self, scope: str) -> list[ProductConfigurationModel]:
        rows = await self.session.scalars(
            select(ProductConfigurationModel)
            .where(ProductConfigurationModel.scope == scope)
            .order_by(ProductConfigurationModel.profile_name)
        )
        return list(rows.all())

    async def list_all(self) -> list[ProductConfigurationModel]:
        rows = await self.session.scalars(
            select(ProductConfigurationModel).order_by(
                ProductConfigurationModel.scope, ProductConfigurationModel.profile_name
            )
        )
        return list(rows.all())


class CompatibilityResultRepository(BaseRepository[CompatibilityResultModel]):
    model = CompatibilityResultModel

    async def get_latest(self) -> CompatibilityResultModel | None:
        return await self.session.scalar(
            select(CompatibilityResultModel).order_by(CompatibilityResultModel.created_at.desc())
        )


class UpdateManifestRepository(BaseRepository[UpdateManifestModel]):
    model = UpdateManifestModel

    async def get_by_release(self, release_id: str) -> UpdateManifestModel | None:
        return await self.session.scalar(
            select(UpdateManifestModel)
            .where(UpdateManifestModel.release_id == release_id)
            .order_by(UpdateManifestModel.created_at.desc())
        )

    async def list_by_channel(self, channel: str) -> list[UpdateManifestModel]:
        rows = await self.session.scalars(
            select(UpdateManifestModel)
            .where(UpdateManifestModel.channel == channel)
            .order_by(UpdateManifestModel.created_at.desc())
        )
        return list(rows.all())


class UpdateOperationRepository(BaseRepository[UpdateOperationModel]):
    model = UpdateOperationModel

    async def get_latest(self) -> UpdateOperationModel | None:
        return await self.session.scalar(
            select(UpdateOperationModel).order_by(UpdateOperationModel.created_at.desc())
        )

    async def list_unfinished(self) -> list[UpdateOperationModel]:
        rows = await self.session.scalars(
            select(UpdateOperationModel).where(
                UpdateOperationModel.status.not_in(("COMPLETED", "FAILED", "REJECTED"))
            )
        )
        return list(rows.all())


class ProductMigrationRepository(BaseRepository[ProductMigrationModel]):
    model = ProductMigrationModel

    async def get_by_versions(
        self, from_version: str, to_version: str
    ) -> ProductMigrationModel | None:
        return await self.session.scalar(
            select(ProductMigrationModel).where(
                ProductMigrationModel.from_schema_version == from_version,
                ProductMigrationModel.to_schema_version == to_version,
            )
        )


class ProductMigrationRunRepository(BaseRepository[ProductMigrationRunModel]):
    model = ProductMigrationRunModel

    async def list_by_migration(self, migration_id: str) -> list[ProductMigrationRunModel]:
        rows = await self.session.scalars(
            select(ProductMigrationRunModel)
            .where(ProductMigrationRunModel.migration_id == migration_id)
            .order_by(ProductMigrationRunModel.created_at.desc())
        )
        return list(rows.all())

    async def list_unfinished(self) -> list[ProductMigrationRunModel]:
        rows = await self.session.scalars(
            select(ProductMigrationRunModel).where(
                ProductMigrationRunModel.status.not_in(("COMPLETED", "FAILED"))
            )
        )
        return list(rows.all())


class RecoveryPointRepository(BaseRepository[RecoveryPointModel]):
    model = RecoveryPointModel

    async def list_latest(self, limit: int = 50) -> list[RecoveryPointModel]:
        rows = await self.session.scalars(
            select(RecoveryPointModel).order_by(RecoveryPointModel.created_at.desc()).limit(limit)
        )
        return list(rows.all())


class RecoveryOperationRepository(BaseRepository[RecoveryOperationModel]):
    model = RecoveryOperationModel

    async def list_unfinished(self) -> list[RecoveryOperationModel]:
        rows = await self.session.scalars(
            select(RecoveryOperationModel).where(
                RecoveryOperationModel.status.not_in(("RECOVERED", "RECOVERY_FAILED"))
            )
        )
        return list(rows.all())


class LicenseRepository(BaseRepository[ProductLicenseModel]):
    model = ProductLicenseModel

    async def get_latest(self) -> ProductLicenseModel | None:
        return await self.session.scalar(
            select(ProductLicenseModel).order_by(ProductLicenseModel.created_at.desc())
        )


class EntitlementRepository(BaseRepository[ProductEntitlementModel]):
    model = ProductEntitlementModel

    async def list_by_license(self, license_id: str) -> list[ProductEntitlementModel]:
        rows = await self.session.scalars(
            select(ProductEntitlementModel).where(ProductEntitlementModel.license_id == license_id)
        )
        return list(rows.all())

    async def get_by_feature(
        self, license_id: str, feature_key: str
    ) -> ProductEntitlementModel | None:
        return await self.session.scalar(
            select(ProductEntitlementModel).where(
                ProductEntitlementModel.license_id == license_id,
                ProductEntitlementModel.feature_key == feature_key,
            )
        )


class FeatureFlagRepository(BaseRepository[ProductFeatureFlagModel]):
    model = ProductFeatureFlagModel

    async def list_all(self) -> list[ProductFeatureFlagModel]:
        rows = await self.session.scalars(
            select(ProductFeatureFlagModel).order_by(ProductFeatureFlagModel.feature_key)
        )
        return list(rows.all())


class TelemetryConsentRepository(BaseRepository[TelemetryConsentModel]):
    model = TelemetryConsentModel

    async def get_latest(self) -> TelemetryConsentModel | None:
        return await self.session.scalar(
            select(TelemetryConsentModel).order_by(TelemetryConsentModel.created_at.desc())
        )


class SupportBundleRepository(BaseRepository[SupportBundleModel]):
    model = SupportBundleModel

    async def list_latest(self, limit: int = 20) -> list[SupportBundleModel]:
        rows = await self.session.scalars(
            select(SupportBundleModel).order_by(SupportBundleModel.created_at.desc()).limit(limit)
        )
        return list(rows.all())


class CrashReportRepository(BaseRepository[CrashReportModel]):
    model = CrashReportModel

    async def list_latest(self, limit: int = 20) -> list[CrashReportModel]:
        rows = await self.session.scalars(
            select(CrashReportModel).order_by(CrashReportModel.created_at.desc()).limit(limit)
        )
        return list(rows.all())


class ProductAuditRepository(BaseRepository[ProductAuditModel]):
    model = ProductAuditModel

    async def list_latest(self, limit: int = 100) -> list[ProductAuditModel]:
        rows = await self.session.scalars(
            select(ProductAuditModel).order_by(ProductAuditModel.created_at.desc()).limit(limit)
        )
        return list(rows.all())


class ProductPolicyRepository(BaseRepository[ProductPolicyModel]):
    model = ProductPolicyModel

    async def get_by_key(self, policy_key: str) -> ProductPolicyModel | None:
        return await self.session.scalar(
            select(ProductPolicyModel).where(ProductPolicyModel.policy_key == policy_key)
        )

    async def list_all(self) -> list[ProductPolicyModel]:
        rows = await self.session.scalars(
            select(ProductPolicyModel).order_by(ProductPolicyModel.policy_key)
        )
        return list(rows.all())
