"""游戏开发工作流模板（E7-T14）。

Workflow Engine 拥有 Workflow/Phase/Node 状态；本模块只登记游戏开发模板并用
E4 的定义/实例服务落地。每个 AI 步骤都对应一个已登记的专用 Agent，并保留
Phase Review，不允许仅因 Assignment 完成就自动进入下一 Phase。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.errors import NotFoundError
from modules.multi_agent.specialized import SPECIALIZED_AGENTS
from modules.workflow.models import (
    NODE_TYPE_AI_EXECUTION,
    NODE_TYPE_USER_CONFIRMATION,
    NODE_TYPE_VERIFICATION,
)
from modules.workflow.service import (
    DefinitionView as WorkflowDefinitionView,
)
from modules.workflow.service import (
    InstanceView,
    WorkflowDefinitionService,
    WorkflowInstanceService,
)

WORKFLOW_CATEGORY = "GAME_DEVELOPMENT"

WORKFLOW_CONCEPT = "game_concept_design"
WORKFLOW_CORE_GAMEPLAY = "core_gameplay_development"
WORKFLOW_UI = "ui_development"
WORKFLOW_TILEMAP = "tilemap_level_development"
WORKFLOW_CODE_QUALITY = "code_quality_review"


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    key: str
    name: str
    node_type: str = NODE_TYPE_AI_EXECUTION
    agent_key: str | None = None
    review_required: bool = True


@dataclass(frozen=True, slots=True)
class GameWorkflowSpec:
    key: str
    name: str
    description: str
    steps: tuple[WorkflowStep, ...]


def _ai(key: str, name: str, agent_key: str) -> WorkflowStep:
    return WorkflowStep(key=key, name=name, agent_key=agent_key)


def _gate(key: str, name: str, node_type: str) -> WorkflowStep:
    return WorkflowStep(key=key, name=name, node_type=node_type)


GAME_WORKFLOWS: tuple[GameWorkflowSpec, ...] = (
    GameWorkflowSpec(
        key=WORKFLOW_CONCEPT,
        name="游戏概念设计",
        description="从用户需求到可评审的游戏概念与架构草案",
        steps=(
            _ai("concept", "游戏概念", "game_designer"),
            _ai("gameplay", "核心玩法", "gameplay_designer"),
            _ai("level", "关卡草案", "level_designer"),
            _ai("architecture", "架构草案", "game_architect"),
            _gate("user_review", "用户评审", NODE_TYPE_USER_CONFIRMATION),
        ),
    ),
    GameWorkflowSpec(
        key=WORKFLOW_CORE_GAMEPLAY,
        name="核心玩法开发",
        description="架构、玩法、场景、集成与 QA 的串行交付",
        steps=(
            _ai("architecture", "架构设计", "game_architect"),
            _ai("gameplay_code", "玩法实现", "gameplay_programmer"),
            _ai("scene", "场景搭建", "scene_developer"),
            _ai("integration", "编辑器集成", "godot_integration_specialist"),
            _ai("qa", "QA 验证", "qa_engineer"),
            _gate("verification", "客观验证", NODE_TYPE_VERIFICATION),
        ),
    ),
    GameWorkflowSpec(
        key=WORKFLOW_UI,
        name="UI 开发",
        description="界面设计、实现、场景接入与 QA",
        steps=(
            _ai("ux", "界面设计", "ui_ux_designer"),
            _ai("ui_code", "界面实现", "ui_developer"),
            _ai("scene", "界面场景", "scene_developer"),
            _ai("qa", "QA 验证", "qa_engineer"),
            _gate("verification", "客观验证", NODE_TYPE_VERIFICATION),
        ),
    ),
    GameWorkflowSpec(
        key=WORKFLOW_TILEMAP,
        name="TileMap 关卡开发",
        description="关卡设计、TileMap、资源、场景与 QA",
        steps=(
            _ai("level", "关卡设计", "level_designer"),
            _ai("tilemap", "TileMap 实现", "tilemap_level_specialist"),
            _ai("resource", "资源整理", "godot_resource_specialist"),
            _ai("scene", "场景整合", "scene_developer"),
            _ai("qa", "QA 验证", "qa_engineer"),
            _gate("verification", "客观验证", NODE_TYPE_VERIFICATION),
        ),
    ),
    GameWorkflowSpec(
        key=WORKFLOW_CODE_QUALITY,
        name="代码审查与质量改进",
        description="重构、回归实现与 QA 复核",
        steps=(
            _ai("refactor", "代码重构", "code_quality_refactoring_engineer"),
            _ai("gameplay_fix", "回归修复", "gameplay_programmer"),
            _ai("qa", "QA 复核", "qa_engineer"),
            _gate("verification", "客观验证", NODE_TYPE_VERIFICATION),
        ),
    ),
)

_WORKFLOWS: dict[str, GameWorkflowSpec] = {spec.key: spec for spec in GAME_WORKFLOWS}
_AGENT_KEYS = {spec.key for spec in SPECIALIZED_AGENTS}


def build_document(spec: GameWorkflowSpec) -> dict:
    """把模板转换为 E4 Workflow Definition 文档；每个 AI 节点都有 Phase Review。"""

    phases = []
    nodes = []
    for index, step in enumerate(spec.steps):
        phase_key = f"phase_{step.key}"
        phases.append(
            {
                "phase_key": phase_key,
                "name": step.name,
                "sequence": index + 1,
                "entry_criteria": "上一 Phase 已通过评审" if index else "Workflow 已启动",
                "exit_criteria": "产出满足验收标准",
                "review_required": step.review_required,
            }
        )
        config = {"agent_key": step.agent_key} if step.agent_key else {}
        nodes.append(
            {
                "node_key": step.key,
                "node_type": step.node_type,
                "config": config,
                "next_node_rules": [spec.steps[index + 1].key]
                if index + 1 < len(spec.steps)
                else [],
                "dependency_keys": [spec.steps[index - 1].key] if index else [],
                "phase_key": phase_key,
            }
        )
    return {"nodes": nodes, "phases": phases}


def validate_workflow_specs() -> None:
    for spec in GAME_WORKFLOWS:
        for step in spec.steps:
            if step.node_type == NODE_TYPE_AI_EXECUTION:
                if step.agent_key not in _AGENT_KEYS:
                    raise ValueError(f"{spec.key} 引用未登记 Agent: {step.agent_key}")
                if not step.review_required:
                    raise ValueError(f"{spec.key}/{step.key} 缺少 Phase Review")
        build_document(spec)


class GameWorkflowService:
    def __init__(
        self,
        *,
        definitions: WorkflowDefinitionService,
        instances: WorkflowInstanceService,
    ) -> None:
        self._definitions = definitions
        self._instances = instances

    def list_specs(self) -> tuple[GameWorkflowSpec, ...]:
        return GAME_WORKFLOWS

    def get(self, key: str) -> GameWorkflowSpec:
        spec = _WORKFLOWS.get(key)
        if spec is None:
            raise NotFoundError("游戏工作流未登记", details={"workflow_key": key})
        return spec

    async def ensure_definition(self, key: str) -> WorkflowDefinitionView:
        spec = self.get(key)
        name = f"game_workflow_{spec.key}"
        page = await self._definitions.list(limit=200, offset=0)
        for item in page["items"]:
            if item.get("name") == name:
                return await self._definitions.get(item["definition_id"])
        return await self._definitions.create(
            name=name,
            category=WORKFLOW_CATEGORY,
            description=spec.description,
            document=build_document(spec),
        )

    async def instantiate(
        self, key: str, *, project_id: str, task_id: str
    ) -> InstanceView:
        definition = await self.ensure_definition(key)
        return await self._instances.create(
            project_id=project_id,
            task_id=task_id,
            definition_id=definition.definition_id,
        )


__all__ = [
    "GAME_WORKFLOWS",
    "WORKFLOW_CATEGORY",
    "GameWorkflowService",
    "GameWorkflowSpec",
    "WorkflowStep",
    "build_document",
    "validate_workflow_specs",
]
