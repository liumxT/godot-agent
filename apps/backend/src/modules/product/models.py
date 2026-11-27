"""E12 产品化领域模型（T01 / T02 / T03 / T05 / T06 / T07 / T08 / T12 / T17）。

边界：

- 产品域只保存平台自身的安装、升级、兼容、授权、隐私与诊断数据；
- 不复制 Task / Workflow / Agent / Verification / Build 等业务状态；
- 敏感凭证不进入普通字段，只允许保存凭证引用。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

# 安装状态机
INSTALL_CREATED = "CREATED"
INSTALL_PRECHECK = "PRECHECK"
INSTALL_INSTALLING = "INSTALLING"
INSTALL_VERIFYING = "VERIFYING"
INSTALL_COMPLETED = "COMPLETED"
INSTALL_FAILED = "FAILED"
INSTALL_PARTIAL = "PARTIAL"
INSTALL_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
INSTALL_ROLLED_BACK = "ROLLED_BACK"
INSTALL_STATUSES = frozenset(
    {
        INSTALL_CREATED,
        INSTALL_PRECHECK,
        INSTALL_INSTALLING,
        INSTALL_VERIFYING,
        INSTALL_COMPLETED,
        INSTALL_FAILED,
        INSTALL_PARTIAL,
        INSTALL_RECOVERY_REQUIRED,
        INSTALL_ROLLED_BACK,
    }
)

STEP_PENDING = "PENDING"
STEP_RUNNING = "RUNNING"
STEP_COMPLETED = "COMPLETED"
STEP_FAILED = "FAILED"
STEP_SKIPPED = "SKIPPED"
INSTALL_STEP_STATUSES = frozenset(
    {STEP_PENDING, STEP_RUNNING, STEP_COMPLETED, STEP_FAILED, STEP_SKIPPED}
)

# 更新状态机
UPDATE_CHECKED = "CHECKED"
UPDATE_VERIFIED = "VERIFIED"
UPDATE_APPROVED = "APPROVED"
UPDATE_DOWNLOADED = "DOWNLOADED"
UPDATE_STAGED = "STAGED"
UPDATE_INSTALLING = "INSTALLING"
UPDATE_VERIFYING = "VERIFYING"
UPDATE_COMPLETED = "COMPLETED"
UPDATE_FAILED = "FAILED"
UPDATE_REJECTED = "REJECTED"
UPDATE_STATUSES = frozenset(
    {
        UPDATE_CHECKED,
        UPDATE_VERIFIED,
        UPDATE_APPROVED,
        UPDATE_DOWNLOADED,
        UPDATE_STAGED,
        UPDATE_INSTALLING,
        UPDATE_VERIFYING,
        UPDATE_COMPLETED,
        UPDATE_FAILED,
        UPDATE_REJECTED,
    }
)

SIGNATURE_SIGNED = "SIGNED"
SIGNATURE_UNSIGNED = "UNSIGNED"
SIGNATURE_INVALID = "INVALID"
SIGNATURE_STATUSES = frozenset({SIGNATURE_SIGNED, SIGNATURE_UNSIGNED, SIGNATURE_INVALID})

# 迁移
MIGRATION_PLANNED = "PLANNED"
MIGRATION_BACKED_UP = "BACKED_UP"
MIGRATION_EXECUTING = "EXECUTING"
MIGRATION_COMPLETED = "COMPLETED"
MIGRATION_FAILED = "FAILED"
MIGRATION_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
MIGRATION_STATUSES = frozenset(
    {
        MIGRATION_PLANNED,
        MIGRATION_BACKED_UP,
        MIGRATION_EXECUTING,
        MIGRATION_COMPLETED,
        MIGRATION_FAILED,
        MIGRATION_RECOVERY_REQUIRED,
    }
)

MIGRATION_REVERSIBLE = "REVERSIBLE"
MIGRATION_FORWARD_ONLY = "FORWARD_ONLY"
MIGRATION_DATA_TRANSFORMATION = "DATA_TRANSFORMATION"
MIGRATION_INDEX_REBUILD = "INDEX_REBUILD"
MIGRATION_SCHEMA_COMPATIBILITY = "SCHEMA_COMPATIBILITY"
MIGRATION_TYPES = frozenset(
    {
        MIGRATION_REVERSIBLE,
        MIGRATION_FORWARD_ONLY,
        MIGRATION_DATA_TRANSFORMATION,
        MIGRATION_INDEX_REBUILD,
        MIGRATION_SCHEMA_COMPATIBILITY,
    }
)

# 恢复
RECOVERY_DETECTED = "RECOVERY_DETECTED"
RECOVERY_INSPECTED = "STATE_INSPECTION"
RECOVERY_PLANNED = "RECOVERY_PLAN"
RECOVERY_CONFIRMED = "USER_CONFIRMATION"
RECOVERY_EXECUTING = "EXECUTION"
RECOVERY_VERIFYING = "VERIFICATION"
RECOVERY_COMPLETED = "RECOVERED"
RECOVERY_FAILED = "RECOVERY_FAILED"
RECOVERY_PARTIAL = "PARTIAL_RECOVERY"
RECOVERY_MANUAL = "MANUAL_INTERVENTION_REQUIRED"
RECOVERY_STATUSES = frozenset(
    {
        RECOVERY_DETECTED,
        RECOVERY_INSPECTED,
        RECOVERY_PLANNED,
        RECOVERY_CONFIRMED,
        RECOVERY_EXECUTING,
        RECOVERY_VERIFYING,
        RECOVERY_COMPLETED,
        RECOVERY_FAILED,
        RECOVERY_PARTIAL,
        RECOVERY_MANUAL,
    }
)

# 授权
LICENSE_ACTIVE = "ACTIVE"
LICENSE_GRACE = "GRACE"
LICENSE_EXPIRED = "EXPIRED"
LICENSE_REVOKED = "REVOKED"
LICENSE_CLOCK_ANOMALY = "CLOCK_ANOMALY"
LICENSE_UNKNOWN = "UNKNOWN"
LICENSE_STATUSES = frozenset(
    {
        LICENSE_ACTIVE,
        LICENSE_GRACE,
        LICENSE_EXPIRED,
        LICENSE_REVOKED,
        LICENSE_CLOCK_ANOMALY,
        LICENSE_UNKNOWN,
    }
)

LICENSE_MODE_DEVELOPMENT = "DEVELOPMENT"
LICENSE_MODE_LOCAL = "LOCAL"
LICENSE_MODE_ONLINE = "ONLINE"
LICENSE_MODE_ENTERPRISE = "ENTERPRISE"
LICENSE_MODE_SUBSCRIPTION = "SUBSCRIPTION"
LICENSE_MODES = frozenset(
    {
        LICENSE_MODE_DEVELOPMENT,
        LICENSE_MODE_LOCAL,
        LICENSE_MODE_ONLINE,
        LICENSE_MODE_ENTERPRISE,
        LICENSE_MODE_SUBSCRIPTION,
    }
)

# 发布流水线
RELEASE_DRAFT = "DRAFT"
RELEASE_CANDIDATE = "RELEASE_CANDIDATE"
RELEASE_APPROVED = "APPROVED"
RELEASE_REJECTED = "REJECTED"
RELEASE_PUBLISHED = "PUBLISHED"
RELEASE_STATUSES = frozenset(
    {RELEASE_DRAFT, RELEASE_CANDIDATE, RELEASE_APPROVED, RELEASE_REJECTED, RELEASE_PUBLISHED}
)


class ProductInstallationModel(Base):
    """安装实例：记录组件、目录边界与可恢复步骤。"""

    __tablename__ = "product_installations"

    installation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    install_dir: Mapped[str] = mapped_column(Text, nullable=False)
    data_dir: Mapped[str] = mapped_column(Text, nullable=False)
    config_dir: Mapped[str] = mapped_column(Text, nullable=False)
    log_dir: Mapped[str] = mapped_column(Text, nullable=False)
    database_path: Mapped[str] = mapped_column(Text, nullable=False)
    components_json: Mapped[str] = mapped_column(Text, nullable=False)
    last_step: Mapped[str] = mapped_column(String(64), nullable=False)
    error_detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_product_installations_status", "status"),)


class ProductInstallationStepModel(Base):
    """安装步骤与已创建文件：中断后据此判断真实进度。"""

    __tablename__ = "product_installation_steps"

    step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    files_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("installation_id", "step_name", name="uq_product_install_step"),
        Index("ix_product_install_steps_installation", "installation_id"),
    )


class ProductComponentModel(Base):
    """产品组件版本登记表。"""

    __tablename__ = "product_components"

    component_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    component_name: Mapped[str] = mapped_column(String(128), nullable=False)
    component_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductReleaseModel(Base):
    """产品发布版本（与 E10 游戏制品版本完全隔离）。"""

    __tablename__ = "product_releases"

    release_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_version: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    component_versions_json: Mapped[str] = mapped_column(Text, nullable=False)
    compatibility_matrix_version: Mapped[str] = mapped_column(String(32), nullable=False)
    minimum_supported_version: Mapped[str] = mapped_column(String(32), nullable=False)
    migration_requirements_json: Mapped[str] = mapped_column(Text, nullable=False)
    package_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    package_signature: Mapped[str] = mapped_column(Text, nullable=False)
    signature_status: Mapped[str] = mapped_column(String(16), nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, nullable=False)
    sbom_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("product_version", "channel", name="uq_product_release_version_channel"),
        Index("ix_product_releases_channel", "channel", "status"),
    )


class ProductConfigurationModel(Base):
    """产品配置 Profile：包含安全策略来源与哈希。"""

    __tablename__ = "product_configurations"

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    values_json: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("profile_name", "scope", name="uq_product_profile_name_scope"),
        Index("ix_product_configurations_scope", "scope", "status"),
    )


class CompatibilityResultModel(Base):
    """环境检查结果：UNKNOWN 始终保持 UNKNOWN。"""

    __tablename__ = "compatibility_results"

    result_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    matrix_version: Mapped[str] = mapped_column(String(32), nullable=False)
    overall: Mapped[str] = mapped_column(String(16), nullable=False)
    environment_json: Mapped[str] = mapped_column(Text, nullable=False)
    checks_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_compatibility_results_created", "created_at"),)


class UpdateManifestModel(Base):
    """更新清单：签名与 Hash 是安装前置条件。"""

    __tablename__ = "update_manifests"

    manifest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_version: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    package_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    package_signature: Mapped[str] = mapped_column(Text, nullable=False)
    signature_status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_update_manifests_channel", "channel", "product_version"),)


class UpdateOperationModel(Base):
    """更新执行记录：中断后据此恢复而不会盲目重复安装。"""

    __tablename__ = "update_operations"

    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    from_version: Mapped[str] = mapped_column(String(32), nullable=False)
    to_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_step: Mapped[str] = mapped_column(String(64), nullable=False)
    approved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_update_operations_status", "status"),)


class ProductMigrationModel(Base):
    """产品迁移定义：不可逆迁移必须显式标记。"""

    __tablename__ = "product_migrations"

    migration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    to_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    migration_type: Mapped[str] = mapped_column(String(32), nullable=False)
    precondition: Mapped[str] = mapped_column(Text, nullable=False)
    backup_requirement: Mapped[int] = mapped_column(Integer, nullable=False)
    rollback_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    verification_query: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductMigrationRunModel(Base):
    """产品迁移执行：记录备份、状态与验证结果。"""

    __tablename__ = "product_migration_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    migration_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    backup_path: Mapped[str] = mapped_column(Text, nullable=False)
    current_step: Mapped[str] = mapped_column(String(64), nullable=False)
    error_detail: Mapped[str] = mapped_column(Text, nullable=False)
    verification_detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_product_migration_runs_status", "status"),)


class RecoveryPointModel(Base):
    """恢复点：二进制/插件/数据库/配置快照的引用与校验值。"""

    __tablename__ = "recovery_points"

    recovery_point_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    product_version: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    integrity_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecoveryOperationModel(Base):
    """恢复操作：必须经过状态检查与用户确认。"""

    __tablename__ = "recovery_operations"

    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recovery_point_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_step: Mapped[str] = mapped_column(String(64), nullable=False)
    inspection_json: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_recovery_operations_status", "status"),)


class ProductLicenseModel(Base):
    """授权记录：只保存授权引用，不保存任何密钥材料。"""

    __tablename__ = "product_licenses"

    license_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    license_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    license_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offline_grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    device_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductEntitlementModel(Base):
    """功能使用权。"""

    __tablename__ = "product_entitlements"

    entitlement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    license_id: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("license_id", "feature_key", name="uq_product_entitlement"),)


class ProductFeatureFlagModel(Base):
    """功能开关：默认关闭，开启必须显式记录。"""

    __tablename__ = "product_feature_flags"

    feature_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelemetryConsentModel(Base):
    """Telemetry 同意记录：默认关闭，撤销需留痕。"""

    __tablename__ = "product_telemetry_consents"

    consent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    categories_json: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupportBundleModel(Base):
    """支持包记录：导出前必须用户确认。"""

    __tablename__ = "product_support_bundles"

    bundle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_product_support_bundles_status", "status"),)


class CrashReportModel(Base):
    """崩溃报告：本地生成，发送需用户确认。"""

    __tablename__ = "product_crash_reports"

    crash_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    sanitized_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductAuditModel(Base):
    """产品级审计：安装、更新、迁移、恢复、隐私与发布审批。"""

    __tablename__ = "product_audits"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_product_audits_action", "action", "created_at"),)


class ProductPolicyModel(Base):
    """产品策略：安全、隐私与更新策略的唯一来源。"""

    __tablename__ = "product_policies"

    policy_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_value: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
