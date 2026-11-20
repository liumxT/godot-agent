"""e3 events and snapshots

Revision ID: 000008
Revises: 000007
Create Date: 2026-11-20

E3-M4：Bridge 事件（只持久化 PERSISTENT）与编辑器基准快照。
Runtime 表（e3_runtime_instances）由 E3-M6 补充，本迁移不提前创建。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000008"
down_revision: str | None = "000007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "e3_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["e3_editor_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["e3_projects.project_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_e3_events_session_sequence",
        "e3_events",
        ["session_id", "sequence"],
    )
    op.create_index("ix_e3_events_created_at", "e3_events", ["created_at"])

    op.create_table(
        "e3_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("editor_instance_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("last_event_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["e3_editor_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["e3_projects.project_id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "session_id",
            "snapshot_version",
            name="uq_e3_snapshots_session_version",
        ),
    )
    op.create_index(
        "ix_e3_snapshots_session_created",
        "e3_snapshots",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_e3_snapshots_session_created", table_name="e3_snapshots")
    op.drop_table("e3_snapshots")
    op.drop_index("ix_e3_events_created_at", table_name="e3_events")
    op.drop_index("ix_e3_events_session_sequence", table_name="e3_events")
    op.drop_table("e3_events")
