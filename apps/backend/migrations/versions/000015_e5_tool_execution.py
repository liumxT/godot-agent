"""e5 tool execution

Revision ID: 000015
Revises: 000014
Create Date: 2026-11-20

E5-T22 / T23 / T24 / T25 / T26：工具执行、资源锁、工具审计与结果验证。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000015"
down_revision: str | None = "000014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_executions",
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("tool_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_version", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=4), nullable=False),
        sa.Column("input_payload", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("changeset_id", sa.String(length=64), nullable=True),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("resource_scope", sa.Text(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("output_payload", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("evidence_refs", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    op.create_index("ix_tool_executions_project", "tool_executions", ["project_id", "status"])
    op.create_index(
        "ix_tool_executions_idempotency", "tool_executions", ["project_id", "idempotency_key"]
    )
    op.create_index("ix_tool_executions_task", "tool_executions", ["task_id"])

    op.create_table(
        "resource_locks",
        sa.Column("lock_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("resource_key", sa.String(length=512), nullable=False),
        sa.Column("owner_type", sa.String(length=16), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("lock_type", sa.String(length=16), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("lock_id"),
    )
    op.create_index(
        "ix_resource_locks_resource", "resource_locks", ["project_id", "resource_key", "status"]
    )
    op.create_index("ix_resource_locks_expires", "resource_locks", ["expires_at"])

    op.create_table(
        "tool_audit_records",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("tool_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_version", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=4), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("execution_status", sa.String(length=16), nullable=False),
        sa.Column("failure_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index("ix_tool_audit_project", "tool_audit_records", ["project_id", "created_at"])
    op.create_index("ix_tool_audit_execution", "tool_audit_records", ["execution_id"])

    op.create_table(
        "tool_verification_results",
        sa.Column("verification_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False),
        sa.Column("checks", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["tool_executions.execution_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("verification_id"),
    )
    op.create_index(
        "ix_tool_verification_execution",
        "tool_verification_results",
        ["execution_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_verification_execution", table_name="tool_verification_results")
    op.drop_table("tool_verification_results")
    op.drop_index("ix_tool_audit_execution", table_name="tool_audit_records")
    op.drop_index("ix_tool_audit_project", table_name="tool_audit_records")
    op.drop_table("tool_audit_records")
    op.drop_index("ix_resource_locks_expires", table_name="resource_locks")
    op.drop_index("ix_resource_locks_resource", table_name="resource_locks")
    op.drop_table("resource_locks")
    op.drop_index("ix_tool_executions_task", table_name="tool_executions")
    op.drop_index("ix_tool_executions_idempotency", table_name="tool_executions")
    op.drop_index("ix_tool_executions_project", table_name="tool_executions")
    op.drop_table("tool_executions")
