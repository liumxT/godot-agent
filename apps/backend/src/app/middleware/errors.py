"""中间件错误响应辅助：与统一错误契约保持一致。"""

from __future__ import annotations

import json
from uuid import uuid4

from core.errors import error_payload


def correlation_id(scope: dict) -> str:
    for name in (b"x-request-id", b"x-correlation-id"):
        for header, value in scope.get("headers", ()):
            if header.lower() == name:
                return value.decode("latin-1")
    return f"req-{uuid4().hex}"


async def send_error(
    send,
    scope: dict,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
) -> None:
    request_id = correlation_id(scope)
    body = json.dumps(
        error_payload(
            code,
            message,
            retryable=retryable,
            correlation_id=request_id,
        ),
        ensure_ascii=False,
    ).encode()
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
        (b"x-request-id", request_id.encode()),
        (b"x-correlation-id", request_id.encode()),
    ]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})
