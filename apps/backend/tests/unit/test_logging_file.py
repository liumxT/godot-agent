"""日志文件输出、轮转与脱敏测试（E1-T07-UT-001…004）。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from core.errors import StartupError
from core.logging import (
    RedactionFilter,
    capture_logs,
    clear_registered_secrets,
    configure_logging,
    flush_logging,
    get_logger,
    log_event,
    redact_text,
    register_secret,
)


def _reset_logging() -> None:
    configure_logging("INFO")


def test_file_output_contains_structured_record(tmp_path: Path) -> None:
    try:
        configure_logging("INFO", log_dir=tmp_path)
        log_event(get_logger("tests.file"), logging.INFO, "file_event", component="test")
        flush_logging()

        lines = (tmp_path / "backend.log").read_text(encoding="utf-8").splitlines()
    finally:
        _reset_logging()

    assert any('"event": "file_event"' in line for line in lines)
    assert any('"component": "test"' in line for line in lines)


def test_file_rotation_keeps_backup_files(tmp_path: Path) -> None:
    try:
        configure_logging("INFO", log_dir=tmp_path, max_bytes=200, backup_count=2)
        logger = get_logger("tests.rotate")
        for index in range(6):
            log_event(logger, logging.INFO, f"rotate_event_{index}", component="test")
        flush_logging()

        files = sorted(path.name for path in tmp_path.iterdir())
    finally:
        _reset_logging()

    assert "backend.log" in files
    assert "backend.log.1" in files


def test_registered_secret_is_redacted() -> None:
    register_secret("top-secret-token")
    try:
        with capture_logs() as records:
            log_event(
                get_logger("tests.secret"),
                logging.INFO,
                "secret_event",
                "value=top-secret-token",
                component="test",
            )
    finally:
        clear_registered_secrets()

    assert "top-secret-token" not in records[0]["message"]
    assert "***" in records[0]["message"]


def test_known_credential_patterns_are_redacted() -> None:
    credential = "sk-" + "a" * 24
    text = f"call {credential} and password=hunter2"

    redacted = redact_text(text)

    assert credential not in redacted
    assert "hunter2" not in redacted


def test_redaction_filter_rewrites_message() -> None:
    record = logging.LogRecord(
        "tests.filter", logging.INFO, __file__, 1, "authorization=Bearer abc123456789", None, None
    )

    assert RedactionFilter().filter(record) is True
    assert "abc123456789" not in record.getMessage()


def test_capture_logs_records_event_and_component() -> None:
    with capture_logs() as records:
        log_event(get_logger("tests.capture"), logging.INFO, "capture_event", component="test")

    assert records[0]["event"] == "capture_event"
    assert records[0]["component"] == "test"
    assert records[0]["level"] == "INFO"


def test_unwritable_log_dir_raises_startup_error(tmp_path: Path) -> None:
    blocker = tmp_path / "logs"
    blocker.write_text("not a directory", encoding="utf-8")

    try:
        with pytest.raises(StartupError) as exc_info:
            configure_logging("INFO", log_dir=blocker)
    finally:
        _reset_logging()

    assert exc_info.value.details["log_dir"] == str(blocker)
