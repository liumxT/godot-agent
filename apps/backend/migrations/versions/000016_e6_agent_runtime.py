"""e6 agent runtime domain

Revision ID: 000016
Revises: 000015
Create Date: 2026-11-23

E6-T01：Agent Definition / Version / Instance / Config Snapshot /
Execution / Plan / Step / Checkpoint / Event 基础表。

约束：Definition Version 只追加；Event 只追加；Instance 的配置必须来自
已冻结的 Config Snapshot。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000016"
down_revision: str | None = "000015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_definitions",
        sa.Column("definition_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_version", sa.String(length=32), nullable=True),
        sa.Column("supported_capabilities", sa.Text(), nullable=False),
        sa.Column("model_policy_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_profile_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("context_profile_id", sa.String(length=64), nullable=False),
        sa.Column("context_profile_version", sa.String(length=32), nullable=False),
        sa.Column("tool_whitelist", sa.Text(), nullable=False),
        sa.Column("permission_ceiling", sa.String(length=4), nullable=False),
        sa.Column("budget_profile_id", sa.String(length=64), nullable=False),
        sa.Column("budget_json", sa.Text(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("definition_id"),
        sa.UniqueConstraint("name", name="uq_agent_definitions_name"),
    )
    op.create_index("ix_agent_definitions_status", "agent_definitions", ["status"])

    op.create_table(
        "agent_definition_versions",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("agent_definition_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by", sa.String(length=64), nullable=True),
        sa.Column("compatibility_metadata", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"], ["agent_definitions.definition_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint(
            "agent_definition_id", "version", name="uq_agent_definition_version"
        ),
    )
    op.create_index(
        "ix_agent_definition_versions_def",
        "agent_definition_versions",
        ["agent_definition_id", "published_at"],
    )

    op.create_table(
        "agent_config_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("agent_definition_id", sa.String(length=64), nullable=False),
        sa.Column("agent_version", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("model_policy_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=True),
        sa.Column("prompt_profile_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("context_profile_id", sa.String(length=64), nullable=False),
        sa.Column("context_profile_version", sa.String(length=32), nullable=False),
        sa.Column("tool_whitelist", sa.Text(), nullable=False),
        sa.Column("permission_ceiling", sa.String(length=4), nullable=False),
        sa.Column("budget_json", sa.Text(), nullable=False),
        sa.Column("runtime_policy_version", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"], ["agent_definitions.definition_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index(
        "ix_agent_config_snapshots_def", "agent_config_snapshots", ["agent_definition_id"]
    )
    op.create_index(
        "ix_agent_config_snapshots_project", "agent_config_snapshots", ["project_id"]
    )

    op.create_table(
        "agent_instances",
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("agent_definition_id", sa.String(length=64), nullable=False),
        sa.Column("agent_version", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("config_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("termination_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"], ["agent_definitions.definition_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["task_attempts.attempt_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["config_snapshot_id"],
            ["agent_config_snapshots.snapshot_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    op.create_index(
        "ix_agent_instances_project_status", "agent_instances", ["project_id", "status"]
    )
    op.create_index("ix_agent_instances_attempt", "agent_instances", ["attempt_id"])

    op.create_table(
        "agent_executions",
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("execution_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_checkpoint_id", sa.String(length=64), nullable=True),
        sa.Column("termination_reason", sa.String(length=128), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_instance_id"], ["agent_instances.instance_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("execution_id"),
        sa.UniqueConstraint(
            "agent_instance_id", "execution_number", name="uq_agent_execution_number"
        ),
    )
    op.create_index(
        "ix_agent_executions_instance_status",
        "agent_executions",
        ["agent_instance_id", "status"],
    )

    op.create_table(
        "agent_plans",
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("supersedes_plan_id", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_instance_id"], ["agent_instances.instance_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["agent_executions.execution_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("plan_id"),
        sa.UniqueConstraint(
            "execution_id", "plan_version", name="uq_agent_plan_version"
        ),
    )
    op.create_index("ix_agent_plans_execution", "agent_plans", ["execution_id", "status"])

    op.create_table(
        "agent_steps",
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=24), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("dependencies", sa.Text(), nullable=False),
        sa.Column("input_reference", sa.String(length=128), nullable=True),
        sa.Column("output_reference", sa.String(length=128), nullable=True),
        sa.Column("tool_execution_id", sa.String(length=64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["agent_plans.plan_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["agent_executions.execution_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("step_id"),
        sa.UniqueConstraint("plan_id", "step_number", name="uq_agent_step_number"),
    )
    op.create_index(
        "ix_agent_steps_execution_status", "agent_steps", ["execution_id", "status"]
    )

    op.create_table(
        "agent_checkpoints",
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=True),
        sa.Column("last_completed_step_id", sa.String(length=64), nullable=True),
        sa.Column("current_step_id", sa.String(length=64), nullable=True),
        sa.Column("state_snapshot", sa.Text(), nullable=False),
        sa.Column("budget_snapshot", sa.Text(), nullable=False),
        sa.Column("context_snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("last_event_sequence", sa.Integer(), nullable=False),
        sa.Column("checkpoint_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_instance_id"], ["agent_instances.instance_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["agent_executions.execution_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("checkpoint_id"),
    )
    op.create_index(
        "ix_agent_checkpoints_instance",
        "agent_checkpoints",
        ["agent_instance_id", "checkpoint_version"],
    )
    op.create_index("ix_agent_checkpoints_execution", "agent_checkpoints", ["execution_id"])

    op.create_table(
        "agent_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("event_payload", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_instance_id"], ["agent_instances.instance_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint(
            "agent_instance_id", "sequence_number", name="uq_agent_event_sequence"
        ),
    )
    op.create_index(
        "ix_agent_events_instance", "agent_events", ["agent_instance_id", "sequence_number"]
    )
    op.create_index(
        "ix_agent_events_execution", "agent_events", ["execution_id", "sequence_number"]
    )


def downgrade() -> None:
    op.drop_table("agent_events")
    op.drop_table("agent_checkpoints")
    op.drop_table("agent_steps")
    op.drop_table("agent_plans")
    op.drop_table("agent_executions")
    op.drop_table("agent_instances")
    op.drop_table("agent_config_snapshots")
    op.drop_table("agent_definition_versions")
    op.drop_table("agent_definitions")
