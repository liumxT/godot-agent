"""E6-T20 架构边界守卫：Agent Runtime 只能经由 Gateway / Tool System 工作。"""

from __future__ import annotations

import ast
from pathlib import Path

_MODULE_ROOT = Path(__file__).resolve().parents[2] / "src" / "modules" / "agent_runtime"

_FORBIDDEN = (
    "modules.model_gateway.providers",
    "modules.workflow",
    "openai",
    "anthropic",
    "httpx",
    "requests",
    "aiofiles",
    "shutil",
)


def _imported_modules(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_agent_runtime_does_not_bypass_gateway_tool_or_task_boundaries() -> None:
    violations: list[str] = []
    for source in sorted(_MODULE_ROOT.glob("*.py")):
        for name in _imported_modules(source):
            if any(name == item or name.startswith(f"{item}.") for item in _FORBIDDEN):
                violations.append(f"{source.name}: {name}")
    assert violations == []
