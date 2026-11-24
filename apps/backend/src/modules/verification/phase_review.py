"""Phase Review 报告构建（E9-T17）。

纯函数模块：

- 报告只汇总 Verification 数据，不修改 Workflow / Phase / Task 状态；
- Campaign PASSED 不会自动产生 ACCEPTED，用户验收是独立决策；
- 未执行、UNKNOWN、阻断缺陷都会进入“需要用户确认的事项”与风险清单。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from modules.verification.models import (
    CAMPAIGN_CANCELLED,
    CAMPAIGN_COMPLETED,
    GATE_FAILED,
    GATE_OVERALL_PARTIAL,
    GATE_PASSED,
    GATE_UNKNOWN,
    RESULT_FAILED,
    RESULT_NOT_RUN,
    RESULT_PASSED,
    RESULT_SKIPPED,
    RESULT_UNKNOWN,
    RESULT_WAIVED,
)

RECOMMENDATION_ACCEPT = "ACCEPT"
RECOMMENDATION_REVISION = "REQUEST_REVISION"
RECOMMENDATION_REJECT = "REJECT"
RECOMMENDATION_PENDING = "PENDING"
RECOMMENDATIONS = frozenset(
    {
        RECOMMENDATION_ACCEPT,
        RECOMMENDATION_REVISION,
        RECOMMENDATION_REJECT,
        RECOMMENDATION_PENDING,
    }
)


def recommendation_for(
    *,
    campaign_status: str | None,
    gate_status: str | None,
    blocking_defects: int,
) -> str:
    """给出建议结论；这只是建议，最终由用户决定。"""

    if campaign_status == CAMPAIGN_CANCELLED:
        return RECOMMENDATION_REJECT
    if blocking_defects:
        return RECOMMENDATION_REVISION
    if gate_status in {GATE_FAILED, GATE_UNKNOWN, GATE_OVERALL_PARTIAL}:
        return RECOMMENDATION_REVISION
    if gate_status == GATE_PASSED and campaign_status == CAMPAIGN_COMPLETED:
        return RECOMMENDATION_ACCEPT
    return RECOMMENDATION_PENDING


def build_review_summary(
    *,
    project_id: str,
    workflow_id: str,
    phase_id: str,
    campaign_id: str | None = None,
    campaign_status: str | None = None,
    gate_status: str | None = None,
    gate_details: Mapping[str, Any] | None = None,
    result_counts: Mapping[str, int] | None = None,
    defects: Iterable[Mapping[str, Any]] = (),
    evidence_total: int = 0,
    goals: Iterable[str] = (),
    completed: Iterable[str] = (),
    incomplete: Iterable[str] = (),
    user_confirmations: Iterable[str] = (),
) -> dict[str, Any]:
    """构建 Phase Review 报告，数字全部来自真实验证数据。"""

    counts = dict(result_counts or {})
    defect_items = list(defects)
    blocking = [
        item for item in defect_items if str(item.get("severity")) in {"BLOCKER", "CRITICAL"}
    ]
    passed = counts.get(RESULT_PASSED, 0)
    failed = counts.get(RESULT_FAILED, 0)
    unknown = sum(
        counts.get(status, 0) for status in (RESULT_UNKNOWN, RESULT_NOT_RUN, RESULT_SKIPPED)
    )
    waived = counts.get(RESULT_WAIVED, 0)
    executed = passed + failed
    risks: list[str] = []
    for item in blocking:
        risks.append(
            f"阻断缺陷：{item.get('title') or item.get('defect_id')} ({item.get('severity')})"
        )
    if gate_details:
        for gate in gate_details.get("gates", []):
            if gate.get("status") in {GATE_FAILED, GATE_UNKNOWN}:
                risks.append(f"门禁未通过：{gate.get('gate')} {gate.get('status')}")
    if unknown:
        risks.append(f"存在 {unknown} 条未执行或 UNKNOWN 的验证结果")
    if waived:
        risks.append(f"存在 {waived} 条豁免结果，需用户确认接受风险")

    confirmations = list(user_confirmations)
    if unknown:
        confirmations.append("确认未执行测试是否可接受")
    if blocking:
        confirmations.append("确认阻断缺陷的处理方式")
    if gate_status == GATE_OVERALL_PARTIAL:
        confirmations.append("确认是否在部分门禁未完成时继续")

    return {
        "project_id": project_id,
        "workflow_id": workflow_id,
        "phase_id": phase_id,
        "campaign_id": campaign_id,
        "campaign_status": campaign_status,
        "gate_status": gate_status,
        "goals": list(goals),
        "completed": list(completed),
        "incomplete": list(incomplete),
        "verification": {
            "passed": passed,
            "failed": failed,
            "unknown_or_not_run": unknown,
            "waived": waived,
            "executed": executed,
            "pass_rate": round(passed / executed * 100, 2) if executed else 0.0,
        },
        "defects": {
            "total": len(defect_items),
            "blocking": len(blocking),
            "items": defect_items,
        },
        "evidence_total": evidence_total,
        "risks": risks,
        "user_confirmations": confirmations,
    }
