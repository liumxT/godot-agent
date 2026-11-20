"""Provider 错误分类（E5-T02 / T14）。

不同 Provider 的异常必须转换为同一套分类，调用方据此决定是否重试。
"请求已发送但结果未知" 属于 ``UNKNOWN_RESULT``，不得当作可重试失败。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderErrorCategory(str, Enum):
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID_REQUEST = "INVALID_REQUEST"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    CONTENT_REJECTED = "CONTENT_REJECTED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"


RETRYABLE_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.RATE_LIMIT,
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        ProviderErrorCategory.NETWORK_ERROR,
        ProviderErrorCategory.TIMEOUT,
    }
)


@dataclass(frozen=True, slots=True)
class ProviderErrorInfo:
    """标准化后的 Provider 错误。"""

    category: ProviderErrorCategory
    message: str
    retryable: bool
    provider_code: str | None = None
    http_status: int | None = None
