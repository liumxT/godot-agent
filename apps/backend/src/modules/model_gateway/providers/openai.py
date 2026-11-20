"""OpenAI 兼容 Provider 适配器（E5-T03）。

官方 OpenAI 与兼容服务共用请求结构，仅在 provider_type 上区分。
"""

from __future__ import annotations

from modules.model_gateway.models import (
    PROVIDER_TYPE_OPENAI,
    PROVIDER_TYPE_OPENAI_COMPATIBLE,
)
from modules.model_gateway.providers.base import BaseProviderAdapter


class OpenAICompatibleAdapter(BaseProviderAdapter):
    provider_type = PROVIDER_TYPE_OPENAI_COMPATIBLE
    requires_api_key = True
    allowed_schemes = frozenset({"https"})


class OpenAIAdapter(OpenAICompatibleAdapter):
    provider_type = PROVIDER_TYPE_OPENAI
