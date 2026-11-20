"""工具执行辅助逻辑单元测试（E5-T23 / T25 / T26）。"""

from __future__ import annotations

from modules.tool.adapters import AdapterResult, VerificationCheck
from modules.tool.audit import summarize
from modules.tool.idempotency import build_idempotency_key
from modules.tool.models import (
    EXECUTION_FAILED,
    EXECUTION_SUCCEEDED,
    EXECUTION_TIMEOUT,
    EXECUTION_UNKNOWN,
)
from modules.tool.verification import evaluate


def _checks(*values: bool) -> tuple[VerificationCheck, ...]:
    return tuple(
        VerificationCheck(name=f"CHECK_{index}", passed=value) for index, value in enumerate(values)
    )


def test_summarize_redacts_sensitive_fields_and_truncates() -> None:
    summary = summarize({"path": "res://main.gd", "api_key": "sk-secret", "note": "x" * 400})

    assert summary is not None
    assert "sk-secret" not in summary
    assert '"api_key": "***"' in summary
    assert len(summary) <= 1024


def test_verification_requires_observed_checks() -> None:
    status, checks = evaluate(
        execution_status=EXECUTION_SUCCEEDED,
        output_valid=True,
        adapter_result=AdapterResult(status=EXECUTION_SUCCEEDED, checks=_checks(True)),
    )
    assert status == "VERIFIED"
    assert [check.name for check in checks] == ["EXECUTION_STATUS", "OUTPUT_SCHEMA", "CHECK_0"]

    partial, _ = evaluate(
        execution_status=EXECUTION_SUCCEEDED,
        output_valid=True,
        adapter_result=AdapterResult(status=EXECUTION_SUCCEEDED),
    )
    assert partial == "PARTIAL"

    unknown_check, _ = evaluate(
        execution_status=EXECUTION_SUCCEEDED,
        output_valid=True,
        adapter_result=AdapterResult(status=EXECUTION_SUCCEEDED, checks=_checks(None)),
    )
    assert unknown_check == "PARTIAL"


def test_verification_fails_on_bad_output_or_failed_execution() -> None:
    failed_output, _ = evaluate(
        execution_status=EXECUTION_SUCCEEDED,
        output_valid=False,
        adapter_result=AdapterResult(status=EXECUTION_SUCCEEDED, checks=_checks(True)),
    )
    assert failed_output == "FAILED"

    failed_check, _ = evaluate(
        execution_status=EXECUTION_SUCCEEDED,
        output_valid=True,
        adapter_result=AdapterResult(status=EXECUTION_SUCCEEDED, checks=_checks(True, False)),
    )
    assert failed_check == "FAILED"

    failed_execution, _ = evaluate(
        execution_status=EXECUTION_FAILED, output_valid=True, adapter_result=None
    )
    assert failed_execution == "FAILED"

    unknown_execution, _ = evaluate(
        execution_status=EXECUTION_UNKNOWN, output_valid=True, adapter_result=None
    )
    assert unknown_execution == "UNKNOWN"

    timeout_execution, _ = evaluate(
        execution_status=EXECUTION_TIMEOUT, output_valid=True, adapter_result=None
    )
    assert timeout_execution == "UNKNOWN"


def test_idempotency_key_is_stable_and_scoped() -> None:
    base = {
        "project_id": "prj_1",
        "tool_id": "tol_1",
        "logical_operation_id": "op-1",
    }
    first = build_idempotency_key(**base)
    second = build_idempotency_key(**base)

    assert first == second
    assert len(first) == 64
    assert build_idempotency_key(**base, task_id="tsk_1") != first
    assert build_idempotency_key(**{**base, "logical_operation_id": "op-2"}) != first
