"""最近错误环形缓冲（E1-T13）。

诊断接口需要「最近错误摘要」，但不允许把错误原文中的凭证带出去。
所有条目在写入时统一走 ``redact_text``，读取时只返回脱敏后的摘要。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from core.logging import redact_text

DEFAULT_MAX_ENTRIES = 20
DEFAULT_SNAPSHOT_SIZE = 10
_MESSAGE_LIMIT = 500


@dataclass(frozen=True, slots=True)
class RecentError:
    timestamp: str
    component: str
    event: str
    error_code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "timestamp": self.timestamp,
            "component": self.component,
            "event": self.event,
            "error_code": self.error_code,
            "message": self.message,
        }


class ErrorBuffer:
    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._entries: deque[RecentError] = deque(maxlen=max_entries)

    def record(
        self,
        *,
        component: str,
        event: str,
        error_code: str,
        message: str,
    ) -> None:
        text = redact_text(" ".join(message.split()))[:_MESSAGE_LIMIT]
        self._entries.append(
            RecentError(
                timestamp=datetime.now(UTC).isoformat(),
                component=component or "unknown",
                event=event or "unknown",
                error_code=error_code or "INTERNAL_ERROR",
                message=text,
            )
        )

    def snapshot(self, limit: int = DEFAULT_SNAPSHOT_SIZE) -> list[RecentError]:
        if limit <= 0:
            return []
        return list(self._entries)[-limit:][::-1]

    def clear(self) -> None:
        self._entries.clear()


_buffer = ErrorBuffer()


def record_recent_error(
    *,
    component: str,
    event: str,
    error_code: str,
    message: str,
) -> None:
    _buffer.record(component=component, event=event, error_code=error_code, message=message)


def recent_errors(limit: int = DEFAULT_SNAPSHOT_SIZE) -> list[RecentError]:
    return _buffer.snapshot(limit)


def clear_recent_errors() -> None:
    _buffer.clear()
