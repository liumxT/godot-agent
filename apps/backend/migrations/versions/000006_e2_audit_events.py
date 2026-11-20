"""audit events

Revision ID: 000006
Revises: 000005
Create Date: 2026-11-18

E2-T11：审计事件表。审计只追加、不修改；``details`` 保存脱敏后的 JSON 文本。
不对 client/session 建外键，避免凭证清理影响审计历史。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000006"
down_revision: str | None = "000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "e2_audit_events",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource", sa.String(length=128), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index("ix_e2_audit_events_timestamp", "e2_audit_events", ["timestamp"])
    op.create_index(
        "ix_e2_audit_events_client_timestamp",
        "e2_audit_events",
        ["client_id", "timestamp"],
    )
    op.create_index("ix_e2_audit_events_action", "e2_audit_events", ["action"])


def downgrade() -> None:
    op.drop_index("ix_e2_audit_events_action", table_name="e2_audit_events")
    op.drop_index("ix_e2_audit_events_client_timestamp", table_name="e2_audit_events")
    op.drop_index("ix_e2_audit_events_timestamp", table_name="e2_audit_events")
    op.drop_table("e2_audit_events")
