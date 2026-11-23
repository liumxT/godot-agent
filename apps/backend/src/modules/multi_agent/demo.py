"""Platformer Demo 多 Agent 编排计划（E7-T22）。

Demo 只定义任务结构、能力需求与依赖顺序，实际执行、Handoff、评审与集成
仍由 Orchestrator 与各既有服务完成；本模块不直接修改任何状态。
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.multi_agent.decomposition import DecompositionPlan, SubtaskSpec

__all__ = [
    "PLATFORMER_DEMO_STEPS",
    "PlatformerDemoStep",
    "build_platformer_plan",
]


@dataclass(frozen=True, slots=True)
class PlatformerDemoStep:
    key: str
    objective: str
    capabilities: tuple[str, ...]
    required_tools: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    risk_level: str = "R1"


PLATFORMER_DEMO_STEPS: tuple[PlatformerDemoStep, ...] = (
    PlatformerDemoStep(
        key="design",
        objective="定义玩家移动、跳跃、敌人与生命系统的玩法规则",
        capabilities=("gameplay_design",),
        required_tools=("file.read",),
        acceptance_criteria=("移动与跳跃规则明确", "敌人与生命规则明确"),
    ),
    PlatformerDemoStep(
        key="player_controller",
        objective="实现玩家移动、跳跃、受伤与死亡",
        capabilities=("gameplay_programming",),
        required_tools=("file.read", "file.write"),
        acceptance_criteria=("玩家可以移动和跳跃", "受伤与死亡逻辑可运行"),
        dependencies=("design",),
    ),
    PlatformerDemoStep(
        key="tilemap_level",
        objective="搭建包含地面、平台与终点的 TileMap 关卡",
        capabilities=("tilemap_development",),
        required_tools=("godot.tilemap.get_cells", "godot.tilemap.set_cells"),
        acceptance_criteria=("关卡可以通行", "存在明确终点"),
        dependencies=("design",),
    ),
    PlatformerDemoStep(
        key="hud",
        objective="实现生命值与关卡完成的 HUD",
        capabilities=("ui_programming",),
        required_tools=("godot.scene.create", "godot.node.create"),
        acceptance_criteria=("HUD 显示生命值", "完成时给出提示"),
        dependencies=("player_controller",),
    ),
    PlatformerDemoStep(
        key="integration",
        objective="整合玩法、关卡与 HUD 并整理验收材料",
        capabilities=("project_planning",),
        required_tools=(),
        acceptance_criteria=("所有子任务输出可追溯", "验收材料完整"),
        dependencies=("player_controller", "tilemap_level", "hud"),
        risk_level="R0",
    ),
)


def build_platformer_plan() -> DecompositionPlan:
    steps = PLATFORMER_DEMO_STEPS
    return DecompositionPlan(
        task_objective="创建一个 2D 平台跳跃游戏，包含玩家移动、跳跃、敌人、关卡、生命系统和 HUD",
        acceptance_criteria=tuple(
            criterion for step in steps for criterion in step.acceptance_criteria
        ),
        subtasks=tuple(
            SubtaskSpec(
                key=step.key,
                objective=step.objective,
                capabilities=step.capabilities,
                acceptance_criteria=step.acceptance_criteria,
                required_tools=step.required_tools,
                dependencies=step.dependencies,
                risk_level=step.risk_level,
            )
            for step in steps
        ),
    )
