"""E10-T01 领域状态机单元测试。"""

from __future__ import annotations

import pytest

from modules.build_release.models import (
    ARTIFACT_TRANSITIONS,
    BUILD_TRANSITIONS,
    BUILD_UNKNOWN,
    RC_TRANSITIONS,
    RELEASE_TRANSITIONS,
    RELEASE_UNKNOWN,
    transitions_for,
)


def test_build_state_machine_allows_progress() -> None:
    assert "PREPARING" in BUILD_TRANSITIONS["QUEUED"]
    assert "COLLECTING" in BUILD_TRANSITIONS["EXPORTING"]
    assert "SUCCEEDED" in BUILD_TRANSITIONS["COLLECTING"]


def test_unknown_is_not_terminal_and_needs_reconciliation() -> None:
    # UNKNOWN 不是成功也不是失败，必须允许经核对后收敛
    assert BUILD_TRANSITIONS[BUILD_UNKNOWN]
    assert "QUEUED" in BUILD_TRANSITIONS[BUILD_UNKNOWN]
    assert RELEASE_TRANSITIONS[RELEASE_UNKNOWN]


def test_terminal_success_states_are_closed() -> None:
    assert BUILD_TRANSITIONS["SUCCEEDED"] == frozenset()
    assert BUILD_TRANSITIONS["CANCELLED"] == frozenset()


def test_artifact_content_transitions_are_limited() -> None:
    # 验证状态可以变化，但不存在回到 VERIFYING 之外的“回写内容”路径
    assert "VERIFIED" in ARTIFACT_TRANSITIONS["VERIFYING"]
    assert "QUARANTINED" in ARTIFACT_TRANSITIONS["VERIFIED"]


def test_release_candidate_and_release_paths() -> None:
    assert "READY_FOR_APPROVAL" in RC_TRANSITIONS["VALIDATING"]
    assert "APPROVED" in RC_TRANSITIONS["READY_FOR_APPROVAL"]
    assert "PUBLISHED" in RELEASE_TRANSITIONS["DISTRIBUTING"]
    assert "COMPLETED" in RELEASE_TRANSITIONS["POST_VERIFYING"]


def test_rolled_back_keeps_history_reachable() -> None:
    # ROLLED_BACK 只是终态，历史发布记录仍然存在
    assert RELEASE_TRANSITIONS["ROLLED_BACK"] == frozenset()
    assert "ROLLED_BACK" in RELEASE_TRANSITIONS["COMPLETED"]


def test_transitions_for_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        transitions_for("nope")
