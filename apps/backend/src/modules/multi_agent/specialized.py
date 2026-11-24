"""专用 Agent 目录（E7-T13）。

目录为每个专业角色提供统一 Definition 结构：身份、职责、能力、工具、权限上限、
输入/输出契约、验收标准、协作规则与版本。P0 角色具备完整可执行定义，P1/P2
使用同一结构的基础定义；实际执行仍由 E6 Runtime 与 Tool System 约束。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from core.errors import NotFoundError
from modules.agent_runtime.service import DefinitionRegistryService, DefinitionView
from modules.multi_agent.capabilities import BUILTIN_CAPABILITY_NAMES
from modules.multi_agent.models import RISK_PROFILES
from modules.prompt.service import PromptService

PRIORITY_P0 = "P0"
PRIORITY_P1 = "P1"
PRIORITY_P2 = "P2"
PRIORITIES = (PRIORITY_P0, PRIORITY_P1, PRIORITY_P2)

DOMAIN_DESIGN = "DESIGN"
DOMAIN_PROGRAMMING = "PROGRAMMING"
DOMAIN_GODOT = "GODOT"
DOMAIN_ART = "ART"
DOMAIN_QA = "QA"

EXECUTION_READY_AGENTS = frozenset(
    {
        "game_designer",
        "gameplay_designer",
        "level_designer",
        "gameplay_programmer",
        "scene_developer",
        "qa_engineer",
    }
)


@dataclass(frozen=True, slots=True)
class SpecializedAgentSpec:
    key: str
    name: str
    role: str
    description: str
    domain: str
    priority: str
    capabilities: tuple[str, ...]
    required_tools: tuple[str, ...]
    permission_ceiling: str
    input_contract: str
    output_contract: str
    acceptance_criteria: tuple[str, ...]
    collaboration_rules: tuple[str, ...]
    version: str = "1.0.0"

    @property
    def execution_ready(self) -> bool:
        return self.key in EXECUTION_READY_AGENTS


def _spec(
    key: str,
    name: str,
    role: str,
    description: str,
    domain: str,
    priority: str,
    capabilities: Iterable[str],
    tools: Iterable[str],
    ceiling: str,
    input_contract: str,
    output_contract: str,
    acceptance: Iterable[str],
    rules: Iterable[str],
) -> SpecializedAgentSpec:
    return SpecializedAgentSpec(
        key=key,
        name=name,
        role=role,
        description=description,
        domain=domain,
        priority=priority,
        capabilities=tuple(capabilities),
        required_tools=tuple(tools),
        permission_ceiling=ceiling,
        input_contract=input_contract,
        output_contract=output_contract,
        acceptance_criteria=tuple(acceptance),
        collaboration_rules=tuple(rules),
    )


_READ = ("file.read",)
_WRITE = ("file.read", "file.write", "file.patch")

SPECIALIZED_AGENTS: tuple[SpecializedAgentSpec, ...] = (
    # ---- P0 ----
    _spec(
        "game_designer",
        "Game Designer",
        "游戏概念设计",
        "定义游戏概念、目标受众与核心体验",
        DOMAIN_DESIGN,
        PRIORITY_P0,
        ("game_concept_design",),
        _READ,
        "R1",
        "design.brief.v1",
        "design.concept.v1",
        ("概念文档覆盖目标受众与核心循环",),
        ("概念必须交给 Gameplay Designer 细化", "不得直接修改项目文件"),
    ),
    _spec(
        "gameplay_designer",
        "Gameplay Designer",
        "核心玩法设计",
        "定义玩家行为、规则与机制交互",
        DOMAIN_DESIGN,
        PRIORITY_P0,
        ("gameplay_design",),
        _READ,
        "R1",
        "design.concept.v1",
        "design.gameplay.v1",
        ("玩法规则可被程序实现", "边界条件与失败状态明确"),
        ("与 Level Designer 对齐关卡约束",),
    ),
    _spec(
        "level_designer",
        "Level Designer",
        "关卡设计",
        "设计关卡布局、流程与难度曲线",
        DOMAIN_DESIGN,
        PRIORITY_P0,
        ("level_design",),
        _READ,
        "R1",
        "design.gameplay.v1",
        "design.level.v1",
        ("关卡流程完整且可通关",),
        ("关卡资源需求交给 Scene Developer",),
    ),
    _spec(
        "game_architect",
        "Game Architect",
        "游戏架构设计",
        "划分系统边界、模块接口与数据流",
        DOMAIN_PROGRAMMING,
        PRIORITY_P0,
        ("game_system_programming", "project_planning"),
        _READ,
        "R1",
        "design.gameplay.v1",
        "code.architecture.v1",
        ("模块接口与依赖方向明确",),
        ("不得直接修改实现文件",),
    ),
    _spec(
        "gameplay_programmer",
        "Gameplay Programmer",
        "核心玩法程序",
        "实现移动、跳跃、攻击、受伤与死亡等玩法",
        DOMAIN_PROGRAMMING,
        PRIORITY_P0,
        ("gameplay_programming",),
        _WRITE,
        "R2",
        "design.gameplay.v1",
        "code.change.v1",
        ("玩法行为符合设计", "相关测试通过"),
        ("写文件需 Resource Lock 与 ChangeSet",),
    ),
    _spec(
        "ui_developer",
        "UI Developer",
        "界面开发",
        "实现 HUD、菜单与界面交互逻辑",
        DOMAIN_PROGRAMMING,
        PRIORITY_P0,
        ("ui_programming", "ui_ux_design"),
        ("file.read", "file.write", "godot.scene.create", "godot.node.create"),
        "R2",
        "design.ui.v1",
        "code.change.v1",
        ("界面元素可交互且布局正确",),
        ("遵守 UI/UX 规范",),
    ),
    _spec(
        "scene_developer",
        "Scene Developer",
        "场景开发",
        "创建、组织并保存 Godot 场景",
        DOMAIN_GODOT,
        PRIORITY_P0,
        ("scene_development", "node_configuration"),
        ("godot.scene.create", "godot.scene.open", "godot.scene.save", "godot.node.create"),
        "R2",
        "godot.change.v1",
        "godot.change.result.v1",
        ("场景可在编辑器中打开且节点结构正确",),
        ("场景写入必须持有资源锁",),
    ),
    _spec(
        "inspector_property_specialist",
        "Inspector Property Specialist",
        "属性配置",
        "读取与修改 Inspector 属性",
        DOMAIN_GODOT,
        PRIORITY_P0,
        ("inspector_property_editing",),
        ("godot.inspector.get_properties", "godot.inspector.set_property"),
        "R2",
        "godot.change.v1",
        "godot.change.result.v1",
        ("属性修改可追溯到变更记录",),
        ("批量属性修改需说明依据",),
    ),
    _spec(
        "tilemap_level_specialist",
        "TileMap Level Specialist",
        "TileMap 关卡",
        "维护 TileMap 图层与单元格",
        DOMAIN_GODOT,
        PRIORITY_P0,
        ("tilemap_development", "level_design"),
        ("godot.tilemap.get_layers", "godot.tilemap.get_cells", "godot.tilemap.set_cells"),
        "R2",
        "design.level.v1",
        "godot.change.result.v1",
        ("TileMap 数据与关卡设计一致",),
        ("图层写入需独占锁",),
    ),
    _spec(
        "godot_resource_specialist",
        "Godot Resource Specialist",
        "资源管理",
        "管理资源引用、导入与命名规范",
        DOMAIN_GODOT,
        PRIORITY_P0,
        ("resource_management", "asset_pipeline_management"),
        ("file.read", "file.list", "file.stat"),
        "R1",
        "art.pipeline.v1",
        "art.pipeline.result.v1",
        ("资源引用无悬空路径",),
        ("不得重命名未登记的共享资源",),
    ),
    _spec(
        "godot_integration_specialist",
        "Godot Integration Specialist",
        "编辑器集成",
        "通过编辑器命令执行重复操作并核对运行结果",
        DOMAIN_GODOT,
        PRIORITY_P0,
        ("editor_automation", "runtime_debugging"),
        ("godot.scene.list", "godot.node.list", "godot.debug.get_errors"),
        "R2",
        "godot.change.v1",
        "godot.change.result.v1",
        ("操作后编辑器状态与预期一致",),
        ("任何写入仍需 Tool Permission",),
    ),
    _spec(
        "2d_artist",
        "2D Artist",
        "2D 美术",
        "创建 2D 美术内容",
        DOMAIN_ART,
        PRIORITY_P0,
        ("2d_art_creation",),
        (
            "asset.read",
            "asset.brief.submit",
            "asset.generation.request",
            "asset.processing.request",
            "asset.review.submit",
        ),
        "R1",
        "art.brief.v1",
        "art.asset.v1",
        ("交付物符合美术简报",),
        ("资源命名遵循管线规范", "不得直接写项目文件，写入必须经 Tool System"),
    ),
    _spec(
        "ui_ux_designer",
        "UI/UX Designer",
        "界面体验设计",
        "设计界面结构与交互体验",
        DOMAIN_ART,
        PRIORITY_P0,
        ("ui_ux_design",),
        (),
        "R1",
        "design.brief.v1",
        "design.ui.v1",
        ("交互流程完整且可被 UI Developer 实现",),
        ("与 UI Developer 对齐组件边界",),
    ),
    _spec(
        "animation_specialist",
        "Animation Specialist",
        "动画",
        "设计动画表现并配置动画轨道",
        DOMAIN_ART,
        PRIORITY_P0,
        ("animation_design", "animation_configuration"),
        (
            "godot.animation.list",
            "godot.animation.create",
            "godot.animation.add_track",
            "asset.read",
            "asset.processing.request",
        ),
        "R2",
        "art.animation.v1",
        "art.animation.result.v1",
        ("动画轨道完整且可播放",),
        ("动画资源写入需锁", "资产处理必须经 Asset Pipeline"),
    ),
    _spec(
        "qa_engineer",
        "QA Engineer",
        "质量保证",
        "设计并执行测试用例",
        DOMAIN_QA,
        PRIORITY_P0,
        ("qa_testing", "test_automation"),
        ("godot.runtime.start", "godot.debug.get_errors"),
        "R1",
        "qa.scope.v1",
        "qa.report.v1",
        ("测试覆盖验收标准", "失败有复现证据"),
        ("QA 结论不能替代 Verification System",),
    ),
    # ---- P1 ----
    _spec(
        "game_systems_designer",
        "Game Systems Designer",
        "系统与数值设计",
        "定义系统规则与数值平衡",
        DOMAIN_DESIGN,
        PRIORITY_P1,
        ("gameplay_design", "game_balance_design"),
        _READ,
        "R1",
        "design.gameplay.v1",
        "design.balance.v1",
        ("数值目标与成长曲线明确",),
        ("数值调整需保留依据",),
    ),
    _spec(
        "game_balance_designer",
        "Game Balance Designer",
        "数值平衡",
        "维护成长曲线与平衡目标",
        DOMAIN_DESIGN,
        PRIORITY_P1,
        ("game_balance_design",),
        _READ,
        "R1",
        "design.gameplay.v1",
        "design.balance.v1",
        ("关键数值区间可验证",),
        ("不得直接修改运行时代码",),
    ),
    _spec(
        "game_systems_programmer",
        "Game Systems Programmer",
        "系统程序",
        "实现游戏系统与状态管理",
        DOMAIN_PROGRAMMING,
        PRIORITY_P1,
        ("game_system_programming",),
        _WRITE,
        "R2",
        "code.architecture.v1",
        "code.change.v1",
        ("系统状态迁移可测试",),
        ("接口变更需通知依赖方",),
    ),
    _spec(
        "data_save_programmer",
        "Data & Save Programmer",
        "存档与数据",
        "实现存档、配置与数据持久化",
        DOMAIN_PROGRAMMING,
        PRIORITY_P1,
        ("data_save_programming",),
        _WRITE,
        "R2",
        "code.task.v1",
        "code.change.v1",
        ("存档读写一致且可恢复",),
        ("版本迁移需保留兼容性",),
    ),
    _spec(
        "performance_optimization_engineer",
        "Performance Optimization Engineer",
        "性能优化",
        "分析并优化运行时性能",
        DOMAIN_PROGRAMMING,
        PRIORITY_P1,
        ("performance_optimization",),
        ("file.read", "file.patch", "godot.debug.get_errors"),
        "R2",
        "code.optimization.v1",
        "code.optimization.v1",
        ("优化前后有可对比指标",),
        ("不得牺牲行为正确性",),
    ),
    _spec(
        "code_quality_refactoring_engineer",
        "Code Quality Engineer",
        "代码质量",
        "在不改变行为的前提下重构代码",
        DOMAIN_PROGRAMMING,
        PRIORITY_P1,
        ("code_refactoring",),
        _WRITE,
        "R2",
        "code.refactor.v1",
        "code.refactor.v1",
        ("重构后测试保持通过",),
        ("必须保留原有公共契约",),
    ),
    _spec(
        "signal_interaction_specialist",
        "Signal Interaction Specialist",
        "信号交互",
        "连接与调试节点信号",
        DOMAIN_GODOT,
        PRIORITY_P1,
        ("signal_configuration",),
        ("godot.signal.list", "godot.signal.connect", "godot.signal.disconnect"),
        "R2",
        "godot.change.v1",
        "godot.change.result.v1",
        ("信号连接可被编辑器观察",),
        ("断开共享信号前需确认依赖",),
    ),
    _spec(
        "editor_automation_specialist",
        "Editor Automation Specialist",
        "编辑器自动化",
        "批量执行编辑器命令",
        DOMAIN_GODOT,
        PRIORITY_P1,
        ("editor_automation",),
        ("godot.scene.list", "godot.node.list"),
        "R2",
        "godot.change.v1",
        "godot.change.result.v1",
        ("批量操作结果可核对",),
        ("不得绕过 Tool System",),
    ),
    _spec(
        "art_director",
        "Art Director",
        "美术方向",
        "统一视觉风格与美术规范",
        DOMAIN_ART,
        PRIORITY_P1,
        ("2d_art_creation", "ui_ux_design"),
        ("asset.read", "asset.brief.submit", "asset.review.submit"),
        "R1",
        "art.brief.v1",
        "art.direction.v1",
        ("风格指南可被美术执行",),
        ("与 UX 规范保持一致", "不得直接写项目文件"),
    ),
    _spec(
        "2d_technical_artist",
        "2D Technical Artist",
        "技术美术",
        "把美术需求转换为资源规范",
        DOMAIN_ART,
        PRIORITY_P1,
        ("2d_technical_art",),
        ("file.read", "file.list"),
        "R1",
        "art.brief.v1",
        "art.technical.v1",
        ("资源规格可被管线导入",),
        ("与资源专家对齐命名",),
    ),
    _spec(
        "audio_designer",
        "Audio Designer",
        "音频设计",
        "设计音效与音乐需求",
        DOMAIN_ART,
        PRIORITY_P1,
        ("audio_design",),
        ("asset.read", "asset.brief.submit", "asset.generation.request"),
        "R1",
        "art.brief.v1",
        "art.audio.v1",
        ("音频需求包含触发条件",),
        ("资源引用交给资源专家", "音频生成必须经 Model Gateway"),
    ),
    _spec(
        "vfx_artist",
        "VFX Artist",
        "特效",
        "设计视觉特效需求",
        DOMAIN_ART,
        PRIORITY_P1,
        ("vfx_creation",),
        ("asset.read", "asset.brief.submit", "asset.generation.request"),
        "R1",
        "art.brief.v1",
        "art.vfx.v1",
        ("特效触发与性能预算明确",),
        ("高成本特效需性能评估",),
    ),
    _spec(
        "asset_pipeline_specialist",
        "Asset Pipeline Specialist",
        "资源管线",
        "管理资源导入与命名规范",
        DOMAIN_ART,
        PRIORITY_P1,
        ("asset_pipeline_management",),
        (
            "asset.read",
            "asset.dependency.read",
            "asset.import.request",
            "asset.import.status",
            "asset.provenance.read",
            "asset.license.read",
        ),
        "R1",
        "art.pipeline.v1",
        "art.pipeline.result.v1",
        ("资源命名与目录规范一致",),
        ("批量迁移需保留映射记录", "导入必须经 Tool System 与真实 Editor Import"),
    ),
    _spec(
        "lighting_rendering_artist",
        "Lighting & Rendering Artist",
        "光照渲染",
        "配置光照与渲染效果",
        DOMAIN_ART,
        PRIORITY_P1,
        ("vfx_creation",),
        ("godot.inspector.get_properties",),
        "R2",
        "art.brief.v1",
        "art.lighting.v1",
        ("效果与目标画风一致",),
        ("修改渲染设置需审批",),
    ),
    _spec(
        "ui_motion_designer",
        "UI Motion Designer",
        "界面动效",
        "设计界面动效与转场",
        DOMAIN_ART,
        PRIORITY_P1,
        ("animation_design", "ui_ux_design"),
        (),
        "R1",
        "design.ui.v1",
        "art.ui_motion.v1",
        ("动效时长与层级符合体验目标",),
        ("动效资源交给 UI Developer 落地",),
    ),
    _spec(
        "test_automation_engineer",
        "Test Automation Engineer",
        "测试自动化",
        "自动化重复测试流程",
        DOMAIN_QA,
        PRIORITY_P1,
        ("test_automation",),
        ("file.read", "godot.runtime.start"),
        "R1",
        "qa.scope.v1",
        "qa.automation.v1",
        ("自动化用例可重复执行",),
        ("不能替代人工验收",),
    ),
    _spec(
        "project_planning_delivery_agent",
        "Project Planning & Delivery",
        "计划与交付",
        "规划任务顺序、依赖与交付边界",
        DOMAIN_QA,
        PRIORITY_P1,
        ("project_planning",),
        (),
        "R0",
        "project.goal.v1",
        "project.plan.v1",
        ("依赖图无环且交付边界清晰",),
        ("不得修改 Task 状态",),
    ),
    _spec(
        "build_release_engineer",
        "Build & Release Engineer",
        "构建发布",
        "准备构建与发布检查",
        DOMAIN_QA,
        PRIORITY_P1,
        ("build_release",),
        ("godot.runtime.get_status",),
        "R1",
        "project.plan.v1",
        "release.report.v1",
        ("发布检查项全部有结果",),
        ("发布操作需要用户批准",),
    ),
    # ---- P2 ----
    _spec(
        "narrative_designer",
        "Narrative Designer",
        "叙事设计",
        "定义叙事结构、角色与文本",
        DOMAIN_DESIGN,
        PRIORITY_P2,
        ("narrative_design",),
        _READ,
        "R1",
        "design.concept.v1",
        "design.narrative.v1",
        ("叙事与玩法目标一致",),
        ("文本需可本地化",),
    ),
    _spec(
        "3d_artist",
        "3D Artist",
        "3D 美术",
        "创建 3D 资产需求与占位资源",
        DOMAIN_ART,
        PRIORITY_P2,
        ("2d_art_creation",),
        ("asset.read", "asset.brief.submit", "asset.generation.request"),
        "R1",
        "art.brief.v1",
        "art.asset.v1",
        ("资产规格与性能预算一致",),
        ("当前阶段以占位资源优先", "3D 生成能力通过 Adapter 扩展"),
    ),
    _spec(
        "3d_technical_artist",
        "3D Technical Artist",
        "3D 技术美术",
        "定义 3D 资源导入规范",
        DOMAIN_ART,
        PRIORITY_P2,
        ("2d_technical_art",),
        ("file.read", "file.list", "asset.read", "asset.brief.submit", "asset.processing.request"),
        "R1",
        "art.brief.v1",
        "art.technical.v1",
        ("导入规范可被管线执行",),
        ("需要资源管线配合",),
    ),
    _spec(
        "cinematic_designer",
        "Cinematic Designer",
        "过场设计",
        "设计过场与镜头表现",
        DOMAIN_ART,
        PRIORITY_P2,
        ("animation_design",),
        (),
        "R1",
        "design.narrative.v1",
        "art.cinematic.v1",
        ("镜头清单可被实现",),
        ("过场可跳过",),
    ),
    _spec(
        "post_processing_artist",
        "Post Processing Artist",
        "后处理",
        "设计后处理与画面风格",
        DOMAIN_ART,
        PRIORITY_P2,
        ("vfx_creation",),
        (),
        "R1",
        "art.brief.v1",
        "art.post.v1",
        ("后处理参数在性能预算内",),
        ("需保留可关闭选项",),
    ),
)

_CATALOG: dict[str, SpecializedAgentSpec] = {spec.key: spec for spec in SPECIALIZED_AGENTS}
_CATALOG_BY_NAME: dict[str, SpecializedAgentSpec] = {spec.name: spec for spec in SPECIALIZED_AGENTS}


def validate_catalog() -> None:
    """启动自检：能力名与风险等级必须已登记。"""

    for spec in SPECIALIZED_AGENTS:
        if spec.priority not in PRIORITIES:
            raise ValueError(f"未知优先级: {spec.priority}")
        unknown = set(spec.capabilities) - BUILTIN_CAPABILITY_NAMES
        if unknown:
            raise ValueError(f"{spec.key} 使用未登记能力: {sorted(unknown)}")
        if spec.permission_ceiling not in RISK_PROFILES:
            raise ValueError(f"{spec.key} 权限上限非法: {spec.permission_ceiling}")
        if not spec.acceptance_criteria:
            raise ValueError(f"{spec.key} 缺少验收标准")


class SpecializedAgentCatalog:
    def __init__(
        self,
        *,
        definitions: DefinitionRegistryService,
        prompts: PromptService,
    ) -> None:
        self._definitions = definitions
        self._prompts = prompts

    def list(self, *, priority: str | None = None) -> tuple[SpecializedAgentSpec, ...]:
        if priority is None:
            return SPECIALIZED_AGENTS
        return tuple(spec for spec in SPECIALIZED_AGENTS if spec.priority == priority)

    def get(self, key: str) -> SpecializedAgentSpec:
        spec = _CATALOG.get(key) or _CATALOG_BY_NAME.get(key)
        if spec is None:
            raise NotFoundError("专用 Agent 未登记", details={"agent_key": key})
        return spec

    async def ensure_definition(self, key: str, *, created_by: str | None = None) -> DefinitionView:
        spec = self.get(key)
        prompt_name = f"agent_{spec.key}"
        try:
            await self._prompts.get_version(prompt_name, 1)
        except NotFoundError:
            await self._prompts.create(
                name=prompt_name,
                category="AGENT",
                content=(
                    f"你是 {spec.name}（{spec.role}）。职责：{spec.description}。"
                    f"输入契约：{spec.input_contract}；输出契约：{spec.output_contract}。"
                    "必须遵守 Tool System、Permission 与 Resource Lock；"
                    "不得绕过 Orchestrator 创建 Assignment 或修改 Task 状态。"
                ),
            )
        try:
            existing = await self._definitions.get_by_name(spec.key)
            if existing.current_version:
                return existing
            definition = existing
        except NotFoundError:
            definition = await self._definitions.create(
                name=spec.key,
                description=spec.description,
                category=spec.domain,
                capabilities=spec.capabilities,
                model_policy_id="default_agent_policy",
                prompt_profile_id=prompt_name,
                prompt_version=1,
                tool_whitelist=spec.required_tools,
                permission_ceiling=spec.permission_ceiling,
                max_concurrency=1,
                created_by=created_by,
            )
        await self._definitions.publish(definition.definition_id)
        return await self._definitions.get(definition.definition_id)

    async def ensure_all(
        self, *, priorities: Iterable[str] = (PRIORITY_P0,), created_by: str | None = None
    ) -> dict[str, DefinitionView]:
        selected = set(priorities)
        result: dict[str, DefinitionView] = {}
        for spec in SPECIALIZED_AGENTS:
            if spec.priority in selected:
                result[spec.key] = await self.ensure_definition(spec.key, created_by=created_by)
        return result


__all__ = [
    "EXECUTION_READY_AGENTS",
    "PRIORITIES",
    "PRIORITY_P0",
    "PRIORITY_P1",
    "PRIORITY_P2",
    "SPECIALIZED_AGENTS",
    "SpecializedAgentCatalog",
    "SpecializedAgentSpec",
    "validate_catalog",
]
