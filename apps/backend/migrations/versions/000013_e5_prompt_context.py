"""e5 prompt and context assembly

Revision ID: 000013
Revises: 000012
Create Date: 2026-11-20

E5-T15 / T16：Prompt 版本化定义与测试记录，Context 装配结果与来源追踪。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000013"
down_revision: str | None = "000012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_definitions",
        sa.Column("prompt_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("variables_schema", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("prompt_id"),
        sa.UniqueConstraint("name", "version", name="uq_prompt_definitions_name_version"),
    )
    op.create_index("ix_prompt_definitions_name", "prompt_definitions", ["name", "version"])

    op.create_table(
        "prompt_test_results",
        sa.Column("test_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_id", sa.String(length=64), nullable=False),
        sa.Column("model_request_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("test_id"),
        sa.ForeignKeyConstraint(
            ["prompt_id"], ["prompt_definitions.prompt_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_request_id"], ["model_requests.request_id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_prompt_test_results_prompt",
        "prompt_test_results",
        ["prompt_id", "created_at"],
    )

    op.create_table(
        "context_assemblies",
        sa.Column("context_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("agent_definition_id", sa.String(length=64), nullable=True),
        sa.Column("context_profile", sa.String(length=32), nullable=False),
        sa.Column("context_version", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=True),
        sa.Column("token_budget", sa.Integer(), nullable=True),
        sa.Column("budget_exceeded", sa.Boolean(), nullable=False),
        sa.Column("layers_json", sa.Text(), nullable=False),
        sa.Column("source_refs_json", sa.Text(), nullable=False),
        sa.Column("fixed_refs_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("context_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "context_version", name="uq_context_assemblies_version"),
    )
    op.create_index(
        "ix_context_assemblies_project",
        "context_assemblies",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_context_assemblies_project", table_name="context_assemblies")
    op.drop_table("context_assemblies")
    op.drop_index("ix_prompt_test_results_prompt", table_name="prompt_test_results")
    op.drop_table("prompt_test_results")
    op.drop_index("ix_prompt_definitions_name", table_name="prompt_definitions")
    op.drop_table("prompt_definitions")
