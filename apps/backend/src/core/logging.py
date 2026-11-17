"""统一日志入口（E0-T08）。

日志必须结构化输出（单行 JSON），字段与 Godot 插件侧保持一致：
timestamp / level / component / event / request_id / correlation_id /
session_id / project_id / error_code / message。

请求级关联 ID 由 ``request_context()`` 绑定，格式化时自动附加。
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_CONTEXT_FIELDS = ("request_id", "correlation_id", "session_id", "project_id")

# 允许写入日志的扩展字段；其余 extra 会被忽略，避免污染日志或与 LogRecord 冲突
_EXTRA_FIELDS = (
    "component",
    "event",
    "environment",
    "route",
    "task_id",
    "error_code",
) + _CONTEXT_FIELDS

_context: ContextVar[dict[str, str] | None] = ContextVar("log_request_context", default=None)


@contextmanager
def request_context(**ids: str) -> Iterator[None]:
    """绑定请求级关联字段；退出时恢复上一层上下文。"""

    token = _context.set({key: value for key, value in ids.items() if key in _CONTEXT_FIELDS and value})
    try:
        yield
    finally:
        _context.reset(token)


def context_values() -> dict[str, str]:
    return dict(_context.get() or {})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "component": getattr(record, "component", record.name),
            "event": getattr(record, "event", None) or record.getMessage(),
            "message": record.getMessage(),
        }
        payload.update(context_values())
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """配置根日志。重复调用不会叠加 handler。"""

    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str = "",
    **fields: Any,
) -> None:
    """记录带明确事件名的结构化日志。

    ``event`` 使用 snake_case（如 ``migration_applied``）；
    ``message`` 缺省时复用事件名。未声明的扩展字段不会写入日志。
    """

    extra = {key: value for key, value in fields.items() if key in _EXTRA_FIELDS and value is not None}
    extra["event"] = event
    logger.log(level, message or event, extra=extra)
