"""E9-T14 缺陷领域辅助单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

from modules.verification.defect import (
    DEFAULT_DEFECT_AGENT,
    default_priority,
    defect_summary,
    recommend_agent,
)
from modules.verification.models import (
    DEFECT_ASSIGNED,
    DEFECT_BLOCKER,
    DEFECT_CATEGORY_ANIMATION,
    DEFECT_CATEGORY_GAMEPLAY,
    DEFECT_CATEGORY_OTHER,
    DEFECT_CATEGORY_PERFORMANCE,
    DEFECT_CATEGORY_SCRIPT,
    DEFECT_CATEGORY_TILEMAP,
    DEFECT_CATEGORY_UI,
    DEFECT_CRITICAL,
    DEFECT_MAJOR,
    DEFECT_MINOR,
    DEFECT_OPEN,
    DEFECT_P0,
    DEFECT_P1,
    DEFECT_P2,
    DEFECT_P3,
    DEFECT_RESOLVED,
    DEFECT_TRIVIAL,
)


def test_recommend_agent_by_category() -> None:
    assert recommend_agent(DEFECT_CATEGORY_GAMEPLAY) == "gameplay_designer"
    assert recommend_agent(DEFECT_CATEGORY_SCRIPT) == "gameplay_programmer"
    assert recommend_agent(DEFECT_CATEGORY_UI) == "ui_developer"
    assert recommend_agent(DEFECT_CATEGORY_TILEMAP) == "tilemap_level_specialist"
    assert recommend_agent(DEFECT_CATEGORY_ANIMATION) == "animation_specialist"
    assert recommend_agent(DEFECT_CATEGORY_PERFORMANCE) == (
        "performance_optimization_engineer"
    )
    assert recommend_agent(DEFECT_CATEGORY_OTHER) == "godot_integration_specialist"


def test_recommend_agent_falls_back_for_unknown_category() -> None:
    assert recommend_agent("NOT_A_CATEGORY") == DEFAULT_DEFECT_AGENT


def test_default_priority_mapping() -> None:
    assert default_priority(DEFECT_BLOCKER) == DEFECT_P0
    assert default_priority(DEFECT_CRITICAL) == DEFECT_P1
    assert default_priority(DEFECT_MAJOR) == DEFECT_P2
    assert default_priority(DEFECT_MINOR) == DEFECT_P3
    assert default_priority(DEFECT_TRIVIAL) == DEFECT_P3
    assert default_priority("UNKNOWN") == DEFECT_P2


def test_defect_summary_separates_active_and_blocking() -> None:
    items = [
        SimpleNamespace(
            status=DEFECT_OPEN,
            severity=DEFECT_BLOCKER,
            category=DEFECT_CATEGORY_SCRIPT,
        ),
        SimpleNamespace(
            status=DEFECT_ASSIGNED,
            severity=DEFECT_MINOR,
            category=DEFECT_CATEGORY_UI,
        ),
        SimpleNamespace(
            status=DEFECT_RESOLVED,
            severity=DEFECT_CRITICAL,
            category=DEFECT_CATEGORY_SCRIPT,
        ),
    ]

    summary = defect_summary(items)

    assert summary["total"] == 3
    assert summary["active"] == 2
    assert summary["blocking_active"] == 1
    assert summary["by_status"][DEFECT_OPEN] == 1
    assert summary["by_severity"][DEFECT_CRITICAL] == 1
    assert summary["by_category"][DEFECT_CATEGORY_SCRIPT] == 2
