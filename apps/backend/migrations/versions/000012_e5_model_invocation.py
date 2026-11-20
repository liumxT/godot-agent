"""e5 model invocation tracking

Revision ID: 000012
Revises: 000011
Create Date: 2026-11-20

E5 模型调用追踪：Token 使用、费用与调用审计；为按 Workflow 维度统计补充
``model_requests.workflow_id``。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000012"
down_revision: str | None = "000011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_requests", sa.Column("workflow_id", sa.String(length=64), nullable=True)
    )

    op.create_table(
        "model_usage_records",
        sa.Column("usage_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("usage_source", sa.String(length=16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("usage_id"),
        sa.ForeignKeyConstraint(
            ["request_id"], ["model_requests.request_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("request_id", name="uq_model_usage_records_request"),
    )
    op.create_index(
        "ix_model_usage_records_project", "model_usage_records", ["project_id", "recorded_at"]
    )
    op.create_index(
        "ix_model_usage_records_model", "model_usage_records", ["model_id", "recorded_at"]
    )

    op.create_table(
        "model_cost_records",
        sa.Column("cost_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("input_cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("output_cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("cached_input_cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("additional_cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("provider_reported_cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("pricing_version_id", sa.String(length=64), nullable=True),
        sa.Column("calculation_status", sa.String(length=16), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("cost_id"),
        sa.ForeignKeyConstraint(
            ["request_id"], ["model_requests.request_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("request_id", name="uq_model_cost_records_request"),
    )
    op.create_index(
        "ix_model_cost_records_project", "model_cost_records", ["project_id", "calculated_at"]
    )
    op.create_index(
        "ix_model_cost_records_model", "model_cost_records", ["model_id", "calculated_at"]
    )

    op.create_table(
        "model_call_audits",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("usage_id", sa.String(length=64), nullable=True),
        sa.Column("cost_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("request_bytes", sa.Integer(), nullable=False),
        sa.Column("response_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
        sa.ForeignKeyConstraint(
            ["request_id"], ["model_requests.request_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("request_id", name="uq_model_call_audits_request"),
    )
    op.create_index(
        "ix_model_call_audits_project", "model_call_audits", ["project_id", "requested_at"]
    )
    op.create_index(
        "ix_model_call_audits_model", "model_call_audits", ["model_id", "requested_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_model_call_audits_model", table_name="model_call_audits")
    op.drop_index("ix_model_call_audits_project", table_name="model_call_audits")
    op.drop_table("model_call_audits")
    op.drop_index("ix_model_cost_records_model", table_name="model_cost_records")
    op.drop_index("ix_model_cost_records_project", table_name="model_cost_records")
    op.drop_table("model_cost_records")
    op.drop_index("ix_model_usage_records_model", table_name="model_usage_records")
    op.drop_index("ix_model_usage_records_project", table_name="model_usage_records")
    op.drop_table("model_usage_records")
    op.drop_column("model_requests", "workflow_id")
