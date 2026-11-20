"""e3 editor bridge

Revision ID: 000007
Revises: 000006
Create Date: 2026-11-20

E3-M3：项目身份、Editor 绑定、Session 租约与项目级 Fencing。
事件、快照与 Runtime 表（e3_events / e3_snapshots / e3_runtime_instances）
由后续批次补充，本迁移不提前创建。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000007"
down_revision: str | None = "000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "e3_projects",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("project_root", sa.String(length=1024), nullable=False),
        sa.Column("project_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("project_name", sa.String(length=256), nullable=False),
        sa.Column("godot_version", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("project_id"),
        sa.UniqueConstraint("project_root", name="uq_e3_projects_project_root"),
    )
    op.create_index("ix_e3_projects_fingerprint", "e3_projects", ["project_fingerprint"])

    op.create_table(
        "e3_editor_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("editor_instance_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("godot_version", sa.String(length=32), nullable=True),
        sa.Column("plugin_version", sa.String(length=32), nullable=True),
        sa.Column("transport", sa.String(length=16), nullable=False),
        sa.Column("binding_status", sa.String(length=16), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
        sa.ForeignKeyConstraint(["session_id"], ["e2_sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["e3_projects.project_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_e3_editor_sessions_project_status",
        "e3_editor_sessions",
        ["project_id", "binding_status"],
    )
    op.create_index(
        "ix_e3_editor_sessions_editor_instance",
        "e3_editor_sessions",
        ["editor_instance_id"],
    )

    op.create_table(
        "e3_session_leases",
        sa.Column("lease_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("lease_id"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["e3_editor_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["e3_projects.project_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_e3_session_leases_session_status",
        "e3_session_leases",
        ["session_id", "status"],
    )
    op.create_index(
        "ix_e3_session_leases_project_status",
        "e3_session_leases",
        ["project_id", "status"],
    )

    op.create_table(
        "e3_project_fencing",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("last_token", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
        sa.ForeignKeyConstraint(["project_id"], ["e3_projects.project_id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("e3_project_fencing")
    op.drop_index("ix_e3_session_leases_project_status", table_name="e3_session_leases")
    op.drop_index("ix_e3_session_leases_session_status", table_name="e3_session_leases")
    op.drop_table("e3_session_leases")
    op.drop_index("ix_e3_editor_sessions_editor_instance", table_name="e3_editor_sessions")
    op.drop_index("ix_e3_editor_sessions_project_status", table_name="e3_editor_sessions")
    op.drop_table("e3_editor_sessions")
    op.drop_index("ix_e3_projects_fingerprint", table_name="e3_projects")
    op.drop_table("e3_projects")
