"""e8 asset pipeline domain

Revision ID: 000022
Revises: 000021
Create Date: 2026-11-23

E8-T01 / T02：Asset / AssetVersion / Variant / Brief / Generation / Processing /
Import / Provenance / License / Quality / Dependency / Delivery / Storage /
Provider Job 基础表。

约束：
- Asset 与 AssetVersion 分离，AssetVersion 不可变；
- Generation / Processing / Import / Quality / License / Delivery 状态独立；
- 文件内容存文件系统，数据库只存元数据、Hash 与状态；
- 内部暂存区与 Godot 项目目录隔离。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000022"
down_revision: str | None = "000021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("current_version_id", sa.String(length=64), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_index("ix_assets_project_status", "assets", ["project_id", "lifecycle_status"])
    op.create_index(
        "ix_assets_project_category", "assets", ["project_id", "category", "asset_type"]
    )
    op.create_index("ix_assets_current_version", "assets", ["current_version_id"])

    op.create_table(
        "asset_versions",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("provenance_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("asset_id", "version_number", name="uq_asset_versions_number"),
    )
    op.create_index("ix_asset_versions_hash", "asset_versions", ["content_hash"])

    op.create_table(
        "asset_variants",
        sa.Column("variant_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("asset_version_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("variant_type", sa.String(length=32), nullable=False),
        sa.Column("variant_key", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.version_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("variant_id"),
        sa.UniqueConstraint(
            "asset_id", "variant_type", "variant_key", name="uq_asset_variants_key"
        ),
    )

    op.create_table(
        "asset_briefs",
        sa.Column("brief_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("asset_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("asset_category", sa.String(length=64), nullable=False),
        sa.Column("visual_direction", sa.Text(), nullable=False),
        sa.Column("style_reference", sa.Text(), nullable=False),
        sa.Column("technical_constraints_json", sa.Text(), nullable=False),
        sa.Column("animation_requirements_json", sa.Text(), nullable=False),
        sa.Column("delivery_requirements_json", sa.Text(), nullable=False),
        sa.Column("license_requirements_json", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("brief_id"),
    )
    op.create_index("ix_asset_briefs_project_status", "asset_briefs", ["project_id", "status"])
    op.create_index("ix_asset_briefs_task", "asset_briefs", ["task_id"])

    op.create_table(
        "asset_generations",
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("brief_id", sa.String(length=64), nullable=True),
        sa.Column("requested_spec_json", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("provider_job_id", sa.String(length=128), nullable=True),
        sa.Column("generation_status", sa.String(length=24), nullable=False),
        sa.Column("result_version_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("budget_reservation_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["brief_id"], ["asset_briefs.brief_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("generation_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_asset_generations_idempotency"),
    )
    op.create_index(
        "ix_asset_generations_asset_status", "asset_generations", ["asset_id", "generation_status"]
    )
    op.create_index(
        "ix_asset_generations_provider_job",
        "asset_generations",
        ["provider_id", "provider_job_id"],
    )

    op.create_table(
        "asset_generation_outputs",
        sa.Column("output_id", sa.String(length=64), nullable=False),
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("temporary_reference", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_id"], ["asset_generations.generation_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("output_id"),
    )
    op.create_index(
        "ix_asset_generation_outputs_generation", "asset_generation_outputs", ["generation_id"]
    )

    op.create_table(
        "asset_processing_jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("input_version_id", sa.String(length=64), nullable=False),
        sa.Column("output_version_id", sa.String(length=64), nullable=True),
        sa.Column("processing_graph_json", sa.Text(), nullable=False),
        sa.Column("processing_status", sa.String(length=24), nullable=False),
        sa.Column("execution_metadata_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["input_version_id"], ["asset_versions.version_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_asset_processing_jobs_idempotency"),
    )
    op.create_index(
        "ix_asset_processing_jobs_asset_status",
        "asset_processing_jobs",
        ["asset_id", "processing_status"],
    )

    op.create_table(
        "asset_processing_steps",
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("processor_id", sa.String(length=128), nullable=False),
        sa.Column("processor_version", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("execution_status", sa.String(length=24), nullable=False),
        sa.Column("resource_usage_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["asset_processing_jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("step_id"),
    )
    op.create_index(
        "ix_asset_processing_steps_job", "asset_processing_steps", ["job_id", "node_id"]
    )

    op.create_table(
        "asset_import_jobs",
        sa.Column("import_job_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("asset_version_id", sa.String(length=64), nullable=False),
        sa.Column("target_path", sa.String(length=1024), nullable=False),
        sa.Column("godot_resource_type", sa.String(length=64), nullable=True),
        sa.Column("import_status", sa.String(length=24), nullable=False),
        sa.Column("godot_uid", sa.String(length=128), nullable=True),
        sa.Column("import_evidence_id", sa.String(length=64), nullable=True),
        sa.Column("changeset_id", sa.String(length=64), nullable=True),
        sa.Column("editor_session_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.version_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("import_job_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_asset_import_jobs_idempotency"),
    )
    op.create_index(
        "ix_asset_import_jobs_project_status",
        "asset_import_jobs",
        ["project_id", "import_status"],
    )
    op.create_index("ix_asset_import_jobs_version", "asset_import_jobs", ["asset_version_id"])

    op.create_table(
        "asset_import_evidence",
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("import_job_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("editor_session_id", sa.String(length=64), nullable=True),
        sa.Column("asset_version_id", sa.String(length=64), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("target_path", sa.String(length=1024), nullable=False),
        sa.Column("import_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("import_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("godot_version", sa.String(length=32), nullable=True),
        sa.Column("import_result_json", sa.Text(), nullable=False),
        sa.Column("resource_uid", sa.String(length=128), nullable=True),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("import_metadata_json", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_job_id"], ["asset_import_jobs.import_job_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index("ix_asset_import_evidence_job", "asset_import_evidence", ["import_job_id"])

    op.create_table(
        "asset_provenance",
        sa.Column("provenance_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("asset_version_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("generation_id", sa.String(length=64), nullable=True),
        sa.Column("request_reference", sa.String(length=512), nullable=True),
        sa.Column("prompt_version_id", sa.String(length=64), nullable=True),
        sa.Column("seed", sa.String(length=128), nullable=True),
        sa.Column("input_hashes_json", sa.Text(), nullable=False),
        sa.Column("output_hashes_json", sa.Text(), nullable=False),
        sa.Column("processing_graph_json", sa.Text(), nullable=True),
        sa.Column("processor_versions_json", sa.Text(), nullable=False),
        sa.Column("operator_agent_id", sa.String(length=64), nullable=True),
        sa.Column("operator_user_id", sa.String(length=64), nullable=True),
        sa.Column("license_reference", sa.String(length=128), nullable=True),
        sa.Column("external_source_reference", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.version_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("provenance_id"),
        sa.UniqueConstraint("asset_version_id", name="uq_asset_provenance_version"),
    )
    op.create_index("ix_asset_provenance_asset", "asset_provenance", ["asset_id"])

    op.create_table(
        "asset_licenses",
        sa.Column("license_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("asset_version_id", sa.String(length=64), nullable=False),
        sa.Column("license_name", sa.String(length=128), nullable=False),
        sa.Column("license_family", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=512), nullable=True),
        sa.Column("commercial_use", sa.Boolean(), nullable=True),
        sa.Column("modification_allowed", sa.Boolean(), nullable=True),
        sa.Column("redistribution_allowed", sa.Boolean(), nullable=True),
        sa.Column("attribution_required", sa.Boolean(), nullable=True),
        sa.Column("attribution_text", sa.Text(), nullable=True),
        sa.Column("expiration_policy", sa.String(length=128), nullable=True),
        sa.Column("expiration_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("territory", sa.String(length=128), nullable=True),
        sa.Column("evidence_reference", sa.String(length=512), nullable=True),
        sa.Column("verification_method", sa.String(length=128), nullable=True),
        sa.Column("verification_status", sa.String(length=24), nullable=False),
        sa.Column("reviewer_id", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.version_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("license_id"),
    )
    op.create_index(
        "ix_asset_licenses_version", "asset_licenses", ["asset_version_id", "verification_status"]
    )
    op.create_index("ix_asset_licenses_asset", "asset_licenses", ["asset_id"])

    op.create_table(
        "asset_license_evidence",
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("license_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("reference", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["license_id"], ["asset_licenses.license_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index("ix_asset_license_evidence_license", "asset_license_evidence", ["license_id"])

    op.create_table(
        "asset_quality_reviews",
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("asset_version_id", sa.String(length=64), nullable=False),
        sa.Column("review_type", sa.String(length=16), nullable=False),
        sa.Column("machine_result_json", sa.Text(), nullable=True),
        sa.Column("human_result_json", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.version_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("review_id"),
    )
    op.create_index(
        "ix_asset_quality_reviews_version",
        "asset_quality_reviews",
        ["asset_version_id", "review_status"],
    )
    op.create_index("ix_asset_quality_reviews_asset", "asset_quality_reviews", ["asset_id"])

    op.create_table(
        "asset_quality_findings",
        sa.Column("finding_id", sa.String(length=64), nullable=False),
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_id"], ["asset_quality_reviews.review_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("finding_id"),
    )
    op.create_index("ix_asset_quality_findings_review", "asset_quality_findings", ["review_id"])

    op.create_table(
        "asset_dependencies",
        sa.Column("dependency_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("asset_version_id", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=512), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_reference", sa.String(length=512), nullable=False),
        sa.Column("dependency_type", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.version_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("dependency_id"),
    )
    op.create_index(
        "ix_asset_dependencies_project_target",
        "asset_dependencies",
        ["project_id", "target_reference"],
    )
    op.create_index("ix_asset_dependencies_version", "asset_dependencies", ["asset_version_id"])

    op.create_table(
        "asset_deliveries",
        sa.Column("delivery_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("asset_version_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("changeset_id", sa.String(length=64), nullable=True),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("import_job_id", sa.String(length=64), nullable=True),
        sa.Column("delivery_status", sa.String(length=24), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.version_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["import_job_id"], ["asset_import_jobs.import_job_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("delivery_id"),
    )
    op.create_index(
        "ix_asset_deliveries_project_status", "asset_deliveries", ["project_id", "delivery_status"]
    )
    op.create_index("ix_asset_deliveries_version", "asset_deliveries", ["asset_version_id"])

    op.create_table(
        "asset_storage_objects",
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("asset_version_id", sa.String(length=64), nullable=True),
        sa.Column("storage_area", sa.String(length=32), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.version_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("object_id"),
        sa.UniqueConstraint("project_id", "relative_path", name="uq_asset_storage_objects_path"),
    )
    op.create_index("ix_asset_storage_objects_hash", "asset_storage_objects", ["content_hash"])

    op.create_table(
        "asset_provider_jobs",
        sa.Column("record_id", sa.String(length=64), nullable=False),
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("provider_job_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("result_reference", sa.String(length=512), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_id"], ["asset_generations.generation_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint(
            "provider_id", "provider_job_id", name="uq_asset_provider_jobs_external"
        ),
    )
    op.create_index("ix_asset_provider_jobs_generation", "asset_provider_jobs", ["generation_id"])


def downgrade() -> None:
    op.drop_table("asset_provider_jobs")
    op.drop_table("asset_storage_objects")
    op.drop_table("asset_deliveries")
    op.drop_table("asset_dependencies")
    op.drop_table("asset_quality_findings")
    op.drop_table("asset_quality_reviews")
    op.drop_table("asset_license_evidence")
    op.drop_table("asset_licenses")
    op.drop_table("asset_provenance")
    op.drop_table("asset_import_evidence")
    op.drop_table("asset_import_jobs")
    op.drop_table("asset_processing_steps")
    op.drop_table("asset_processing_jobs")
    op.drop_table("asset_generation_outputs")
    op.drop_table("asset_generations")
    op.drop_table("asset_briefs")
    op.drop_table("asset_variants")
    op.drop_table("asset_versions")
    op.drop_table("assets")
