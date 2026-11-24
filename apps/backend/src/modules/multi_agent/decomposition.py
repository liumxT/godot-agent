"""任务分解校验与拓扑排序（E7-T05）。

分解不得改变原始 Task 的目标与验收标准。调用方必须显式声明每个子任务
覆盖的原始验收标准（``covers``），校验失败整体拒绝，不创建半个 Team。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

from core.errors import AgentDecompositionInvalid
from modules.multi_agent.models import DEFAULT_RISK_PROFILE, RISK_PROFILES

COMPLEXITY_SIMPLE = "SIMPLE"
COMPLEXITY_COMPLEX = "COMPLEX"


@dataclass(frozen=True, slots=True)
class SubtaskSpec:
    key: str
    objective: str
    capabilities: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    covers: tuple[str, ...] = ()
    scope: str | None = None
    input_reference: str | None = None
    output_reference: str | None = None
    required_tools: tuple[str, ...] = ()
    permission_requirements: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    budget: Mapping[str, int] = field(default_factory=dict)
    estimated_duration_seconds: int | None = None
    risk_level: str = DEFAULT_RISK_PROFILE
    priority: int = 0


@dataclass(frozen=True, slots=True)
class DecompositionPlan:
    task_objective: str
    acceptance_criteria: tuple[str, ...]
    subtasks: tuple[SubtaskSpec, ...]

    def validate(self) -> tuple[SubtaskSpec, ...]:
        """校验并返回拓扑有序的子任务；失败时抛出 ``AgentDecompositionInvalid``。"""

        reasons: list[str] = []
        if not (self.task_objective or "").strip():
            reasons.append("TASK_OBJECTIVE_REQUIRED")
        if not self.subtasks:
            reasons.append("SUBTASKS_REQUIRED")

        by_key: dict[str, SubtaskSpec] = {}
        for spec in self.subtasks:
            key = (spec.key or "").strip()
            if not key:
                reasons.append("SUBTASK_KEY_REQUIRED")
                continue
            if key in by_key:
                reasons.append(f"DUPLICATE_SUBTASK_KEY:{key}")
            by_key[key] = spec

        for key, spec in by_key.items():
            if not (spec.objective or "").strip():
                reasons.append(f"SUBTASK_OBJECTIVE_REQUIRED:{key}")
            if not spec.capabilities:
                reasons.append(f"SUBTASK_CAPABILITIES_REQUIRED:{key}")
            if not spec.acceptance_criteria:
                reasons.append(f"SUBTASK_CRITERIA_REQUIRED:{key}")
            if spec.risk_level not in RISK_PROFILES:
                reasons.append(f"INVALID_RISK_LEVEL:{key}")
            for dependency in spec.dependencies:
                if dependency == key:
                    reasons.append(f"SELF_DEPENDENCY:{key}")
                elif dependency not in by_key:
                    reasons.append(f"UNKNOWN_DEPENDENCY:{key}->{dependency}")

        if reasons:
            raise AgentDecompositionInvalid("任务分解不合法", details={"reasons": reasons})

        order = _topological_order(by_key)
        if order is None:
            raise AgentDecompositionInvalid(
                "子任务依赖存在循环", details={"reasons": ["DEPENDENCY_CYCLE"]}
            )

        missing = _uncovered_criteria(self.acceptance_criteria, by_key.values())
        if missing:
            raise AgentDecompositionInvalid(
                "子任务未覆盖原始验收标准",
                details={"reasons": ["ACCEPTANCE_NOT_COVERED"], "missing": missing},
            )
        return tuple(by_key[key] for key in order)


def _uncovered_criteria(criteria: tuple[str, ...], subtasks) -> list[str]:
    if not criteria:
        return []
    covered: set[str] = set()
    for spec in subtasks:
        covered.update(spec.covers)
        covered.update(spec.acceptance_criteria)
    return [criterion for criterion in criteria if criterion not in covered]


def _topological_order(by_key: dict[str, SubtaskSpec]) -> list[str] | None:
    indegree = {key: len(set(spec.dependencies)) for key, spec in by_key.items()}
    dependents: dict[str, list[str]] = {key: [] for key in by_key}
    for key, spec in by_key.items():
        for dependency in set(spec.dependencies):
            dependents[dependency].append(key)
    ready = deque(sorted(key for key, count in indegree.items() if count == 0))
    order: list[str] = []
    while ready:
        key = ready.popleft()
        order.append(key)
        for dependent in sorted(dependents[key]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    if len(order) != len(by_key):
        return None
    return order


@dataclass(frozen=True, slots=True)
class ComplexityAssessment:
    level: str
    requires_multi_agent: bool
    reasons: tuple[str, ...]


def assess_complexity(plan: DecompositionPlan) -> ComplexityAssessment:
    """单 Agent 足以完成时不拆分；多子任务才进入多 Agent 流程。"""

    count = len(plan.subtasks)
    if count <= 1:
        return ComplexityAssessment(
            level=COMPLEXITY_SIMPLE,
            requires_multi_agent=False,
            reasons=("SINGLE_SUBTASK",),
        )
    capabilities = {capability for spec in plan.subtasks for capability in spec.capabilities}
    reasons = ["MULTIPLE_SUBTASKS"]
    if len(capabilities) > 1:
        reasons.append("MULTIPLE_CAPABILITIES")
    if any(spec.dependencies for spec in plan.subtasks):
        reasons.append("DEPENDENCY_GRAPH")
    return ComplexityAssessment(
        level=COMPLEXITY_COMPLEX,
        requires_multi_agent=True,
        reasons=tuple(reasons),
    )


__all__ = [
    "COMPLEXITY_COMPLEX",
    "COMPLEXITY_SIMPLE",
    "ComplexityAssessment",
    "DecompositionPlan",
    "SubtaskSpec",
    "assess_complexity",
]
