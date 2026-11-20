"""Context 装配实体（E5-T16）。

E5 只持久化装配结果与来源，用于追踪 Agent 实际看到的上下文；
完整 Project Intelligence 与 Memory 在后续阶段扩展。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

CONTEXT_PROFILE_DEFAULT = "DEFAULT"
CONTEXT_PROFILES = frozenset({CONTEXT_PROFILE_DEFAULT, "CODING", "REVIEW", "PLANNING"})

LAYER_SYSTEM = "SYSTEM"
LAYER_PROJECT = "PROJECT"
LAYER_TASK = "TASK"
LAYER_WORKFLOW = "WORKFLOW"
LAYER_AGENT = "AGENT"
LAYER_TOOL = "TOOL"
LAYER_POLICY = "POLICY"
LAYER_RETRIEVED = "RETRIEVED"
CONTEXT_LAYERS = frozenset(
    {
        LAYER_SYSTEM,
        LAYER_PROJECT,
        LAYER_TASK,
        LAYER_WORKFLOW,
        LAYER_AGENT,
        LAYER_TOOL,
        LAYER_POLICY,
        LAYER_RETRIEVED,
    }
)
CONTEXT_LAYER_ORDER = (
    LAYER_SYSTEM,
    LAYER_PROJECT,
    LAYER_TASK,
    LAYER_WORKFLOW,
    LAYER_AGENT,
    LAYER_TOOL,
    LAYER_POLICY,
    LAYER_RETRIEVED,
)

ORIGIN_FACT = "FACT"
ORIGIN_INFERENCE = "INFERENCE"
CONTEXT_ORIGINS = frozenset({ORIGIN_FACT, ORIGIN_INFERENCE})


class ContextAssemblyModel(Base):
    __tablename__ = "context_assemblies"

    context_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_definition_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    context_version: Mapped[int] = mapped_column(Integer, nullable=False)
    token_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_exceeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    layers_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    fixed_refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "context_version", name="uq_context_assemblies_version"),
        Index("ix_context_assemblies_project", "project_id", "created_at"),
    )
