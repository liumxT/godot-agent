"""E7-T05 任务分解与复杂度单元测试。"""

from __future__ import annotations

import pytest

from core.errors import AgentDecompositionInvalid
from modules.multi_agent.decomposition import (
    COMPLEXITY_COMPLEX,
    COMPLEXITY_SIMPLE,
    DecompositionPlan,
    SubtaskSpec,
    assess_complexity,
)


def _subtask(key: str, **overrides) -> SubtaskSpec:
    defaults = {
        "key": key,
        "objective": f"完成 {key}",
        "capabilities": ("gameplay_programming",),
        "acceptance_criteria": (f"{key} 通过检查",),
        "covers": (f"{key} 覆盖标准",),
        "dependencies": (),
        "risk_level": "R2",
    }
    defaults.update(overrides)
    return SubtaskSpec(**defaults)


def test_topological_order_is_deterministic() -> None:
    plan = DecompositionPlan(
        task_objective="平台跳跃游戏",
        acceptance_criteria=("移动", "跳跃", "HUD"),
        subtasks=(
            _subtask("qa", dependencies=("code", "hud"), covers=("跳跃",)),
            _subtask("code", dependencies=("design",), covers=("移动",), acceptance_criteria=("移动",)),
            _subtask("design", covers=("移动",)),
            _subtask("hud", dependencies=("design",), covers=("HUD",), acceptance_criteria=("HUD",)),
        ),
    )
    order = [spec.key for spec in plan.validate()]
    assert order.index("design") < order.index("code")
    assert order.index("design") < order.index("hud")
    assert order.index("code") < order.index("qa")
    assert order.index("hud") < order.index("qa")


def test_cycle_is_rejected() -> None:
    plan = DecompositionPlan(
        task_objective="循环",
        acceptance_criteria=(),
        subtasks=(
            _subtask("a", dependencies=("b",)),
            _subtask("b", dependencies=("a",)),
        ),
    )
    with pytest.raises(AgentDecompositionInvalid) as exc_info:
        plan.validate()
    assert "DEPENDENCY_CYCLE" in exc_info.value.details["reasons"]


def test_missing_dependency_and_duplicate_key_are_rejected() -> None:
    plan = DecompositionPlan(
        task_objective="非法依赖",
        acceptance_criteria=(),
        subtasks=(
            _subtask("a", dependencies=("missing",)),
            _subtask("b"),
            _subtask("b"),
        ),
    )
    with pytest.raises(AgentDecompositionInvalid) as exc_info:
        plan.validate()
    reasons = " ".join(exc_info.value.details["reasons"])
    assert "UNKNOWN_DEPENDENCY" in reasons
    assert "DUPLICATE_SUBTASK_KEY" in reasons


def test_acceptance_coverage_is_enforced() -> None:
    plan = DecompositionPlan(
        task_objective="覆盖检查",
        acceptance_criteria=("玩家可以跳跃", "敌人会受伤"),
        subtasks=(
            _subtask("a", covers=("玩家可以跳跃",), acceptance_criteria=("玩家可以跳跃",)),
        ),
    )
    with pytest.raises(AgentDecompositionInvalid) as exc_info:
        plan.validate()
    assert exc_info.value.details["missing"] == ["敌人会受伤"]


def test_empty_capabilities_and_criteria_are_rejected() -> None:
    plan = DecompositionPlan(
        task_objective="空字段",
        acceptance_criteria=(),
        subtasks=(_subtask("a", capabilities=(), acceptance_criteria=()),),
    )
    with pytest.raises(AgentDecompositionInvalid) as exc_info:
        plan.validate()
    reasons = " ".join(exc_info.value.details["reasons"])
    assert "SUBTASK_CAPABILITIES_REQUIRED" in reasons
    assert "SUBTASK_CRITERIA_REQUIRED" in reasons


def test_complexity_distinguishes_single_and_multi_agent() -> None:
    single = DecompositionPlan(
        task_objective="单任务",
        acceptance_criteria=(),
        subtasks=(_subtask("a"),),
    )
    assert assess_complexity(single).level == COMPLEXITY_SIMPLE
    assert assess_complexity(single).requires_multi_agent is False

    multi = DecompositionPlan(
        task_objective="多任务",
        acceptance_criteria=(),
        subtasks=(
            _subtask("a", capabilities=("gameplay_design",)),
            _subtask("b", dependencies=("a",)),
        ),
    )
    assessment = assess_complexity(multi)
    assert assessment.level == COMPLEXITY_COMPLEX
    assert assessment.requires_multi_agent is True
    assert "DEPENDENCY_GRAPH" in assessment.reasons
