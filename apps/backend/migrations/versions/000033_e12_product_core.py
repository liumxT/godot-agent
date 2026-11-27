"""E12-T01/T02/T03/T05/T06/T07/T08/T12/T17：产品化领域表。

Revision ID: 000033
Revises: 000032
Create Date: 2026-11-27

约束：
- 产品版本与游戏制品版本使用独立表，禁止共用版本域；
- 安装、更新、迁移与恢复记录必须包含状态、步骤与时间；
- 凭证只保存引用，不保存密钥本体。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000033"
down_revision: str | None = "000032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_installations",
        sa.Column("installation_id", sa.String(length=64), nullable=False),
        sa.Column("product_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("install_dir", sa.Text(), nullable=False),
        sa.Column("data_dir", sa.Text(), nullable=False),
        sa.Column("config_dir", sa.Text(), nullable=False),
        sa.Column("log_dir", sa.Text(), nullable=False),
        sa.Column("database_path", sa.Text(), nullable=False),
        sa.Column("components_json", sa.Text(), nullable=False),
        sa.Column("last_step", sa.String(length=64), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("installation_id"),
    )
    op.create_index("ix_product_installations_status", "product_installations", ["status"])

    op.create_table(
        "product_installation_steps",
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("installation_id", sa.String(length=64), nullable=False),
        sa.Column("step_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("files_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("step_id"),
        sa.UniqueConstraint("installation_id", "step_name", name="uq_product_install_step"),
    )
    op.create_index(
        "ix_product_install_steps_installation",
        "product_installation_steps",
        ["installation_id"],
    )

    op.create_table(
        "product_components",
        sa.Column("component_id", sa.String(length=64), nullable=False),
        sa.Column("component_name", sa.String(length=128), nullable=False),
        sa.Column("component_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("component_id"),
    )

    op.create_table(
        "product_releases",
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("product_version", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("component_versions_json", sa.Text(), nullable=False),
        sa.Column("compatibility_matrix_version", sa.String(length=32), nullable=False),
        sa.Column("minimum_supported_version", sa.String(length=32), nullable=False),
        sa.Column("migration_requirements_json", sa.Text(), nullable=False),
        sa.Column("package_hash", sa.String(length=128), nullable=False),
        sa.Column("package_signature", sa.Text(), nullable=False),
        sa.Column("signature_status", sa.String(length=16), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=False),
        sa.Column("sbom_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("release_id"),
        sa.UniqueConstraint(
            "product_version", "channel", name="uq_product_release_version_channel"
        ),
    )
    op.create_index("ix_product_releases_channel", "product_releases", ["channel", "status"])

    op.create_table(
        "product_configurations",
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("profile_name", sa.String(length=64), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("profile_id"),
        sa.UniqueConstraint("profile_name", "scope", name="uq_product_profile_name_scope"),
    )
    op.create_index(
        "ix_product_configurations_scope", "product_configurations", ["scope", "status"]
    )

    op.create_table(
        "compatibility_results",
        sa.Column("result_id", sa.String(length=64), nullable=False),
        sa.Column("matrix_version", sa.String(length=32), nullable=False),
        sa.Column("overall", sa.String(length=16), nullable=False),
        sa.Column("environment_json", sa.Text(), nullable=False),
        sa.Column("checks_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("result_id"),
    )
    op.create_index("ix_compatibility_results_created", "compatibility_results", ["created_at"])

    op.create_table(
        "update_manifests",
        sa.Column("manifest_id", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("product_version", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("package_hash", sa.String(length=128), nullable=False),
        sa.Column("package_signature", sa.Text(), nullable=False),
        sa.Column("signature_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("manifest_id"),
    )
    op.create_index(
        "ix_update_manifests_channel", "update_manifests", ["channel", "product_version"]
    )

    op.create_table(
        "update_operations",
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("from_version", sa.String(length=32), nullable=False),
        sa.Column("to_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=False),
        sa.Column("approved", sa.Integer(), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index("ix_update_operations_status", "update_operations", ["status"])

    op.create_table(
        "product_migrations",
        sa.Column("migration_id", sa.String(length=64), nullable=False),
        sa.Column("from_schema_version", sa.String(length=32), nullable=False),
        sa.Column("to_schema_version", sa.String(length=32), nullable=False),
        sa.Column("migration_type", sa.String(length=32), nullable=False),
        sa.Column("precondition", sa.Text(), nullable=False),
        sa.Column("backup_requirement", sa.Integer(), nullable=False),
        sa.Column("rollback_strategy", sa.Text(), nullable=False),
        sa.Column("verification_query", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("migration_id"),
    )

    op.create_table(
        "product_migration_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("migration_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("backup_path", sa.Text(), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("verification_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_product_migration_runs_status", "product_migration_runs", ["status"])

    op.create_table(
        "recovery_points",
        sa.Column("recovery_point_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("product_version", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("integrity_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("recovery_point_id"),
    )

    op.create_table(
        "recovery_operations",
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("recovery_point_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=False),
        sa.Column("inspection_json", sa.Text(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("confirmed", sa.Integer(), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index("ix_recovery_operations_status", "recovery_operations", ["status"])

    op.create_table(
        "product_licenses",
        sa.Column("license_id", sa.String(length=64), nullable=False),
        sa.Column("license_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("license_reference", sa.String(length=128), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offline_grace_days", sa.Integer(), nullable=False),
        sa.Column("device_reference", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("license_id"),
    )

    op.create_table(
        "product_entitlements",
        sa.Column("entitlement_id", sa.String(length=64), nullable=False),
        sa.Column("license_id", sa.String(length=64), nullable=False),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("entitlement_id"),
        sa.UniqueConstraint("license_id", "feature_key", name="uq_product_entitlement"),
    )

    op.create_table(
        "product_feature_flags",
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("feature_key"),
    )

    op.create_table(
        "product_telemetry_consents",
        sa.Column("consent_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("categories_json", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.String(length=64), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("consent_id"),
    )

    op.create_table(
        "product_support_bundles",
        sa.Column("bundle_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bundle_id"),
    )
    op.create_index("ix_product_support_bundles_status", "product_support_bundles", ["status"])

    op.create_table(
        "product_crash_reports",
        sa.Column("crash_id", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("sanitized_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("crash_id"),
    )

    op.create_table(
        "product_audits",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("target", sa.String(length=128), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index("ix_product_audits_action", "product_audits", ["action", "created_at"])

    op.create_table(
        "product_policies",
        sa.Column("policy_key", sa.String(length=64), nullable=False),
        sa.Column("policy_value", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("policy_key"),
    )


def downgrade() -> None:
    for table in (
        "product_policies",
        "product_audits",
        "product_crash_reports",
        "product_support_bundles",
        "product_telemetry_consents",
        "product_feature_flags",
        "product_entitlements",
        "product_licenses",
        "recovery_operations",
        "recovery_points",
        "product_migration_runs",
        "product_migrations",
        "update_operations",
        "update_manifests",
        "compatibility_results",
        "product_configurations",
        "product_releases",
        "product_components",
        "product_installation_steps",
        "product_installations",
    ):
        op.drop_table(table)
