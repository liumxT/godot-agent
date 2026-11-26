"""E10-T01 / T02 / T03 / T04：Build & Release 领域基础表。

Revision ID: 000028
Revises: 000027
Create Date: 2026-11-26

约束：
- Build 与 Attempt 分离，重试只新增 Attempt；
- 构建配置版本快照不可变，修改产生新版本；
- Export Preset 默认只读，敏感字段脱敏保存；
- 构建环境指纹用于判断历史构建可比性。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000028"
down_revision: str | None = "000027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "build_configurations",
        sa.Column("configuration_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("target_platform", sa.String(length=16), nullable=False),
        sa.Column("architecture", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("configuration_id"),
        sa.UniqueConstraint("project_id", "name", name="uq_build_configuration_name"),
    )
    op.create_index(
        "ix_build_configurations_project", "build_configurations", ["project_id", "created_at"]
    )

    op.create_table(
        "build_configuration_versions",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("configuration_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("godot_version_constraint", sa.String(length=64), nullable=False),
        sa.Column("target_platform", sa.String(length=16), nullable=False),
        sa.Column("architecture", sa.String(length=32), nullable=False),
        sa.Column("renderer", sa.String(length=32), nullable=False),
        sa.Column("export_preset_name", sa.String(length=128), nullable=False),
        sa.Column("build_mode", sa.String(length=16), nullable=False),
        sa.Column("feature_tags_json", sa.Text(), nullable=False),
        sa.Column("output_format", sa.String(length=32), nullable=False),
        sa.Column("env_allowlist_json", sa.Text(), nullable=False),
        sa.Column("build_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("resource_budget_json", sa.Text(), nullable=False),
        sa.Column("packaging_policy_json", sa.Text(), nullable=False),
        sa.Column("verification_policy_json", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["configuration_id"],
            ["build_configurations.configuration_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("configuration_id", "version", name="uq_build_config_version"),
    )
    op.create_index(
        "ix_build_config_versions_project_platform",
        "build_configuration_versions",
        ["project_id", "target_platform"],
    )

    op.create_table(
        "export_presets",
        sa.Column("preset_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("preset_name", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("export_mode", sa.String(length=16), nullable=False),
        sa.Column("export_path", sa.String(length=512), nullable=False),
        sa.Column("features_json", sa.Text(), nullable=False),
        sa.Column("resource_filters_json", sa.Text(), nullable=False),
        sa.Column("template_required", sa.String(length=64), nullable=False),
        sa.Column("template_available", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("validation_errors_json", sa.Text(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("preset_id"),
        sa.UniqueConstraint("project_id", "preset_name", name="uq_export_preset_name"),
    )
    op.create_index(
        "ix_export_presets_project_platform", "export_presets", ["project_id", "platform"]
    )

    op.create_table(
        "build_environments",
        sa.Column("environment_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("os_name", sa.String(length=32), nullable=False),
        sa.Column("os_version", sa.String(length=64), nullable=False),
        sa.Column("cpu_architecture", sa.String(length=32), nullable=False),
        sa.Column("godot_version", sa.String(length=32), nullable=False),
        sa.Column("godot_executable_path", sa.String(length=512), nullable=False),
        sa.Column("godot_executable_hash", sa.String(length=64), nullable=False),
        sa.Column("export_template_version", sa.String(length=32), nullable=False),
        sa.Column("toolchain_versions_json", sa.Text(), nullable=False),
        sa.Column("sdk_versions_json", sa.Text(), nullable=False),
        sa.Column("renderer", sa.String(length=32), nullable=False),
        sa.Column("build_executor_version", sa.String(length=32), nullable=False),
        sa.Column("environment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("environment_id"),
    )
    op.create_index(
        "ix_build_environments_project_fingerprint",
        "build_environments",
        ["project_id", "environment_fingerprint"],
    )
    op.create_index(
        "ix_build_environments_fingerprint", "build_environments", ["environment_fingerprint"]
    )

    op.create_table(
        "platform_capabilities",
        sa.Column("capability_id", sa.String(length=64), nullable=False),
        sa.Column("platform_id", sa.String(length=16), nullable=False),
        sa.Column("platform_name", sa.String(length=64), nullable=False),
        sa.Column("supported_architectures_json", sa.Text(), nullable=False),
        sa.Column("supported_godot_versions_json", sa.Text(), nullable=False),
        sa.Column("required_export_templates_json", sa.Text(), nullable=False),
        sa.Column("required_sdks_json", sa.Text(), nullable=False),
        sa.Column("required_signing_tools_json", sa.Text(), nullable=False),
        sa.Column("supported_package_formats_json", sa.Text(), nullable=False),
        sa.Column("capability_status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("capability_id"),
        sa.UniqueConstraint("platform_id", name="uq_platform_capability_platform"),
    )

    op.create_table(
        "build_jobs",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("build_config_id", sa.String(length=64), nullable=True),
        sa.Column("build_config_version", sa.Integer(), nullable=False),
        sa.Column("source_revision", sa.String(length=128), nullable=False),
        sa.Column("changeset_id", sa.String(length=64), nullable=True),
        sa.Column("environment_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_attempt_id", sa.String(length=64), nullable=True),
        sa.Column("executor_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.String(length=64), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["build_config_id"], ["build_configurations.configuration_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("build_id"),
    )
    op.create_index("ix_build_jobs_project_status", "build_jobs", ["project_id", "status"])
    op.create_index("ix_build_jobs_config", "build_jobs", ["build_config_id"])

    op.create_table(
        "build_attempts",
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("executor_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("command_template_id", sa.String(length=64), nullable=False),
        sa.Column("command_json", sa.Text(), nullable=False),
        sa.Column("environment_id", sa.String(length=64), nullable=True),
        sa.Column("environment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("log_reference", sa.String(length=512), nullable=True),
        sa.Column("stdout_reference", sa.String(length=512), nullable=True),
        sa.Column("stderr_reference", sa.String(length=512), nullable=True),
        sa.Column("output_manifest_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["build_id"], ["build_jobs.build_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("build_id", "attempt_number", name="uq_build_attempt_number"),
    )
    op.create_index("ix_build_attempts_build", "build_attempts", ["build_id"])
    op.create_index("ix_build_attempts_status", "build_attempts", ["status"])

    op.create_table(
        "build_logs",
        sa.Column("log_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["build_attempts.attempt_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("log_id"),
    )
    op.create_index("ix_build_logs_attempt_seq", "build_logs", ["attempt_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_build_logs_attempt_seq", table_name="build_logs")
    op.drop_table("build_logs")

    op.drop_index("ix_build_attempts_status", table_name="build_attempts")
    op.drop_index("ix_build_attempts_build", table_name="build_attempts")
    op.drop_table("build_attempts")

    op.drop_index("ix_build_jobs_config", table_name="build_jobs")
    op.drop_index("ix_build_jobs_project_status", table_name="build_jobs")
    op.drop_table("build_jobs")

    op.drop_table("platform_capabilities")

    op.drop_index("ix_build_environments_fingerprint", table_name="build_environments")
    op.drop_index("ix_build_environments_project_fingerprint", table_name="build_environments")
    op.drop_table("build_environments")

    op.drop_index("ix_export_presets_project_platform", table_name="export_presets")
    op.drop_table("export_presets")

    op.drop_index(
        "ix_build_config_versions_project_platform", table_name="build_configuration_versions"
    )
    op.drop_table("build_configuration_versions")

    op.drop_index("ix_build_configurations_project", table_name="build_configurations")
    op.drop_table("build_configurations")
