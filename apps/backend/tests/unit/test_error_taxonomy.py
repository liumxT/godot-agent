"""异常分类与错误码登记测试（E1-T08-UT-001…004）。"""

from __future__ import annotations

import pytest

from core.errors import (
    AppError,
    AuthenticationError,
    BackupError,
    DatabaseError,
    InfrastructureError,
    MigrationError,
    NotFoundError,
    OperationTimeout,
    PermissionDenied,
    ShutdownTimeout,
    StartupError,
    ValidationFailed,
    error_payload,
    iter_error_types,
    validate_error_registry,
)
from shared.contracts import load_json, validate_instance

EXPECTED = (
    (ValidationFailed, "INVALID_REQUEST", 400, False),
    (AuthenticationError, "UNAUTHORIZED", 401, False),
    (PermissionDenied, "PERMISSION_DENIED", 403, False),
    (NotFoundError, "NOT_FOUND", 404, False),
    (OperationTimeout, "TIMEOUT", 504, True),
    (ShutdownTimeout, "SHUTDOWN_TIMEOUT", 504, True),
    (DatabaseError, "DATABASE_UNAVAILABLE", 503, True),
    (InfrastructureError, "INFRASTRUCTURE_ERROR", 500, False),
    (MigrationError, "MIGRATION_FAILED", 500, False),
    (BackupError, "BACKUP_FAILED", 500, False),
)


@pytest.mark.parametrize(("error_type", "code", "status", "retryable"), EXPECTED)
def test_exception_defaults(
    error_type: type[AppError], code: str, status: int, retryable: bool
) -> None:
    error = error_type("测试错误")

    assert error.code == code
    assert error.status_code == status
    assert error.retryable is retryable


def test_registry_declarations_are_valid() -> None:
    validate_error_registry()


def test_contract_codes_match_exception_defaults() -> None:
    registered = {item["code"]: item for item in load_json("errors/error-codes.json")["codes"]}

    for error_type in iter_error_types():
        entry = registered.get(error_type.code)
        if entry is None:
            continue
        assert entry["http_status"] == error_type.status_code, error_type.__name__
        assert entry["retryable"] is error_type.retryable, error_type.__name__


def test_public_error_payload_matches_contract() -> None:
    payload = error_payload(
        "DATABASE_UNAVAILABLE",
        "数据库不可用",
        {"reason": "locked"},
        retryable=True,
        correlation_id="corr-1",
    )

    assert validate_instance(payload["error"], "errors/error.schema.json") == []


def test_local_only_codes_are_not_exposed_in_contract() -> None:
    registered = {item["code"] for item in load_json("errors/error-codes.json")["codes"]}

    assert "STARTUP_ERROR" not in registered
    assert "LIFECYCLE_STATE_ERROR" not in registered
    assert "SHUTDOWN_TIMEOUT" not in registered


class _SampleError(StartupError):
    """仅用于验证错误码登记检查的测试子类。"""

    code = "SAMPLE_ERROR"


def test_error_registry_detects_invalid_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_SampleError, "code", "bad-code")

    with pytest.raises(StartupError) as exc_info:
        validate_error_registry()

    assert "bad-code" in exc_info.value.details["errors"][0]
