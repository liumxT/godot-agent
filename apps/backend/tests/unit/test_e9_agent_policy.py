"""E9-T19 Agent 验证策略与验证预算单元测试。"""

from __future__ import annotations

import pytest

from core.errors import PermissionDenied, ValidationFailed
from modules.verification.agent_policy import (
    AGENT_ACTION_READ_RESULT,
    AGENT_ACTION_REQUEST_RUN,
    AGENT_ALLOWED_ACTIONS,
    AGENT_FORBIDDEN_ACTIONS,
    BUDGET_REGRESSIONS,
    BUDGET_RETRIES,
    BUDGET_SCREENSHOTS,
    BUDGET_TEST_RUNS,
    DEFAULT_BUDGET_BY_RISK,
    VerificationBudgetLimits,
    budget_limits_for,
    budget_statuses,
    ensure_agent_action_allowed,
    exhausted_dimensions,
)


def test_agent_action_matrix_separates_allowed_and_forbidden() -> None:
    assert AGENT_ACTION_REQUEST_RUN in AGENT_ALLOWED_ACTIONS
    assert AGENT_ACTION_READ_RESULT in AGENT_ALLOWED_ACTIONS
    assert "SELF_WAIVE_GATE" in AGENT_FORBIDDEN_ACTIONS
    assert "FORGE_RESULT" in AGENT_FORBIDDEN_ACTIONS
    assert AGENT_ALLOWED_ACTIONS.isdisjoint(AGENT_FORBIDDEN_ACTIONS)

    ensure_agent_action_allowed(AGENT_ACTION_REQUEST_RUN)

    with pytest.raises(PermissionDenied):
        ensure_agent_action_allowed("SELF_DECLARE_PHASE_COMPLETE")
    with pytest.raises(ValidationFailed):
        ensure_agent_action_allowed("NOT_A_REAL_ACTION")


def test_budget_limits_follow_risk_level_and_never_relax_by_agent() -> None:
    low = budget_limits_for("LOW")
    critical = budget_limits_for("CRITICAL")
    assert low.test_runs < critical.test_runs
    assert set(DEFAULT_BUDGET_BY_RISK) == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    custom = VerificationBudgetLimits(test_runs=1)
    assert budget_limits_for("MEDIUM", custom) is custom

    with pytest.raises(ValidationFailed):
        budget_limits_for("UNKNOWN")


def test_budget_statuses_and_exhaustion_are_computed_from_usage() -> None:
    limits = VerificationBudgetLimits(test_runs=1, retries=0, screenshots=2)
    usage = {BUDGET_TEST_RUNS: 1, BUDGET_RETRIES: 0, BUDGET_SCREENSHOTS: 1}

    statuses = {item.dimension: item for item in budget_statuses(usage, limits)}
    assert statuses[BUDGET_TEST_RUNS].exhausted is True
    assert statuses[BUDGET_SCREENSHOTS].exhausted is False
    assert statuses[BUDGET_REGRESSIONS].used == 0

    # 已用满 test_runs：即使当前用量未超限，再申请 1 次也应被拒绝
    problems = exhausted_dimensions(usage, limits, amounts={BUDGET_TEST_RUNS: 1, BUDGET_RETRIES: 1})
    dimensions = {item["dimension"] for item in problems}
    assert dimensions == {BUDGET_TEST_RUNS, BUDGET_RETRIES}
