"""e6 agent client binding

Revision ID: 000017
Revises: 000016
Create Date: 2026-11-23

Agent Instance 与配置快照需要保存发起会话的 Client，用于 Tool System 的
Session + Client 双重访问校验。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000017"
down_revision: str | None = "000016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_config_snapshots", sa.Column("client_id", sa.String(length=64), nullable=True)
    )
    op.add_column("agent_instances", sa.Column("client_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_instances", "client_id")
    op.drop_column("agent_config_snapshots", "client_id")
