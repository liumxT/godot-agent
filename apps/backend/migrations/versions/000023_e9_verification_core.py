"""E9-T01 / T02 / T03：Verification 领域基础表。

Revision ID: 000023
Revises: 000022
Create Date: 2026-11-24

约束：
- Campaign / Plan / Run / Result / Evidence 状态由 Verification System 拥有；
- 本模块只保存 Task / Workflow / Phase / ChangeSet 的引用，不修改其状态；
- 结果必须可追踪到需求与证据，UNKNOWN 与 FAILED 分离；
- 验收标准与追踪关系独立建表，不覆盖 E4 的需求基线。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000023"
down_revision: str | None = "000022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_campaigns",
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=True),
        sa.Column("phase_id", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("changeset_id", sa.String(length=64), nullable=True),
        sa.Column("campaign_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("verification_policy_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id"),
    )
    op.create_index(
        "ix_verification_campaigns_project_status",
        "verification_campaigns",
        ["project_id", "status"],
    )
    op.create_index("ix_verification_campaigns_task", "verification_campaigns", ["task_id"])
    op.create_index("ix_verification_campaigns_phase", "verification_campaigns", ["phase_id"])

    op.create_table(
        "verification_plans",
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_ids_json", sa.Text(), nullable=False),
        sa.Column("test_suite_ids_json", sa.Text(), nullable=False),
        sa.Column("verification_layers_json", sa.Text(), nullable=False),
        sa.Column("environment_profile", sa.String(length=128), nullable=True),
        sa.Column("target_platforms_json", sa.Text(), nullable=False),
        sa.Column("acceptance_policy_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["verification_campaigns.campaign_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_index(
        "ix_verification_plans_campaign", "verification_plans", ["campaign_id", "status"]
    )

    op.create_table(
        "verification_test_cases",
        sa.Column("test_case_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("test_type", sa.String(length=32), nullable=False),
        sa.Column("execution_method", sa.String(length=64), nullable=False),
        sa.Column("preconditions_json", sa.Text(), nullable=False),
        sa.Column("steps_json", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("automation_level", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("test_case_id"),
        sa.UniqueConstraint("project_id", "name", name="uq_verification_test_case_name"),
    )
    op.create_index(
        "ix_verification_test_cases_project_type",
        "verification_test_cases",
        ["project_id", "test_type"],
    )

    op.create_table(
        "verification_criteria",
        sa.Column("criterion_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_id", sa.String(length=64), nullable=False),
        sa.Column("criterion_type", sa.String(length=24), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("verification_method", sa.String(length=64), nullable=False),
        sa.Column("expected_json", sa.Text(), nullable=False),
        sa.Column("threshold_json", sa.Text(), nullable=False),
        sa.Column("required_evidence_json", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.requirement_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("criterion_id"),
    )
    op.create_index(
        "ix_verification_criteria_project", "verification_criteria", ["project_id", "status"]
    )
    op.create_index(
        "ix_verification_criteria_requirement", "verification_criteria", ["requirement_id"]
    )

    op.create_table(
        "verification_test_links",
        sa.Column("link_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_id", sa.String(length=64), nullable=False),
        sa.Column("criterion_id", sa.String(length=64), nullable=True),
        sa.Column("test_case_id", sa.String(length=64), nullable=False),
        sa.Column("coverage_type", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.requirement_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id"], ["verification_criteria.criterion_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"], ["verification_test_cases.test_case_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("link_id"),
        sa.UniqueConstraint(
            "requirement_id", "test_case_id", name="uq_verification_test_link"
        ),
    )
    op.create_index(
        "ix_verification_test_links_requirement",
        "verification_test_links",
        ["requirement_id"],
    )

    op.create_table(
        "verification_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=True),
        sa.Column("test_suite_id", sa.String(length=64), nullable=True),
        sa.Column("test_case_id", sa.String(length=64), nullable=True),
        sa.Column("environment_id", sa.String(length=64), nullable=True),
        sa.Column("execution_status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executor_id", sa.String(length=64), nullable=True),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["verification_campaigns.campaign_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["verification_plans.plan_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"], ["verification_test_cases.test_case_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_verification_runs_campaign_status",
        "verification_runs",
        ["campaign_id", "execution_status"],
    )
    op.create_index("ix_verification_runs_test_case", "verification_runs", ["test_case_id"])

    op.create_table(
        "verification_results",
        sa.Column("result_id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("requirement_id", sa.String(length=64), nullable=True),
        sa.Column("criterion_id", sa.String(length=64), nullable=True),
        sa.Column("test_case_id", sa.String(length=64), nullable=True),
        sa.Column("result_status", sa.String(length=24), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("confidence_level", sa.String(length=16), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["verification_campaigns.campaign_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["verification_runs.run_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.requirement_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id"], ["verification_criteria.criterion_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"], ["verification_test_cases.test_case_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("result_id"),
    )
    op.create_index(
        "ix_verification_results_campaign",
        "verification_results",
        ["campaign_id", "result_status"],
    )
    op.create_index(
        "ix_verification_results_requirement", "verification_results", ["requirement_id"]
    )
    op.create_index("ix_verification_results_run", "verification_results", ["run_id"])

    op.create_table(
        "verification_evidence",
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("verification_run_id", sa.String(length=64), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validity_status", sa.String(length=16), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["verification_run_id"], ["verification_runs.run_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index(
        "ix_verification_evidence_project_type",
        "verification_evidence",
        ["project_id", "evidence_type"],
    )
    op.create_index(
        "ix_verification_evidence_run", "verification_evidence", ["verification_run_id"]
    )
    op.create_index("ix_verification_evidence_hash", "verification_evidence", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_verification_evidence_hash", table_name="verification_evidence")
    op.drop_index("ix_verification_evidence_run", table_name="verification_evidence")
    op.drop_index("ix_verification_evidence_project_type", table_name="verification_evidence")
    op.drop_table("verification_evidence")

    op.drop_index("ix_verification_results_run", table_name="verification_results")
    op.drop_index("ix_verification_results_requirement", table_name="verification_results")
    op.drop_index("ix_verification_results_campaign", table_name="verification_results")
    op.drop_table("verification_results")

    op.drop_index("ix_verification_runs_test_case", table_name="verification_runs")
    op.drop_index("ix_verification_runs_campaign_status", table_name="verification_runs")
    op.drop_table("verification_runs")

    op.drop_index("ix_verification_test_links_requirement", table_name="verification_test_links")
    op.drop_table("verification_test_links")

    op.drop_index("ix_verification_criteria_requirement", table_name="verification_criteria")
    op.drop_index("ix_verification_criteria_project", table_name="verification_criteria")
    op.drop_table("verification_criteria")

    op.drop_index("ix_verification_test_cases_project_type", table_name="verification_test_cases")
    op.drop_table("verification_test_cases")

    op.drop_index("ix_verification_plans_campaign", table_name="verification_plans")
    op.drop_table("verification_plans")

    op.drop_index("ix_verification_campaigns_phase", table_name="verification_campaigns")
    op.drop_index("ix_verification_campaigns_task", table_name="verification_campaigns")
    op.drop_index(
        "ix_verification_campaigns_project_status", table_name="verification_campaigns"
    )
    op.drop_table("verification_campaigns")
