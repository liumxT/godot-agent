"""工具域的持久化模型（E5-T17 / T18 / T20 / T22–T26）。

工具定义按版本不可变：执行请求绑定具体 ``tool_id``（即具体版本），
登记新版本不会改变已创建的执行请求。风险等级由工具定义与统一风险策略共同决定。

执行、资源锁、审计与验证记录都只追加或按状态机迁移，不能事后改写历史。
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

EXECUTION_CREATED = "CREATED"
EXECUTION_VALIDATING = "VALIDATING"
EXECUTION_AUTHORIZED = "AUTHORIZED"
EXECUTION_READY = "READY"
EXECUTION_EXECUTING = "EXECUTING"
EXECUTION_SUCCEEDED = "SUCCEEDED"
EXECUTION_FAILED = "FAILED"
EXECUTION_CANCELLED = "CANCELLED"
EXECUTION_TIMEOUT = "TIMEOUT"
EXECUTION_UNKNOWN = "UNKNOWN"
TOOL_EXECUTION_STATUSES = frozenset(
    {
        EXECUTION_CREATED,
        EXECUTION_VALIDATING,
        EXECUTION_AUTHORIZED,
        EXECUTION_READY,
        EXECUTION_EXECUTING,
        EXECUTION_SUCCEEDED,
        EXECUTION_FAILED,
        EXECUTION_CANCELLED,
        EXECUTION_TIMEOUT,
        EXECUTION_UNKNOWN,
    }
)
TOOL_EXECUTION_TERMINAL = frozenset(
    {EXECUTION_SUCCEEDED, EXECUTION_FAILED, EXECUTION_CANCELLED, EXECUTION_TIMEOUT, EXECUTION_UNKNOWN}
)
TOOL_EXECUTION_IN_FLIGHT = frozenset(
    {EXECUTION_CREATED, EXECUTION_VALIDATING, EXECUTION_AUTHORIZED, EXECUTION_READY, EXECUTION_EXECUTING}
)

VERIFICATION_PENDING = "PENDING"
VERIFICATION_VERIFIED = "VERIFIED"
VERIFICATION_FAILED = "FAILED"
VERIFICATION_PARTIAL = "PARTIAL"
VERIFICATION_UNKNOWN = "UNKNOWN"
TOOL_VERIFICATION_STATUSES = frozenset(
    {VERIFICATION_PENDING, VERIFICATION_VERIFIED, VERIFICATION_FAILED, VERIFICATION_PARTIAL, VERIFICATION_UNKNOWN}
)

LOCK_TYPE_READ = "READ_LOCK"
LOCK_TYPE_WRITE = "WRITE_LOCK"
LOCK_TYPE_EXCLUSIVE = "EXCLUSIVE_LOCK"
LOCK_TYPES = frozenset({LOCK_TYPE_READ, LOCK_TYPE_WRITE, LOCK_TYPE_EXCLUSIVE})
LOCK_STATUS_ACTIVE = "ACTIVE"
LOCK_STATUS_RELEASED = "RELEASED"
LOCK_STATUS_EXPIRED = "EXPIRED"
LOCK_OWNER_EXECUTION = "EXECUTION"
LOCK_OWNER_SESSION = "SESSION"
LOCK_OWNER_TASK = "TASK"
LOCK_OWNER_TYPES = frozenset({LOCK_OWNER_EXECUTION, LOCK_OWNER_SESSION, LOCK_OWNER_TASK})

ACTOR_TYPE_USER = "USER"
ACTOR_TYPE_AGENT = "AGENT"
ACTOR_TYPE_SYSTEM = "SYSTEM"
TOOL_ACTOR_TYPES = frozenset({ACTOR_TYPE_USER, ACTOR_TYPE_AGENT, ACTOR_TYPE_SYSTEM})


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


class ToolExecutionModel(Base):
    """工具执行记录（E5-T22 / T23 / T27）。状态只按状态机前进。"""

    __tablename__ = "tool_executions"

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(4), nullable=False)
    input_payload: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_scope: Mapped[str] = mapped_column(Text, nullable=False)
    fencing_token: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    output_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_tool_executions_project", "project_id", "status"),
        Index("ix_tool_executions_idempotency", "project_id", "idempotency_key"),
        Index("ix_tool_executions_task", "task_id"),
    )


class ResourceLockModel(Base):
    """项目资源锁（E5-T24）。服务端权威，过期按 ``expires_at`` 判定。"""

    __tablename__ = "resource_locks"

    lock_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    resource_key: Mapped[str] = mapped_column(String(512), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lock_type: Mapped[str] = mapped_column(String(16), nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        Index("ix_resource_locks_resource", "project_id", "resource_key", "status"),
        Index("ix_resource_locks_expires", "expires_at"),
    )


class ToolAuditRecordModel(Base):
    """工具操作审计（E5-T25）。只追加，敏感参数脱敏后再摘要。"""

    __tablename__ = "tool_audit_records"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(4), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_status: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_tool_audit_project", "project_id", "created_at"),
        Index("ix_tool_audit_execution", "execution_id"),
    )


class ToolVerificationRecordModel(Base):
    """工具结果验证记录（E5-T26）。每次验证追加一行，不覆盖历史。"""

    __tablename__ = "tool_verification_results"

    verification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tool_executions.execution_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False)
    checks: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_tool_verification_execution", "execution_id"),)

