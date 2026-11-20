"""请求超时中间件（E2-T09）。

响应已开始后不再改写，避免破坏已发送的数据；超时响应为 504 ``REQUEST_TIMEOUT``。
"""

from __future__ import annotations

import asyncio

from app.middleware.errors import send_error


class RequestTimeoutMiddleware:
    def __init__(self, app, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope: dict, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def send_tracked(message: dict) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.app(scope, receive, send_tracked)
        except TimeoutError:
            if not started:
                await send_error(
                    send,
                    scope,
                    status_code=504,
                    code="REQUEST_TIMEOUT",
                    message="请求处理超时",
                    retryable=True,
                )
