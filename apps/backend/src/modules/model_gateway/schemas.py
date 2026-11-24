"""统一模型请求 / 响应 / 流式事件（E5-T08 / T09 / T10）。

这些结构是 Agent 与 Provider 之间的唯一契约：Provider 只负责把自身协议
映射到此处，业务侧不需要理解任何厂商字段。

约束：

- 消息、内容与工具调用都是类型化结构，不能拼接成裸字符串；
- 请求在进入 Gateway 前必须通过 :func:`validate_invocation` 校验与大小限制；
- ``usage`` 只保留 Provider 实际返回的字段，缺省为 ``None``，不伪造 0；
- 流式输出中的工具调用只有在完整解析后才允许转换为执行请求。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.errors import RequestTooLarge, ValidationFailed
from modules.model_gateway.providers.errors import ProviderErrorInfo

MESSAGE_SYSTEM = "SYSTEM"
MESSAGE_USER = "USER"
MESSAGE_ASSISTANT = "ASSISTANT"
MESSAGE_TOOL = "TOOL"
MESSAGE_ROLES = frozenset({MESSAGE_SYSTEM, MESSAGE_USER, MESSAGE_ASSISTANT, MESSAGE_TOOL})

FINISH_STOP = "STOP"
FINISH_MAX_TOKENS = "MAX_TOKENS"
FINISH_TOOL_CALL = "TOOL_CALL"
FINISH_CONTENT_FILTER = "CONTENT_FILTER"
FINISH_CANCELLED = "CANCELLED"
FINISH_UNKNOWN = "UNKNOWN"
FINISH_REASONS = frozenset(
    {
        FINISH_STOP,
        FINISH_MAX_TOKENS,
        FINISH_TOOL_CALL,
        FINISH_CONTENT_FILTER,
        FINISH_CANCELLED,
        FINISH_UNKNOWN,
    }
)

RESPONSE_FORMAT_TEXT = "TEXT"
RESPONSE_FORMAT_JSON_OBJECT = "JSON_OBJECT"
RESPONSE_FORMAT_JSON_SCHEMA = "JSON_SCHEMA"
RESPONSE_FORMATS = frozenset(
    {RESPONSE_FORMAT_TEXT, RESPONSE_FORMAT_JSON_OBJECT, RESPONSE_FORMAT_JSON_SCHEMA}
)

USAGE_SOURCE_PROVIDER = "PROVIDER"
USAGE_SOURCE_PARTIAL = "PARTIAL"
USAGE_SOURCE_UNKNOWN = "UNKNOWN"
USAGE_SOURCES = frozenset({USAGE_SOURCE_PROVIDER, USAGE_SOURCE_PARTIAL, USAGE_SOURCE_UNKNOWN})

STREAM_STARTED = "STREAM_STARTED"
STREAM_CONTENT_DELTA = "CONTENT_DELTA"
STREAM_TOOL_CALL_DELTA = "TOOL_CALL_DELTA"
STREAM_USAGE_UPDATE = "USAGE_UPDATE"
STREAM_COMPLETED = "STREAM_COMPLETED"
STREAM_FAILED = "STREAM_FAILED"
STREAM_CANCELLED = "STREAM_CANCELLED"
STREAM_EVENT_TYPES = frozenset(
    {
        STREAM_STARTED,
        STREAM_CONTENT_DELTA,
        STREAM_TOOL_CALL_DELTA,
        STREAM_USAGE_UPDATE,
        STREAM_COMPLETED,
        STREAM_FAILED,
        STREAM_CANCELLED,
    }
)

_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")
_IMAGE_MAX_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TextPart:
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValidationFailed("文本内容不能为空")


@dataclass(frozen=True, slots=True)
class ImagePart:
    """图片内容：URL 或 base64 二选一，必须声明媒体类型以外的信息由 Provider 判定。"""

    url: str | None = None
    data_base64: str | None = None
    media_type: str | None = None

    def __post_init__(self) -> None:
        if (self.url is None) == (self.data_base64 is None):
            raise ValidationFailed("图片内容必须且只能提供 url 或 data_base64")
        if self.data_base64 is not None:
            if not self.media_type:
                raise ValidationFailed("base64 图片必须提供 media_type")
            try:
                raw = base64.b64decode(self.data_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValidationFailed("图片 base64 内容非法") from exc
            if len(raw) > _IMAGE_MAX_BYTES:
                raise ValidationFailed(
                    "图片超过大小限制", details={"limit_bytes": _IMAGE_MAX_BYTES}
                )


ContentPart = TextPart | ImagePart


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.call_id:
            raise ValidationFailed("工具调用缺少 call_id")
        if not _TOOL_NAME_PATTERN.match(self.name or ""):
            raise ValidationFailed("工具名称非法", details={"name": self.name})
        if not isinstance(self.arguments, Mapping):
            raise ValidationFailed("工具调用参数必须是对象", details={"name": self.name})


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not _TOOL_NAME_PATTERN.match(self.name or ""):
            raise ValidationFailed("工具名称非法", details={"name": self.name})
        if self.parameters.get("type") != "object":
            raise ValidationFailed("工具参数 Schema 必须是 object", details={"name": self.name})


@dataclass(frozen=True, slots=True)
class ResponseFormat:
    kind: str = RESPONSE_FORMAT_TEXT
    schema: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind not in RESPONSE_FORMATS:
            raise ValidationFailed("response_format 非法", details={"kind": self.kind})
        if self.kind == RESPONSE_FORMAT_JSON_SCHEMA and not self.schema:
            raise ValidationFailed("JSON_SCHEMA 格式必须提供 schema")


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: str
    content: tuple[ContentPart, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if self.role not in MESSAGE_ROLES:
            raise ValidationFailed("消息角色非法", details={"role": self.role})
        if self.role == MESSAGE_TOOL:
            if not self.tool_call_id:
                raise ValidationFailed("TOOL 消息必须提供 tool_call_id")
            if self.tool_calls:
                raise ValidationFailed("TOOL 消息不能携带 tool_calls")
        elif self.tool_call_id is not None:
            raise ValidationFailed("只有 TOOL 消息可以携带 tool_call_id")
        if self.role == MESSAGE_ASSISTANT:
            if not self.content and not self.tool_calls:
                raise ValidationFailed("ASSISTANT 消息必须包含内容或工具调用")
        elif not self.content:
            raise ValidationFailed("消息内容不能为空", details={"role": self.role})
        if self.tool_calls and self.role != MESSAGE_ASSISTANT:
            raise ValidationFailed("只有 ASSISTANT 消息可以携带 tool_calls")

    def text(self) -> str:
        return "".join(part.text for part in self.content if isinstance(part, TextPart))


@dataclass(frozen=True, slots=True)
class ModelInvocationRequest:
    project_id: str
    model_id: str
    model_key: str
    messages: tuple[ModelMessage, ...]
    request_id: str = ""
    task_id: str | None = None
    attempt_id: str | None = None
    agent_instance_id: str | None = None
    workflow_id: str | None = None
    system_instructions: str | None = None
    tools: tuple[ToolDefinition, ...] = ()
    response_format: ResponseFormat | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    timeout_seconds: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    stream: bool = False


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    usage_source: str = USAGE_SOURCE_UNKNOWN

    def __post_init__(self) -> None:
        if self.usage_source not in USAGE_SOURCES:
            raise ValidationFailed("usage_source 非法", details={"value": self.usage_source})
        for name in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValidationFailed("Token 计数必须为非负整数", details={"field": name})

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "usage_source": self.usage_source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ModelUsage | None:
        if not data:
            return None
        source = data.get("usage_source", USAGE_SOURCE_UNKNOWN)
        if source not in USAGE_SOURCES:
            source = USAGE_SOURCE_UNKNOWN
        return cls(
            input_tokens=_optional_int(data.get("input_tokens")),
            output_tokens=_optional_int(data.get("output_tokens")),
            cached_input_tokens=_optional_int(data.get("cached_input_tokens")),
            reasoning_tokens=_optional_int(data.get("reasoning_tokens")),
            total_tokens=_optional_int(data.get("total_tokens")),
            usage_source=source,
        )


@dataclass(frozen=True, slots=True)
class ModelResponse:
    request_id: str
    provider_id: str
    model_id: str
    status: str
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = FINISH_UNKNOWN
    usage: ModelUsage | None = None
    provider_request_id: str | None = None
    latency_ms: int | None = None
    error: ProviderErrorInfo | None = None


@dataclass(frozen=True, slots=True)
class StreamEvent:
    type: str
    request_id: str
    content_delta: str | None = None
    tool_call_delta: Mapping[str, Any] | None = None
    usage: ModelUsage | None = None
    finish_reason: str | None = None
    error: ProviderErrorInfo | None = None

    def __post_init__(self) -> None:
        if self.type not in STREAM_EVENT_TYPES:
            raise ValidationFailed("流式事件类型非法", details={"type": self.type})


def validate_invocation(request: ModelInvocationRequest, *, max_bytes: int) -> None:
    """请求结构、语义与大小校验；失败时抛 ``ValidationFailed`` / ``RequestTooLarge``。"""

    if not request.project_id:
        raise ValidationFailed("请求必须关联 Project")
    if not request.model_id:
        raise ValidationFailed("请求必须指定模型")
    if not request.model_key:
        raise ValidationFailed("请求缺少 Provider 模型键")
    if not request.messages:
        raise ValidationFailed("请求至少需要一条消息")
    if request.max_output_tokens is not None and request.max_output_tokens <= 0:
        raise ValidationFailed("max_output_tokens 必须为正数")
    if request.temperature is not None and not 0 <= request.temperature <= 2:
        raise ValidationFailed("temperature 必须在 0 到 2 之间")
    if request.timeout_seconds is not None and request.timeout_seconds <= 0:
        raise ValidationFailed("timeout_seconds 必须为正数")
    names = [tool.name for tool in request.tools]
    if len(names) != len(set(names)):
        raise ValidationFailed("工具定义名称重复")
    size = measure_request_bytes(request)
    if size > max_bytes:
        raise RequestTooLarge(
            "模型请求超过大小限制", details={"limit_bytes": max_bytes, "size_bytes": size}
        )


def measure_request_bytes(request: ModelInvocationRequest) -> int:
    """按统一结构序列化后的字节数，用于请求大小限制与审计。"""

    return len(json.dumps(_request_shape(request), ensure_ascii=False, default=str).encode())


def _request_shape(request: ModelInvocationRequest) -> dict[str, Any]:
    return {
        "system_instructions": request.system_instructions,
        "messages": [
            {
                "role": message.role,
                "content": [_part_shape(part) for part in message.content],
                "tool_calls": [
                    {"call_id": call.call_id, "name": call.name, "arguments": call.arguments}
                    for call in message.tool_calls
                ],
                "tool_call_id": message.tool_call_id,
            }
            for message in request.messages
        ],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in request.tools
        ],
        "response_format": (
            {"kind": request.response_format.kind, "schema": request.response_format.schema}
            if request.response_format
            else None
        ),
    }


def _part_shape(part: ContentPart) -> dict[str, Any]:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    return {
        "type": "image",
        "url": part.url,
        "data_base64": part.data_base64,
        "media_type": part.media_type,
    }


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None
