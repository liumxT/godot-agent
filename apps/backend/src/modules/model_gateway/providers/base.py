"""Provider 适配器基类与声明结构（E5-T02 / T03）。

设计约束：

- 模型能力只能来自显式声明、官方文档或探测结果，不能按模型名称推断；
- 未声明的能力一律视为 ``UNKNOWN``，路由不得当作支持；
- 连接配置校验失败必须在调用前暴露，而不是等生成阶段失败。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from core.errors import AppError, ProviderConfigurationInvalid, ProviderNotConfigured
from modules.model_gateway.models import (
    CAPABILITIES,
    CAPABILITY_STATUSES,
    CAPABILITY_UNKNOWN,
)
from modules.model_gateway.providers.errors import (
    RETRYABLE_CATEGORIES,
    ProviderErrorCategory,
    ProviderErrorInfo,
)
from modules.model_gateway.schemas import (
    ModelInvocationRequest,
    ModelUsage,
    StreamEvent,
    ToolCall,
)

DEFAULT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    provider_type: str
    endpoint: str
    api_version: str | None


@dataclass(frozen=True, slots=True)
class ProviderModelDeclaration:
    """Provider 侧确认过的模型元数据；能力需显式给出。"""

    model_key: str
    display_name: str
    context_window: int
    max_output_tokens: int | None = None
    capabilities: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_key.strip():
            raise ProviderConfigurationInvalid("模型键不能为空")
        if self.context_window <= 0:
            raise ProviderConfigurationInvalid(
                "上下文窗口必须为正数", details={"model_key": self.model_key}
            )
        for capability, status in self.capabilities.items():
            if capability not in CAPABILITIES:
                raise ProviderConfigurationInvalid(
                    "未登记的模型能力",
                    details={"model_key": self.model_key, "capability": capability},
                )
            if status not in CAPABILITY_STATUSES:
                raise ProviderConfigurationInvalid(
                    "模型能力状态非法",
                    details={"model_key": self.model_key, "status": status},
                )


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Provider 健康探测结果；M1 只覆盖配置可用性，网络探测在 T03 后续补全。"""

    provider_type: str
    status: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderGenerationResult:
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str
    usage: ModelUsage | None
    provider_request_id: str | None


class ProviderCallFailure(Exception):
    """Provider 调用失败；``sent`` 表示请求是否可能已被 Provider 接收。"""

    def __init__(self, info: ProviderErrorInfo, *, sent: bool) -> None:
        super().__init__(info.message)
        self.info = info
        self.sent = sent


class ModelProviderAdapter(Protocol):
    """所有 Provider 适配器必须实现的稳定接口。"""

    def get_provider_info(self) -> ProviderInfo: ...

    def list_models(self) -> tuple[ProviderModelDeclaration, ...]: ...

    def get_model_capabilities(self, model_key: str) -> dict[str, str]: ...

    def validate_configuration(self) -> None: ...

    def health_check(self) -> ProviderHealth: ...

    def normalize_error(self, error: BaseException) -> ProviderErrorInfo: ...

    def normalize_usage(self, usage: Mapping[str, Any]) -> dict[str, int]: ...

    async def generate(self, request: ModelInvocationRequest) -> ProviderGenerationResult: ...

    def generate_stream(self, request: ModelInvocationRequest) -> AsyncIterator[StreamEvent]: ...


class BaseProviderAdapter:
    """通用实现：负责配置校验、能力默认值与错误标准化。"""

    provider_type: str = ""
    requires_api_key: bool = True
    allowed_schemes: frozenset[str] = frozenset({"https"})

    def __init__(
        self,
        *,
        endpoint: str,
        api_version: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        models: tuple[ProviderModelDeclaration, ...] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not self.provider_type:
            raise ProviderConfigurationInvalid("适配器缺少 provider_type 声明")
        self._endpoint = endpoint.strip()
        self._api_version = api_version
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._models = {model.model_key: model for model in models}
        self._transport = transport

    def get_provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider_type=self.provider_type,
            endpoint=self._endpoint,
            api_version=self._api_version,
        )

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    def list_models(self) -> tuple[ProviderModelDeclaration, ...]:
        return tuple(self._models.values())

    def get_model_capabilities(self, model_key: str) -> dict[str, str]:
        declaration = self._models.get(model_key)
        if declaration is None:
            raise ProviderConfigurationInvalid(
                "Provider 未声明该模型",
                details={"provider_type": self.provider_type, "model_key": model_key},
            )
        explicit = declaration.capabilities
        return {
            capability: explicit.get(capability, CAPABILITY_UNKNOWN) for capability in CAPABILITIES
        }

    def validate_configuration(self) -> None:
        if not self._endpoint:
            raise ProviderConfigurationInvalid(
                "Provider endpoint 不能为空", details={"provider_type": self.provider_type}
            )
        parsed = urlsplit(self._endpoint)
        if parsed.scheme not in self.allowed_schemes or not parsed.netloc:
            raise ProviderConfigurationInvalid(
                "Provider endpoint 非法",
                details={
                    "provider_type": self.provider_type,
                    "allowed_schemes": sorted(self.allowed_schemes),
                },
            )
        if self._timeout_seconds < 1:
            raise ProviderConfigurationInvalid(
                "timeout 必须大于等于 1 秒", details={"provider_type": self.provider_type}
            )
        if self.requires_api_key and not self._api_key:
            raise ProviderNotConfigured(
                "Provider 缺少 API Key",
                details={"provider_type": self.provider_type, "secret_hint": "api_key"},
            )

    def health_check(self) -> ProviderHealth:
        try:
            self.validate_configuration()
        except AppError as exc:
            return ProviderHealth(
                provider_type=self.provider_type,
                status="UNCONFIGURED",
                detail=exc.message,
            )
        return ProviderHealth(provider_type=self.provider_type, status="CONFIGURED")

    def normalize_error(self, error: BaseException) -> ProviderErrorInfo:
        category = _category_for(error)
        return ProviderErrorInfo(
            category=category,
            message=_error_message(error),
            retryable=category.value in _RETRYABLE_VALUES,
        )

    def normalize_usage(self, usage: Mapping[str, Any]) -> dict[str, int]:
        """只保留 Provider 实际返回的计数字段，不推断、不补零。"""

        normalized: dict[str, int] = {}
        for key in _USAGE_FIELDS:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                normalized[key] = value
        return normalized

    async def generate(self, request: ModelInvocationRequest) -> ProviderGenerationResult:
        raise NotImplementedError("Provider 适配器未实现非流式生成")

    async def generate_stream(self, request: ModelInvocationRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("Provider 适配器未实现流式生成")
        yield  # pragma: no cover - 使函数成为异步生成器

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
        )

    def _failure_from_response(self, response: httpx.Response) -> ProviderCallFailure:
        category = _category_for_status(response.status_code)
        provider_code, message = _response_error_detail(response)
        return ProviderCallFailure(
            ProviderErrorInfo(
                category=category,
                message=message or f"Provider 返回 HTTP {response.status_code}",
                retryable=category in RETRYABLE_CATEGORIES,
                provider_code=provider_code,
                http_status=response.status_code,
            ),
            sent=True,
        )

    def _failure_from_exception(self, error: Exception) -> ProviderCallFailure:
        if isinstance(error, httpx.ConnectError):
            category, sent = ProviderErrorCategory.NETWORK_ERROR, False
        elif isinstance(error, httpx.ConnectTimeout):
            category, sent = ProviderErrorCategory.TIMEOUT, False
        elif isinstance(error, httpx.TimeoutException):
            category, sent = ProviderErrorCategory.TIMEOUT, True
        elif isinstance(error, httpx.HTTPError):
            category, sent = ProviderErrorCategory.NETWORK_ERROR, True
        else:
            category, sent = ProviderErrorCategory.UNKNOWN_RESULT, True
        return ProviderCallFailure(
            ProviderErrorInfo(
                category=category,
                message=str(error) or type(error).__name__,
                retryable=category in RETRYABLE_CATEGORIES,
            ),
            sent=sent,
        )


_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "total_tokens",
)
_RETRYABLE_VALUES = frozenset({"RATE_LIMIT", "PROVIDER_UNAVAILABLE", "NETWORK_ERROR", "TIMEOUT"})


class ToolCallAccumulator:
    """聚合流式工具调用；只有完整 JSON 才能构造 :class:`ToolCall`。"""

    def __init__(self) -> None:
        self._entries: dict[int, dict[str, str]] = {}

    def add(
        self,
        index: int,
        *,
        call_id: str | None = None,
        name: str | None = None,
        arguments_delta: str | None = None,
    ) -> None:
        entry = self._entries.setdefault(index, {"call_id": "", "name": "", "arguments": ""})
        if call_id:
            entry["call_id"] = call_id
        if name:
            entry["name"] = name
        if arguments_delta:
            entry["arguments"] += arguments_delta

    def add_complete(self, call_id: str, name: str, arguments_json: str) -> None:
        self._entries[len(self._entries)] = {
            "call_id": call_id,
            "name": name,
            "arguments": arguments_json,
        }

    def build(self) -> tuple[ToolCall, ...]:
        calls: list[ToolCall] = []
        for index in sorted(self._entries):
            entry = self._entries[index]
            if not entry["call_id"] or not entry["name"]:
                raise _invalid_tool_call("工具调用缺少标识或名称")
            raw = entry["arguments"] or "{}"
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise _invalid_tool_call("工具调用参数不是合法 JSON") from exc
            if not isinstance(arguments, dict):
                raise _invalid_tool_call("工具调用参数必须是 JSON 对象")
            calls.append(
                ToolCall(call_id=entry["call_id"], name=entry["name"], arguments=arguments)
            )
        return tuple(calls)


def _invalid_tool_call(message: str) -> ProviderCallFailure:
    return ProviderCallFailure(
        ProviderErrorInfo(
            category=ProviderErrorCategory.INVALID_REQUEST,
            message=message,
            retryable=False,
        ),
        sent=True,
    )


def _category_for_status(status_code: int) -> ProviderErrorCategory:
    if status_code in (401, 403):
        return ProviderErrorCategory.AUTH_ERROR
    if status_code == 429:
        return ProviderErrorCategory.RATE_LIMIT
    if status_code >= 500:
        return ProviderErrorCategory.PROVIDER_UNAVAILABLE
    return ProviderErrorCategory.INVALID_REQUEST


def _response_error_detail(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        data = response.json()
    except ValueError:
        return None, None
    if not isinstance(data, Mapping):
        return None, None
    error = data.get("error")
    if isinstance(error, Mapping):
        code = error.get("code") or error.get("type")
        message = error.get("message")
        return (
            str(code) if code is not None else None,
            str(message) if message is not None else None,
        )
    if isinstance(error, str):
        return None, error
    return None, None


def _category_for(error: BaseException) -> ProviderErrorCategory:
    if isinstance(error, TimeoutError):
        return ProviderErrorCategory.TIMEOUT
    if isinstance(error, ConnectionError):
        return ProviderErrorCategory.NETWORK_ERROR
    if isinstance(error, AppError):
        if error.status_code == 401:
            return ProviderErrorCategory.AUTH_ERROR
        if error.status_code == 429:
            return ProviderErrorCategory.RATE_LIMIT
        if error.status_code >= 500:
            return ProviderErrorCategory.PROVIDER_UNAVAILABLE
        return ProviderErrorCategory.INVALID_REQUEST
    return ProviderErrorCategory.UNKNOWN_RESULT


def _error_message(error: BaseException) -> str:
    if isinstance(error, AppError):
        return error.message
    return str(error) or type(error).__name__
