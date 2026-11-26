"""E10-T11 / T14：发布候选与冒烟测试结果。

Revision ID: 000030
Revises: 000029
Create Date: 2026-11-26

约束：
- 候选清单哈希绑定制品内容哈希与交付包清单哈希；
- 冒烟测试 SKIPPED / UNKNOWN 不等同于通过；
- 候选状态经 DRAFT → VALIDATING → READY_FOR_APPROVAL 等迁移。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000030"
down_revision: str | None = "000029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "release_candidates",
        sa.Column("release_candidate_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("package_id", sa.String(length=64), nullable=True),
        sa.Column("verification_campaign_id", sa.String(length=64), nullable=True),
        sa.Column("candidate_manifest_json", sa.Text(), nullable=False),
        sa.Column("candidate_manifest_hash", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("superseded_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.artifact_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["package_id"], ["artifact_packages.package_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("release_candidate_id"),
    )
    op.create_index(
        "ix_release_candidates_project", "release_candidates", ["project_id", "version"]
    )
    op.create_index("ix_release_candidates_status", "release_candidates", ["status"])

    op.create_table(
        "smoke_test_results",
        sa.Column("smoke_test_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=True),
        sa.Column("package_id", sa.String(length=64), nullable=True),
        sa.Column("release_candidate_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("checks_json", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(length=512), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("smoke_test_id"),
    )
    op.create_index(
        "ix_smoke_test_results_project", "smoke_test_results", ["project_id", "created_at"]
    )
    op.create_index("ix_smoke_test_results_artifact", "smoke_test_results", ["artifact_id"])
    op.create_index(
        "ix_smoke_test_results_candidate", "smoke_test_results", ["release_candidate_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_smoke_test_results_candidate", table_name="smoke_test_results")
    op.drop_index("ix_smoke_test_results_artifact", table_name="smoke_test_results")
    op.drop_index("ix_smoke_test_results_project", table_name="smoke_test_results")
    op.drop_table("smoke_test_results")

    op.drop_index("ix_release_candidates_status", table_name="release_candidates")
    op.drop_index("ix_release_candidates_project", table_name="release_candidates")
    op.drop_table("release_candidates")
