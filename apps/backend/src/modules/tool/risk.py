"""工具风险分级（E5-T20）。

风险等级由工具定义与统一风险策略共同决定，Agent 只能提出更高等级：
请求的等级低于工具定义等级时按工具定义执行，并在结果中标注未被降级。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.errors import ValidationFailed
from modules.tool.models import (
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_NORMAL_WRITE,
    RISK_RANK,
    TOOL_RISK_LEVELS,
)
from modules.tool.registry import ToolView

__all__ = ["RiskAssessment", "ToolRiskPolicy"]


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: str
    tool_level: str
    requested_level: str | None
    approval_required: bool
    strong_approval_required: bool
    changeset_required: bool
    warnings: tuple[str, ...]


class ToolRiskPolicy:
    def assess(self, tool: ToolView, *, requested_level: str | None = None) -> RiskAssessment:
        if requested_level is not None and requested_level not in TOOL_RISK_LEVELS:
            raise ValidationFailed(
                "requested_risk_level 非法",
                details={"requested_level": requested_level},
            )
        warnings: list[str] = []
        effective = tool.risk_level
        if requested_level is not None:
            if RISK_RANK[requested_level] > RISK_RANK[tool.risk_level]:
                effective = requested_level
                warnings.append("RISK_RAISED_BY_REQUEST")
            elif RISK_RANK[requested_level] < RISK_RANK[tool.risk_level]:
                warnings.append("RISK_DOWNGRADE_IGNORED")

        rank = RISK_RANK[effective]
        return RiskAssessment(
            level=effective,
            tool_level=tool.risk_level,
            requested_level=requested_level,
            approval_required=rank >= RISK_RANK[RISK_HIGH],
            strong_approval_required=effective == RISK_CRITICAL,
            changeset_required=effective == RISK_NORMAL_WRITE,
            warnings=tuple(warnings),
        )
