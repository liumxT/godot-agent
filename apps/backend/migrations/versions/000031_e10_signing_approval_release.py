"""E10-T10 / T12 / T15 / T16：签名配置、发布审批、发布与分发操作。

Revision ID: 000031
Revises: 000030
Create Date: 2026-11-26

约束：
- 签名配置只保存证书/凭证引用，不保存密钥本体；
- 审批绑定候选清单、制品与交付包哈希；
- 分发操作以 idempotency_key 保证幂等；
- 本地交付与线上发布分开记录。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000031"
down_revision: str | None = "000030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signing_profiles",
        sa.Column("signing_profile_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("signing_method", sa.String(length=32), nullable=False),
        sa.Column("certificate_reference", sa.String(length=512), nullable=False),
        sa.Column("credential_reference", sa.String(length=512), nullable=False),
        sa.Column("allowed_channels_json", sa.Text(), nullable=False),
        sa.Column("expiration", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("signing_profile_id"),
        sa.UniqueConstraint(
            "project_id", "platform", "signing_method", name="uq_signing_profile_scope"
        ),
    )
    op.create_index("ix_signing_profiles_project", "signing_profiles", ["project_id", "status"])

    op.create_table(
        "signing_attempts",
        sa.Column("signing_attempt_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("signing_profile_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_hash", sa.String(length=80), nullable=False),
        sa.Column("tool_version", sa.String(length=64), nullable=False),
        sa.Column("certificate_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("signature_reference", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["signing_profile_id"],
            ["signing_profiles.signing_profile_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.artifact_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("signing_attempt_id"),
    )
    op.create_index("ix_signing_attempts_project", "signing_attempts", ["project_id", "created_at"])
    op.create_index("ix_signing_attempts_artifact", "signing_attempts", ["artifact_id"])
    op.create_index("ix_signing_attempts_profile", "signing_attempts", ["signing_profile_id"])

    op.create_table(
        "release_approvals",
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("release_candidate_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_hash", sa.String(length=80), nullable=False),
        sa.Column("package_hash", sa.String(length=80), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("target_platform", sa.String(length=32), nullable=False),
        sa.Column("distribution_channel", sa.String(length=32), nullable=False),
        sa.Column("release_version", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=True),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_candidate_id"],
            ["release_candidates.release_candidate_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index(
        "ix_release_approvals_project", "release_approvals", ["project_id", "requested_at"]
    )
    op.create_index(
        "ix_release_approvals_candidate",
        "release_approvals",
        ["release_candidate_id", "status"],
    )

    op.create_table(
        "releases",
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("release_candidate_id", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("distribution_reference", sa.String(length=1024), nullable=False),
        sa.Column("external_operation_id", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_candidate_id"],
            ["release_candidates.release_candidate_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["release_approvals.approval_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("release_id"),
    )
    op.create_index("ix_releases_project", "releases", ["project_id", "version"])
    op.create_index("ix_releases_candidate", "releases", ["release_candidate_id"])
    op.create_index("ix_releases_status", "releases", ["status"])

    op.create_table(
        "distribution_operations",
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.String(length=64), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("operation_status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("external_operation_id", sa.String(length=128), nullable=True),
        sa.Column("target_reference", sa.String(length=1024), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["release_id"], ["releases.release_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("operation_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_distribution_operations_project",
        "distribution_operations",
        ["project_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_distribution_operations_project", table_name="distribution_operations")
    op.drop_table("distribution_operations")

    op.drop_index("ix_releases_status", table_name="releases")
    op.drop_index("ix_releases_candidate", table_name="releases")
    op.drop_index("ix_releases_project", table_name="releases")
    op.drop_table("releases")

    op.drop_index("ix_release_approvals_candidate", table_name="release_approvals")
    op.drop_index("ix_release_approvals_project", table_name="release_approvals")
    op.drop_table("release_approvals")

    op.drop_index("ix_signing_attempts_profile", table_name="signing_attempts")
    op.drop_index("ix_signing_attempts_artifact", table_name="signing_attempts")
    op.drop_index("ix_signing_attempts_project", table_name="signing_attempts")
    op.drop_table("signing_attempts")

    op.drop_index("ix_signing_profiles_project", table_name="signing_profiles")
    op.drop_table("signing_profiles")
