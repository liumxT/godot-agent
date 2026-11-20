"""Prompt 版本化实体（E5-T15）。

每个版本是独立不可变行；``name`` 表示逻辑 Prompt，``version`` 单调递增。
运行中的 Agent Instance 绑定具体 ``prompt_id``，激活新版本不会静默改变旧绑定。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

PROMPT_CATEGORY_SYSTEM = "SYSTEM"
PROMPT_CATEGORY_AGENT = "AGENT"
PROMPT_CATEGORY_TASK = "TASK"
PROMPT_CATEGORY_TOOL = "TOOL"
PROMPT_CATEGORY_REVIEW = "REVIEW"
PROMPT_CATEGORY_VERIFICATION = "VERIFICATION"
PROMPT_CATEGORY_PLANNING = "PLANNING"
PROMPT_CATEGORY_SPECIALIST = "SPECIALIST"
PROMPT_CATEGORIES = frozenset(
    {
        PROMPT_CATEGORY_SYSTEM,
        PROMPT_CATEGORY_AGENT,
        PROMPT_CATEGORY_TASK,
        PROMPT_CATEGORY_TOOL,
        PROMPT_CATEGORY_REVIEW,
        PROMPT_CATEGORY_VERIFICATION,
        PROMPT_CATEGORY_PLANNING,
        PROMPT_CATEGORY_SPECIALIST,
    }
)

PROMPT_STATUS_DRAFT = "DRAFT"
PROMPT_STATUS_ACTIVE = "ACTIVE"
PROMPT_STATUS_ARCHIVED = "ARCHIVED"
PROMPT_STATUSES = frozenset({PROMPT_STATUS_DRAFT, PROMPT_STATUS_ACTIVE, PROMPT_STATUS_ARCHIVED})

PROMPT_TEST_PASSED = "PASSED"
PROMPT_TEST_FAILED = "FAILED"
PROMPT_TEST_ERROR = "ERROR"
PROMPT_TEST_STATUSES = frozenset({PROMPT_TEST_PASSED, PROMPT_TEST_FAILED, PROMPT_TEST_ERROR})


class PromptDefinitionModel(Base):
    __tablename__ = "prompt_definitions"

    prompt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables_schema: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_definitions_name_version"),
        Index("ix_prompt_definitions_name", "name", "version"),
    )


class PromptTestResultModel(Base):
    __tablename__ = "prompt_test_results"

    test_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prompt_definitions.prompt_id", ondelete="CASCADE"),
        nullable=False,
    )
    model_request_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("model_requests.request_id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_prompt_test_results_prompt", "prompt_id", "created_at"),)
