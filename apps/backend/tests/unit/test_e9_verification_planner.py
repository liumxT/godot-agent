"""E9-T04 验证计划引擎单元测试。"""

from __future__ import annotations

from datetime import datetime

import pytest

from core.errors import VerificationRequirementUntraceable
from modules.verification.planner import (
    DEFAULT_ACCEPTANCE_POLICY,
    LAYER_ORDER,
    METHOD_TO_LAYER,
    TEST_TYPE_TO_LAYER,
    build_plan_proposal,
)
from modules.verification.service import (
    CriterionView,
)
from modules.verification.service import (
    TestCaseView as CaseView,
)
from modules.verification.service import (
    TestLinkView as LinkView,
)

NOW = datetime(2026, 11, 24, 8, 0, 0)


def _criterion(
    criterion_id: str,
    requirement_id: str,
    method: str = "RUNTIME_TEST",
    *,
    status: str = "ACTIVE",
) -> CriterionView:
    return CriterionView(
        criterion_id=criterion_id,
        project_id="prj_1",
        requirement_id=requirement_id,
        criterion_type="FUNCTIONAL",
        statement="可判定描述",
        verification_method=method,
        expected={},
        threshold={},
        required_evidence=(),
        priority="HIGH",
        status=status,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _link(
    link_id: str, requirement_id: str, test_case_id: str, criterion_id: str | None
) -> LinkView:
    return LinkView(
        link_id=link_id,
        requirement_id=requirement_id,
        criterion_id=criterion_id,
        test_case_id=test_case_id,
        coverage_type="DIRECT",
        created_at=NOW,
    )


def _test_case(test_case_id: str, test_type: str = "RUNTIME") -> CaseView:
    return CaseView(
        test_case_id=test_case_id,
        project_id="prj_1",
        name=test_case_id,
        description=None,
        test_type=test_type,
        execution_method="godot_headless",
        preconditions=(),
        setup=(),
        steps=(),
        expected_result="",
        cleanup=(),
        timeout_seconds=300,
        evidence_requirements=(),
        risk_level="MEDIUM",
        automation_level="AUTOMATED",
        status="ACTIVE",
        created_at=NOW,
        updated_at=NOW,
    )


def test_full_trace_produces_ready_plan_in_layer_order() -> None:
    proposal = build_plan_proposal(
        project_id="prj_1",
        requirement_ids=("req_1",),
        criteria_by_requirement={
            "req_1": [
                _criterion("vcr_b", "req_1", "RUNTIME_TEST"),
                _criterion("vcr_a", "req_1", "STATIC_ANALYSIS"),
            ]
        },
        links_by_requirement={
            "req_1": [
                _link("vtl_1", "req_1", "vtc_1", "vcr_a"),
                _link("vtl_2", "req_1", "vtc_2", "vcr_b"),
            ]
        },
        test_cases={"vtc_1": _test_case("vtc_1", "STATIC"), "vtc_2": _test_case("vtc_2")},
        target_platforms=("windows",),
        environment_profile="local",
    )
    assert proposal.ready is True
    assert proposal.gaps == ()
    assert proposal.verification_layers == ("STATIC", "RUNTIME")
    assert proposal.test_case_ids == ("vtc_1", "vtc_2")
    assert proposal.acceptance_policy == DEFAULT_ACCEPTANCE_POLICY


def test_missing_criteria_blocks_plan() -> None:
    proposal = build_plan_proposal(
        project_id="prj_1",
        requirement_ids=("req_1",),
        criteria_by_requirement={"req_1": []},
        links_by_requirement={"req_1": []},
        test_cases={},
    )
    assert proposal.ready is False
    assert proposal.missing_requirements == ("req_1",)
    kinds = {gap.kind for gap in proposal.gaps}
    assert kinds == {"missing_criteria", "uncovered_requirement"}
    assert proposal.verification_layers == ()


def test_criterion_without_test_is_a_gap() -> None:
    proposal = build_plan_proposal(
        project_id="prj_1",
        requirement_ids=("req_1",),
        criteria_by_requirement={"req_1": [_criterion("vcr_1", "req_1")]},
        links_by_requirement={"req_1": []},
        test_cases={},
    )
    assert proposal.ready is False
    kinds = {gap.kind for gap in proposal.gaps}
    assert "uncovered_criterion" in kinds
    assert "uncovered_requirement" in kinds
    assert proposal.verification_layers == ("RUNTIME",)


def test_unknown_test_case_reference_is_a_gap() -> None:
    proposal = build_plan_proposal(
        project_id="prj_1",
        requirement_ids=("req_1",),
        criteria_by_requirement={"req_1": [_criterion("vcr_1", "req_1")]},
        links_by_requirement={"req_1": [_link("vtl_1", "req_1", "vtc_missing", "vcr_1")]},
        test_cases={},
    )
    assert proposal.ready is False
    assert {gap.kind for gap in proposal.gaps} == {"unknown_test_case"}


def test_retired_criteria_do_not_contribute_layers() -> None:
    proposal = build_plan_proposal(
        project_id="prj_1",
        requirement_ids=("req_1",),
        criteria_by_requirement={
            "req_1": [_criterion("vcr_old", "req_1", "STATIC_ANALYSIS", status="SUPERSEDED")]
        },
        links_by_requirement={"req_1": []},
        test_cases={},
    )
    assert proposal.verification_layers == ()
    assert proposal.ready is False


def test_empty_requirement_list_is_rejected() -> None:
    with pytest.raises(VerificationRequirementUntraceable):
        build_plan_proposal(
            project_id="prj_1",
            requirement_ids=(),
            criteria_by_requirement={},
            links_by_requirement={},
            test_cases={},
        )


def test_layer_mappings_cover_all_methods_and_test_types() -> None:
    assert set(METHOD_TO_LAYER.values()) <= set(LAYER_ORDER)
    assert TEST_TYPE_TO_LAYER["DEBUGGER"] == "RUNTIME"
    assert TEST_TYPE_TO_LAYER["REGRESSION"] == "FUNCTIONAL"
    assert tuple(dict.fromkeys(METHOD_TO_LAYER.values())) == LAYER_ORDER
