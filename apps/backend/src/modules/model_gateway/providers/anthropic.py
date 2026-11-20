"""Anthropic Provider 适配器（E5-T03）。"""

from __future__ import annotations

from modules.model_gateway.models import PROVIDER_TYPE_ANTHROPIC
from modules.model_gateway.providers.base import BaseProviderAdapter


class AnthropicAdapter(BaseProviderAdapter):
    provider_type = PROVIDER_TYPE_ANTHROPIC
    requires_api_key = True
    allowed_schemes = frozenset({"https"})
