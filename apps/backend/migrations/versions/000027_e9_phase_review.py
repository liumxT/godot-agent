"""E9-T17：Phase Review 与用户验收决策。

Revision ID: 000027
Revises: 000026
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000027"
down_revision: str | None = "000026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phase_reviews",
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("phase_id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.String(length=32), nullable=False),
        sa.Column("submitted_by", sa.String(length=64), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["verification_campaigns.campaign_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("review_id"),
    )
    op.create_index(
        "ix_phase_reviews_project_phase",
        "phase_reviews",
        ["project_id", "workflow_id", "phase_id"],
    )
    op.create_index("ix_phase_reviews_campaign", "phase_reviews", ["campaign_id"])

    op.create_table(
        "phase_review_decisions",
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["phase_reviews.review_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index(
        "ix_phase_review_decisions_review",
        "phase_review_decisions",
        ["review_id", "decided_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_phase_review_decisions_review", table_name="phase_review_decisions")
    op.drop_table("phase_review_decisions")

    op.drop_index("ix_phase_reviews_campaign", table_name="phase_reviews")
    op.drop_index("ix_phase_reviews_project_phase", table_name="phase_reviews")
    op.drop_table("phase_reviews")
