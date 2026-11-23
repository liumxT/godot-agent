"""e7 multi agent domain

Revision ID: 000019
Revises: 000018
Create Date: 2026-11-23

E7-T01：Capability / Team / Member / Assignment / Dependency / Handoff /
Collaboration / Message / Conflict / Integration / Review / Team Budget /
Shared Context 基础表。

约束：Assignment 必须绑定 Team、Task 与 Attempt；Team 状态不替代 Task 状态；
重要记录只追加，不通过删除隐藏执行失败。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000019"
down_revision: str | None = "000018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_capabilities",
        sa.Column("capability_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("input_contract", sa.String(length=128), nullable=True),
        sa.Column("output_contract", sa.String(length=128), nullable=True),
        sa.Column("required_tools", sa.Text(), nullable=False),
        sa.Column("required_model_capabilities", sa.Text(), nullable=False),
        sa.Column("dependencies", sa.Text(), nullable=False),
        sa.Column("risk_profile", sa.String(length=4), nullable=False),
        sa.Column("validation_method", sa.String(length=128), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("capability_id"),
        sa.UniqueConstraint("name", name="uq_agent_capabilities_name"),
    )
    op.create_index(
        "ix_agent_capabilities_category", "agent_capabilities", ["category", "enabled"]
    )

    op.create_table(
        "agent_teams",
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("lead_agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("team_policy_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["task_attempts.attempt_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("team_id"),
    )
    op.create_index("ix_agent_teams_task_status", "agent_teams", ["task_id", "status"])
    op.create_index("ix_agent_teams_project_status", "agent_teams", ["project_id", "status"])

    op.create_table(
        "agent_assignments",
        sa.Column("assignment_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("agent_definition_id", sa.String(length=64), nullable=False),
        sa.Column("agent_definition_version", sa.String(length=32), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("parent_assignment_id", sa.String(length=64), nullable=True),
        sa.Column("assigned_objective", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("input_reference", sa.String(length=128), nullable=True),
        sa.Column("output_reference", sa.String(length=128), nullable=True),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False),
        sa.Column("dependencies", sa.Text(), nullable=False),
        sa.Column("required_capabilities", sa.Text(), nullable=False),
        sa.Column("required_tools", sa.Text(), nullable=False),
        sa.Column("permission_requirements", sa.Text(), nullable=False),
        sa.Column("budget_json", sa.Text(), nullable=False),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("risk_level", sa.String(length=4), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("assigned_by", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"], ["agent_definitions.definition_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["task_attempts.attempt_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assignment_id"),
    )
    op.create_index(
        "ix_agent_assignments_team_status", "agent_assignments", ["team_id", "status"]
    )
    op.create_index(
        "ix_agent_assignments_task_status", "agent_assignments", ["task_id", "status"]
    )
    op.create_index("ix_agent_assignments_instance", "agent_assignments", ["agent_instance_id"])

    op.create_table(
        "agent_team_members",
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("assignment_id", sa.String(length=64), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["agent_assignments.assignment_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("member_id"),
        sa.UniqueConstraint("assignment_id", name="uq_agent_team_member_assignment"),
    )
    op.create_index("ix_agent_team_members_team", "agent_team_members", ["team_id", "role"])

    op.create_table(
        "agent_assignment_dependencies",
        sa.Column("dependency_id", sa.String(length=64), nullable=False),
        sa.Column("assignment_id", sa.String(length=64), nullable=False),
        sa.Column("depends_on_assignment_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["agent_assignments.assignment_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_assignment_id"], ["agent_assignments.assignment_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("dependency_id"),
        sa.UniqueConstraint(
            "assignment_id",
            "depends_on_assignment_id",
            name="uq_agent_assignment_dependency",
        ),
    )

    op.create_table(
        "agent_handoffs",
        sa.Column("handoff_id", sa.String(length=64), nullable=False),
        sa.Column("source_assignment_id", sa.String(length=64), nullable=False),
        sa.Column("target_assignment_id", sa.String(length=64), nullable=True),
        sa.Column("source_agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("target_agent_definition_id", sa.String(length=64), nullable=False),
        sa.Column("handoff_type", sa.String(length=32), nullable=False),
        sa.Column("handoff_payload_reference", sa.String(length=128), nullable=False),
        sa.Column("context_snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("approval_reference", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by_assignment_id", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_assignment_id"], ["agent_assignments.assignment_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_agent_definition_id"],
            ["agent_definitions.definition_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("handoff_id"),
    )
    op.create_index("ix_agent_handoffs_source", "agent_handoffs", ["source_assignment_id", "status"])

    op.create_table(
        "agent_collaborations",
        sa.Column("collaboration_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("participant_assignments", sa.Text(), nullable=False),
        sa.Column("shared_context_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collaboration_id"),
    )
    op.create_index(
        "ix_agent_collaborations_team", "agent_collaborations", ["team_id", "status"]
    )

    op.create_table(
        "agent_messages",
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("source_assignment_id", sa.String(length=64), nullable=True),
        sa.Column("target_assignment_id", sa.String(length=64), nullable=True),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("payload_reference", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint("team_id", "sequence_number", name="uq_agent_message_sequence"),
    )
    op.create_index("ix_agent_messages_correlation", "agent_messages", ["correlation_id"])
    op.create_index(
        "ix_agent_messages_target", "agent_messages", ["target_assignment_id", "consumed_at"]
    )

    op.create_table(
        "agent_conflicts",
        sa.Column("conflict_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("conflicting_assignments", sa.Text(), nullable=False),
        sa.Column("conflict_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("resolution_status", sa.String(length=16), nullable=False),
        sa.Column("resolution_reference", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conflict_id"),
    )
    op.create_index(
        "ix_agent_conflicts_team", "agent_conflicts", ["team_id", "resolution_status"]
    )

    op.create_table(
        "agent_integrations",
        sa.Column("integration_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("source_assignment_ids", sa.Text(), nullable=False),
        sa.Column("integration_owner", sa.String(length=64), nullable=True),
        sa.Column("integration_plan", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verification_reference", sa.String(length=128), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("integration_id"),
    )
    op.create_index("ix_agent_integrations_team", "agent_integrations", ["team_id", "status"])

    op.create_table(
        "agent_reviews",
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("target_assignment_id", sa.String(length=64), nullable=False),
        sa.Column("reviewer_assignment_id", sa.String(length=64), nullable=True),
        sa.Column("review_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("findings", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("evidence_reference", sa.String(length=128), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("acceptance_status", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["target_assignment_id"], ["agent_assignments.assignment_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("review_id"),
    )
    op.create_index(
        "ix_agent_reviews_target", "agent_reviews", ["target_assignment_id", "status"]
    )

    op.create_table(
        "agent_team_budgets",
        sa.Column("budget_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("budget_json", sa.Text(), nullable=False),
        sa.Column("usage_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("budget_id"),
        sa.UniqueConstraint("team_id", name="uq_agent_team_budget_team"),
    )

    op.create_table(
        "agent_shared_context",
        sa.Column("context_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("context_version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("content_reference", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_assignment_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("superseded_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.team_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("context_id"),
        sa.UniqueConstraint(
            "team_id", "context_version", name="uq_agent_shared_context_version"
        ),
    )
    op.create_index(
        "ix_agent_shared_context_team", "agent_shared_context", ["team_id", "status"]
    )


def downgrade() -> None:
    op.drop_table("agent_shared_context")
    op.drop_table("agent_team_budgets")
    op.drop_table("agent_reviews")
    op.drop_table("agent_integrations")
    op.drop_table("agent_conflicts")
    op.drop_table("agent_messages")
    op.drop_table("agent_collaborations")
    op.drop_table("agent_handoffs")
    op.drop_table("agent_assignment_dependencies")
    op.drop_table("agent_team_members")
    op.drop_table("agent_assignments")
    op.drop_table("agent_teams")
    op.drop_table("agent_capabilities")
