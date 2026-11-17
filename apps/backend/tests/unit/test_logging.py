"""统一日志格式测试（E0-T08）。"""

from __future__ import annotations

import io
import json
import logging

from core.logging import JsonFormatter, log_event, request_context


def _record(message: str = "hello") -> logging.LogRecord:
    return logging.LogRecord("backend.test", logging.INFO, __file__, 1, message, None, None)


def test_formatter_contains_required_fields() -> None:
    payload = json.loads(JsonFormatter().format(_record()))

    assert {"timestamp", "level", "component", "event", "message"} <= payload.keys()
    assert payload["level"] == "INFO"
    assert payload["event"] == "hello"


def test_formatter_includes_request_context() -> None:
    with request_context(request_id="req-1", correlation_id="corr-1", session_id="s-1"):
        payload = json.loads(JsonFormatter().format(_record()))

    assert payload["request_id"] == "req-1"
    assert payload["correlation_id"] == "corr-1"
    assert payload["session_id"] == "s-1"


def test_request_context_is_reset_after_exit() -> None:
    with request_context(request_id="req-1"):
        pass

    payload = json.loads(JsonFormatter().format(_record()))
    assert "request_id" not in payload


def test_formatter_keeps_exception_traceback() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "backend.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )

    payload = json.loads(JsonFormatter().format(record))
    assert "RuntimeError: boom" in payload["exception"]


def test_log_event_sets_event_and_ignores_unknown_fields() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("tests.log_event")
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    log_event(logger, logging.INFO, "migration_applied", component="database", unknown="x")

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "migration_applied"
    assert payload["component"] == "database"
    assert "unknown" not in payload
