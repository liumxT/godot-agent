"""event infrastructure

Revision ID: 000003
Revises: 000002
Create Date: 2026-11-18

Outbox 与 Inbox：业务事务只写 Outbox，提交后由 EventDispatcher 轮询派发；
消费方通过 Inbox 记录 ``(event_id, consumer_id)`` 实现至少一次投递下的幂等。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000003"
down_revision: str | None = "000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("event_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_event_outbox_status_id", "event_outbox", ["status", "id"])

    op.create_table(
        "event_inbox",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("consumer_id", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'processed'"),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("event_id", "consumer_id"),
    )


def downgrade() -> None:
    op.drop_table("event_inbox")
    op.drop_index("ix_event_outbox_status_id", table_name="event_outbox")
    op.drop_table("event_outbox")
