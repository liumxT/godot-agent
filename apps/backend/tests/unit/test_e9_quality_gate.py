"""E9-T16 质量门禁引擎单元测试。"""

from __future__ import annotations

from datetime import timedelta

from core.security.tokens import utcnow
from modules.verification.models import (
    CAMPAIGN_TYPE_ASSET,
    CAMPAIGN_TYPE_TASK,
    GATE_DEFECT,
    GATE_EVIDENCE,
    GATE_FAILED,
    GATE_LICENSE,
    GATE_OVERALL_PARTIAL,
    GATE_PASSED,
    GATE_PENDING,
    GATE_REGRESSION,
    GATE_SECURITY,
    GATE_STATIC,
    GATE_UNKNOWN,
    GATE_WAIVED,
    QUALITY_GATES,
)
from modules.verification.quality_gate import (
    GateOutcome,
    GateWaiver,
    combine_outcomes,
    layer_gate,
    required_gates,
    waiver_problem,
)


def test_required_gates_follow_campaign_type_and_risk() -> None:
    task = required_gates(CAMPAIGN_TYPE_TASK)
    assert GATE_STATIC in task
    assert GATE_REGRESSION not in task

    asset = required_gates(CAMPAIGN_TYPE_ASSET)
    assert GATE_LICENSE in asset

    high_risk = required_gates(CAMPAIGN_TYPE_TASK, "HIGH")
    assert GATE_REGRESSION in high_risk
    assert GATE_SECURITY in high_risk

    everything = required_gates("UNKNOWN")
    assert set(everything).issubset(set(QUALITY_GATES))


def test_waiver_requires_traceable_fields() -> None:
    now = utcnow()
    valid = GateWaiver(
        authorized_by="user:owner",
        reason="已知风险",
        risk_statement="可能影响少量 UI",
        scope="phase-1",
        expires_at=now + timedelta(days=1),
    )
    assert waiver_problem(valid, now) is None
    assert waiver_problem(None, now) == "缺少豁免记录"
    assert (
        waiver_problem(GateWaiver("", "原因", "风险", "范围", now + timedelta(days=1)), now)
        == "豁免缺少授权者"
    )
    assert (
        waiver_problem(
            GateWaiver("owner", "原因", "风险", "范围", now - timedelta(seconds=1)),
            now,
        )
        == "豁免已过期"
    )
    assert (
        waiver_problem(
            GateWaiver(
                "owner",
                "原因",
                "风险",
                "范围",
                now + timedelta(days=1),
                revoked_at=now,
            ),
            now,
        )
        == "豁免已撤销"
    )


def test_layer_gate_maps_result_statuses() -> None:
    pending = layer_gate(GATE_STATIC, [])
    assert pending.status == GATE_PENDING

    failed = layer_gate(GATE_STATIC, ["PASSED", "FAILED"])
    assert failed.status == GATE_FAILED

    unknown = layer_gate(GATE_STATIC, ["PASSED", "NOT_RUN"])
    assert unknown.status == GATE_UNKNOWN

    passed = layer_gate(GATE_STATIC, ["PASSED", "WAIVED"])
    assert passed.status == GATE_PASSED

    skipped = layer_gate(GATE_STATIC, ["SKIPPED"])
    assert skipped.status == GATE_UNKNOWN


def test_combine_outcomes_distinguishes_partial_and_blocking() -> None:
    passed = combine_outcomes([GateOutcome(GATE_STATIC, GATE_PASSED, True)])
    assert passed.status == GATE_PASSED

    partial = combine_outcomes(
        [
            GateOutcome(GATE_STATIC, GATE_PASSED, True),
            GateOutcome(GATE_EVIDENCE, GATE_PENDING, True),
        ]
    )
    assert partial.status == GATE_OVERALL_PARTIAL
    assert partial.pending == (GATE_EVIDENCE,)

    unknown = combine_outcomes([GateOutcome(GATE_EVIDENCE, GATE_UNKNOWN, True)])
    assert unknown.status == GATE_UNKNOWN

    failed = combine_outcomes(
        [
            GateOutcome(GATE_STATIC, GATE_FAILED, True),
            GateOutcome(GATE_DEFECT, GATE_PENDING, True),
        ]
    )
    assert failed.status == GATE_FAILED

    waived = combine_outcomes(
        [
            GateOutcome(GATE_STATIC, GATE_WAIVED, True),
            GateOutcome(GATE_LICENSE, GATE_PENDING, False),
        ]
    )
    assert waived.status == GATE_PASSED
    assert waived.waived == (GATE_STATIC,)
