"""e5 tool registry

Revision ID: 000014
Revises: 000013
Create Date: 2026-11-20

E5-T17 / T18 / T20：工具定义版本、输入输出 Schema、风险等级与执行约束。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000014"
down_revision: str | None = "000013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_definitions",
        sa.Column("tool_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.Text(), nullable=False),
        sa.Column("output_schema", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=4), nullable=False),
        sa.Column("required_capabilities", sa.Text(), nullable=False),
        sa.Column("required_permissions", sa.Text(), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("idempotency_policy", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tool_id"),
        sa.UniqueConstraint("name", "version", name="uq_tool_definitions_name_version"),
    )
    op.create_index("ix_tool_definitions_name", "tool_definitions", ["name", "version"])


def downgrade() -> None:
    op.drop_index("ix_tool_definitions_name", table_name="tool_definitions")
    op.drop_table("tool_definitions")
