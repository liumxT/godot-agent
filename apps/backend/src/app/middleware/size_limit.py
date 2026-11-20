"""请求体大小限制中间件（E2-T09 / T10-UT-004）。

优先检查 ``Content-Length``；缺少该头时对流式读取的字节数累计校验。
"""

from __future__ import annotations

from app.middleware.errors import send_error
from core.errors import RequestTooLarge


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes 必须大于 0")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await send_error(
                send,
                scope,
                status_code=413,
                code="REQUEST_TOO_LARGE",
                message="请求体超过大小限制",
            )
            return

        received = 0

        async def receive_limited():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestTooLarge(
                        "请求体超过大小限制",
                        details={"max_bytes": self.max_bytes},
                    )
            return message

        try:
            await self.app(scope, receive_limited, send)
        except RequestTooLarge:
            await send_error(
                send,
                scope,
                status_code=413,
                code="REQUEST_TOO_LARGE",
                message="请求体超过大小限制",
            )


def _declared_length(scope: dict) -> int | None:
    for header, value in scope.get("headers", ()):
        if header.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
