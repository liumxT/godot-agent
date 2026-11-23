"""e6 agent budget usage

Revision ID: 000018
Revises: 000017
Create Date: 2026-11-23

Execution 需要持久化预算用量，恢复后才能继续按同一 Budget Profile 结算，
不允许重启后重置预算或自动放宽。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000018"
down_revision: str | None = "000017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_executions",
        sa.Column(
            "budget_usage_json", sa.Text(), nullable=False, server_default="{}"
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_executions", "budget_usage_json")
