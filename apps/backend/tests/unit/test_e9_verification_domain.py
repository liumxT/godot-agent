"""E9-T01 验证领域模型单元测试。"""

from __future__ import annotations

import pytest

from modules.verification import models


def _assert_transitions(table: dict[str, frozenset[str]], statuses: frozenset[str]) -> None:
    assert set(table) == set(statuses)
    for current, targets in table.items():
        assert targets <= statuses, (current, targets - statuses)


def test_campaign_plan_run_status_machines_are_closed() -> None:
    _assert_transitions(models.CAMPAIGN_TRANSITIONS, models.CAMPAIGN_STATUSES)
    _assert_transitions(models.PLAN_TRANSITIONS, models.PLAN_STATUSES)
    _assert_transitions(models.RUN_TRANSITIONS, models.RUN_STATUSES)
    _assert_transitions(models.RESULT_TRANSITIONS, models.RESULT_STATUSES)
    _assert_transitions(models.EVIDENCE_TRANSITIONS, models.EVIDENCE_VALIDITY_STATUSES)
    _assert_transitions(models.TEST_CASE_TRANSITIONS, models.TEST_CASE_STATUSES)
    _assert_transitions(models.CRITERION_TRANSITIONS, models.CRITERION_STATUSES)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    assert models.CAMPAIGN_TRANSITIONS[models.CAMPAIGN_COMPLETED] == frozenset()
    assert models.CAMPAIGN_TRANSITIONS[models.CAMPAIGN_CANCELLED] == frozenset()
    assert models.RUN_TRANSITIONS[models.RUN_COMPLETED] == frozenset()
    assert models.RUN_TRANSITIONS[models.RUN_FAILED] == frozenset()
    assert models.RESULT_TRANSITIONS[models.RESULT_SUPERSEDED] == frozenset()
    assert models.EVIDENCE_TRANSITIONS[models.EVIDENCE_REVOKED] == frozenset()


def test_unknown_and_failed_are_distinct() -> None:
    assert models.RESULT_UNKNOWN != models.RESULT_FAILED
    assert models.RUN_UNKNOWN != models.RUN_FAILED
    assert models.RESULT_UNKNOWN in models.RESULT_STATUSES
    assert models.RESULT_FAILED in models.RESULT_STATUSES
    assert models.RESULT_PASSED not in models.NON_PASSING_RESULT_STATUSES
    assert models.RESULT_UNKNOWN in models.NON_PASSING_RESULT_STATUSES


def test_skipped_and_not_run_are_not_passed() -> None:
    assert models.EXECUTED_RESULT_STATUSES == {models.RESULT_PASSED, models.RESULT_FAILED}
    assert models.RESULT_SKIPPED not in models.EXECUTED_RESULT_STATUSES
    assert models.RESULT_NOT_RUN not in models.EXECUTED_RESULT_STATUSES
    assert models.RESULT_WAIVED not in models.EXECUTED_RESULT_STATUSES


def test_result_transitions_do_not_rewrite_verdict() -> None:
    assert models.RESULT_FAILED not in models.RESULT_TRANSITIONS[models.RESULT_PASSED]
    assert models.RESULT_SUPERSEDED in models.RESULT_TRANSITIONS[models.RESULT_PASSED]
    assert models.RESULT_PASSED in models.RESULT_TRANSITIONS[models.RESULT_NOT_RUN]
    assert models.RESULT_WAIVED in models.RESULT_TRANSITIONS[models.RESULT_FAILED]
    assert models.RESULT_WAIVED not in models.RESULT_TRANSITIONS[models.RESULT_PASSED]


def test_transitions_for_unknown_kind_raises() -> None:
    assert models.transitions_for("campaign") is models.CAMPAIGN_TRANSITIONS
    with pytest.raises(ValueError):
        models.transitions_for("unknown")


def test_verification_layers_cover_six_layer_model() -> None:
    assert {
        models.LAYER_STATIC,
        models.LAYER_STRUCTURE,
        models.LAYER_RESOURCE,
        models.LAYER_RUNTIME,
        models.LAYER_FUNCTIONAL,
        models.LAYER_VISUAL,
        models.LAYER_PERFORMANCE,
    } == set(models.VERIFICATION_LAYERS)


def test_evidence_and_criterion_enums_are_consistent() -> None:
    assert models.EVIDENCE_TYPE_MANUAL_NOTE in models.EVIDENCE_TYPES
    assert models.SOURCE_TYPE_GODOT_RUNTIME in models.EVIDENCE_SOURCE_TYPES
    assert models.METHOD_RUNTIME_TEST in models.VERIFICATION_METHODS
    assert models.CRITERION_FUNCTIONAL in models.CRITERION_TYPES
    assert models.AUTOMATION_AUTOMATED in models.AUTOMATION_LEVELS
