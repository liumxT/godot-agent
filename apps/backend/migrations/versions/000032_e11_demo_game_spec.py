"""E11-T01 / T02：Platformer Demo 需求、设计与验收数据。

Revision ID: 000032
Revises: 000031
Create Date: 2026-11-26

约束：
- Demo 数据只描述规格、设计、验收条件与验收记录；
- 不复制 Task / Workflow / Agent / Approval / Verification / Build 状态表；
- 需求键在规格内唯一，规格与项目一对一。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000032"
down_revision: str | None = "000031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_game_specs",
        sa.Column("spec_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("codename", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("genre", sa.String(length=64), nullable=False),
        sa.Column("godot_version", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("core_loop", sa.Text(), nullable=False),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("spec_id"),
        sa.UniqueConstraint("project_id", name="uq_demo_spec_project"),
    )
    op.create_index("ix_demo_game_specs_project", "demo_game_specs", ["project_id"])

    op.create_table(
        "demo_game_requirements",
        sa.Column("demo_requirement_id", sa.String(length=64), nullable=False),
        sa.Column("spec_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["spec_id"], ["demo_game_specs.spec_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("demo_requirement_id"),
        sa.UniqueConstraint("spec_id", "requirement_key", name="uq_demo_requirement_key"),
    )
    op.create_index(
        "ix_demo_game_requirements_spec",
        "demo_game_requirements",
        ["spec_id", "priority"],
    )

    op.create_table(
        "demo_game_mechanics",
        sa.Column("demo_mechanic_id", sa.String(length=64), nullable=False),
        sa.Column("spec_id", sa.String(length=64), nullable=False),
        sa.Column("mechanic_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["spec_id"], ["demo_game_specs.spec_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("demo_mechanic_id"),
        sa.UniqueConstraint("spec_id", "mechanic_key", name="uq_demo_mechanic_key"),
    )

    op.create_table(
        "demo_game_levels",
        sa.Column("demo_level_id", sa.String(length=64), nullable=False),
        sa.Column("spec_id", sa.String(length=64), nullable=False),
        sa.Column("level_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("layout_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["spec_id"], ["demo_game_specs.spec_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("demo_level_id"),
        sa.UniqueConstraint("spec_id", "level_key", name="uq_demo_level_key"),
    )

    op.create_table(
        "demo_game_features",
        sa.Column("demo_feature_id", sa.String(length=64), nullable=False),
        sa.Column("spec_id", sa.String(length=64), nullable=False),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("system", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("requirement_keys", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["spec_id"], ["demo_game_specs.spec_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("demo_feature_id"),
        sa.UniqueConstraint("spec_id", "feature_key", name="uq_demo_feature_key"),
    )

    op.create_table(
        "demo_game_acceptance_criteria",
        sa.Column("demo_criterion_id", sa.String(length=64), nullable=False),
        sa.Column("demo_requirement_id", sa.String(length=64), nullable=False),
        sa.Column("criterion_key", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("verification_method", sa.String(length=64), nullable=False),
        sa.Column("required_evidence", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["demo_requirement_id"],
            ["demo_game_requirements.demo_requirement_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("demo_criterion_id"),
        sa.UniqueConstraint("demo_requirement_id", "criterion_key", name="uq_demo_criterion_key"),
    )
    op.create_index(
        "ix_demo_game_criteria_requirement",
        "demo_game_acceptance_criteria",
        ["demo_requirement_id", "status"],
    )

    op.create_table(
        "demo_game_test_scenarios",
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("spec_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("scenario_type", sa.String(length=32), nullable=False),
        sa.Column("requirement_keys", sa.Text(), nullable=False),
        sa.Column("steps_json", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["spec_id"], ["demo_game_specs.spec_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("scenario_id"),
        sa.UniqueConstraint("spec_id", "scenario_key", name="uq_demo_scenario_key"),
    )
    op.create_index(
        "ix_demo_game_scenarios_spec", "demo_game_test_scenarios", ["spec_id", "status"]
    )

    op.create_table(
        "demo_game_acceptance_reports",
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("spec_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("known_issues", sa.Text(), nullable=False),
        sa.Column("remaining_risks", sa.Text(), nullable=False),
        sa.Column("follow_up_title", sa.String(length=256), nullable=True),
        sa.Column("reviewer", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["spec_id"], ["demo_game_specs.spec_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id"),
    )
    op.create_index(
        "ix_demo_game_acceptance_project",
        "demo_game_acceptance_reports",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_demo_game_acceptance_project", table_name="demo_game_acceptance_reports")
    op.drop_table("demo_game_acceptance_reports")

    op.drop_index("ix_demo_game_scenarios_spec", table_name="demo_game_test_scenarios")
    op.drop_table("demo_game_test_scenarios")

    op.drop_index("ix_demo_game_criteria_requirement", table_name="demo_game_acceptance_criteria")
    op.drop_table("demo_game_acceptance_criteria")

    op.drop_table("demo_game_features")
    op.drop_table("demo_game_levels")
    op.drop_table("demo_game_mechanics")

    op.drop_index("ix_demo_game_requirements_spec", table_name="demo_game_requirements")
    op.drop_table("demo_game_requirements")

    op.drop_index("ix_demo_game_specs_project", table_name="demo_game_specs")
    op.drop_table("demo_game_specs")
