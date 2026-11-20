"""e4 project & workflow systems

Revision ID: 000010
Revises: 000009
Create Date: 2026-11-20

E4：Project / Task / Workflow / Requirement / ChangeSet / Approval 全部业务表。
状态权威按模块划分：``projects`` 归 Project，``tasks`` 归 Task，
``workflow_*`` 归 Workflow，``change_sets`` 归 ChangeSet，
``approvals`` 归 Approval，``requirements`` 归 Requirement Tracking。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000010"
down_revision: str | None = "000009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SERVER_DEFAULT = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("project_root", sa.String(length=1024), nullable=False),
        sa.Column("project_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("godot_version", sa.String(length=32), nullable=True),
        sa.Column("project_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("configuration_id", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("project_id"),
        sa.UniqueConstraint("project_root", name="uq_projects_root"),
    )
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_index("ix_projects_fingerprint", "projects", ["project_fingerprint"])

    op.create_table(
        "project_identities",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_algorithm", sa.String(length=32), nullable=False),
        sa.Column("fingerprint_value", sa.String(length=64), nullable=False),
        sa.Column("project_config_path", sa.String(length=1024), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "project_configurations",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("default_game_type", sa.String(length=32), nullable=True),
        sa.Column("default_language", sa.String(length=32), nullable=True),
        sa.Column("preferred_rendering_method", sa.String(length=32), nullable=True),
        sa.Column("target_platforms", sa.Text(), nullable=True),
        sa.Column("godot_version_policy", sa.String(length=32), nullable=True),
        sa.Column("default_ai_model", sa.String(length=64), nullable=True),
        sa.Column("default_agent_profile", sa.String(length=64), nullable=True),
        sa.Column("coding_conventions", sa.Text(), nullable=True),
        sa.Column("naming_conventions", sa.Text(), nullable=True),
        sa.Column("asset_policy", sa.Text(), nullable=True),
        sa.Column("verification_policy", sa.Text(), nullable=True),
        sa.Column("approval_policy", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "project_configuration_versions",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "version_no", name="uq_config_version"),
    )

    op.create_table(
        "project_memberships",
        sa.Column("membership_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "client_id", name="uq_project_member"),
    )

    op.create_table(
        "workflow_definitions",
        sa.Column("definition_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("definition_id"),
    )

    op.create_table(
        "workflow_definition_versions",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("definition_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version_id"),
        sa.ForeignKeyConstraint(
            ["definition_id"], ["workflow_definitions.definition_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("definition_id", "version", name="uq_workflow_version"),
    )

    op.create_table(
        "workflow_node_definitions",
        sa.Column("node_definition_id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("config", sa.Text(), nullable=True),
        sa.Column("next_node_rules", sa.Text(), nullable=True),
        sa.Column("dependency_keys", sa.Text(), nullable=True),
        sa.Column("phase_key", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("node_definition_id"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["workflow_definition_versions.version_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("version_id", "node_key", name="uq_node_definition_key"),
    )

    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("parent_task_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("assigned_to", sa.String(length=64), nullable=True),
        sa.Column("workflow_instance_id", sa.String(length=64), nullable=True),
        sa.Column("requirement_set_id", sa.String(length=64), nullable=True),
        sa.Column("current_attempt_id", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("task_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_task_id"], ["tasks.task_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tasks_project_status", "tasks", ["project_id", "status"])
    op.create_index("ix_tasks_parent", "tasks", ["parent_task_id"])

    op.create_table(
        "task_attempts",
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_instance_id", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=True),
        sa.Column("execution_summary", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("resource_usage", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "attempt_number", name="uq_attempt_number"),
    )
    op.create_index("ix_task_attempts_task", "task_attempts", ["task_id", "status"])

    op.create_table(
        "task_dependencies",
        sa.Column("dependency_id", sa.String(length=64), nullable=False),
        sa.Column("source_task_id", sa.String(length=64), nullable=False),
        sa.Column("target_task_id", sa.String(length=64), nullable=False),
        sa.Column("dependency_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("dependency_id"),
        sa.ForeignKeyConstraint(["source_task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_task_id", "target_task_id", name="uq_task_dependency"),
    )

    op.create_table(
        "task_checkpoints",
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_type", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("workflow_state_ref", sa.String(length=128), nullable=True),
        sa.Column("context_ref", sa.String(length=128), nullable=True),
        sa.Column("changeset_ref", sa.String(length=128), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("checkpoint_id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["task_attempts.attempt_id"], ondelete="SET NULL"),
        sa.UniqueConstraint("task_id", "sequence", name="uq_checkpoint_sequence"),
    )

    op.create_table(
        "task_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("previous_status", sa.String(length=24), nullable=True),
        sa.Column("new_status", sa.String(length=24), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "sequence", name="uq_task_event_sequence"),
    )
    op.create_index("ix_task_events_task", "task_events", ["task_id", "sequence"])

    op.create_table(
        "workflow_instances",
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("definition_id", sa.String(length=64), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_node_id", sa.String(length=64), nullable=True),
        sa.Column("current_phase_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("instance_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workflow_instances_project", "workflow_instances", ["project_id", "status"])

    op.create_table(
        "workflow_node_instances",
        sa.Column("node_instance_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_instance_id", sa.String(length=64), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("phase_key", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_ref", sa.String(length=128), nullable=True),
        sa.Column("output_ref", sa.String(length=128), nullable=True),
        sa.Column("error_ref", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("node_instance_id"),
        sa.ForeignKeyConstraint(
            ["workflow_instance_id"], ["workflow_instances.instance_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("workflow_instance_id", "node_key", name="uq_node_instance_key"),
    )

    op.create_table(
        "workflow_phases",
        sa.Column("phase_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_instance_id", sa.String(length=64), nullable=False),
        sa.Column("phase_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("entry_criteria", sa.Text(), nullable=True),
        sa.Column("exit_criteria", sa.Text(), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("phase_id"),
        sa.ForeignKeyConstraint(
            ["workflow_instance_id"], ["workflow_instances.instance_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("workflow_instance_id", "phase_key", name="uq_workflow_phase_key"),
    )

    op.create_table(
        "workflow_phase_reviews",
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_instance_id", sa.String(length=64), nullable=False),
        sa.Column("phase_id", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("deliverables", sa.Text(), nullable=True),
        sa.Column("evidence_refs", sa.Text(), nullable=True),
        sa.Column("verification_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("review_id"),
        sa.ForeignKeyConstraint(
            ["workflow_instance_id"], ["workflow_instances.instance_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["phase_id"], ["workflow_phases.phase_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "requirements",
        sa.Column("requirement_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("requirement_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "requirement_key", name="uq_requirement_key"),
    )

    op.create_table(
        "acceptance_criteria",
        sa.Column("criterion_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_id", sa.String(length=64), nullable=False),
        sa.Column("criterion_key", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("verification_method", sa.String(length=64), nullable=True),
        sa.Column("required_evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("criterion_id"),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.requirement_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("requirement_id", "criterion_key", name="uq_criterion_key"),
    )

    op.create_table(
        "requirement_traces",
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("phase_id", sa.String(length=64), nullable=True),
        sa.Column("changeset_id", sa.String(length=64), nullable=True),
        sa.Column("verification_result_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("trace_id"),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.requirement_id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "change_sets",
        sa.Column("changeset_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("base_revision", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("changeset_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_change_sets_project", "change_sets", ["project_id", "status"])

    op.create_table(
        "change_set_versions",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("changeset_id", sa.String(length=64), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version_id"),
        sa.ForeignKeyConstraint(["changeset_id"], ["change_sets.changeset_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("changeset_id", "version_no", name="uq_changeset_version"),
    )

    op.create_table(
        "change_manifest_items",
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("changeset_id", sa.String(length=64), nullable=False),
        sa.Column("resource_path", sa.String(length=1024), nullable=False),
        sa.Column("operation_type", sa.String(length=16), nullable=False),
        sa.Column("old_content_hash", sa.String(length=64), nullable=True),
        sa.Column("new_content_hash", sa.String(length=64), nullable=True),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("item_id"),
        sa.ForeignKeyConstraint(["changeset_id"], ["change_sets.changeset_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_change_manifest_changeset", "change_manifest_items", ["changeset_id"])

    op.create_table(
        "change_set_validation_results",
        sa.Column("result_id", sa.String(length=64), nullable=False),
        sa.Column("changeset_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("errors", sa.Text(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("result_id"),
        sa.ForeignKeyConstraint(["changeset_id"], ["change_sets.changeset_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_instance_id", sa.String(length=64), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=True),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column("approval_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=True),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("approval_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_approvals_project", "approvals", ["project_id", "status"])
    op.create_index("ix_approvals_target", "approvals", ["target_type", "target_id"])

    op.create_table(
        "approval_decisions",
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.approval_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "approval_audit_events",
        sa.Column("audit_event_id", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_event_id"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.approval_id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    for table in (
        "approval_audit_events",
        "approval_decisions",
        "approvals",
        "change_set_validation_results",
        "change_manifest_items",
        "change_set_versions",
        "change_sets",
        "requirement_traces",
        "acceptance_criteria",
        "requirements",
        "workflow_phase_reviews",
        "workflow_phases",
        "workflow_node_instances",
        "workflow_instances",
        "task_events",
        "task_checkpoints",
        "task_dependencies",
        "task_attempts",
        "tasks",
        "workflow_node_definitions",
        "workflow_definition_versions",
        "workflow_definitions",
        "project_memberships",
        "project_configuration_versions",
        "project_configurations",
        "project_identities",
        "projects",
    ):
        op.drop_table(table)
