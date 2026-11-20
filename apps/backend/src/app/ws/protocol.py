"""Editor WebSocket 协议层（E3-M3）。

只负责帧解析、大小限制、控制帧构造与关闭码映射；
不访问数据库、不创建 Session、不做业务判断。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import uuid4

PROTOCOL_VERSION = "1.0"
CONTROL_MESSAGE_TYPES = frozenset(
    {"HELLO", "AUTH_CHALLENGE", "AUTH_RESPONSE", "SESSION_CREATED", "ERROR"}
)

CLOSE_NORMAL = 1000
CLOSE_AUTH_FAILED = 4401
CLOSE_PERMISSION_DENIED = 4403
CLOSE_HANDSHAKE_TIMEOUT = 4408
CLOSE_MESSAGE_TOO_LARGE = 4409
CLOSE_SERVER_ERROR = 1011

_PROTOCOL_PATTERN = re.compile(r"^1\.[0-9]+$")
_MESSAGE_ID_PATTERN = re.compile(r"^ctl_[a-z0-9]{8}$")
_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

_RETRYABLE_CODES = frozenset(
    {
        "SESSION_SUSPENDED",
        "LEASE_EXPIRED",
        "SNAPSHOT_UNAVAILABLE",
        "EVENT_SEQUENCE_GAP",
        "RUNTIME_UNAVAILABLE",
        "RATE_LIMITED",
        "INFRASTRUCTURE_ERROR",
    }
)


class ProtocolViolation(Exception):
    """协议级错误：携带契约错误码与建议关闭码。"""

    def __init__(self, code: str, message: str, close_code: int = CLOSE_AUTH_FAILED) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.close_code = close_code


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_retryable(code: str) -> bool:
    return code in _RETRYABLE_CODES


def decode_text(text: str, *, max_bytes: int) -> dict:
    """解析入站文本帧并做大小限制。"""

    if len(text.encode("utf-8")) > max_bytes:
        raise ProtocolViolation(
            "REQUEST_TOO_LARGE", "frame exceeds max message bytes", CLOSE_MESSAGE_TOO_LARGE
        )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolViolation("INVALID_REQUEST", "frame is not valid json") from exc
    if not isinstance(parsed, dict):
        raise ProtocolViolation("INVALID_REQUEST", "frame must be a json object")
    return parsed


def validate_control(frame: dict) -> dict:
    """校验控制帧外层字段；payload 交由调用方按类型校验。"""

    message_type = frame.get("message_type")
    if not isinstance(message_type, str) or message_type not in CONTROL_MESSAGE_TYPES:
        raise ProtocolViolation(
            "UNKNOWN_MESSAGE_TYPE", f"unknown control message_type: {message_type!r}"
        )
    version = frame.get("protocol_version")
    if not isinstance(version, str) or not _PROTOCOL_PATTERN.match(version):
        raise ProtocolViolation("INVALID_REQUEST", "protocol_version must match 1.x")
    message_id = frame.get("message_id")
    if not isinstance(message_id, str) or not _MESSAGE_ID_PATTERN.match(message_id):
        raise ProtocolViolation("INVALID_REQUEST", "message_id must match ctl_[a-z0-9]{8}")
    if not isinstance(frame.get("payload"), dict):
        raise ProtocolViolation("INVALID_REQUEST", "payload must be an object")
    return frame


def normalize_correlation_id(value: object) -> str | None:
    if isinstance(value, str) and _CORRELATION_PATTERN.match(value):
        return value
    return None


def build_control(
    message_type: str,
    payload: dict,
    *,
    session_id: str | None = None,
    project_id: str | None = None,
    correlation_id: str | None = None,
) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": f"ctl_{uuid4().hex[:8]}",
        "message_type": message_type,
        "timestamp": utc_timestamp(),
        "session_id": session_id,
        "project_id": project_id,
        "correlation_id": normalize_correlation_id(correlation_id),
        "payload": payload,
    }


def build_error_payload(
    code: str,
    message: str,
    *,
    details: dict | None = None,
    correlation_id: str | None = None,
    retryable: bool | None = None,
) -> dict:
    return {
        "code": code,
        "message": message,
        "details": details or {},
        "retryable": is_retryable(code) if retryable is None else retryable,
        "correlation_id": normalize_correlation_id(correlation_id) or "unknown",
    }


def build_success_response(request_frame: dict, data: dict | None = None) -> dict:
    """构造成功 response；``request_id`` 回填请求值。"""

    request_id = request_frame.get("request_id")
    if not isinstance(request_id, str) or not _CORRELATION_PATTERN.match(request_id):
        request_id = "req_unknown"
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "success": True,
        "data": data if data is not None else {},
        "error": None,
    }


def build_error_response(
    request_frame: dict,
    code: str,
    message: str,
    *,
    retryable: bool | None = None,
) -> dict:
    """把业务帧错误统一转成 response 契约，而不是自定义 envelope。"""

    request_id = request_frame.get("request_id")
    if not isinstance(request_id, str) or not _CORRELATION_PATTERN.match(request_id):
        request_id = "req_unknown"
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "success": False,
        "data": None,
        "error": build_error_payload(
            code,
            message,
            correlation_id=request_frame.get("correlation_id"),
            retryable=retryable,
        ),
    }
