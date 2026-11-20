"""clients and authentication

Revision ID: 000004
Revises: 000003
Create Date: 2026-11-18

E2-T06 / T03 / T04：客户端注册、一次性认证挑战与 Access Token。
数据库只存 client_secret 的状态与 Token 的 SHA-256 摘要；明文分别位于
操作系统凭证库与注册/认证响应中。

说明：认证挑战需要服务端重算 HMAC，因此持久化 nonce 本身（``challenge``），
它是一次性随机值而非凭证；``used_at`` 保证只能消费一次。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000004"
down_revision: str | None = "000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "e2_clients",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("client_type", sa.String(length=32), nullable=False),
        sa.Column("client_name", sa.String(length=128), nullable=False),
        sa.Column("client_version", sa.String(length=64), nullable=True),
        sa.Column("godot_version", sa.String(length=64), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_index("ix_e2_clients_status", "e2_clients", ["status"])

    op.create_table(
        "e2_client_credentials",
        sa.Column("credential_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("credential_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["e2_clients.client_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("credential_id"),
    )
    op.create_index("ix_e2_client_credentials_client_id", "e2_client_credentials", ["client_id"])

    op.create_table(
        "e2_auth_challenges",
        sa.Column("challenge_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("challenge", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["e2_clients.client_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("challenge_id"),
    )
    op.create_index(
        "ix_e2_auth_challenges_client_status",
        "e2_auth_challenges",
        ["client_id", "status"],
    )

    op.create_table(
        "e2_access_tokens",
        sa.Column("token_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["e2_clients.client_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_e2_access_tokens_client_id", "e2_access_tokens", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_e2_access_tokens_client_id", table_name="e2_access_tokens")
    op.drop_table("e2_access_tokens")
    op.drop_index("ix_e2_auth_challenges_client_status", table_name="e2_auth_challenges")
    op.drop_table("e2_auth_challenges")
    op.drop_index("ix_e2_client_credentials_client_id", table_name="e2_client_credentials")
    op.drop_table("e2_client_credentials")
    op.drop_index("ix_e2_clients_status", table_name="e2_clients")
    op.drop_table("e2_clients")
