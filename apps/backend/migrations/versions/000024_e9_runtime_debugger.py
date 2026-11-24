"""E9-T08 / T09 / T10：运行时环境、功能测试字段与 Debugger 错误表。

Revision ID: 000024
Revises: 000023
Create Date: 2026-11-24

约束：
- 运行时环境独立记录，环境故障不得伪装成功能通过；
- TestCase 补齐 setup / cleanup / timeout / evidence 要求；
- Debugger 错误按 fingerprint 聚合，用 is_baseline 区分历史问题。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000024"
down_revision: str | None = "000023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("verification_test_cases") as batch:
        batch.add_column(sa.Column("setup_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("cleanup_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(
            sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300")
        )
        batch.add_column(
            sa.Column(
                "evidence_requirements_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )

    op.create_table(
        "verification_runtime_environments",
        sa.Column("environment_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("project_revision", sa.String(length=128), nullable=False),
        sa.Column("godot_version", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("display_resolution", sa.String(length=32), nullable=False),
        sa.Column("renderer", sa.String(length=32), nullable=False),
        sa.Column("runtime_instance_id", sa.String(length=128), nullable=True),
        sa.Column("test_configuration_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("environment_id"),
    )
    op.create_index(
        "ix_verification_runtime_environments_project_status",
        "verification_runtime_environments",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_verification_runtime_environments_instance",
        "verification_runtime_environments",
        ["runtime_instance_id"],
    )

    op.create_table(
        "verification_debugger_errors",
        sa.Column("error_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("scene", sa.String(length=256), nullable=True),
        sa.Column("node", sa.String(length=256), nullable=True),
        sa.Column("script", sa.String(length=512), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("runtime_instance_id", sa.String(length=128), nullable=True),
        sa.Column("godot_version", sa.String(length=32), nullable=True),
        sa.Column("project_revision", sa.String(length=128), nullable=True),
        sa.Column("changeset_id", sa.String(length=64), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("is_baseline", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["verification_runs.run_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("error_id"),
        sa.UniqueConstraint(
            "project_id", "fingerprint", name="uq_verification_debugger_error_fingerprint"
        ),
    )
    op.create_index(
        "ix_verification_debugger_errors_project_status",
        "verification_debugger_errors",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_verification_debugger_errors_project_severity",
        "verification_debugger_errors",
        ["project_id", "severity"],
    )
    op.create_index(
        "ix_verification_debugger_errors_run", "verification_debugger_errors", ["run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_verification_debugger_errors_run", table_name="verification_debugger_errors")
    op.drop_index(
        "ix_verification_debugger_errors_project_severity",
        table_name="verification_debugger_errors",
    )
    op.drop_index(
        "ix_verification_debugger_errors_project_status",
        table_name="verification_debugger_errors",
    )
    op.drop_table("verification_debugger_errors")

    op.drop_index(
        "ix_verification_runtime_environments_instance",
        table_name="verification_runtime_environments",
    )
    op.drop_index(
        "ix_verification_runtime_environments_project_status",
        table_name="verification_runtime_environments",
    )
    op.drop_table("verification_runtime_environments")

    with op.batch_alter_table("verification_test_cases") as batch:
        batch.drop_column("evidence_requirements_json")
        batch.drop_column("timeout_seconds")
        batch.drop_column("cleanup_json")
        batch.drop_column("setup_json")
