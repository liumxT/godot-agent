"""sessions and project access

Revision ID: 000005
Revises: 000004
Create Date: 2026-11-18

E2-T05 / T07：Session 与 Project Access。
Session 只存 ``gds_`` Token 的 SHA-256 摘要；Project Access 同时绑定
client_id 与 session_id，用于服务端项目范围校验。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000005"
down_revision: str | None = "000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "e2_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'ACTIVE'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["e2_clients.client_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_e2_sessions_client_id", "e2_sessions", ["client_id"])
    op.create_index("ix_e2_sessions_status", "e2_sessions", ["status"])

    op.create_table(
        "e2_project_access",
        sa.Column("access_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("access_level", sa.String(length=16), nullable=False),
        sa.Column("granted_by", sa.String(length=64), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'ACTIVE'"), nullable=False
        ),
        sa.ForeignKeyConstraint(["client_id"], ["e2_clients.client_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["e2_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("access_id"),
    )
    op.create_index(
        "ix_e2_project_access_client_project_status",
        "e2_project_access",
        ["client_id", "project_id", "status"],
    )
    op.create_index("ix_e2_project_access_session_id", "e2_project_access", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_e2_project_access_session_id", table_name="e2_project_access")
    op.drop_index("ix_e2_project_access_client_project_status", table_name="e2_project_access")
    op.drop_table("e2_project_access")
    op.drop_index("ix_e2_sessions_status", table_name="e2_sessions")
    op.drop_index("ix_e2_sessions_client_id", table_name="e2_sessions")
    op.drop_table("e2_sessions")
