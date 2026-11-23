"""Backend → Godot Editor 的命令通道（E5-T28）。

WebSocket 连接建立后注册到本通道；后端通过 ``editor.command.execute``
下发命令，插件以同 ``request_id`` 的 response 帧回复。命令超时只代表
"结果未知"，是否已产生副作用必须由结果核验或恢复流程判断。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core.errors import EditorCommandTimeout, EditorNotConnected

EDITOR_COMMAND_ACTION = "editor.command.execute"

Sender = Callable[[dict], Awaitable[None]]

__all__ = [
    "EDITOR_COMMAND_ACTION",
    "EditorCommandHub",
    "EditorCommandResponse",
    "EditorConnection",
]


@dataclass(frozen=True, slots=True)
class EditorCommandResponse:
    success: bool
    data: dict[str, Any]
    error: dict[str, Any] | None


class EditorConnection:
    """单个 Editor WebSocket 连接的请求/响应关联。"""

    def __init__(self, *, session_id: str, project_id: str, sender: Sender) -> None:
        self._session_id = session_id
        self._project_id = project_id
        self._sender = sender
        self._pending: dict[str, asyncio.Future[EditorCommandResponse]] = {}
        self._closed = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def project_id(self) -> str:
        return self._project_id

    @property
    def is_open(self) -> bool:
        return not self._closed

    async def send_command(
        self,
        action: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> EditorCommandResponse:
        if self._closed:
            raise EditorNotConnected(
                "编辑器连接已断开", details={"session_id": self._session_id}
            )
        from app.ws.protocol import build_request

        request_id = f"req_{uuid4().hex[:12]}"
        frame = build_request(
            action,
            payload,
            session_id=self._session_id,
            project_id=self._project_id,
            request_id=request_id,
        )
        loop = asyncio.get_running_loop()
        future: asyncio.Future[EditorCommandResponse] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._sender(frame)
        except Exception as exc:
            self._pending.pop(request_id, None)
            raise EditorNotConnected(
                "编辑器命令发送失败", details={"session_id": self._session_id, "reason": str(exc)}
            ) from exc
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise EditorCommandTimeout(
                "编辑器命令超时",
                details={"session_id": self._session_id, "request_id": request_id, "action": action},
            ) from exc

    def resolve(self, frame: dict) -> bool:
        """把 response 帧交给等待中的请求；无法识别时返回 False。"""

        request_id = frame.get("request_id")
        success = frame.get("success")
        if not isinstance(request_id, str) or not isinstance(success, bool):
            return False
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        data = frame.get("data")
        error = frame.get("error")
        future.set_result(
            EditorCommandResponse(
                success=success,
                data=data if isinstance(data, dict) else {},
                error=error if isinstance(error, dict) else None,
            )
        )
        return True

    def close(self, reason: str = "EDITOR_DISCONNECTED") -> None:
        self._closed = True
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(
                    EditorNotConnected(
                        "编辑器连接已断开",
                        details={"session_id": self._session_id, "reason": reason},
                    )
                )


class EditorCommandHub:
    def __init__(self) -> None:
        self._connections: dict[str, EditorConnection] = {}

    def open(self, *, session_id: str, project_id: str, sender: Sender) -> EditorConnection:
        previous = self._connections.get(session_id)
        if previous is not None:
            previous.close("EDITOR_SESSION_REPLACED")
        connection = EditorConnection(
            session_id=session_id, project_id=project_id, sender=sender
        )
        self._connections[session_id] = connection
        return connection

    def close(self, connection: EditorConnection) -> None:
        if self._connections.get(connection.session_id) is connection:
            self._connections.pop(connection.session_id, None)
        connection.close()

    def resolve(self, session_id: str, frame: dict) -> bool:
        connection = self._connections.get(session_id)
        return connection.resolve(frame) if connection is not None else False

    def is_connected(self, session_id: str) -> bool:
        connection = self._connections.get(session_id)
        return connection is not None and connection.is_open

    def get(self, session_id: str) -> EditorConnection | None:
        connection = self._connections.get(session_id)
        return connection if connection is not None and connection.is_open else None
