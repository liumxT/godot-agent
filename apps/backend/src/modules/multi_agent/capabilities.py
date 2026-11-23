"""Capability 目录与候选匹配（E7-T02）。

能力（Capability）描述“能做什么”，权限（Permission）描述“被允许做什么”，
二者必须分开。匹配分两阶段：

1. 硬性过滤：启用状态、能力、权限上限、Tool、Model 能力、项目访问、预算；
2. 软性排序：能力覆盖度、成功率、当前负载、预计成本。

软性评分永远不能覆盖硬性限制。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from modules.multi_agent.models import (
    CAPABILITY_CATEGORY_ART,
    CAPABILITY_CATEGORY_DESIGN,
    CAPABILITY_CATEGORY_GODOT,
    CAPABILITY_CATEGORY_PROGRAMMING,
    CAPABILITY_CATEGORY_QA,
    DEFAULT_RISK_PROFILE,
    RISK_PROFILES,
)
from modules.tool.models import RISK_RANK

REASON_AGENT_DISABLED = "AGENT_DISABLED"
REASON_CAPABILITY_MISSING = "CAPABILITY_MISSING"
REASON_PERMISSION_INSUFFICIENT = "PERMISSION_INSUFFICIENT"
REASON_TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
REASON_MODEL_CAPABILITY_UNKNOWN = "MODEL_CAPABILITY_UNKNOWN"
REASON_MODEL_CAPABILITY_UNSUPPORTED = "MODEL_CAPABILITY_UNSUPPORTED"
REASON_PROJECT_INACCESSIBLE = "PROJECT_INACCESSIBLE"
REASON_BUDGET_INSUFFICIENT = "BUDGET_INSUFFICIENT"

MODEL_SUPPORTED = "SUPPORTED"
MODEL_UNSUPPORTED = "UNSUPPORTED"

_STRUCTURED_OUTPUT = ("TEXT_INPUT", "TEXT_OUTPUT", "STRUCTURED_OUTPUT")


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    name: str
    category: str
    description: str
    input_contract: str = ""
    output_contract: str = ""
    required_tools: tuple[str, ...] = ()
    required_model_capabilities: tuple[str, ...] = _STRUCTURED_OUTPUT
    dependencies: tuple[str, ...] = ()
    risk_profile: str = DEFAULT_RISK_PROFILE
    validation_method: str = "review"


def _design(
    name: str, description: str, *, input_contract: str, output_contract: str
) -> CapabilitySpec:
    return CapabilitySpec(
        name=name,
        category=CAPABILITY_CATEGORY_DESIGN,
        description=description,
        input_contract=input_contract,
        output_contract=output_contract,
        validation_method="lead_review",
    )


def _code(
    name: str,
    description: str,
    *,
    tools: tuple[str, ...],
    risk_profile: str = "R2",
    output_contract: str = "code.change.v1",
) -> CapabilitySpec:
    return CapabilitySpec(
        name=name,
        category=CAPABILITY_CATEGORY_PROGRAMMING,
        description=description,
        input_contract="code.task.v1",
        output_contract=output_contract,
        required_tools=tools,
        risk_profile=risk_profile,
        validation_method="tests_and_review",
    )


def _godot(
    name: str, description: str, *, tools: tuple[str, ...], risk_profile: str = "R2"
) -> CapabilitySpec:
    return CapabilitySpec(
        name=name,
        category=CAPABILITY_CATEGORY_GODOT,
        description=description,
        input_contract="godot.change.v1",
        output_contract="godot.change.result.v1",
        required_tools=tools,
        risk_profile=risk_profile,
        validation_method="editor_observation",
    )


def _art(name: str, description: str, output_contract: str) -> CapabilitySpec:
    return CapabilitySpec(
        name=name,
        category=CAPABILITY_CATEGORY_ART,
        description=description,
        input_contract="art.brief.v1",
        output_contract=output_contract,
        required_model_capabilities=("TEXT_INPUT", "TEXT_OUTPUT"),
        validation_method="lead_review",
    )


def _qa(name: str, description: str, *, tools: tuple[str, ...], risk_profile: str = "R1") -> CapabilitySpec:
    return CapabilitySpec(
        name=name,
        category=CAPABILITY_CATEGORY_QA,
        description=description,
        input_contract="qa.scope.v1",
        output_contract="qa.report.v1",
        required_tools=tools,
        risk_profile=risk_profile,
        validation_method="verification",
    )


BUILTIN_CAPABILITIES: tuple[CapabilitySpec, ...] = (
    # 游戏设计
    _design(
        "game_concept_design",
        "定义游戏概念、目标受众与核心体验",
        input_contract="design.brief.v1",
        output_contract="design.concept.v1",
    ),
    _design(
        "gameplay_design",
        "定义核心玩法规则、玩家行为与机制交互",
        input_contract="design.concept.v1",
        output_contract="design.gameplay.v1",
    ),
    _design(
        "level_design",
        "设计关卡布局、流程、难度曲线与空间结构",
        input_contract="design.gameplay.v1",
        output_contract="design.level.v1",
    ),
    _design(
        "game_balance_design",
        "定义数值框架、成长曲线与平衡目标",
        input_contract="design.gameplay.v1",
        output_contract="design.balance.v1",
    ),
    _design(
        "narrative_design",
        "定义叙事结构、角色与文本内容",
        input_contract="design.concept.v1",
        output_contract="design.narrative.v1",
    ),
    # 程序开发
    _code(
        "gameplay_programming",
        "实现玩家移动、跳跃、攻击、受伤与死亡等核心玩法",
        tools=("file.read", "file.write", "file.create", "file.patch"),
    ),
    _code(
        "game_system_programming",
        "实现游戏系统、状态管理与模块接口",
        tools=("file.read", "file.write", "file.patch"),
    ),
    _code(
        "ui_programming",
        "实现 HUD、菜单与界面交互逻辑",
        tools=("file.read", "file.write", "godot.scene.create", "godot.node.create"),
    ),
    _code(
        "data_save_programming",
        "实现存档、配置与数据持久化",
        tools=("file.read", "file.write", "file.patch"),
    ),
    _code(
        "performance_optimization",
        "分析并优化运行时性能",
        tools=("file.read", "file.patch", "godot.debug.get_errors"),
        output_contract="code.optimization.v1",
    ),
    _code(
        "code_refactoring",
        "在不改变行为的前提下重构代码",
        tools=("file.read", "file.write", "file.patch"),
        output_contract="code.refactor.v1",
    ),
    # Godot 专业能力
    _godot(
        "scene_development",
        "创建、组织并保存 Godot 场景",
        tools=("godot.scene.create", "godot.scene.open", "godot.scene.save"),
    ),
    _godot(
        "node_configuration",
        "创建、重命名与组织节点层级",
        tools=("godot.node.create", "godot.node.rename", "godot.node.set_parent"),
    ),
    _godot(
        "inspector_property_editing",
        "读取与修改 Inspector 属性",
        tools=("godot.inspector.get_properties", "godot.inspector.set_property"),
        risk_profile="R2",
    ),
    _godot(
        "signal_configuration",
        "连接与断开关联信号",
        tools=("godot.signal.list", "godot.signal.connect", "godot.signal.disconnect"),
    ),
    _godot(
        "group_management",
        "管理节点分组",
        tools=("godot.group.list", "godot.group.add", "godot.group.remove"),
        risk_profile="R1",
    ),
    _godot(
        "animation_configuration",
        "创建动画并配置动画轨道",
        tools=("godot.animation.list", "godot.animation.create", "godot.animation.add_track"),
    ),
    _godot(
        "tilemap_development",
        "维护 TileMap 图层与单元格",
        tools=("godot.tilemap.get_layers", "godot.tilemap.get_cells", "godot.tilemap.set_cells"),
    ),
    _godot(
        "resource_management",
        "管理项目内资源引用与文件",
        tools=("file.read", "file.list", "file.stat"),
        risk_profile="R1",
    ),
    _godot(
        "editor_automation",
        "通过编辑器命令自动执行重复操作",
        tools=("godot.scene.list", "godot.node.list"),
        risk_profile="R2",
    ),
    _godot(
        "runtime_debugging",
        "读取运行状态、错误与输出用于定位问题",
        tools=("godot.runtime.get_status", "godot.debug.get_errors", "godot.debug.get_output"),
        risk_profile="R0",
    ),
    # 美术与内容
    _art("2d_art_creation", "创建 2D 美术内容", "art.asset.v1"),
    _art("2d_technical_art", "把美术需求转换为资源规范", "art.technical.v1"),
    _art("ui_ux_design", "设计界面结构与交互体验", "design.ui.v1"),
    _art("animation_design", "设计动画表现与节奏", "art.animation.v1"),
    _art("audio_design", "设计音效与音乐需求", "art.audio.v1"),
    _art("vfx_creation", "设计视觉特效需求", "art.vfx.v1"),
    _art("asset_pipeline_management", "管理资源导入与命名规范", "art.pipeline.v1"),
    # 质量与交付
    _qa("qa_testing", "设计并执行测试用例", tools=("godot.runtime.start", "godot.debug.get_errors")),
    _qa("test_automation", "自动化重复测试流程", tools=("file.read", "godot.runtime.start")),
    _qa("project_planning", "规划任务顺序、依赖与交付边界", tools=(), risk_profile="R0"),
    _qa("build_release", "准备构建与发布检查", tools=("godot.runtime.get_status",), risk_profile="R1"),
)

BUILTIN_CAPABILITY_NAMES = frozenset(spec.name for spec in BUILTIN_CAPABILITIES)


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    capabilities: tuple[str, ...]
    required_tools: tuple[str, ...] = ()
    required_model_capabilities: tuple[str, ...] = ()
    required_risk_level: str = "R0"
    project_id: str | None = None

    def __post_init__(self) -> None:
        if not self.capabilities:
            raise ValueError("至少需要一个能力")
        if self.required_risk_level not in RISK_PROFILES:
            raise ValueError(f"未知风险等级: {self.required_risk_level}")


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    definition_id: str
    name: str
    enabled: bool
    capabilities: tuple[str, ...]
    permission_ceiling: str
    available_tools: frozenset[str] = field(default_factory=frozenset)
    model_capabilities: Mapping[str, str] = field(default_factory=dict)
    project_id: str | None = None
    project_accessible: bool = True
    budget_available: bool = True
    current_load: int = 0
    max_concurrency: int = 1
    success_rate: float = 0.0
    estimated_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    definition_id: str
    name: str
    eligible: bool
    reasons: tuple[str, ...]
    score: float


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    ranked: tuple[CandidateEvaluation, ...]
    excluded: tuple[CandidateEvaluation, ...]

    @property
    def best(self) -> CandidateEvaluation | None:
        return self.ranked[0] if self.ranked else None


def _hard_filters(
    requirement: CapabilityRequirement, candidate: CandidateProfile
) -> list[str]:
    reasons: list[str] = []
    if not candidate.enabled:
        reasons.append(REASON_AGENT_DISABLED)
    missing = [cap for cap in requirement.capabilities if cap not in candidate.capabilities]
    if missing:
        reasons.append(REASON_CAPABILITY_MISSING)
    if RISK_RANK.get(candidate.permission_ceiling, -1) < RISK_RANK[
        requirement.required_risk_level
    ]:
        reasons.append(REASON_PERMISSION_INSUFFICIENT)
    if any(tool not in candidate.available_tools for tool in requirement.required_tools):
        reasons.append(REASON_TOOL_UNAVAILABLE)
    for capability in requirement.required_model_capabilities:
        status = candidate.model_capabilities.get(capability)
        if status is None or status == "UNKNOWN":
            reasons.append(REASON_MODEL_CAPABILITY_UNKNOWN)
            break
        if status != MODEL_SUPPORTED:
            reasons.append(REASON_MODEL_CAPABILITY_UNSUPPORTED)
            break
    if requirement.project_id is not None and (
        candidate.project_id != requirement.project_id or not candidate.project_accessible
    ):
        reasons.append(REASON_PROJECT_INACCESSIBLE)
    if not candidate.budget_available:
        reasons.append(REASON_BUDGET_INSUFFICIENT)
    return reasons


def _score(
    requirement: CapabilityRequirement,
    candidate: CandidateProfile,
    *,
    cost_reference: float,
) -> float:
    coverage = len(set(requirement.capabilities) & set(candidate.capabilities)) / len(
        set(requirement.capabilities)
    )
    success = max(0.0, min(candidate.success_rate, 1.0))
    load_ratio = min(
        candidate.current_load / max(candidate.max_concurrency, 1),
        1.0,
    )
    cost_ratio = 0.0
    if cost_reference > 0:
        cost_ratio = min(max(candidate.estimated_cost, 0.0) / cost_reference, 1.0)
    return round(50.0 * coverage + 30.0 * success + 20.0 * (1.0 - load_ratio) - 10.0 * cost_ratio, 4)


def match_candidates(
    requirement: CapabilityRequirement, candidates: Iterable[CandidateProfile]
) -> MatchOutcome:
    """两阶段匹配：先硬性过滤，再对合格候选按软性评分排序。"""

    profiles = list(candidates)
    evaluations: list[tuple[CandidateProfile, CandidateEvaluation]] = []
    for candidate in profiles:
        reasons = _hard_filters(requirement, candidate)
        evaluations.append(
            (
                candidate,
                CandidateEvaluation(
                    definition_id=candidate.definition_id,
                    name=candidate.name,
                    eligible=not reasons,
                    reasons=tuple(dict.fromkeys(reasons)),
                    score=0.0,
                ),
            )
        )
    eligible = [(profile, item) for profile, item in evaluations if item.eligible]
    cost_reference = max((profile.estimated_cost for profile, _ in eligible), default=0.0)
    scored = [
        (
            CandidateEvaluation(
                definition_id=item.definition_id,
                name=item.name,
                eligible=True,
                reasons=(),
                score=_score(requirement, profile, cost_reference=cost_reference),
            ),
            profile.definition_id,
        )
        for profile, item in eligible
    ]
    scored.sort(key=lambda pair: (-pair[0].score, pair[1]))
    excluded = tuple(item for _, item in evaluations if not item.eligible)
    return MatchOutcome(ranked=tuple(item for item, _ in scored), excluded=excluded)


__all__ = [
    "BUILTIN_CAPABILITIES",
    "BUILTIN_CAPABILITY_NAMES",
    "MODEL_SUPPORTED",
    "MODEL_UNSUPPORTED",
    "REASON_AGENT_DISABLED",
    "REASON_BUDGET_INSUFFICIENT",
    "REASON_CAPABILITY_MISSING",
    "REASON_MODEL_CAPABILITY_UNKNOWN",
    "REASON_MODEL_CAPABILITY_UNSUPPORTED",
    "REASON_PERMISSION_INSUFFICIENT",
    "REASON_PROJECT_INACCESSIBLE",
    "REASON_TOOL_UNAVAILABLE",
    "CandidateEvaluation",
    "CandidateProfile",
    "CapabilityRequirement",
    "CapabilitySpec",
    "MatchOutcome",
    "match_candidates",
]
