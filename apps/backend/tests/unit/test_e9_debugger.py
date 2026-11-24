"""E9-T10 Debugger 错误归一化与门禁单元测试。"""

from __future__ import annotations

import pytest

from modules.verification.debugger import (
    DebuggerErrorInput,
    DebuggerGatePolicy,
    build_snapshot,
    classify,
    evaluate_gate,
    fingerprint_error,
    normalize_message,
    severity_for,
)
from modules.verification.models import (
    ERROR_CATEGORY_ENGINE_CRASH,
    ERROR_CATEGORY_INVALID_ACCESS,
    ERROR_CATEGORY_INVALID_CALL,
    ERROR_CATEGORY_NULL_REFERENCE,
    ERROR_CATEGORY_PARSER,
    ERROR_CATEGORY_RUNTIME,
    ERROR_STATUS_IGNORED,
    ERROR_STATUS_OPEN,
    ERROR_STATUS_RESOLVED,
    SEVERITY_ERROR,
    SEVERITY_FATAL,
    SEVERITY_WARNING,
)


def test_classify_known_error_texts() -> None:
    assert classify("Parse Error: unexpected token") == ERROR_CATEGORY_PARSER
    assert classify("Invalid call. Nonexistent function 'foo'") == ERROR_CATEGORY_INVALID_CALL
    assert classify("Invalid access to property 'hp'") == ERROR_CATEGORY_INVALID_ACCESS
    assert classify("Attempt to call function on a null instance") == ERROR_CATEGORY_NULL_REFERENCE
    assert classify("Segmentation fault") == ERROR_CATEGORY_ENGINE_CRASH
    assert classify("something strange happened") == ERROR_CATEGORY_RUNTIME


def test_severity_for_category() -> None:
    assert severity_for(ERROR_CATEGORY_PARSER) == SEVERITY_FATAL
    assert severity_for(ERROR_CATEGORY_ENGINE_CRASH) == SEVERITY_FATAL
    assert severity_for(ERROR_CATEGORY_RUNTIME) == SEVERITY_ERROR
    assert severity_for(ERROR_CATEGORY_RUNTIME, SEVERITY_WARNING) == SEVERITY_WARNING


def test_fingerprint_ignores_addresses_and_numbers() -> None:
    first = DebuggerErrorInput(
        category=ERROR_CATEGORY_NULL_REFERENCE,
        severity=SEVERITY_ERROR,
        message="Null instance at 0x1a2b3c line 42",
        script="res://player.gd",
    )
    second = DebuggerErrorInput(
        category=ERROR_CATEGORY_NULL_REFERENCE,
        severity=SEVERITY_ERROR,
        message="Null instance at 0xffff line 77",
        script="res://player.gd",
    )
    assert normalize_message(first.message) == normalize_message(second.message)
    assert fingerprint_error(first) == fingerprint_error(second)


def test_invalid_error_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        DebuggerErrorInput(category="NOPE", severity=SEVERITY_ERROR, message="x")
    with pytest.raises(ValueError):
        DebuggerErrorInput(category=ERROR_CATEGORY_RUNTIME, severity="BAD", message="x")
    with pytest.raises(ValueError):
        DebuggerErrorInput(category=ERROR_CATEGORY_RUNTIME, severity=SEVERITY_ERROR, message="  ")


def _snapshot(severity: str, *, baseline: bool = False, status: str = ERROR_STATUS_OPEN):
    return build_snapshot(
        severity=severity,
        category=ERROR_CATEGORY_RUNTIME,
        is_baseline=baseline,
        status=status,
        message="boom",
    )


def test_new_fatal_blocks() -> None:
    decision = evaluate_gate([_snapshot(SEVERITY_FATAL)])

    assert decision.blocking is True
    assert decision.allowed is False
    assert decision.new_fatal == 1
    assert decision.reasons


def test_new_error_blocks_by_default() -> None:
    decision = evaluate_gate([_snapshot(SEVERITY_ERROR)])
    assert decision.blocking is True
    assert decision.new_error == 1


def test_new_error_can_require_approval_instead() -> None:
    policy = DebuggerGatePolicy(block_new_error=False, require_approval_for_new_error=True)
    decision = evaluate_gate([_snapshot(SEVERITY_ERROR)], policy)
    assert decision.blocking is False
    assert decision.requires_approval is True


def test_conflicting_policy_is_rejected() -> None:
    with pytest.raises(ValueError):
        DebuggerGatePolicy(block_new_error=True, require_approval_for_new_error=True)


def test_baseline_errors_are_recorded_not_blocking() -> None:
    decision = evaluate_gate([_snapshot(SEVERITY_FATAL, baseline=True)])
    assert decision.blocking is False
    assert decision.baseline_open == 1
    assert any("基线" in reason for reason in decision.reasons)


def test_resolved_and_ignored_errors_do_not_block() -> None:
    decision = evaluate_gate(
        [
            _snapshot(SEVERITY_FATAL, status=ERROR_STATUS_RESOLVED),
            _snapshot(SEVERITY_ERROR, status=ERROR_STATUS_IGNORED),
        ]
    )
    assert decision.blocking is False
    assert decision.counts["resolved"] == 1
    assert decision.counts["ignored"] == 1


def test_warning_only_is_not_blocking_by_default() -> None:
    decision = evaluate_gate([_snapshot(SEVERITY_WARNING)])
    assert decision.blocking is False
    assert decision.new_warning == 1
    assert decision.to_dict()["new_warning"] == 1
