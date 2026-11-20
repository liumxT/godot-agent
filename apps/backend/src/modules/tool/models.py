"""工具定义实体（E5-T17 / T18 / T20）。

工具定义按版本不可变：执行请求绑定具体 ``tool_id``（即具体版本），
登记新版本不会改变已创建的执行请求。风险等级由工具定义与统一风险策略共同决定。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

TOOL_CATEGORIES = frozenset(
    {
        "GODOT_EDITOR",
        "GODOT_RUNTIME",
        "FILE_SYSTEM",
        "CODE",
        "SCENE",
        "NODE",
        "INSPECTOR",
        "SIGNAL",
        "GROUP",
        "ANIMATION",
        "TILEMAP",
        "RESOURCE",
        "IMPORT",
        "DEBUG",
        "TEST",
        "BUILD",
        "EXTERNAL_SERVICE",
    }
)

RISK_READ_ONLY = "R0"
RISK_LOW_WRITE = "R1"
RISK_NORMAL_WRITE = "R2"
RISK_HIGH = "R3"
RISK_CRITICAL = "R4"
TOOL_RISK_LEVELS = (RISK_READ_ONLY, RISK_LOW_WRITE, RISK_NORMAL_WRITE, RISK_HIGH, RISK_CRITICAL)
RISK_RANK = {level: rank for rank, level in enumerate(TOOL_RISK_LEVELS)}

EXECUTION_MODE_SYNC = "SYNC"
EXECUTION_MODE_ASYNC = "ASYNC"
EXECUTION_MODES = frozenset({EXECUTION_MODE_SYNC, EXECUTION_MODE_ASYNC})

IDEMPOTENCY_NONE = "NONE"
IDEMPOTENCY_KEYED = "KEYED"
IDEMPOTENCY_POLICIES = frozenset({IDEMPOTENCY_NONE, IDEMPOTENCY_KEYED})

TOOL_CAPABILITIES = frozenset(
    {
        "PROJECT_READ",
        "PROJECT_WRITE",
        "PROJECT_DELETE",
        "CODE_WRITE",
        "SCENE_WRITE",
        "RUNTIME_CONTROL",
        "DEBUG_CONTROL",
        "EXTERNAL_CALL",
        "BUILD",
    }
)

DEFAULT_TOOL_TIMEOUT_SECONDS = 60


class ToolDefinitionModel(Base):
    __tablename__ = "tool_definitions"

    tool_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(4), nullable=False)
    required_capabilities: Mapped[str] = mapped_column(Text, nullable=False)
    required_permissions: Mapped[str] = mapped_column(Text, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_policy: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_tool_definitions_name_version"),
        Index("ix_tool_definitions_name", "name", "version"),
    )
