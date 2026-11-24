"""Provider Adapter 注册表（E5-T03）。

新增 Provider 只需注册工厂，不影响 Task / Agent 的调用面。
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from core.errors import ProviderConfigurationInvalid, StartupError
from modules.model_gateway.models import (
    PROVIDER_TYPE_ANTHROPIC,
    PROVIDER_TYPE_LOCAL,
    PROVIDER_TYPE_OPENAI,
    PROVIDER_TYPE_OPENAI_COMPATIBLE,
    PROVIDER_TYPES,
)
from modules.model_gateway.providers.anthropic import AnthropicAdapter
from modules.model_gateway.providers.base import BaseProviderAdapter, ProviderModelDeclaration
from modules.model_gateway.providers.local import LocalAdapter
from modules.model_gateway.providers.openai import OpenAIAdapter, OpenAICompatibleAdapter

AdapterFactory = Callable[..., BaseProviderAdapter]


class AdapterRegistry:
    """按 provider_type 创建适配器；重复注册视为装配错误。"""

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, provider_type: str, factory: AdapterFactory) -> None:
        if provider_type not in PROVIDER_TYPES:
            raise StartupError("未登记的 Provider 类型", details={"provider_type": provider_type})
        if provider_type in self._factories:
            raise StartupError("Provider 适配器重复注册", details={"provider_type": provider_type})
        self._factories[provider_type] = factory

    def types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def supports(self, provider_type: str) -> bool:
        return provider_type in self._factories

    def create(
        self,
        provider_type: str,
        *,
        endpoint: str,
        api_version: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
        models: tuple[ProviderModelDeclaration, ...] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> BaseProviderAdapter:
        factory = self._factories.get(provider_type)
        if factory is None:
            raise ProviderConfigurationInvalid(
                "Provider 类型未注册适配器", details={"provider_type": provider_type}
            )
        kwargs: dict[str, object] = {
            "endpoint": endpoint,
            "api_version": api_version,
            "api_key": api_key,
            "models": models,
        }
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        if transport is not None:
            kwargs["transport"] = transport
        return factory(**kwargs)


def default_adapter_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(PROVIDER_TYPE_OPENAI, OpenAIAdapter)
    registry.register(PROVIDER_TYPE_OPENAI_COMPATIBLE, OpenAICompatibleAdapter)
    registry.register(PROVIDER_TYPE_ANTHROPIC, AnthropicAdapter)
    registry.register(PROVIDER_TYPE_LOCAL, LocalAdapter)
    return registry
