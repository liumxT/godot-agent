"""migration history

Revision ID: 000002
Revises: 000001
Create Date: 2026-11-18

新增迁移审计表。Alembic 的 ``alembic_version`` 仍是版本事实源，
``migration_history`` 只记录执行审计（checksum、耗时、失败摘要）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000002"
down_revision: str | None = "000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "migration_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("revision", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_migration_history_revision_applied_at",
        "migration_history",
        ["revision", "applied_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_migration_history_revision_applied_at", table_name="migration_history")
    op.drop_table("migration_history")
