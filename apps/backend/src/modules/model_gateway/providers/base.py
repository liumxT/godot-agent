"""Provider 适配器基类与声明结构（E5-T02 / T03）。

设计约束：

- 模型能力只能来自显式声明、官方文档或探测结果，不能按模型名称推断；
- 未声明的能力一律视为 ``UNKNOWN``，路由不得当作支持；
- 连接配置校验失败必须在调用前暴露，而不是等生成阶段失败。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from core.errors import AppError, ProviderConfigurationInvalid, ProviderNotConfigured
from modules.model_gateway.models import (
    CAPABILITIES,
    CAPABILITY_STATUSES,
    CAPABILITY_UNKNOWN,
)
from modules.model_gateway.providers.errors import (
    ProviderErrorCategory,
    ProviderErrorInfo,
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


class ModelProviderAdapter(Protocol):
    """所有 Provider 适配器必须实现的稳定接口。"""

    def get_provider_info(self) -> ProviderInfo: ...

    def list_models(self) -> tuple[ProviderModelDeclaration, ...]: ...

    def get_model_capabilities(self, model_key: str) -> dict[str, str]: ...

    def validate_configuration(self) -> None: ...

    def health_check(self) -> ProviderHealth: ...

    def normalize_error(self, error: BaseException) -> ProviderErrorInfo: ...

    def normalize_usage(self, usage: Mapping[str, Any]) -> dict[str, int]: ...


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
    ) -> None:
        if not self.provider_type:
            raise ProviderConfigurationInvalid("适配器缺少 provider_type 声明")
        self._endpoint = endpoint.strip()
        self._api_version = api_version
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._models = {model.model_key: model for model in models}

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
            capability: explicit.get(capability, CAPABILITY_UNKNOWN)
            for capability in CAPABILITIES
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


_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "total_tokens",
)
_RETRYABLE_VALUES = frozenset({"RATE_LIMIT", "PROVIDER_UNAVAILABLE", "NETWORK_ERROR", "TIMEOUT"})


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
