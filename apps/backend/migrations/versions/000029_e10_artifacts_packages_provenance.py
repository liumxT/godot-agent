"""E10-T08 / T09 / T13：制品、交付包、构建来源与发布证据。

Revision ID: 000029
Revises: 000028
Create Date: 2026-11-26

约束：
- 已注册 Artifact 内容不可变，内容变化生成新版本与新哈希；
- Package 绑定 Artifact，清单与包哈希用于完整性校验；
- Provenance 记录构建输入、环境指纹与产物哈希；
- Release Evidence 只追加，不覆盖。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000029"
down_revision: str | None = "000028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("build_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("architecture", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("storage_reference", sa.String(length=512), nullable=False),
        sa.Column("verification_status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["build_id"], ["build_jobs.build_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("artifact_id"),
        sa.UniqueConstraint(
            "project_id", "build_id", "artifact_version", name="uq_artifact_build_version"
        ),
    )
    op.create_index("ix_artifacts_project", "artifacts", ["project_id", "created_at"])
    op.create_index("ix_artifacts_hash", "artifacts", ["content_hash"])

    op.create_table(
        "artifact_manifests",
        sa.Column("manifest_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.artifact_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("manifest_id"),
    )
    op.create_index("ix_artifact_manifests_artifact", "artifact_manifests", ["artifact_id"])

    op.create_table(
        "artifact_packages",
        sa.Column("package_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("package_hash", sa.String(length=80), nullable=False),
        sa.Column("storage_reference", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.artifact_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("package_id"),
        sa.UniqueConstraint("artifact_id", "package_version", name="uq_package_artifact_version"),
    )
    op.create_index(
        "ix_artifact_packages_project", "artifact_packages", ["project_id", "created_at"]
    )

    op.create_table(
        "package_manifests",
        sa.Column("manifest_id", sa.String(length=64), nullable=False),
        sa.Column("package_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"], ["artifact_packages.package_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("manifest_id"),
    )
    op.create_index("ix_package_manifests_package", "package_manifests", ["package_id"])

    op.create_table(
        "build_provenance",
        sa.Column("provenance_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=True),
        sa.Column("source_revision", sa.String(length=128), nullable=False),
        sa.Column("config_snapshot_hash", sa.String(length=80), nullable=False),
        sa.Column("environment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("command_template_id", sa.String(length=64), nullable=False),
        sa.Column("executor_id", sa.String(length=64), nullable=False),
        sa.Column("inputs_json", sa.Text(), nullable=False),
        sa.Column("outputs_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("provenance_id"),
        sa.UniqueConstraint("build_id", "attempt_id", name="uq_provenance_build_attempt"),
    )
    op.create_index("ix_build_provenance_project", "build_provenance", ["project_id", "created_at"])

    op.create_table(
        "release_evidence",
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("release_candidate_id", sa.String(length=64), nullable=True),
        sa.Column("artifact_id", sa.String(length=64), nullable=True),
        sa.Column("package_id", sa.String(length=64), nullable=True),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("reference", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index("ix_release_evidence_project", "release_evidence", ["project_id", "created_at"])
    op.create_index("ix_release_evidence_artifact", "release_evidence", ["artifact_id"])
    op.create_index("ix_release_evidence_candidate", "release_evidence", ["release_candidate_id"])


def downgrade() -> None:
    op.drop_index("ix_release_evidence_candidate", table_name="release_evidence")
    op.drop_index("ix_release_evidence_artifact", table_name="release_evidence")
    op.drop_index("ix_release_evidence_project", table_name="release_evidence")
    op.drop_table("release_evidence")

    op.drop_index("ix_build_provenance_project", table_name="build_provenance")
    op.drop_table("build_provenance")

    op.drop_index("ix_package_manifests_package", table_name="package_manifests")
    op.drop_table("package_manifests")

    op.drop_index("ix_artifact_packages_project", table_name="artifact_packages")
    op.drop_table("artifact_packages")

    op.drop_index("ix_artifact_manifests_artifact", table_name="artifact_manifests")
    op.drop_table("artifact_manifests")

    op.drop_index("ix_artifacts_hash", table_name="artifacts")
    op.drop_index("ix_artifacts_project", table_name="artifacts")
    op.drop_table("artifacts")
