"""E9-T16：质量门禁策略、结果与豁免。

Revision ID: 000026
Revises: 000025
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000026"
down_revision: str | None = "000025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_gate_policies",
        sa.Column("gate_policy_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("campaign_type", sa.String(length=16), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=True),
        sa.Column("required_gates_json", sa.Text(), nullable=False),
        sa.Column("waivers_allowed", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("gate_policy_id"),
    )
    op.create_index(
        "ix_quality_gate_policies_project",
        "quality_gate_policies",
        ["project_id", "created_at"],
    )

    op.create_table(
        "quality_gate_results",
        sa.Column("gate_result_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("gate_policy_id", sa.String(length=64), nullable=True),
        sa.Column("gate_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["verification_campaigns.campaign_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["gate_policy_id"],
            ["quality_gate_policies.gate_policy_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("gate_result_id"),
    )
    op.create_index(
        "ix_quality_gate_results_campaign",
        "quality_gate_results",
        ["campaign_id", "evaluated_at"],
    )
    op.create_index(
        "ix_quality_gate_results_project",
        "quality_gate_results",
        ["project_id", "evaluated_at"],
    )

    op.create_table(
        "quality_gate_waivers",
        sa.Column("waiver_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("gate_result_id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("gate_name", sa.String(length=64), nullable=False),
        sa.Column("authorized_by", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk_statement", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=256), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["gate_result_id"],
            ["quality_gate_results.gate_result_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("waiver_id"),
    )
    op.create_index(
        "ix_quality_gate_waivers_gate_result",
        "quality_gate_waivers",
        ["gate_result_id"],
    )
    op.create_index(
        "ix_quality_gate_waivers_campaign_gate",
        "quality_gate_waivers",
        ["campaign_id", "gate_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_quality_gate_waivers_campaign_gate", table_name="quality_gate_waivers")
    op.drop_index("ix_quality_gate_waivers_gate_result", table_name="quality_gate_waivers")
    op.drop_table("quality_gate_waivers")

    op.drop_index("ix_quality_gate_results_project", table_name="quality_gate_results")
    op.drop_index("ix_quality_gate_results_campaign", table_name="quality_gate_results")
    op.drop_table("quality_gate_results")

    op.drop_index("ix_quality_gate_policies_project", table_name="quality_gate_policies")
    op.drop_table("quality_gate_policies")
