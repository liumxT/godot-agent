"""API 版本常量。

``API_VERSION`` 与 Shared Contracts 的 ``protocol_version`` 相互独立：
前者描述 HTTP 接口契约，后者描述跨端消息协议。
"""

from __future__ import annotations

API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"
