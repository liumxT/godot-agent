"""最近错误缓冲单元测试（E1-T13-UT-001…002）。"""

from __future__ import annotations

from core.diagnostics import ErrorBuffer, clear_recent_errors, recent_errors, record_recent_error


def test_record_and_snapshot() -> None:
    clear_recent_errors()
    record_recent_error(
        component="database",
        event="migration_failed",
        error_code="MIGRATION_FAILED",
        message="数据库升级失败",
    )

    entries = recent_errors()

    assert len(entries) == 1
    assert entries[0].component == "database"
    assert entries[0].error_code == "MIGRATION_FAILED"
    assert entries[0].to_dict()["event"] == "migration_failed"


def test_sensitive_fields_are_redacted() -> None:
    clear_recent_errors()
    record_recent_error(
        component="config",
        event="config_invalid",
        error_code="CONFIG_ERROR",
        message="token=sk-secret-value authorization: Bearer abcdefghijkl",
    )

    message = recent_errors()[0].message

    assert "sk-secret-value" not in message
    assert "abcdefghijkl" not in message
    assert "***" in message


def test_buffer_keeps_latest_entries() -> None:
    buffer = ErrorBuffer(max_entries=2)
    for index in range(3):
        buffer.record(
            component="test",
            event=f"e{index}",
            error_code="INTERNAL_ERROR",
            message=f"failure {index}",
        )

    entries = buffer.snapshot(limit=10)

    assert [entry.event for entry in entries] == ["e2", "e1"]
    assert buffer.snapshot(limit=0) == []
