"""e3 runtime instances

Revision ID: 000009
Revises: 000008
Create Date: 2026-11-20

E3-M6：Runtime 独立通道的实例登记。Runtime 不写编辑器状态表，也不持有 Lease。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000009"
down_revision: str | None = "000008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "e3_runtime_instances",
        sa.Column("runtime_instance_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("editor_session_id", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("godot_version", sa.String(length=32), nullable=True),
        sa.Column("build_mode", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("runtime_instance_id"),
        sa.ForeignKeyConstraint(["project_id"], ["e3_projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["editor_session_id"],
            ["e3_editor_sessions.session_id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_e3_runtime_instances_project_status",
        "e3_runtime_instances",
        ["project_id", "status"],
    )
    op.create_index("ix_e3_runtime_instances_status", "e3_runtime_instances", ["status"])


def downgrade() -> None:
    op.drop_index("ix_e3_runtime_instances_status", table_name="e3_runtime_instances")
    op.drop_index("ix_e3_runtime_instances_project_status", table_name="e3_runtime_instances")
    op.drop_table("e3_runtime_instances")
