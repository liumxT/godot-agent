"""错误码与错误输出测试（E0-T08）。"""

from __future__ import annotations

import pytest

from core.errors import AppError, ConfigError, StartupError, error_payload
from shared.contracts import validate_instance


def test_error_payload_matches_contract_schema() -> None:
    payload = error_payload(
        "INVALID_REQUEST",
        "请求不合法",
        {"field": "action"},
        correlation_id="corr-1",
    )

    assert payload["error"]["correlation_id"] == "corr-1"
    assert validate_instance(payload["error"], "errors/error.schema.json") == []


def test_error_payload_generates_correlation_id() -> None:
    payload = error_payload("INTERNAL_ERROR", "内部错误")

    assert payload["error"]["correlation_id"]


def test_app_error_rejects_lowercase_code() -> None:
    with pytest.raises(ValueError):
        AppError("x", code="lowercase_code")


def test_app_error_default_code_is_registered() -> None:
    assert AppError("x").code == "INTERNAL_ERROR"
    assert ConfigError("x").code == "CONFIG_ERROR"
    assert StartupError("x").code == "STARTUP_ERROR"


def test_retryable_flag_is_carried() -> None:
    error = AppError("稍后重试", code="TIMEOUT", retryable=True)

    payload = error_payload(error.code, error.message, error.details, retryable=error.retryable)
    assert payload["error"]["retryable"] is True
