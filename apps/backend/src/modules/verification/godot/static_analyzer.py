"""Godot 静态分析（E9-T06）。

不依赖 Godot 进程，直接检查项目文件：

- ``project.godot`` 缺失或为空；
- GDScript 括号/花括号未闭合；
- ``class_name`` 冲突；
- 缩进混用（警告）；
- 空脚本（警告）。

静态分析只做确定性检查，不伪装成运行时测试结果。
"""

from __future__ import annotations

from pathlib import Path

from modules.verification.godot.findings import (
    AnalysisReport,
    Finding,
    error,
    warning,
)

_SKIP_DIRS = {".git", ".godot", "__pycache__", "node_modules", ".venv"}
_OPENERS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = {value: key for key, value in _OPENERS.items()}


def _iter_files(root: Path, suffix: str) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob(f"*{suffix}")):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        paths.append(path)
    return paths


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _scan_delimiters(text: str) -> tuple[int | None, str | None]:
    stack: list[tuple[str, int]] = []
    line = 1
    index = 0
    quote: str | None = None
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\n":
            line += 1
            index += 1
            continue
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if char == "#":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char in _OPENERS:
            stack.append((char, line))
        elif char in _CLOSERS:
            if not stack or stack[-1][0] != _CLOSERS[char]:
                return line, char
            stack.pop()
        index += 1
    if stack:
        opener, opened_at = stack[0]
        return opened_at, opener
    return None, None


def analyze_gdscript(path: Path, root: Path) -> list[Finding]:
    relative = _relative(path, root)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [error("gd_not_utf8", "脚本不是 UTF-8 编码", relative)]

    findings: list[Finding] = []
    if not text.strip():
        findings.append(warning("gd_empty_script", "脚本内容为空", relative))

    line, char = _scan_delimiters(text)
    if line is not None:
        findings.append(
            error("gd_unbalanced_delimiters", f"存在未闭合的 {char}", relative, line)
        )

    indent_styles: set[str] = set()
    for number, content in enumerate(text.splitlines(), start=1):
        stripped = content.lstrip(" \t")
        if not stripped:
            continue
        prefix = content[: len(content) - len(stripped)]
        if prefix.startswith("\t"):
            indent_styles.add("tab")
        elif prefix.startswith(" "):
            indent_styles.add("space")
        if " \t" in prefix:
            indent_styles.add("mixed")
    if len(indent_styles) > 1:
        findings.append(warning("gd_mixed_indentation", "缩进风格不一致", relative))
    return findings


def analyze_project(root: Path) -> AnalysisReport:
    root = root.resolve()
    findings: list[Finding] = []
    files_scanned = 0

    project_file = root / "project.godot"
    if not project_file.is_file():
        findings.append(
            error("project_file_missing", "缺少 project.godot", _relative(project_file, root))
        )
    else:
        files_scanned += 1
        content = project_file.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            findings.append(
                error("project_file_empty", "project.godot 为空", _relative(project_file, root))
            )
        elif "config_version" not in content:
            findings.append(
                warning(
                    "project_config_version_missing",
                    "project.godot 缺少 config_version",
                    _relative(project_file, root),
                )
            )

    class_names: dict[str, tuple[str, int]] = {}
    for path in _iter_files(root, ".gd"):
        files_scanned += 1
        findings.extend(analyze_gdscript(path, root))
        relative = _relative(path, root)
        for number, content in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            stripped = content.strip()
            if not stripped.startswith("class_name "):
                continue
            name = stripped.removeprefix("class_name ").split()[0].strip()
            if not name:
                continue
            if name in class_names:
                first_file, first_line = class_names[name]
                findings.append(
                    error(
                        "gd_class_name_conflict",
                        f"class_name {name} 与 {first_file}:{first_line} 冲突",
                        relative,
                        number,
                    )
                )
            else:
                class_names[name] = (relative, number)

    return AnalysisReport(
        kind="STATIC_ANALYSIS",
        files_scanned=files_scanned,
        findings=tuple(findings),
        details={"scripts": len(_iter_files(root, ".gd")), "class_names": len(class_names)},
    )
