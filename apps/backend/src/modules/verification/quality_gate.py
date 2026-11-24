"""质量门禁引擎（E9-T16）。

纯函数模块，不读写数据库：

- 根据 Campaign 类型与风险决定适用门禁；
- 只有全部强制门禁通过（或存在有效豁免）才能 PASSED；
- 部分未执行只能 PARTIAL，UNKNOWN 不等同于 FAILED；
- 豁免必须由授权者提供原因、风险、范围与有效期，Agent 不能自行豁免。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from modules.verification.models import (
    CAMPAIGN_TYPE_ASSET,
    CAMPAIGN_TYPE_MANUAL,
    CAMPAIGN_TYPE_PHASE,
    CAMPAIGN_TYPE_REGRESSION,
    CAMPAIGN_TYPE_TASK,
    CAMPAIGN_TYPE_WORKFLOW,
    GATE_BLOCKED,
    GATE_DEFECT,
    GATE_EVIDENCE,
    GATE_FAILED,
    GATE_FUNCTIONAL,
    GATE_LICENSE,
    GATE_NOT_REQUIRED,
    GATE_OVERALL_PARTIAL,
    GATE_PASSED,
    GATE_PENDING,
    GATE_REGRESSION,
    GATE_REQUIREMENT_COMPLETENESS,
    GATE_RUNTIME,
    GATE_SECURITY,
    GATE_STATIC,
    GATE_STRUCTURAL,
    GATE_UNKNOWN,
    GATE_WAIVED,
    QUALITY_GATES,
    RESULT_FAILED,
    RESULT_NOT_RUN,
    RESULT_PASSED,
    RESULT_SKIPPED,
    RESULT_UNKNOWN,
    RESULT_WAIVED,
)

_PASSING_RESULT_STATUSES = frozenset({RESULT_PASSED, RESULT_WAIVED})
_UNKNOWN_RESULT_STATUSES = frozenset({RESULT_UNKNOWN, RESULT_NOT_RUN, RESULT_SKIPPED})

# Campaign 类型 → 默认必须执行的门禁。
CAMPAIGN_GATE_MATRIX: dict[str, tuple[str, ...]] = {
    CAMPAIGN_TYPE_TASK: (
        GATE_REQUIREMENT_COMPLETENESS,
        GATE_STATIC,
        GATE_STRUCTURAL,
        GATE_RUNTIME,
        GATE_FUNCTIONAL,
        GATE_EVIDENCE,
        GATE_DEFECT,
    ),
    CAMPAIGN_TYPE_PHASE: QUALITY_GATES,
    CAMPAIGN_TYPE_WORKFLOW: QUALITY_GATES,
    CAMPAIGN_TYPE_REGRESSION: (
        GATE_STATIC,
        GATE_STRUCTURAL,
        GATE_RUNTIME,
        GATE_FUNCTIONAL,
        GATE_EVIDENCE,
        GATE_DEFECT,
        GATE_REGRESSION,
    ),
    CAMPAIGN_TYPE_ASSET: (
        GATE_STATIC,
        GATE_STRUCTURAL,
        GATE_LICENSE,
        GATE_SECURITY,
    ),
    CAMPAIGN_TYPE_MANUAL: (
        GATE_REQUIREMENT_COMPLETENESS,
        GATE_EVIDENCE,
        GATE_DEFECT,
    ),
}
DEFAULT_REQUIRED_GATES: tuple[str, ...] = (
    GATE_REQUIREMENT_COMPLETENESS,
    GATE_STATIC,
    GATE_STRUCTURAL,
    GATE_RUNTIME,
    GATE_FUNCTIONAL,
    GATE_EVIDENCE,
    GATE_DEFECT,
)

# 高风险 / 极高风险的额外门禁。
RISK_EXTRA_GATES: dict[str, tuple[str, ...]] = {
    "HIGH": (GATE_REGRESSION, GATE_SECURITY),
    "CRITICAL": (GATE_REGRESSION, GATE_SECURITY, GATE_LICENSE),
}

# 这些门禁一旦失败会阻断后续流程。
BLOCKING_GATES = frozenset(
    {
        GATE_REQUIREMENT_COMPLETENESS,
        GATE_STATIC,
        GATE_STRUCTURAL,
        GATE_RUNTIME,
        GATE_FUNCTIONAL,
        GATE_EVIDENCE,
        GATE_DEFECT,
        GATE_REGRESSION,
        GATE_SECURITY,
    }
)


def required_gates(campaign_type: str | None, risk_level: str | None = None) -> tuple[str, ...]:
    """计算一次评估必须包含的门禁集合（保持固定顺序）。"""

    base = CAMPAIGN_GATE_MATRIX.get(campaign_type or "", DEFAULT_REQUIRED_GATES)
    extra = RISK_EXTRA_GATES.get((risk_level or "").upper(), ())
    selected = set(base) | set(extra)
    return tuple(gate for gate in QUALITY_GATES if gate in selected)


@dataclass(frozen=True, slots=True)
class GateWaiver:
    authorized_by: str
    reason: str
    risk_statement: str
    scope: str
    expires_at: datetime
    revoked_at: datetime | None = None


def waiver_problem(waiver: GateWaiver | None, now: datetime) -> str | None:
    """返回豁免无效的原因；有效时返回 None。"""

    if waiver is None:
        return "缺少豁免记录"
    if waiver.revoked_at is not None:
        return "豁免已撤销"
    if not waiver.authorized_by.strip():
        return "豁免缺少授权者"
    if not waiver.reason.strip():
        return "豁免缺少原因"
    if not waiver.risk_statement.strip():
        return "豁免缺少风险说明"
    if not waiver.scope.strip():
        return "豁免缺少适用范围"
    if waiver.expires_at <= now:
        return "豁免已过期"
    return None


@dataclass(frozen=True, slots=True)
class GateOutcome:
    gate: str
    status: str
    blocking: bool
    reason: str = ""
    details: dict = field(default_factory=dict)


def layer_gate(
    gate: str,
    result_statuses: Sequence[str],
    *,
    reason: str = "",
    blocking: bool | None = None,
) -> GateOutcome:
    """由某一验证层的结果状态汇总出门禁状态。"""

    statuses = list(result_statuses)
    is_blocking = gate in BLOCKING_GATES if blocking is None else blocking
    if not statuses:
        return GateOutcome(
            gate=gate,
            status=GATE_PENDING,
            blocking=is_blocking,
            reason=reason or "该层尚无验证结果",
            details={"results": 0},
        )
    details = {
        "results": len(statuses),
        "passed": sum(1 for item in statuses if item in _PASSING_RESULT_STATUSES),
        "failed": sum(1 for item in statuses if item == RESULT_FAILED),
        "unknown": sum(1 for item in statuses if item in _UNKNOWN_RESULT_STATUSES),
    }
    if details["failed"]:
        return GateOutcome(
            gate=gate,
            status=GATE_FAILED,
            blocking=is_blocking,
            reason=reason or "存在失败的验证结果",
            details=details,
        )
    if details["unknown"]:
        return GateOutcome(
            gate=gate,
            status=GATE_UNKNOWN,
            blocking=is_blocking,
            reason=reason or "存在未执行或结果未知的验证",
            details=details,
        )
    if details["passed"] == details["results"]:
        return GateOutcome(
            gate=gate,
            status=GATE_PASSED,
            blocking=is_blocking,
            reason=reason or "该层验证全部通过",
            details=details,
        )
    return GateOutcome(
        gate=gate,
        status=GATE_PENDING,
        blocking=is_blocking,
        reason=reason or "该层验证尚未完成",
        details=details,
    )


@dataclass(frozen=True, slots=True)
class GateDecision:
    status: str
    blocking_failures: tuple[str, ...]
    blocking_unknown: tuple[str, ...]
    pending: tuple[str, ...]
    waived: tuple[str, ...]
    gates: tuple[GateOutcome, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "blocking_failures": list(self.blocking_failures),
            "blocking_unknown": list(self.blocking_unknown),
            "pending": list(self.pending),
            "waived": list(self.waived),
            "gates": [
                {
                    "gate": item.gate,
                    "status": item.status,
                    "blocking": item.blocking,
                    "reason": item.reason,
                    "details": item.details,
                }
                for item in self.gates
            ],
        }


def combine_outcomes(outcomes: Iterable[GateOutcome]) -> GateDecision:
    """汇总门禁结论；PARTIAL 表示部分强制门禁尚未执行。"""

    items = tuple(outcomes)
    blocking_failures: list[str] = []
    blocking_blocked: list[str] = []
    blocking_unknown: list[str] = []
    pending: list[str] = []
    waived: list[str] = []
    for item in items:
        if item.status == GATE_WAIVED:
            waived.append(item.gate)
            continue
        if item.status == GATE_NOT_REQUIRED:
            continue
        if not item.blocking:
            continue
        if item.status == GATE_FAILED:
            blocking_failures.append(item.gate)
        elif item.status == GATE_BLOCKED:
            blocking_blocked.append(item.gate)
        elif item.status == GATE_UNKNOWN:
            blocking_unknown.append(item.gate)
        elif item.status in {GATE_PENDING, "RUNNING"}:
            pending.append(item.gate)
    if blocking_failures:
        overall = GATE_FAILED
    elif blocking_blocked:
        overall = GATE_BLOCKED
    elif blocking_unknown:
        overall = GATE_UNKNOWN
    elif pending:
        overall = GATE_OVERALL_PARTIAL
    else:
        overall = GATE_PASSED
    return GateDecision(
        status=overall,
        blocking_failures=tuple(blocking_failures),
        blocking_unknown=tuple(blocking_unknown),
        pending=tuple(pending),
        waived=tuple(waived),
        gates=items,
    )
