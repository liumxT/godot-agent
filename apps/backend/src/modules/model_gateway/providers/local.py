"""本地模型服务适配器（E5-T03）。

本地服务通常监听回环地址并使用 OpenAI 兼容协议；允许 http，但仍要求显式
endpoint，不能默认猜测端口。
"""

from __future__ import annotations

from modules.model_gateway.models import PROVIDER_TYPE_LOCAL
from modules.model_gateway.providers.openai import OpenAICompatibleAdapter


class LocalAdapter(OpenAICompatibleAdapter):
    provider_type = PROVIDER_TYPE_LOCAL
    requires_api_key = False
    allowed_schemes = frozenset({"http", "https"})
