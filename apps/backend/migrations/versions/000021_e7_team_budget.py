"""E7-T18 / T20：团队预算分配记录与 Handoff 拒绝原因。

Revision ID: 000021
Revises: 000020
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000021"
down_revision: str | None = "000020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_team_budgets",
        sa.Column(
            "allocation_log_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "agent_handoffs",
        sa.Column("rejection_reason", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_handoffs", "rejection_reason")
    op.drop_column("agent_team_budgets", "allocation_log_json")
