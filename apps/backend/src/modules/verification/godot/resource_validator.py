"""Godot 资源与引用校验（E9-T07 / E8 导入证据衔接）。

检查 ``.tres`` 资源与二进制/图片/音频资源：

- 资源头缺失或无法读取；
- ``ext_resource`` 指向的文件不存在；
- 引用了未声明的 ``ExtResource``；
- 可导入资源缺少 ``.import`` 元数据（警告）。

只读取文件，不触发重新导入，不修改资源。
"""

from __future__ import annotations

import re
from pathlib import Path

from modules.verification.godot.findings import AnalysisReport, Finding, error, warning

_ATTRIBUTE = re.compile(r'([A-Za-z_]+)="([^"]*)"')
_EXT_REFERENCE = re.compile(r'ExtResource\("([^"]+)"\)')
_SKIP_DIRS = {".git", ".godot", "__pycache__", "node_modules", ".venv"}
_IMPORTABLE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".svg",
    ".wav",
    ".ogg",
    ".mp3",
    ".ttf",
    ".otf",
    ".glb",
    ".gltf",
}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_files(root: Path, suffixes: set[str]) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        paths.append(path)
    return paths


def _check_text_resource(path: Path, root: Path) -> list[Finding]:
    relative = _relative(path, root)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return [error("resource_unreadable", "资源无法读取", relative)]

    findings: list[Finding] = []
    if not text.lstrip().startswith("[gd_resource"):
        findings.append(error("resource_header_missing", "缺少 gd_resource 头", relative))

    declared: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("[ext_resource"):
            continue
        attrs = {key: value for key, value in _ATTRIBUTE.findall(stripped)}
        resource_id = attrs.get("id")
        resource_path = attrs.get("path", "")
        if resource_id:
            declared.add(resource_id)
        if resource_path.startswith("res://"):
            target = root / resource_path.removeprefix("res://")
            if not target.is_file():
                findings.append(
                    error(
                        "resource_missing_ext_resource",
                        f"ext_resource 文件不存在: {resource_path}",
                        relative,
                    )
                )

    for resource_id in sorted(set(_EXT_REFERENCE.findall(text))):
        if resource_id not in declared:
            findings.append(
                error(
                    "resource_unknown_ext_resource",
                    f"引用了未声明的 ExtResource: {resource_id}",
                    relative,
                )
            )
    return findings


def validate_resources(root: Path) -> AnalysisReport:
    root = root.resolve()
    findings: list[Finding] = []

    text_resources = _iter_files(root, {".tres"})
    for path in text_resources:
        findings.extend(_check_text_resource(path, root))

    importable = _iter_files(root, _IMPORTABLE_SUFFIXES)
    for path in importable:
        import_file = path.with_name(path.name + ".import")
        if not import_file.is_file():
            findings.append(
                warning(
                    "resource_missing_import",
                    "可导入资源缺少 .import 元数据",
                    _relative(path, root),
                )
            )

    return AnalysisReport(
        kind="RESOURCE_VALIDATION",
        files_scanned=len(text_resources) + len(importable),
        findings=tuple(findings),
        details={
            "text_resources": len(text_resources),
            "importable_assets": len(importable),
        },
    )
