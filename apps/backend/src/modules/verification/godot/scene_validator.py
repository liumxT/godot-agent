"""Godot 场景结构校验（E9-T07）。

解析 ``.tscn`` 文本格式，检查：

- 场景头缺失或损坏；
- 根节点缺失或存在多个根节点；
- 同级节点重名；
- ``ext_resource`` 指向的文件不存在；
- 引用了未声明的 ``ExtResource``；
- 信号连接指向不存在的节点；
- 验收标准要求的节点路径与类型。

这些检查只读取项目文件，不启动 Godot，也不修改场景。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from modules.verification.godot.findings import (
    AnalysisReport,
    Finding,
    error,
)

_ATTRIBUTE = re.compile(r'([A-Za-z_]+)="([^"]*)"')
_INSTANCE = re.compile(r'instance=\s*ExtResource\("([^"]+)"\)')
_EXT_REFERENCE = re.compile(r'ExtResource\("([^"]+)"\)')
_SKIP_DIRS = {".git", ".godot", "__pycache__", "node_modules", ".venv"}


@dataclass(frozen=True, slots=True)
class SceneNode:
    name: str
    type: str
    parent: str | None
    line: int

    @property
    def is_root(self) -> bool:
        return self.parent is None


@dataclass(frozen=True, slots=True)
class SceneConnection:
    signal: str
    from_node: str
    to_node: str
    method: str
    line: int


@dataclass(frozen=True, slots=True)
class SceneDocument:
    path: Path
    relative: str
    nodes: tuple[SceneNode, ...]
    ext_resources: dict[str, str]
    connections: tuple[SceneConnection, ...]
    findings: tuple[Finding, ...] = ()

    @property
    def root(self) -> SceneNode | None:
        roots = [node for node in self.nodes if node.is_root]
        return roots[0] if len(roots) == 1 else None


@dataclass(frozen=True, slots=True)
class NodeRequirement:
    """结构验收要求：某场景中必须存在指定路径与类型的节点。"""

    scene: str
    path: str
    type: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class SceneInspection:
    document: SceneDocument
    findings: tuple[Finding, ...]
    node_paths: dict[str, str] = field(default_factory=dict)

    @property
    def root_type(self) -> str | None:
        root = self.document.root
        return None if root is None else root.type


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _attributes(header: str) -> dict[str, str]:
    return {key: value for key, value in _ATTRIBUTE.findall(header)}


def parse_scene(path: Path, root: Path) -> SceneDocument:
    relative = _relative(path, root)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        finding = error("scene_unreadable", "场景文件无法读取", relative)
        return SceneDocument(path, relative, (), {}, (), (finding,))

    findings: list[Finding] = []
    nodes: list[SceneNode] = []
    ext_resources: dict[str, str] = {}
    connections: list[SceneConnection] = []
    has_header = False

    for number, content in enumerate(text.splitlines(), start=1):
        line = content.strip()
        if not line.startswith("["):
            continue
        if line.startswith("[gd_scene"):
            has_header = True
        elif line.startswith("[ext_resource"):
            attrs = _attributes(line)
            resource_id = attrs.get("id")
            resource_path = attrs.get("path", "")
            if not resource_id:
                findings.append(
                    error("scene_ext_resource_invalid", "ext_resource 缺少 id", relative, number)
                )
            else:
                ext_resources[resource_id] = resource_path
        elif line.startswith("[node"):
            attrs = _attributes(line)
            name = attrs.get("name", "")
            node_type = attrs.get("type", "")
            # 实例化节点（instance=ExtResource(...)）在合法 .tscn 中不写 type
            instance = "ExtResource" if _INSTANCE.search(line) else attrs.get("instance", "")
            if not name or (not node_type and not instance):
                findings.append(
                    error("scene_node_invalid", "node 缺少 name 或 type", relative, number)
                )
                continue
            nodes.append(
                SceneNode(
                    name=name,
                    type=node_type or "INSTANCE",
                    parent=attrs.get("parent"),
                    line=number,
                )
            )
        elif line.startswith("[connection"):
            attrs = _attributes(line)
            connections.append(
                SceneConnection(
                    signal=attrs.get("signal", ""),
                    from_node=attrs.get("from", ""),
                    to_node=attrs.get("to", ""),
                    method=attrs.get("method", ""),
                    line=number,
                )
            )

    if not has_header:
        findings.append(error("scene_header_missing", "缺少 gd_scene 头", relative, 1))

    return SceneDocument(
        path=path,
        relative=relative,
        nodes=tuple(nodes),
        ext_resources=ext_resources,
        connections=tuple(connections),
        findings=tuple(findings),
    )


def _resolve_path(value: str, root_name: str) -> str:
    """把场景内的节点路径解析为以根节点开头的绝对路径。

    ``.tscn`` 中 ``parent`` / ``connection`` 的路径相对于根节点，
    不包含根节点名；``.`` 表示根节点本身。
    """

    if value in ("", "."):
        return root_name
    relative = value.split(":", 1)[0].strip("/")
    if not relative or relative == root_name:
        return root_name
    return f"{root_name}/{relative}"


def _node_paths(document: SceneDocument) -> dict[str, SceneNode]:
    roots = [node for node in document.nodes if node.is_root]
    if len(roots) != 1:
        return {}
    root_name = roots[0].name
    paths: dict[str, SceneNode] = {root_name: roots[0]}
    pending = [node for node in document.nodes if not node.is_root]
    progress = True
    while pending and progress:
        progress = False
        remaining: list[SceneNode] = []
        for node in pending:
            parent_path = _resolve_path(node.parent or ".", root_name)
            if parent_path in paths:
                paths[f"{parent_path}/{node.name}"] = node
                progress = True
            else:
                remaining.append(node)
        pending = remaining
    return paths


def inspect_scene(path: Path, root: Path) -> SceneInspection:
    document = parse_scene(path, root)
    relative = document.relative
    findings: list[Finding] = list(document.findings)
    roots = [node for node in document.nodes if node.is_root]
    if len(roots) == 0:
        findings.append(error("scene_root_missing", "场景缺少根节点", relative))
    elif len(roots) > 1:
        findings.append(
            error(
                "scene_root_duplicated",
                f"场景存在多个根节点: {[node.name for node in roots]}",
                relative,
            )
        )

    sibling_names: set[tuple[str | None, str]] = set()
    for node in document.nodes:
        key = (node.parent, node.name)
        if key in sibling_names:
            findings.append(
                error(
                    "scene_duplicate_node",
                    f"同级节点重名: {node.name}",
                    relative,
                    node.line,
                )
            )
        sibling_names.add(key)

    for resource_id, resource_path in document.ext_resources.items():
        if resource_path.startswith("res://"):
            target = root / resource_path.removeprefix("res://")
            if not target.is_file():
                findings.append(
                    error(
                        "scene_missing_ext_resource",
                        f"ext_resource 文件不存在: {resource_path}",
                        relative,
                    )
                )
        elif not resource_path:
            findings.append(
                error(
                    "scene_ext_resource_without_path",
                    f"ext_resource {resource_id} 缺少 path",
                    relative,
                )
            )

    text = path.read_text(encoding="utf-8", errors="replace")
    for resource_id in sorted(set(_EXT_REFERENCE.findall(text))):
        if resource_id not in document.ext_resources:
            findings.append(
                error(
                    "scene_unknown_ext_resource",
                    f"引用了未声明的 ExtResource: {resource_id}",
                    relative,
                )
            )

    paths = _node_paths(document)
    root_name = roots[0].name if len(roots) == 1 else "."
    known_paths = set(paths)

    for connection in document.connections:
        for label, value in (("from", connection.from_node), ("to", connection.to_node)):
            resolved = _resolve_path(value, root_name)
            if resolved not in known_paths:
                findings.append(
                    error(
                        "scene_connection_missing_node",
                        f"信号 {connection.signal} 的 {label} 指向不存在节点: {value}",
                        relative,
                        connection.line,
                    )
                )

    return SceneInspection(
        document=document,
        findings=tuple(findings),
        node_paths={path: node.type for path, node in paths.items()},
    )


def _iter_scenes(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob("*.tscn")):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        paths.append(path)
    return paths


def validate_scenes(
    root: Path,
    *,
    scenes: tuple[str, ...] = (),
    required: tuple[NodeRequirement, ...] = (),
) -> AnalysisReport:
    root = root.resolve()
    if scenes:
        paths = [root / relative for relative in scenes]
    else:
        paths = _iter_scenes(root)

    findings: list[Finding] = []
    inspections: list[SceneInspection] = []
    for path in paths:
        if not path.is_file():
            findings.append(error("scene_missing", "场景文件不存在", _relative(path, root)))
            continue
        inspection = inspect_scene(path, root)
        inspections.append(inspection)
        findings.extend(inspection.findings)

    by_scene = {inspection.document.relative: inspection for inspection in inspections}
    for requirement in required:
        inspection = by_scene.get(requirement.scene)
        if inspection is None:
            findings.append(
                error(
                    "scene_required_missing",
                    f"缺少验收要求的场景: {requirement.scene}",
                    requirement.scene,
                )
            )
            continue
        root_name = inspection.document.root.name if inspection.document.root is not None else "."
        expected_path = _resolve_path(requirement.path, root_name)
        actual = inspection.node_paths.get(expected_path)
        if actual is None:
            findings.append(
                error(
                    "scene_required_node_missing",
                    requirement.description or f"缺少节点 {requirement.path}",
                    requirement.scene,
                )
            )
        elif actual != requirement.type:
            findings.append(
                error(
                    "scene_required_node_type",
                    f"节点 {requirement.path} 类型应为 {requirement.type}，实际为 {actual}",
                    requirement.scene,
                )
            )

    return AnalysisReport(
        kind="STRUCTURE_VALIDATION",
        files_scanned=len(inspections),
        findings=tuple(findings),
        details={
            "scenes": {
                inspection.document.relative: {
                    "root_type": inspection.root_type,
                    "nodes": inspection.node_paths,
                }
                for inspection in inspections
            }
        },
    )
