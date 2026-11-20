"""请求保护中间件与并发限制单元测试（E2-T09 / T10）。"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.middleware.size_limit import BodySizeLimitMiddleware
from app.middleware.timeout import RequestTimeoutMiddleware
from infrastructure.security.rate_limit import ConcurrencyLimiter


async def _run(
    middleware, receive, *, headers: list[tuple[bytes, bytes]] | None = None
) -> list[dict]:
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/test",
        "headers": headers or [],
    }
    await middleware(scope, receive, send)
    return sent


def _body_of(sent: list[dict]) -> dict:
    return json.loads(sent[-1]["body"].decode())


def test_concurrency_limiter_enforces_maximum() -> None:
    limiter = ConcurrencyLimiter(2)

    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False
    assert limiter.active == 2

    limiter.release()
    assert limiter.try_acquire() is True
    limiter.release()
    limiter.release()
    assert limiter.active == 0


def test_concurrency_limiter_rejects_invalid_maximum() -> None:
    with pytest.raises(ValueError):
        ConcurrencyLimiter(0)


async def test_body_size_limit_rejects_declared_length() -> None:
    async def app(scope, receive, send):  # pragma: no cover - 不应被调用
        raise AssertionError("超限请求不应进入应用")

    sent = await _run(
        BodySizeLimitMiddleware(app, max_bytes=16),
        _empty_receive,
        headers=[(b"content-length", b"32")],
    )

    assert sent[0]["status"] == 413
    assert _body_of(sent)["error"]["code"] == "REQUEST_TOO_LARGE"


async def test_body_size_limit_counts_streamed_bytes() -> None:
    chunks = [b"a" * 10, b"b" * 10]

    async def app(scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "http.request" and not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict:
        body = chunks.pop(0) if chunks else b""
        return {"type": "http.request", "body": body, "more_body": bool(chunks)}

    sent = await _run(BodySizeLimitMiddleware(app, max_bytes=16), receive)

    assert sent[0]["status"] == 413
    assert _body_of(sent)["error"]["code"] == "REQUEST_TOO_LARGE"


async def test_timeout_middleware_returns_504() -> None:
    async def app(scope, receive, send):
        await asyncio.sleep(0.05)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent = await _run(RequestTimeoutMiddleware(app, timeout_seconds=0.001), _empty_receive)

    assert sent[0]["status"] == 504
    error = _body_of(sent)["error"]
    assert error["code"] == "REQUEST_TIMEOUT"
    assert error["retryable"] is True


async def _empty_receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}
