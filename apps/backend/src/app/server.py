"""API Server 监听封装（E2-T01）。

- 绑定地址只允许回环地址（由 ``Settings.host`` 校验，默认 ``127.0.0.1:8765``）；
- 启动前探测监听地址，端口占用时抛出 ``SERVER_PORT_IN_USE``，避免 uvicorn 的堆栈噪音；
- 信号与关闭由 uvicorn 负责，FastAPI lifespan 复用 E1 的启动/关闭顺序。
"""

from __future__ import annotations

import errno
import socket
from typing import TYPE_CHECKING

import uvicorn

from bootstrap.application import create_app
from config.settings import Settings, load_settings
from core.errors import StartupError

if TYPE_CHECKING:
    from fastapi import FastAPI

_ADDR_IN_USE_ERRNOS = frozenset(
    {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}
)
_WSAEADDRINUSE = 10048


def ensure_port_available(host: str, port: int) -> None:
    """探测监听地址；端口被占用时抛出明确错误，而不是等待 uvicorn 失败。"""

    last_error: OSError | None = None
    in_use = False
    for family, socktype, proto, _, sockaddr in _listen_addresses(host, port):
        probe = socket.socket(family, socktype, proto)
        try:
            probe.bind(sockaddr)
        except OSError as exc:
            last_error = exc
            in_use = in_use or _is_addr_in_use(exc)
        else:
            return
        finally:
            probe.close()

    if in_use:
        raise StartupError(
            "端口已被占用",
            code="SERVER_PORT_IN_USE",
            details={"host": host, "port": port},
        )
    raise StartupError(
        "监听地址不可用",
        details={
            "host": host,
            "port": port,
            "reason": last_error.strerror if last_error is not None else "unknown",
        },
    )


def run(settings: Settings | None = None, *, app: FastAPI | None = None) -> None:
    """启动 API Server，阻塞直到 uvicorn 退出。"""

    resolved = settings or load_settings()
    ensure_port_available(resolved.host, resolved.port)
    uvicorn.run(
        app if app is not None else create_app(resolved),
        host=resolved.host,
        port=resolved.port,
        log_config=None,
    )


def _listen_addresses(host: str, port: int) -> list[tuple]:
    try:
        return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
    except socket.gaierror as exc:
        raise StartupError(
            "监听地址无法解析",
            details={"host": host, "port": port},
        ) from exc


def _is_addr_in_use(exc: OSError) -> bool:
    return exc.errno in _ADDR_IN_USE_ERRNOS or getattr(exc, "winerror", None) == _WSAEADDRINUSE
