"""E9-T17 Phase Review 报告构建单元测试。"""

from __future__ import annotations

from modules.verification.models import (
    CAMPAIGN_CANCELLED,
    CAMPAIGN_COMPLETED,
    GATE_FAILED,
    GATE_OVERALL_PARTIAL,
    GATE_PASSED,
)
from modules.verification.phase_review import (
    RECOMMENDATION_ACCEPT,
    RECOMMENDATION_PENDING,
    RECOMMENDATION_REJECT,
    RECOMMENDATION_REVISION,
    build_review_summary,
    recommendation_for,
)


def test_recommendation_follows_gate_and_campaign_status() -> None:
    assert (
        recommendation_for(
            campaign_status=CAMPAIGN_COMPLETED, gate_status=GATE_PASSED, blocking_defects=0
        )
        == RECOMMENDATION_ACCEPT
    )
    assert (
        recommendation_for(
            campaign_status=CAMPAIGN_COMPLETED, gate_status=GATE_FAILED, blocking_defects=0
        )
        == RECOMMENDATION_REVISION
    )
    assert (
        recommendation_for(
            campaign_status=CAMPAIGN_COMPLETED, gate_status=GATE_PASSED, blocking_defects=2
        )
        == RECOMMENDATION_REVISION
    )
    assert (
        recommendation_for(
            campaign_status=None, gate_status=None, blocking_defects=0
        )
        == RECOMMENDATION_PENDING
    )
    assert (
        recommendation_for(
            campaign_status=CAMPAIGN_CANCELLED,
            gate_status=GATE_PASSED,
            blocking_defects=0,
        )
        == RECOMMENDATION_REJECT
    )


def test_build_review_summary_keeps_unknown_out_of_pass_rate() -> None:
    summary = build_review_summary(
        project_id="p1",
        workflow_id="wf1",
        phase_id="ph1",
        campaign_id="cmp1",
        campaign_status=CAMPAIGN_COMPLETED,
        gate_status=GATE_OVERALL_PARTIAL,
        gate_details={
            "gates": [
                {"gate": "GATE-6_EVIDENCE_COMPLETENESS", "status": GATE_FAILED},
            ]
        },
        result_counts={"PASSED": 3, "FAILED": 1, "UNKNOWN": 2, "NOT_RUN": 1},
        defects=[
            {
                "defect_id": "d1",
                "title": "跳跃失效",
                "severity": "BLOCKER",
                "status": "OPEN",
            }
        ],
        evidence_total=2,
        goals=["跳跃"],
        completed=["移动"],
        incomplete=["音效"],
        user_confirmations=["确认音效暂缓"],
    )

    verification = summary["verification"]
    assert verification["passed"] == 3
    assert verification["failed"] == 1
    assert verification["executed"] == 4
    assert verification["unknown_or_not_run"] == 3
    assert verification["pass_rate"] == 75.0
    assert summary["defects"]["blocking"] == 1
    assert any("阻断缺陷" in risk for risk in summary["risks"])
    assert any("门禁未通过" in risk for risk in summary["risks"])
    assert any("未执行" in item for item in summary["user_confirmations"])
    assert summary["evidence_total"] == 2
    assert summary["goals"] == ["跳跃"]
