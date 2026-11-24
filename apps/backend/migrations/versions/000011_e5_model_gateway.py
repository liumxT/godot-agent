"""e5 model gateway

Revision ID: 000011
Revises: 000010
Create Date: 2026-11-20

E5 Model Gateway：Provider / 配置 / 模型 / 能力 / 价格版本 / 调用请求与响应。
价格版本与能力证据用于历史费用与路由判定，不能被后续修改覆盖。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000011"
down_revision: str | None = "000010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_providers",
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("configuration_ref", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider_id"),
        sa.UniqueConstraint("name", name="uq_model_providers_name"),
    )
    op.create_index("ix_model_providers_type", "model_providers", ["provider_type"])
    op.create_index("ix_model_providers_status", "model_providers", ["status"])

    op.create_table(
        "provider_configurations",
        sa.Column("configuration_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=1024), nullable=False),
        sa.Column("api_version", sa.String(length=64), nullable=True),
        sa.Column("credential_ref", sa.String(length=128), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration_version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("configuration_id"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["model_providers.provider_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "provider_id",
            "configuration_version",
            name="uq_provider_configurations_version",
        ),
    )

    op.create_table(
        "models",
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("model_id"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["model_providers.provider_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("provider_id", "model_key", name="uq_models_provider_key"),
    )
    op.create_index("ix_models_provider_status", "models", ["provider_id", "status"])

    op.create_table(
        "model_capabilities",
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("support_status", sa.String(length=16), nullable=False),
        sa.Column("max_input", sa.Integer(), nullable=True),
        sa.Column("max_output", sa.Integer(), nullable=True),
        sa.Column("evidence_source", sa.String(length=512), nullable=True),
        sa.Column("api_version", sa.String(length=64), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("model_id", "capability"),
        sa.ForeignKeyConstraint(["model_id"], ["models.model_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "model_price_versions",
        sa.Column("price_version_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("input_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("output_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("price_version_id"),
        sa.ForeignKeyConstraint(["model_id"], ["models.model_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("model_id", "effective_at", name="uq_model_price_versions_effective"),
    )
    op.create_index(
        "ix_model_price_versions_lookup", "model_price_versions", ["model_id", "effective_at"]
    )

    op.create_table(
        "model_requests",
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("agent_instance_id", sa.String(length=64), nullable=True),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("request_metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("request_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["model_providers.provider_id"]),
        sa.ForeignKeyConstraint(["model_id"], ["models.model_id"]),
    )
    op.create_index("ix_model_requests_project_status", "model_requests", ["project_id", "status"])
    op.create_index("ix_model_requests_model", "model_requests", ["model_id", "created_at"])

    op.create_table(
        "model_responses",
        sa.Column("response_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("response_metadata", sa.Text(), nullable=True),
        sa.Column("usage", sa.Text(), nullable=True),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("response_id"),
        sa.ForeignKeyConstraint(["request_id"], ["model_requests.request_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("request_id", name="uq_model_responses_request"),
    )


def downgrade() -> None:
    op.drop_table("model_responses")
    op.drop_index("ix_model_requests_model", table_name="model_requests")
    op.drop_index("ix_model_requests_project_status", table_name="model_requests")
    op.drop_table("model_requests")
    op.drop_index("ix_model_price_versions_lookup", table_name="model_price_versions")
    op.drop_table("model_price_versions")
    op.drop_table("model_capabilities")
    op.drop_index("ix_models_provider_status", table_name="models")
    op.drop_table("models")
    op.drop_table("provider_configurations")
    op.drop_index("ix_model_providers_status", table_name="model_providers")
    op.drop_index("ix_model_providers_type", table_name="model_providers")
    op.drop_table("model_providers")
