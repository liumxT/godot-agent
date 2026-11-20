"""Model Gateway 域模型（E5-T01 / T05 / T06 / T13）。

Provider、Model、Capability、Request、Response 分离建模：

- Provider 只描述接入方式，具体模型由 Model Registry 登记；
- 模型价格使用独立版本表，历史调用可按生效时间回溯价格；
- 模型能力区分 SUPPORTED / UNSUPPORTED / UNKNOWN，UNKNOWN 不等于支持。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

PROVIDER_TYPE_OPENAI = "OPENAI"
PROVIDER_TYPE_OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"
PROVIDER_TYPE_ANTHROPIC = "ANTHROPIC"
PROVIDER_TYPE_LOCAL = "LOCAL"
PROVIDER_TYPES = frozenset(
    {
        PROVIDER_TYPE_OPENAI,
        PROVIDER_TYPE_OPENAI_COMPATIBLE,
        PROVIDER_TYPE_ANTHROPIC,
        PROVIDER_TYPE_LOCAL,
    }
)

PROVIDER_ENABLED = "ENABLED"
PROVIDER_DISABLED = "DISABLED"
PROVIDER_STATUSES = frozenset({PROVIDER_ENABLED, PROVIDER_DISABLED})

MODEL_ACTIVE = "ACTIVE"
MODEL_DISABLED = "DISABLED"
MODEL_STATUSES = frozenset({MODEL_ACTIVE, MODEL_DISABLED})

CAPABILITY_TEXT_INPUT = "TEXT_INPUT"
CAPABILITY_TEXT_OUTPUT = "TEXT_OUTPUT"
CAPABILITY_IMAGE_INPUT = "IMAGE_INPUT"
CAPABILITY_AUDIO_INPUT = "AUDIO_INPUT"
CAPABILITY_AUDIO_OUTPUT = "AUDIO_OUTPUT"
CAPABILITY_VIDEO_INPUT = "VIDEO_INPUT"
CAPABILITY_TOOL_CALLING = "TOOL_CALLING"
CAPABILITY_STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
CAPABILITY_JSON_SCHEMA = "JSON_SCHEMA"
CAPABILITY_STREAMING = "STREAMING"
CAPABILITY_LONG_CONTEXT = "LONG_CONTEXT"
CAPABILITY_REASONING_MODE = "REASONING_MODE"
CAPABILITIES = frozenset(
    {
        CAPABILITY_TEXT_INPUT,
        CAPABILITY_TEXT_OUTPUT,
        CAPABILITY_IMAGE_INPUT,
        CAPABILITY_AUDIO_INPUT,
        CAPABILITY_AUDIO_OUTPUT,
        CAPABILITY_VIDEO_INPUT,
        CAPABILITY_TOOL_CALLING,
        CAPABILITY_STRUCTURED_OUTPUT,
        CAPABILITY_JSON_SCHEMA,
        CAPABILITY_STREAMING,
        CAPABILITY_LONG_CONTEXT,
        CAPABILITY_REASONING_MODE,
    }
)

CAPABILITY_SUPPORTED = "SUPPORTED"
CAPABILITY_UNSUPPORTED = "UNSUPPORTED"
CAPABILITY_UNKNOWN = "UNKNOWN"
CAPABILITY_STATUSES = frozenset(
    {CAPABILITY_SUPPORTED, CAPABILITY_UNSUPPORTED, CAPABILITY_UNKNOWN}
)

REQUEST_CREATED = "CREATED"
REQUEST_VALIDATING = "VALIDATING"
REQUEST_QUEUED = "QUEUED"
REQUEST_SENDING = "SENDING"
REQUEST_STREAMING = "STREAMING"
REQUEST_SUCCEEDED = "SUCCEEDED"
REQUEST_FAILED = "FAILED"
REQUEST_TIMEOUT = "TIMEOUT"
REQUEST_UNKNOWN = "UNKNOWN"
REQUEST_CANCELLED = "CANCELLED"
REQUEST_STATUSES = frozenset(
    {
        REQUEST_CREATED,
        REQUEST_VALIDATING,
        REQUEST_QUEUED,
        REQUEST_SENDING,
        REQUEST_STREAMING,
        REQUEST_SUCCEEDED,
        REQUEST_FAILED,
        REQUEST_TIMEOUT,
        REQUEST_UNKNOWN,
        REQUEST_CANCELLED,
    }
)

# 已发送但结果未确认的请求不能被当作失败并重发（E5-T01 / T14）。
REQUEST_UNRESOLVED = frozenset({REQUEST_SENDING, REQUEST_STREAMING, REQUEST_UNKNOWN})

RESPONSE_SUCCEEDED = "SUCCEEDED"
RESPONSE_FAILED = "FAILED"
RESPONSE_CANCELLED = "CANCELLED"
RESPONSE_STATUSES = frozenset({RESPONSE_SUCCEEDED, RESPONSE_FAILED, RESPONSE_CANCELLED})


class ModelProviderModel(Base):
    __tablename__ = "model_providers"

    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    configuration_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("name", name="uq_model_providers_name"),
        Index("ix_model_providers_type", "provider_type"),
        Index("ix_model_providers_status", "status"),
    )


class ProviderConfigurationModel(Base):
    """Provider 连接配置；每次修改追加新版本，旧版本保留用于审计。"""

    __tablename__ = "provider_configurations"

    configuration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_providers.provider_id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False)
    api_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 只保存密钥名称，密钥值由 SecretStore 管理，禁止落库。
    credential_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "configuration_version",
            name="uq_provider_configurations_version",
        ),
    )


class ModelModel(Base):
    __tablename__ = "models"

    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_providers.provider_id", ondelete="CASCADE"), nullable=False
    )
    model_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # 模型元数据来源：registry_import / provider_probe / manual / verified_probe
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider_id", "model_key", name="uq_models_provider_key"),
        Index("ix_models_provider_status", "provider_id", "status"),
    )


class ModelCapabilityModel(Base):
    __tablename__ = "model_capabilities"

    model_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("models.model_id", ondelete="CASCADE"), primary_key=True
    )
    capability: Mapped[str] = mapped_column(String(32), primary_key=True)
    support_status: Mapped[str] = mapped_column(String(16), nullable=False)
    max_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelPriceVersionModel(Base):
    """模型价格版本；费用计算必须绑定具体版本。"""

    __tablename__ = "model_price_versions"

    price_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("models.model_id", ondelete="CASCADE"), nullable=False
    )
    input_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    output_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("model_id", "effective_at", name="uq_model_price_versions_effective"),
        Index("ix_model_price_versions_lookup", "model_id", "effective_at"),
    )


class ModelRequestModel(Base):
    __tablename__ = "model_requests"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_providers.provider_id"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("models.model_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_model_requests_project_status", "project_id", "status"),
        Index("ix_model_requests_model", "model_id", "created_at"),
    )


class ModelResponseModel(Base):
    __tablename__ = "model_responses"

    response_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_requests.request_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[str | None] = mapped_column(Text, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("request_id", name="uq_model_responses_request"),
    )


class ModelUsageRecordModel(Base):
    """Token 使用记录（E5-T11）；维度字段冗余保存以便直接聚合。"""

    __tablename__ = "model_usage_records"

    usage_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_requests.request_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_source: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("request_id", name="uq_model_usage_records_request"),
        Index("ix_model_usage_records_project", "project_id", "recorded_at"),
        Index("ix_model_usage_records_model", "model_id", "recorded_at"),
    )


class ModelCostRecordModel(Base):
    """费用记录（E5-T12）；与价格版本绑定，缺少价格时标记 UNAVAILABLE。"""

    __tablename__ = "model_cost_records"

    cost_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_requests.request_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    input_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    output_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cached_input_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    additional_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    provider_reported_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pricing_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    calculation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("request_id", name="uq_model_cost_records_request"),
        Index("ix_model_cost_records_project", "project_id", "calculated_at"),
        Index("ix_model_cost_records_model", "model_id", "calculated_at"),
    )


class ModelCallAuditModel(Base):
    """调用审计（E5-T13）；默认不保存 Prompt 与模型原始输出。"""

    __tablename__ = "model_call_audits"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_requests.request_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    request_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    response_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("request_id", name="uq_model_call_audits_request"),
        Index("ix_model_call_audits_project", "project_id", "requested_at"),
        Index("ix_model_call_audits_model", "model_id", "requested_at"),
    )
