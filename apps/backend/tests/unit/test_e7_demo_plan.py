"""E7-T22 Platformer Demo 计划结构测试。"""

from __future__ import annotations

from modules.multi_agent.demo import PLATFORMER_DEMO_STEPS, build_platformer_plan


def test_platformer_demo_plan_covers_required_gameplay() -> None:
    plan = build_platformer_plan()
    keys = {item.key for item in plan.subtasks}
    assert len(plan.subtasks) == 5
    assert {"design", "player_controller", "tilemap_level", "hud", "integration"} == keys
    assert "移动" in plan.task_objective and "HUD" in plan.task_objective

    by_key = {item.key: item for item in plan.subtasks}
    assert by_key["player_controller"].dependencies == ("design",)
    assert by_key["tilemap_level"].dependencies == ("design",)
    assert by_key["hud"].dependencies == ("player_controller",)
    assert set(by_key["integration"].dependencies) == {
        "player_controller",
        "tilemap_level",
        "hud",
    }
    assert all(item.acceptance_criteria for item in plan.subtasks)
    assert by_key["integration"].risk_level == "R0"


def test_demo_steps_have_explicit_acceptance() -> None:
    assert all(step.acceptance_criteria for step in PLATFORMER_DEMO_STEPS)
    assert all(step.capabilities for step in PLATFORMER_DEMO_STEPS)
