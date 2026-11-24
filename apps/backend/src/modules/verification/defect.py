"""缺陷领域辅助（E9-T14）。

职责边界：

- 只做缺陷分类、推荐责任 Agent 与统计汇总，不读写数据库；
- Severity（影响程度）与 Priority（处理优先级）必须分开；
- 推荐 Agent 只是建议，实际分配必须经过 E7 Orchestrator；
- 本模块不修改缺陷状态，状态迁移由 Service + Defect 状态机负责。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from modules.verification.models import (
    DEFECT_ACTIVE_STATUSES,
    DEFECT_BLOCKER,
    DEFECT_CATEGORIES,
    DEFECT_CATEGORY_ANIMATION,
    DEFECT_CATEGORY_ASSET,
    DEFECT_CATEGORY_GAMEPLAY,
    DEFECT_CATEGORY_INTEGRATION,
    DEFECT_CATEGORY_OTHER,
    DEFECT_CATEGORY_PERFORMANCE,
    DEFECT_CATEGORY_RESOURCE,
    DEFECT_CATEGORY_SCENE,
    DEFECT_CATEGORY_SCRIPT,
    DEFECT_CATEGORY_SECURITY,
    DEFECT_CATEGORY_TEST,
    DEFECT_CATEGORY_TILEMAP,
    DEFECT_CATEGORY_UI,
    DEFECT_CRITICAL,
    DEFECT_MAJOR,
    DEFECT_MINOR,
    DEFECT_P0,
    DEFECT_P1,
    DEFECT_P2,
    DEFECT_P3,
    DEFECT_PRIORITIES,
    DEFECT_TRIVIAL,
)

# 缺陷类别 → 推荐 Agent（E9 18.7）。
DEFECT_AGENT_MAP: dict[str, str] = {
    DEFECT_CATEGORY_GAMEPLAY: "gameplay_designer",
    DEFECT_CATEGORY_SCRIPT: "gameplay_programmer",
    DEFECT_CATEGORY_UI: "ui_developer",
    DEFECT_CATEGORY_SCENE: "scene_developer",
    DEFECT_CATEGORY_TILEMAP: "tilemap_level_specialist",
    DEFECT_CATEGORY_RESOURCE: "godot_resource_specialist",
    DEFECT_CATEGORY_INTEGRATION: "godot_integration_specialist",
    DEFECT_CATEGORY_ASSET: "asset_pipeline_specialist",
    DEFECT_CATEGORY_ANIMATION: "animation_specialist",
    DEFECT_CATEGORY_PERFORMANCE: "performance_optimization_engineer",
    DEFECT_CATEGORY_TEST: "test_automation_engineer",
    DEFECT_CATEGORY_SECURITY: "godot_integration_specialist",
    DEFECT_CATEGORY_OTHER: "godot_integration_specialist",
}
DEFAULT_DEFECT_AGENT = "godot_integration_specialist"

# Severity 与 Priority 独立，但可从严重程度给出默认优先级建议。
DEFAULT_PRIORITY_BY_SEVERITY: dict[str, str] = {
    DEFECT_BLOCKER: DEFECT_P0,
    DEFECT_CRITICAL: DEFECT_P1,
    DEFECT_MAJOR: DEFECT_P2,
    DEFECT_MINOR: DEFECT_P3,
    DEFECT_TRIVIAL: DEFECT_P3,
}


def recommend_agent(category: str) -> str:
    """按缺陷类别推荐责任 Agent（仅建议，不直接分配）。"""

    if category not in DEFECT_CATEGORIES:
        return DEFAULT_DEFECT_AGENT
    return DEFECT_AGENT_MAP.get(category, DEFAULT_DEFECT_AGENT)


def default_priority(severity: str) -> str:
    """由严重程度推导默认优先级；Priority 仍可被人工覆盖。"""

    return DEFAULT_PRIORITY_BY_SEVERITY.get(severity, DEFECT_P2)


def is_valid_priority(value: str) -> bool:
    return value in DEFECT_PRIORITIES


def defect_summary(defects: Iterable[Any]) -> dict[str, Any]:
    """汇总缺陷分布，区分活跃与已解决/已拒绝。"""

    items = list(defects)
    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    active = 0
    blocking = 0
    for item in items:
        status = str(getattr(item, "status", ""))
        severity = str(getattr(item, "severity", ""))
        category = str(getattr(item, "category", ""))
        by_status[status] = by_status.get(status, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
        if status in DEFECT_ACTIVE_STATUSES:
            active += 1
            if severity in {DEFECT_BLOCKER, DEFECT_CRITICAL}:
                blocking += 1
    return {
        "total": len(items),
        "active": active,
        "blocking_active": blocking,
        "by_status": by_status,
        "by_severity": by_severity,
        "by_category": by_category,
    }
