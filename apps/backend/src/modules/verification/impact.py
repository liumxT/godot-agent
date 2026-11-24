"""变更影响分析与回归计划（E9-T15）。

分析链：

ChangeSet → 变更文件 → 依赖图（反向引用）→ 受影响需求 → 受影响测试用例
→ 风险评估 → 回归策略 → 必须执行的检查。

约束：

- 本模块是纯函数，不读写数据库、不执行测试；
- 依赖关系来自 Godot 资源引用（``res://``），无法解析时不得臆造；
- 覆盖缺口只统计“可测需求中没有任何有效测试追踪”的部分；
- 历史缺陷用于提高重点测试范围，不代表当前一定失败。
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modules.verification.models import (
    DEFECT_BLOCKER,
    DEFECT_CRITICAL,
    REGRESSION_DEPENDENCY,
    REGRESSION_FULL,
    REGRESSION_RISK_CRITICAL,
    REGRESSION_RISK_HIGH,
    REGRESSION_RISK_LOW,
    REGRESSION_RISK_MEDIUM,
    REGRESSION_SECURITY,
    REGRESSION_TARGETED,
    RISK_CRITICAL,
    RISK_HIGH,
)

_RES_REFERENCE = re.compile(r'res://([^"\'\s)]+)')
_SCAN_EXTENSIONS = frozenset({".tscn", ".scn", ".tres", ".res", ".gd", ".import", ".cs"})
_SKIP_DIRECTORIES = frozenset({".git", ".godot", "__pycache__", ".import"})
_SECURITY_PATH_HINTS = (
    "auth",
    "permission",
    "network",
    "http",
    "provider",
    "security",
    "encrypt",
    "credential",
)
_UI_PATH_HINTS = ("ui/", "hud/", "menu", "screen")

CHECK_STATIC = "STATIC_ANALYSIS"
CHECK_STRUCTURE = "SCENE_VALIDATION"
CHECK_RESOURCE = "RESOURCE_VALIDATION"
CHECK_RUNTIME = "RUNTIME_SMOKE"
CHECK_FUNCTIONAL = "FUNCTIONAL_TESTS"
CHECK_VISUAL = "SCREENSHOT_REVIEW"
CHECK_PERFORMANCE = "PERFORMANCE_CHECK"
CHECK_SECURITY = "SECURITY_REGRESSION"
CHECK_FULL = "FULL_REGRESSION"
CHECK_DEFECT_REPRO = "DEFECT_REPRODUCTION"


def normalize_path(path: str) -> str:
    """统一为项目内 POSIX 相对路径。"""

    value = str(path or "").replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return value.strip("/")


def coerce_changed_file(value: Any) -> ChangedFile:
    """把字符串、映射或已有的 ChangedFile 统一为 ChangedFile。"""

    if isinstance(value, ChangedFile):
        return value
    if isinstance(value, Mapping):
        return ChangedFile.from_manifest_item(value)
    return ChangedFile(path=normalize_path(str(value)))


def file_kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".gd", ".cs"}:
        return "script"
    if suffix in {".tscn", ".scn"}:
        return "scene"
    if suffix in {".tres", ".res"}:
        return "resource"
    if suffix == ".import":
        return "import"
    return "other"


def is_security_sensitive(path: str) -> bool:
    lowered = path.lower()
    return any(hint in lowered for hint in _SECURITY_PATH_HINTS)


@dataclass(frozen=True, slots=True)
class ChangedFile:
    path: str
    operation_type: str = "MODIFY"
    risk_level: str = "MEDIUM"

    @classmethod
    def from_manifest_item(cls, item: Mapping[str, Any]) -> ChangedFile:
        return cls(
            path=normalize_path(str(item.get("resource_path") or "")),
            operation_type=str(item.get("operation_type") or "MODIFY"),
            risk_level=str(item.get("risk_level") or "MEDIUM").upper(),
        )


@dataclass(frozen=True, slots=True)
class TestCaseRef:
    __test__ = False

    test_case_id: str
    name: str
    test_type: str
    execution_method: str = ""
    risk_level: str = "MEDIUM"
    status: str = "ACTIVE"
    description: str = ""


@dataclass(frozen=True, slots=True)
class LinkRef:
    requirement_id: str
    test_case_id: str
    coverage_type: str = "DIRECT"


@dataclass(frozen=True, slots=True)
class DefectRef:
    defect_id: str
    requirement_id: str | None
    severity: str
    category: str
    status: str
    title: str = ""
    related_changeset_id: str | None = None


@dataclass(frozen=True, slots=True)
class RegressionPlan:
    project_id: str
    changeset_id: str | None
    strategy: str
    risk_level: str
    changed_files: tuple[str, ...]
    affected_requirements: tuple[str, ...]
    affected_test_cases: tuple[str, ...]
    affected_scenes: tuple[str, ...]
    affected_scripts: tuple[str, ...]
    affected_resources: tuple[str, ...]
    dependents: tuple[str, ...]
    historical_defects: tuple[str, ...]
    coverage_gaps: tuple[str, ...]
    required_checks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "changeset_id": self.changeset_id,
            "strategy": self.strategy,
            "risk_level": self.risk_level,
            "changed_files": list(self.changed_files),
            "affected_requirements": list(self.affected_requirements),
            "affected_test_cases": list(self.affected_test_cases),
            "affected_scenes": list(self.affected_scenes),
            "affected_scripts": list(self.affected_scripts),
            "affected_resources": list(self.affected_resources),
            "dependents": list(self.dependents),
            "historical_defects": list(self.historical_defects),
            "coverage_gaps": list(self.coverage_gaps),
            "required_checks": list(self.required_checks),
        }


def scan_reverse_dependencies(project_root: str | Path) -> dict[str, set[str]]:
    """扫描项目中的 Godot 资源引用，返回“被引用文件 → 引用者集合”。"""

    root = Path(project_root)
    reverse: dict[str, set[str]] = {}
    if not root.is_dir():
        return reverse
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            relative = file_path.relative_to(root).as_posix()
        except ValueError:
            continue
        parts = Path(relative).parts
        if any(part in _SKIP_DIRECTORIES for part in parts):
            continue
        if file_path.suffix.lower() not in _SCAN_EXTENSIONS:
            continue
        try:
            if file_path.stat().st_size > 2_000_000:
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _RES_REFERENCE.finditer(text):
            target = normalize_path(match.group(1))
            if not target or target == relative:
                continue
            reverse.setdefault(target, set()).add(relative)
    return reverse


def _collect_affected(
    changed: Iterable[str], reverse: Mapping[str, Iterable[str]]
) -> tuple[set[str], set[str]]:
    """BFS 收集直接与间接依赖者。"""

    affected: set[str] = set()
    dependents: set[str] = set()
    queue: deque[str] = deque()
    for item in changed:
        affected.add(item)
        queue.append(item)
    while queue:
        current = queue.popleft()
        for dependent in reverse.get(current, ()):
            normalized = normalize_path(str(dependent))
            if not normalized or normalized in affected:
                continue
            affected.add(normalized)
            dependents.add(normalized)
            queue.append(normalized)
    return affected, dependents


def _matches_test(path: str, test: TestCaseRef) -> bool:
    stem = Path(path).stem.lower()
    if len(stem) < 3:
        return False
    haystack = " ".join(
        (test.name, test.execution_method or "", test.description or "")
    ).lower()
    return stem in haystack


def _required_checks(
    *,
    strategy: str,
    affected: Iterable[str],
    has_tests: bool,
    has_history: bool,
) -> list[str]:
    checks = [CHECK_STATIC]
    kinds = {file_kind(path) for path in affected}
    if "scene" in kinds:
        checks.append(CHECK_STRUCTURE)
    if "resource" in kinds or "import" in kinds:
        checks.append(CHECK_RESOURCE)
    if kinds & {"scene", "script"}:
        checks.append(CHECK_RUNTIME)
    if has_tests:
        checks.append(CHECK_FUNCTIONAL)
    if any(hint in path.lower() for path in affected for hint in _UI_PATH_HINTS):
        checks.append(CHECK_VISUAL)
    if strategy == REGRESSION_SECURITY:
        checks.append(CHECK_SECURITY)
    if strategy == REGRESSION_FULL:
        checks.append(CHECK_FULL)
    if has_history:
        checks.append(CHECK_DEFECT_REPRO)
    return checks


def build_regression_plan(
    *,
    project_id: str,
    changed_files: Sequence[ChangedFile],
    reverse_dependencies: Mapping[str, Iterable[str]],
    test_cases: Sequence[TestCaseRef],
    links: Sequence[LinkRef],
    testable_requirement_ids: Iterable[str],
    defects: Sequence[DefectRef] = (),
    changeset_id: str | None = None,
    force_full: bool = False,
    security_requested: bool = False,
) -> RegressionPlan:
    changed_paths = [item.path for item in changed_files if item.path]
    affected, dependents = _collect_affected(changed_paths, reverse_dependencies)

    tests_by_id = {item.test_case_id: item for item in test_cases}
    matched_test_ids: set[str] = set()
    for path in affected:
        for test in test_cases:
            if _matches_test(path, test):
                matched_test_ids.add(test.test_case_id)

    affected_requirements: set[str] = set()
    for link in links:
        if link.test_case_id in matched_test_ids:
            affected_requirements.add(link.requirement_id)

    # 受影响需求关联的其它测试也必须纳入回归范围。
    for link in links:
        if link.requirement_id in affected_requirements:
            matched_test_ids.add(link.test_case_id)
    matched_test_ids &= set(tests_by_id)

    covered_requirements = {link.requirement_id for link in links}
    testable = {normalize_path(item) for item in testable_requirement_ids if item}
    coverage_gaps = sorted(testable - covered_requirements)

    historical = [
        item
        for item in defects
        if (item.requirement_id and item.requirement_id in affected_requirements)
        or (changeset_id is not None and item.related_changeset_id == changeset_id)
    ]

    security_related = security_requested or any(
        is_security_sensitive(item.path) for item in changed_files
    )
    critical = any(item.risk_level == RISK_CRITICAL for item in changed_files)
    if security_related:
        strategy = REGRESSION_SECURITY
    elif force_full or critical or len(changed_files) >= 20:
        strategy = REGRESSION_FULL
    elif dependents:
        strategy = REGRESSION_DEPENDENCY
    else:
        strategy = REGRESSION_TARGETED

    blocking_history = any(
        item.severity in {DEFECT_BLOCKER, DEFECT_CRITICAL} for item in historical
    )
    if critical or blocking_history:
        risk_level = REGRESSION_RISK_CRITICAL
    elif (
        security_related
        or any(item.risk_level == RISK_HIGH for item in changed_files)
        or any(tests_by_id[tid].risk_level == RISK_HIGH for tid in matched_test_ids)
    ):
        risk_level = REGRESSION_RISK_HIGH
    elif dependents or len(changed_files) > 1:
        risk_level = REGRESSION_RISK_MEDIUM
    else:
        risk_level = REGRESSION_RISK_LOW

    affected_sorted = sorted(affected)
    checks = _required_checks(
        strategy=strategy,
        affected=affected_sorted,
        has_tests=bool(matched_test_ids),
        has_history=bool(historical),
    )
    return RegressionPlan(
        project_id=project_id,
        changeset_id=changeset_id,
        strategy=strategy,
        risk_level=risk_level,
        changed_files=tuple(sorted(changed_paths)),
        affected_requirements=tuple(sorted(affected_requirements)),
        affected_test_cases=tuple(sorted(matched_test_ids)),
        affected_scenes=tuple(
            path for path in affected_sorted if file_kind(path) == "scene"
        ),
        affected_scripts=tuple(
            path for path in affected_sorted if file_kind(path) == "script"
        ),
        affected_resources=tuple(
            path for path in affected_sorted if file_kind(path) in {"resource", "import"}
        ),
        dependents=tuple(sorted(dependents)),
        historical_defects=tuple(sorted({item.defect_id for item in historical})),
        coverage_gaps=tuple(coverage_gaps),
        required_checks=tuple(dict.fromkeys(checks)),
    )
