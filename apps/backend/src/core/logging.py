"""统一日志入口（E0-T08 / E1-T07）。

日志必须结构化输出（单行 JSON），字段与 Godot 插件侧保持一致：
timestamp / level / component / event / request_id / correlation_id /
session_id / project_id / error_code / message。

E1 新增：
- 文件输出与轮转（``log_dir/backend.log``，5 MB × 5 份）；
- 敏感字段脱敏（key 命中 api_key/token/secret/password/authorization 时输出 ``***``）；
- 已知 Secret 字符串与常见凭证格式在 message / exception 中替换为 ``***``；
- ``capture_logs()`` 测试工具。

请求级关联 ID 由 ``request_context()`` 绑定，格式化时自动附加。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from uuid import uuid4

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

LOG_FILE_NAME = "backend.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5

_SENSITIVE_KEY = re.compile(r"api[_-]?key|token|secret|password|authorization", re.IGNORECASE)
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+"),
)

_known_secrets: set[str] = set()

_context: ContextVar[dict[str, str] | None] = ContextVar("log_request_context", default=None)


@contextmanager
def request_context(**ids: str) -> Iterator[None]:
    """绑定请求级关联字段；退出时恢复上一层上下文。"""

    token = _context.set(
        {key: value for key, value in ids.items() if key in _CONTEXT_FIELDS and value}
    )
    try:
        yield
    finally:
        _context.reset(token)


def context_values() -> dict[str, str]:
    return dict(_context.get() or {})


def register_secret(value: str | None) -> None:
    """登记一个不允许出现在日志中的已知 Secret 值。"""

    if value:
        _known_secrets.add(value)


def clear_registered_secrets() -> None:
    _known_secrets.clear()


def redact_text(text: str) -> str:
    """将文本中的已知 Secret 与常见凭证格式替换为占位符。"""

    for secret in _known_secrets:
        if secret and secret in text:
            text = text.replace(secret, "***")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("***", text)
    return text


class RedactionFilter(logging.Filter):
    """在格式化前脱敏 message / 参数 / 已声明扩展字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_text(item) if isinstance(item, str) else item for item in record.args
            )
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, str):
                setattr(record, field, redact_text(value))
        return True


class RecentErrorHandler(logging.Handler):
    """收集 ERROR 及以上日志，供诊断接口输出最近错误摘要。"""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return
        from core.diagnostics import record_recent_error  # 延迟导入，避免循环依赖

        try:
            record_recent_error(
                component=str(getattr(record, "component", record.name)),
                event=str(getattr(record, "event", None) or record.getMessage()),
                error_code=str(getattr(record, "error_code", None) or "INTERNAL_ERROR"),
                message=record.getMessage(),
            )
        except Exception:  # noqa: BLE001 - 诊断收集不得影响日志主流程
            self.handleError(record)


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
        return json.dumps(_redact_payload(payload), ensure_ascii=False)


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if _SENSITIVE_KEY.search(key):
            redacted[key] = "***" if value else value
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        else:
            redacted[key] = value
    return redacted


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: str | Path | None = None,
    file_name: str = LOG_FILE_NAME,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
) -> None:
    """配置根日志：控制台 JSON + 可选文件轮转。重复调用不会叠加 handler。

    ``log_dir`` 不可写时抛出 ``StartupError``（E1-FI-005），由生命周期标记启动失败。
    """

    resolved_level: str | int = level.upper() if isinstance(level, str) else level
    formatter = JsonFormatter()

    file_handler: logging.Handler | None = None
    if log_dir is not None:
        file_handler = _build_file_handler(log_dir, file_name, max_bytes, backup_count, formatter)

    root = logging.getLogger()
    root.setLevel(resolved_level)
    _close_handlers(root)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(RedactionFilter())
    root.addHandler(console)
    root.addHandler(RecentErrorHandler())

    if file_handler is not None:
        root.addHandler(file_handler)


def _build_file_handler(
    log_dir: str | Path,
    file_name: str,
    max_bytes: int,
    backup_count: int,
    formatter: logging.Formatter,
) -> logging.Handler:
    from core.errors import StartupError  # 延迟导入，避免与 core.errors 循环依赖

    directory = Path(log_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write-probe-{uuid4().hex}"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise StartupError(
            "日志目录不可写",
            details={"log_dir": str(directory), "reason": str(exc)},
        ) from exc

    handler = RotatingFileHandler(
        directory / file_name,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler.addFilter(RedactionFilter())
    return handler


def _close_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except OSError:  # 关闭失败不影响后续日志配置
            pass


def flush_logging() -> None:
    """刷新所有 handler，供关闭流程调用。"""

    for handler in logging.getLogger().handlers:
        handler.flush()


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(json.loads(self.format(record)))
        except Exception:  # noqa: BLE001 - 测试工具本身不得抛出
            self.handleError(record)


@contextmanager
def capture_logs(level: int = logging.DEBUG) -> Iterator[list[dict[str, Any]]]:
    """捕获根日志器输出的结构化记录，供测试断言。"""

    root = logging.getLogger()
    previous_level = root.level
    handler = _CaptureHandler()
    root.addHandler(handler)
    root.setLevel(min(previous_level, level) if previous_level else level)
    try:
        yield handler.records
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


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

    extra = {
        key: value for key, value in fields.items() if key in _EXTRA_FIELDS and value is not None
    }
    extra["event"] = event
    logger.log(level, message or event, extra=extra)
