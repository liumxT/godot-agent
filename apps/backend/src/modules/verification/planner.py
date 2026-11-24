"""验证计划引擎（E9-T04）。

把需求、验收标准与测试追踪关系转换为可执行的验证计划：

- 验证层次由验收标准的验证方法推导；
- 测试套件由已追踪测试用例推导；
- 缺失验收标准、标准无测试、追踪指向不存在的测试都会形成 gap；
- gap 未清零时计划不能进入执行（Agent 不能跳过覆盖缺口）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.errors import VerificationRequirementUntraceable
from modules.verification.models import (
    CRITERION_ACTIVE,
    LAYER_FUNCTIONAL,
    LAYER_PERFORMANCE,
    LAYER_RESOURCE,
    LAYER_RUNTIME,
    LAYER_STATIC,
    LAYER_STRUCTURE,
    LAYER_VISUAL,
    METHOD_FUNCTIONAL_TEST,
    METHOD_PERFORMANCE_TEST,
    METHOD_RESOURCE_VALIDATION,
    METHOD_RUNTIME_TEST,
    METHOD_STATIC_ANALYSIS,
    METHOD_STRUCTURE_INSPECTION,
    METHOD_VISUAL_CHECK,
    TEST_TYPE_DEBUGGER,
    TEST_TYPE_FUNCTIONAL,
    TEST_TYPE_PERFORMANCE,
    TEST_TYPE_REGRESSION,
    TEST_TYPE_RESOURCE,
    TEST_TYPE_RUNTIME,
    TEST_TYPE_STATIC,
    TEST_TYPE_STRUCTURAL,
    TEST_TYPE_VISUAL,
    VERIFICATION_LAYERS,
)

if TYPE_CHECKING:
    from modules.verification.service import CriterionView, TestCaseView, TestLinkView

LAYER_ORDER = (
    LAYER_STATIC,
    LAYER_STRUCTURE,
    LAYER_RESOURCE,
    LAYER_RUNTIME,
    LAYER_FUNCTIONAL,
    LAYER_VISUAL,
    LAYER_PERFORMANCE,
)

METHOD_TO_LAYER: dict[str, str] = {
    METHOD_STATIC_ANALYSIS: LAYER_STATIC,
    METHOD_STRUCTURE_INSPECTION: LAYER_STRUCTURE,
    METHOD_RESOURCE_VALIDATION: LAYER_RESOURCE,
    METHOD_RUNTIME_TEST: LAYER_RUNTIME,
    METHOD_FUNCTIONAL_TEST: LAYER_FUNCTIONAL,
    METHOD_VISUAL_CHECK: LAYER_VISUAL,
    METHOD_PERFORMANCE_TEST: LAYER_PERFORMANCE,
}

TEST_TYPE_TO_LAYER: dict[str, str] = {
    TEST_TYPE_STATIC: LAYER_STATIC,
    TEST_TYPE_STRUCTURAL: LAYER_STRUCTURE,
    TEST_TYPE_RESOURCE: LAYER_RESOURCE,
    TEST_TYPE_RUNTIME: LAYER_RUNTIME,
    TEST_TYPE_FUNCTIONAL: LAYER_FUNCTIONAL,
    TEST_TYPE_VISUAL: LAYER_VISUAL,
    TEST_TYPE_PERFORMANCE: LAYER_PERFORMANCE,
    TEST_TYPE_DEBUGGER: LAYER_RUNTIME,
    TEST_TYPE_REGRESSION: LAYER_FUNCTIONAL,
}

DEFAULT_ACCEPTANCE_POLICY: dict[str, object] = {
    "require_evidence": True,
    "unknown_blocks": True,
    "skipped_is_pass": False,
    "require_user_acceptance": True,
}


@dataclass(frozen=True, slots=True)
class PlanGap:
    """计划缺口；存在缺口时计划不得执行。"""

    kind: str
    requirement_id: str
    message: str
    criterion_id: str | None = None


@dataclass(frozen=True, slots=True)
class PlanProposal:
    project_id: str
    requirement_ids: tuple[str, ...]
    verification_layers: tuple[str, ...]
    test_case_ids: tuple[str, ...]
    environment_profile: str | None
    target_platforms: tuple[str, ...]
    acceptance_policy: dict[str, object]
    gaps: tuple[PlanGap, ...]

    @property
    def ready(self) -> bool:
        return not self.gaps

    @property
    def missing_requirements(self) -> tuple[str, ...]:
        return tuple(
            sorted({gap.requirement_id for gap in self.gaps if gap.kind == "missing_criteria"})
        )


def _ordered_layers(layers: set[str]) -> tuple[str, ...]:
    return tuple(layer for layer in LAYER_ORDER if layer in layers)


def build_plan_proposal(
    *,
    project_id: str,
    requirement_ids: Sequence[str],
    criteria_by_requirement: Mapping[str, Sequence[CriterionView]],
    links_by_requirement: Mapping[str, Sequence[TestLinkView]],
    test_cases: Mapping[str, TestCaseView],
    target_platforms: Sequence[str] = (),
    environment_profile: str | None = None,
    acceptance_policy: Mapping[str, object] | None = None,
) -> PlanProposal:
    """根据需求与追踪数据生成计划；不写库。"""

    identifiers = tuple(dict.fromkeys(requirement_ids))
    if not identifiers:
        raise VerificationRequirementUntraceable("验证计划必须关联至少一个正式需求")

    layers: set[str] = set()
    case_ids: list[str] = []
    gaps: list[PlanGap] = []

    for requirement_id in identifiers:
        criteria = [
            item
            for item in criteria_by_requirement.get(requirement_id, ())
            if item.status == CRITERION_ACTIVE
        ]
        links = list(links_by_requirement.get(requirement_id, ()))
        if not criteria:
            gaps.append(
                PlanGap(
                    kind="missing_criteria",
                    requirement_id=requirement_id,
                    message="需求缺少 ACTIVE 验收标准",
                )
            )
        if not links:
            gaps.append(
                PlanGap(
                    kind="uncovered_requirement",
                    requirement_id=requirement_id,
                    message="需求没有关联任何测试用例",
                )
            )
        linked_criteria = {link.criterion_id for link in links if link.criterion_id}
        for criterion in criteria:
            layers.add(METHOD_TO_LAYER[criterion.verification_method])
            if criterion.criterion_id not in linked_criteria:
                gaps.append(
                    PlanGap(
                        kind="uncovered_criterion",
                        requirement_id=requirement_id,
                        criterion_id=criterion.criterion_id,
                        message="验收标准没有对应测试用例",
                    )
                )
        for link in links:
            test_case = test_cases.get(link.test_case_id)
            if test_case is None:
                gaps.append(
                    PlanGap(
                        kind="unknown_test_case",
                        requirement_id=requirement_id,
                        criterion_id=link.criterion_id,
                        message=f"追踪引用了不存在的测试用例 {link.test_case_id}",
                    )
                )
                continue
            layers.add(TEST_TYPE_TO_LAYER[test_case.test_type])
            if link.test_case_id not in case_ids:
                case_ids.append(link.test_case_id)

    unknown = layers - set(VERIFICATION_LAYERS)
    if unknown:
        raise VerificationRequirementUntraceable(
            "推导出未知验证层次", details={"layers": sorted(unknown)}
        )

    policy = dict(DEFAULT_ACCEPTANCE_POLICY)
    if acceptance_policy is not None:
        policy.update(acceptance_policy)

    return PlanProposal(
        project_id=project_id,
        requirement_ids=identifiers,
        verification_layers=_ordered_layers(layers),
        test_case_ids=tuple(case_ids),
        environment_profile=environment_profile,
        target_platforms=tuple(dict.fromkeys(target_platforms)),
        acceptance_policy=policy,
        gaps=tuple(gaps),
    )
