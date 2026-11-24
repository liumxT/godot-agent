"""E9-T14 / T15：缺陷管理与回归计划。

Revision ID: 000025
Revises: 000024
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000025"
down_revision: str | None = "000024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_defects",
        sa.Column("defect_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_id", sa.String(length=64), nullable=True),
        sa.Column("source_result_id", sa.String(length=64), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.String(length=4), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reproduction_steps_json", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=False),
        sa.Column("actual_result", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("assigned_agent_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("related_changeset_id", sa.String(length=64), nullable=True),
        sa.Column("resolution_reference", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.requirement_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_result_id"], ["verification_results.result_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("defect_id"),
    )
    op.create_index(
        "ix_verification_defects_project_status",
        "verification_defects",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_verification_defects_project_severity",
        "verification_defects",
        ["project_id", "severity"],
    )
    op.create_index(
        "ix_verification_defects_requirement",
        "verification_defects",
        ["requirement_id"],
    )
    op.create_index(
        "ix_verification_defects_changeset",
        "verification_defects",
        ["related_changeset_id"],
    )

    op.create_table(
        "verification_regression_plans",
        sa.Column("regression_plan_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("changeset_id", sa.String(length=64), nullable=True),
        sa.Column("strategy", sa.String(length=16), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("changed_files_json", sa.Text(), nullable=False),
        sa.Column("affected_requirements_json", sa.Text(), nullable=False),
        sa.Column("affected_test_cases_json", sa.Text(), nullable=False),
        sa.Column("affected_scenes_json", sa.Text(), nullable=False),
        sa.Column("affected_scripts_json", sa.Text(), nullable=False),
        sa.Column("affected_resources_json", sa.Text(), nullable=False),
        sa.Column("dependents_json", sa.Text(), nullable=False),
        sa.Column("historical_defects_json", sa.Text(), nullable=False),
        sa.Column("coverage_gaps_json", sa.Text(), nullable=False),
        sa.Column("required_checks_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("regression_plan_id"),
    )
    op.create_index(
        "ix_verification_regression_plans_project",
        "verification_regression_plans",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_verification_regression_plans_changeset",
        "verification_regression_plans",
        ["changeset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_verification_regression_plans_changeset",
        table_name="verification_regression_plans",
    )
    op.drop_index(
        "ix_verification_regression_plans_project",
        table_name="verification_regression_plans",
    )
    op.drop_table("verification_regression_plans")

    op.drop_index("ix_verification_defects_changeset", table_name="verification_defects")
    op.drop_index("ix_verification_defects_requirement", table_name="verification_defects")
    op.drop_index("ix_verification_defects_project_severity", table_name="verification_defects")
    op.drop_index("ix_verification_defects_project_status", table_name="verification_defects")
    op.drop_table("verification_defects")
