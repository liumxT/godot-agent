"""内置工具目录（E5-T28 / T29）。

Godot 工具必须经 Editor Plugin 的真实 Editor API 执行；文件工具限制在
项目根目录内。目录在启动时幂等登记，已存在且内容一致的版本不会重复写入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.errors import NotFoundError
from modules.tool.registry import ToolRegistryService

GENERIC_OUTPUT: dict[str, Any] = {"type": "object"}


def _obj(properties: dict[str, Any] | None = None, required: tuple[str, ...] = ()) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties or {},
    }
    if required:
        schema["required"] = list(required)
    return schema


def _str(description: str) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "description": description}


_SCENE = _str("场景资源路径（res:// 开头）")
_NODE = _str("节点路径（相对场景根节点，如 Player/Sprite2D）")

__all__ = [
    "ASSET_TOOLS",
    "BUILTIN_TOOLS",
    "FILE_TOOLS",
    "GODOT_TOOLS",
    "ToolSpec",
    "ensure_builtin_tools",
]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    category: str
    description: str
    risk_level: str
    input_schema: dict[str, Any]
    permissions: tuple[str, ...] = ("project.read",)
    capabilities: tuple[str, ...] = ()
    timeout_seconds: int = 60
    tags: tuple[str, ...] = field(default_factory=tuple)


def _read(name: str, category: str, description: str, schema: dict[str, Any]) -> ToolSpec:
    return ToolSpec(
        name=name,
        category=category,
        description=description,
        risk_level="R0",
        input_schema=schema,
    )


def _write(
    name: str,
    category: str,
    description: str,
    schema: dict[str, Any],
    *,
    risk_level: str = "R2",
    capabilities: tuple[str, ...] = ("PROJECT_WRITE",),
) -> ToolSpec:
    return ToolSpec(
        name=name,
        category=category,
        description=description,
        risk_level=risk_level,
        input_schema=schema,
        permissions=("project.write",),
        capabilities=capabilities,
    )


GODOT_TOOLS: tuple[ToolSpec, ...] = (
    _read("godot.project.get_info", "GODOT_EDITOR", "读取项目名称、版本与根路径", _obj()),
    _read(
        "godot.project.get_settings",
        "GODOT_EDITOR",
        "读取 ProjectSettings",
        _obj({"keys": {"type": "array", "items": {"type": "string"}}}),
    ),
    _read("godot.scene.list", "SCENE", "列出项目中的场景文件", _obj()),
    _read("godot.scene.get", "SCENE", "读取场景结构", _obj({"path": _SCENE}, ("path",))),
    _write(
        "godot.scene.create",
        "SCENE",
        "新建场景并保存",
        _obj(
            {"path": _SCENE, "root_type": _str("根节点类型，如 Node2D")},
            ("path", "root_type"),
        ),
    ),
    _write("godot.scene.open", "SCENE", "在编辑器中打开场景", _obj({"path": _SCENE}, ("path",))),
    _write(
        "godot.scene.save",
        "SCENE",
        "保存场景",
        _obj({"path": _SCENE}),
    ),
    _read("godot.node.list", "NODE", "列出场景节点", _obj({"scene_path": _SCENE})),
    _read(
        "godot.node.get",
        "NODE",
        "读取节点详情",
        _obj({"node_path": _NODE, "scene_path": _SCENE}, ("node_path",)),
    ),
    _write(
        "godot.node.create",
        "NODE",
        "创建节点",
        _obj(
            {"node_path": _NODE, "node_type": _str("节点类型"), "scene_path": _SCENE},
            ("node_path", "node_type"),
        ),
    ),
    _write(
        "godot.node.delete",
        "NODE",
        "删除节点",
        _obj({"node_path": _NODE, "scene_path": _SCENE}, ("node_path",)),
        risk_level="R3",
        capabilities=("PROJECT_DELETE",),
    ),
    _write(
        "godot.node.rename",
        "NODE",
        "重命名节点",
        _obj({"node_path": _NODE, "new_name": _str("新名称"), "scene_path": _SCENE}, ("node_path", "new_name")),
    ),
    _write(
        "godot.node.set_parent",
        "NODE",
        "调整节点父级",
        _obj(
            {"node_path": _NODE, "new_parent_path": _NODE, "scene_path": _SCENE},
            ("node_path", "new_parent_path"),
        ),
    ),
    _read(
        "godot.inspector.get_properties",
        "INSPECTOR",
        "读取节点可编辑属性",
        _obj({"node_path": _NODE, "scene_path": _SCENE}, ("node_path",)),
    ),
    _read(
        "godot.inspector.get_property",
        "INSPECTOR",
        "读取单个属性值",
        _obj({"node_path": _NODE, "property": _str("属性名"), "scene_path": _SCENE}, ("node_path", "property")),
    ),
    _write(
        "godot.inspector.set_property",
        "INSPECTOR",
        "设置节点属性",
        _obj(
            {"node_path": _NODE, "property": _str("属性名"), "value": {}, "scene_path": _SCENE},
            ("node_path", "property", "value"),
        ),
        risk_level="R1",
    ),
    _read("godot.signal.list", "SIGNAL", "列出节点信号", _obj({"node_path": _NODE}, ("node_path",))),
    _write(
        "godot.signal.connect",
        "SIGNAL",
        "连接信号",
        _obj(
            {
                "node_path": _NODE,
                "signal_name": _str("信号名"),
                "target_path": _NODE,
                "method": _str("目标方法名"),
            },
            ("node_path", "signal_name", "target_path", "method"),
        ),
        risk_level="R1",
    ),
    _write(
        "godot.signal.disconnect",
        "SIGNAL",
        "断开信号",
        _obj(
            {
                "node_path": _NODE,
                "signal_name": _str("信号名"),
                "target_path": _NODE,
                "method": _str("目标方法名"),
            },
            ("node_path", "signal_name", "target_path", "method"),
        ),
        risk_level="R1",
    ),
    _read("godot.group.list", "GROUP", "列出节点的分组", _obj({"node_path": _NODE}, ("node_path",))),
    _write(
        "godot.group.add",
        "GROUP",
        "把节点加入分组",
        _obj({"node_path": _NODE, "group": _str("分组名")}, ("node_path", "group")),
        risk_level="R1",
    ),
    _write(
        "godot.group.remove",
        "GROUP",
        "把节点移出分组",
        _obj({"node_path": _NODE, "group": _str("分组名")}, ("node_path", "group")),
        risk_level="R1",
    ),
    _read(
        "godot.animation.list",
        "ANIMATION",
        "列出 AnimationPlayer 动画",
        _obj({"node_path": _NODE}, ("node_path",)),
    ),
    _write(
        "godot.animation.create",
        "ANIMATION",
        "创建动画",
        _obj({"node_path": _NODE, "animation_name": _str("动画名")}, ("node_path", "animation_name")),
    ),
    _write(
        "godot.animation.add_track",
        "ANIMATION",
        "为动画添加轨道",
        _obj(
            {"node_path": _NODE, "animation_name": _str("动画名"), "track_type": _str("轨道类型")},
            ("node_path", "animation_name", "track_type"),
        ),
    ),
    _read(
        "godot.tilemap.get_layers",
        "TILEMAP",
        "列出 TileMap 图层",
        _obj({"node_path": _NODE}, ("node_path",)),
    ),
    _read(
        "godot.tilemap.get_cells",
        "TILEMAP",
        "读取图层单元",
        _obj({"node_path": _NODE, "layer": {"type": "integer"}}, ("node_path",)),
    ),
    _write(
        "godot.tilemap.set_cells",
        "TILEMAP",
        "写入图层单元",
        _obj(
            {
                "node_path": _NODE,
                "layer": {"type": "integer"},
                "cells": {"type": "array", "items": {"type": "object"}},
            },
            ("node_path", "cells"),
        ),
    ),
    _write(
        "godot.runtime.start",
        "GODOT_RUNTIME",
        "启动主场景运行",
        _obj({"scene_path": _SCENE}),
        risk_level="R1",
    ),
    _write("godot.runtime.stop", "GODOT_RUNTIME", "停止运行", _obj(), risk_level="R1"),
    _read("godot.runtime.get_status", "GODOT_RUNTIME", "读取运行状态", _obj()),
    _read(
        "godot.debug.get_errors",
        "DEBUG",
        "读取编辑器错误",
        _obj({"limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
    ),
    _read(
        "godot.debug.get_warnings",
        "DEBUG",
        "读取编辑器警告",
        _obj({"limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
    ),
    _read(
        "godot.debug.get_output",
        "DEBUG",
        "读取编辑器输出",
        _obj({"limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
    ),
)


FILE_TOOLS: tuple[ToolSpec, ...] = (
    _read("file.read", "FILE_SYSTEM", "读取项目内文本文件", _obj({"path": _SCENE}, ("path",))),
    _read(
        "file.list",
        "FILE_SYSTEM",
        "列出项目目录",
        _obj({"path": _SCENE, "recursive": {"type": "boolean"}}),
    ),
    _read(
        "file.search",
        "FILE_SYSTEM",
        "在项目文件中搜索文本",
        _obj(
            {
                "path": _SCENE,
                "pattern": _str("搜索文本或正则"),
                "regex": {"type": "boolean"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            ("pattern",),
        ),
    ),
    _write(
        "file.create",
        "FILE_SYSTEM",
        "创建新文件（已存在则失败）",
        _obj({"path": _SCENE, "content": {"type": "string"}}, ("path", "content")),
    ),
    _write(
        "file.write",
        "FILE_SYSTEM",
        "覆盖写入文本文件",
        _obj({"path": _SCENE, "content": {"type": "string"}}, ("path", "content")),
    ),
    _write(
        "file.patch",
        "FILE_SYSTEM",
        "按精确文本替换修改文件",
        _obj(
            {
                "path": _SCENE,
                "old_text": {"type": "string", "minLength": 1},
                "new_text": {"type": "string"},
                "expected_replacements": {"type": "integer", "minimum": 1},
            },
            ("path", "old_text", "new_text"),
        ),
    ),
    _write(
        "file.move",
        "FILE_SYSTEM",
        "移动文件",
        _obj({"path": _SCENE, "destination": _SCENE}, ("path", "destination")),
    ),
    _write(
        "file.rename",
        "FILE_SYSTEM",
        "重命名文件",
        _obj({"path": _SCENE, "new_name": _str("新文件名")}, ("path", "new_name")),
    ),
    _write(
        "file.delete",
        "FILE_SYSTEM",
        "删除文件",
        _obj({"path": _SCENE}, ("path",)),
    ),
    _read("file.hash", "FILE_SYSTEM", "计算文件 SHA-256", _obj({"path": _SCENE}, ("path",))),
    _read("file.stat", "FILE_SYSTEM", "读取文件元信息", _obj({"path": _SCENE}, ("path",))),
)


ASSET_TOOLS: tuple[ToolSpec, ...] = (
    _read(
        "asset.read",
        "RESOURCE",
        "读取资产、版本与状态",
        _obj({"asset_id": _str("资产 ID")}, ("asset_id",)),
    ),
    _read(
        "asset.dependency.read",
        "RESOURCE",
        "读取资产依赖与引用关系",
        _obj({"asset_id": _str("资产 ID")}, ("asset_id",)),
    ),
    _read(
        "asset.provenance.read",
        "RESOURCE",
        "读取资产来源追踪",
        _obj({"asset_id": _str("资产 ID")}, ("asset_id",)),
    ),
    _read(
        "asset.license.read",
        "RESOURCE",
        "读取资产授权状态",
        _obj({"asset_id": _str("资产 ID")}, ("asset_id",)),
    ),
    _read(
        "asset.import.status",
        "RESOURCE",
        "读取 Godot 导入任务与 UID",
        _obj({"import_job_id": _str("导入任务 ID")}, ("import_job_id",)),
    ),
    ToolSpec(
        name="asset.brief.submit",
        category="RESOURCE",
        description="提交资产需求简报，等待审批",
        risk_level="R1",
        input_schema=_obj(
            {"asset_id": _str("资产 ID"), "brief": {"type": "object"}},
            ("asset_id", "brief"),
        ),
        permissions=("project.write",),
        capabilities=(),
    ),
    ToolSpec(
        name="asset.generation.request",
        category="RESOURCE",
        description="通过 Model Gateway 请求资产生成",
        risk_level="R1",
        input_schema=_obj(
            {
                "asset_id": _str("资产 ID"),
                "kind": _str("生成类型"),
                "prompt": _str("生成描述"),
            },
            ("asset_id", "kind", "prompt"),
        ),
        permissions=("project.write",),
        capabilities=(),
    ),
    ToolSpec(
        name="asset.processing.request",
        category="RESOURCE",
        description="请求资产处理（裁切、缩放、Sprite Sheet 等）",
        risk_level="R1",
        input_schema=_obj(
            {
                "asset_id": _str("资产 ID"),
                "input_version_id": _str("输入版本 ID"),
                "graph": {"type": "object"},
            },
            ("asset_id", "input_version_id", "graph"),
        ),
        permissions=("project.write",),
        capabilities=(),
    ),
    ToolSpec(
        name="asset.review.submit",
        category="RESOURCE",
        description="提交机器或人工质量审核结论",
        risk_level="R1",
        input_schema=_obj(
            {
                "asset_id": _str("资产 ID"),
                "version_id": _str("资产版本 ID"),
                "approved": {"type": "boolean"},
            },
            ("asset_id", "version_id", "approved"),
        ),
        permissions=("project.write",),
        capabilities=(),
    ),
    ToolSpec(
        name="asset.import.request",
        category="RESOURCE",
        description="经 Tool System 请求 Godot Editor 真实导入",
        risk_level="R1",
        input_schema=_obj(
            {
                "asset_id": _str("资产 ID"),
                "version_id": _str("资产版本 ID"),
                "target_path": _SCENE,
            },
            ("asset_id", "version_id", "target_path"),
        ),
        permissions=("project.write",),
        capabilities=(),
    ),
)


BUILTIN_TOOLS: tuple[ToolSpec, ...] = GODOT_TOOLS + FILE_TOOLS + ASSET_TOOLS


async def ensure_builtin_tools(registry: ToolRegistryService) -> tuple[int, int]:
    """幂等登记内置工具；返回 (新增, 更新版本) 数量。"""

    created = 0
    versioned = 0
    for spec in BUILTIN_TOOLS:
        try:
            latest = await registry.get_by_name(spec.name)
        except NotFoundError:
            latest = None
        if latest is None:
            await registry.register(
                name=spec.name,
                category=spec.category,
                description=spec.description,
                input_schema=spec.input_schema,
                output_schema=GENERIC_OUTPUT,
                risk_level=spec.risk_level,
                required_permissions=spec.permissions,
                required_capabilities=spec.capabilities,
                timeout_seconds=spec.timeout_seconds,
            )
            created += 1
            continue
        changed = (
            latest.description != spec.description
            or latest.risk_level != spec.risk_level
            or latest.input_schema != spec.input_schema
            or tuple(latest.required_permissions) != spec.permissions
            or tuple(latest.required_capabilities) != spec.capabilities
        )
        if changed:
            await registry.register_version(
                spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                output_schema=GENERIC_OUTPUT,
                risk_level=spec.risk_level,
                required_permissions=spec.permissions,
                required_capabilities=spec.capabilities,
                timeout_seconds=spec.timeout_seconds,
            )
            versioned += 1
    return created, versioned
