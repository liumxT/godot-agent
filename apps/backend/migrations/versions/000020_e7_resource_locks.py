"""E7-T11：资源锁与冲突解决字段。

Revision ID: 000020
Revises: 000019
Create Date: 2026-11-23

- ``agent_resource_locks``：资源级 READ/WRITE 锁与 Fencing Token；
- ``agent_conflicts`` 增加解决策略与解决人字段。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000020"
down_revision: str | None = "000019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_resource_locks",
        sa.Column("lock_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("assignment_id", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_key", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["agent_assignments.assignment_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("lock_id"),
    )
    op.create_index(
        "ix_agent_resource_locks_resource",
        "agent_resource_locks",
        ["resource_key", "status"],
    )
    op.create_index(
        "ix_agent_resource_locks_assignment",
        "agent_resource_locks",
        ["assignment_id", "status"],
    )
    op.create_index(
        "uq_agent_resource_locks_active_write",
        "agent_resource_locks",
        ["resource_key"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE' AND mode = 'WRITE'"),
        postgresql_where=sa.text("status = 'ACTIVE' AND mode = 'WRITE'"),
    )

    op.add_column(
        "agent_conflicts",
        sa.Column("resolution_strategy", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_conflicts",
        sa.Column("resolved_by", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_conflicts", "resolved_by")
    op.drop_column("agent_conflicts", "resolution_strategy")
    op.drop_index("uq_agent_resource_locks_active_write", table_name="agent_resource_locks")
    op.drop_index("ix_agent_resource_locks_assignment", table_name="agent_resource_locks")
    op.drop_index("ix_agent_resource_locks_resource", table_name="agent_resource_locks")
    op.drop_table("agent_resource_locks")
