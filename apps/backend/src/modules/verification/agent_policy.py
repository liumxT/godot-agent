"""Agent 验证策略与验证预算（E9-T19）。

冻结规则：

- Agent 只能发起验证请求、提交计划、请求执行、读取结果与证据、
  创建缺陷修复任务、提交修复 ChangeSet、请求回归；
- Agent 不得伪造结果或证据、修改结果、把 FAILED 改成 PASSED、删除失败记录、
  自行豁免质量门禁、自行宣布 Phase 完成；
- 验证预算（Test Run / Runtime Time / Screenshot / Video Capture / Retry /
  Regression）独立于 Agent 执行预算，按真实持久化数据计算，
  超出即失败关闭，禁止 Agent 无限重复测试。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.errors import PermissionDenied, ValidationFailed
from modules.verification.models import (
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
)

__all__ = [
    "AGENT_ACTIONS",
    "AGENT_ALLOWED_ACTIONS",
    "AGENT_FORBIDDEN_ACTIONS",
    "DEFAULT_BUDGET_BY_RISK",
    "VERIFICATION_BUDGET_DIMENSIONS",
    "BudgetStatus",
    "VerificationBudgetLimits",
    "budget_limits_for",
    "budget_statuses",
    "ensure_agent_action_allowed",
    "exhausted_dimensions",
]

# ---- 操作矩阵 ----

AGENT_ACTION_REQUEST_VERIFICATION = "REQUEST_VERIFICATION"
AGENT_ACTION_SUBMIT_PLAN = "SUBMIT_PLAN"
AGENT_ACTION_REQUEST_RUN = "REQUEST_RUN"
AGENT_ACTION_READ_RESULT = "READ_RESULT"
AGENT_ACTION_READ_EVIDENCE = "READ_EVIDENCE"
AGENT_ACTION_CREATE_DEFECT_TASK = "CREATE_DEFECT_TASK"
AGENT_ACTION_SUBMIT_FIX_CHANGESET = "SUBMIT_FIX_CHANGESET"
AGENT_ACTION_REQUEST_REGRESSION = "REQUEST_REGRESSION"

AGENT_ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        AGENT_ACTION_REQUEST_VERIFICATION,
        AGENT_ACTION_SUBMIT_PLAN,
        AGENT_ACTION_REQUEST_RUN,
        AGENT_ACTION_READ_RESULT,
        AGENT_ACTION_READ_EVIDENCE,
        AGENT_ACTION_CREATE_DEFECT_TASK,
        AGENT_ACTION_SUBMIT_FIX_CHANGESET,
        AGENT_ACTION_REQUEST_REGRESSION,
    }
)

AGENT_FORBIDDEN_ACTION_FORGE_RESULT = "FORGE_RESULT"
AGENT_FORBIDDEN_ACTION_FORGE_EVIDENCE = "FORGE_EVIDENCE"
AGENT_FORBIDDEN_ACTION_MODIFY_RESULT = "MODIFY_RESULT"
AGENT_FORBIDDEN_ACTION_DOWNGRADE_FAILURE = "DOWNGRADE_FAILURE"
AGENT_FORBIDDEN_ACTION_DELETE_FAILURE = "DELETE_FAILURE"
AGENT_FORBIDDEN_ACTION_SELF_WAIVE_GATE = "SELF_WAIVE_GATE"
AGENT_FORBIDDEN_ACTION_SELF_DECLARE_PHASE_COMPLETE = "SELF_DECLARE_PHASE_COMPLETE"

AGENT_FORBIDDEN_ACTIONS: frozenset[str] = frozenset(
    {
        AGENT_FORBIDDEN_ACTION_FORGE_RESULT,
        AGENT_FORBIDDEN_ACTION_FORGE_EVIDENCE,
        AGENT_FORBIDDEN_ACTION_MODIFY_RESULT,
        AGENT_FORBIDDEN_ACTION_DOWNGRADE_FAILURE,
        AGENT_FORBIDDEN_ACTION_DELETE_FAILURE,
        AGENT_FORBIDDEN_ACTION_SELF_WAIVE_GATE,
        AGENT_FORBIDDEN_ACTION_SELF_DECLARE_PHASE_COMPLETE,
    }
)

AGENT_ACTIONS: frozenset[str] = AGENT_ALLOWED_ACTIONS | AGENT_FORBIDDEN_ACTIONS


def ensure_agent_action_allowed(action: str) -> None:
    """校验 Agent 验证操作；禁止操作直接拒绝，未知操作按参数错误处理。"""

    if action in AGENT_FORBIDDEN_ACTIONS:
        raise PermissionDenied(
            "Agent 无权执行该验证操作",
            details={"action": action, "reason": "forbidden_by_policy"},
        )
    if action not in AGENT_ALLOWED_ACTIONS:
        raise ValidationFailed(
            "未知验证操作",
            details={"action": action, "allowed": sorted(AGENT_ALLOWED_ACTIONS)},
        )


# ---- 验证预算 ----

BUDGET_TEST_RUNS = "test_runs"
BUDGET_RUNTIME_SECONDS = "runtime_seconds"
BUDGET_SCREENSHOTS = "screenshots"
BUDGET_VIDEOS = "videos"
BUDGET_RETRIES = "retries"
BUDGET_REGRESSIONS = "regressions"

VERIFICATION_BUDGET_DIMENSIONS = (
    BUDGET_TEST_RUNS,
    BUDGET_RUNTIME_SECONDS,
    BUDGET_SCREENSHOTS,
    BUDGET_VIDEOS,
    BUDGET_RETRIES,
    BUDGET_REGRESSIONS,
)


@dataclass(frozen=True, slots=True)
class VerificationBudgetLimits:
    """单个验证活动的预算上限；预算只能由用户/策略设定，Agent 不得自行放宽。"""

    test_runs: int = 10
    runtime_seconds: float = 900.0
    screenshots: int = 50
    videos: int = 5
    retries: int = 3
    regressions: int = 3

    def limit(self, dimension: str) -> float | None:
        if dimension not in VERIFICATION_BUDGET_DIMENSIONS:
            return None
        return float(getattr(self, dimension))

    def to_dict(self) -> dict[str, float]:
        return {
            dimension: float(getattr(self, dimension))
            for dimension in VERIFICATION_BUDGET_DIMENSIONS
        }


DEFAULT_BUDGET_BY_RISK: dict[str, VerificationBudgetLimits] = {
    RISK_LOW: VerificationBudgetLimits(
        test_runs=5, runtime_seconds=300.0, screenshots=10, videos=1, retries=1, regressions=1
    ),
    RISK_MEDIUM: VerificationBudgetLimits(),
    RISK_HIGH: VerificationBudgetLimits(
        test_runs=20, runtime_seconds=1800.0, screenshots=100, videos=10, retries=5, regressions=6
    ),
    RISK_CRITICAL: VerificationBudgetLimits(
        test_runs=30, runtime_seconds=3600.0, screenshots=200, videos=20, retries=8, regressions=10
    ),
}


def budget_limits_for(
    risk_level: str, limits: VerificationBudgetLimits | None = None
) -> VerificationBudgetLimits:
    if limits is not None:
        return limits
    if risk_level not in DEFAULT_BUDGET_BY_RISK:
        raise ValidationFailed(
            "未知风险级别",
            details={"risk_level": risk_level, "allowed": sorted(DEFAULT_BUDGET_BY_RISK)},
        )
    return DEFAULT_BUDGET_BY_RISK[risk_level]


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    dimension: str
    used: float
    limit: float

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    def to_dict(self) -> dict[str, object]:
        return {
            "dimension": self.dimension,
            "used": round(self.used, 3),
            "limit": self.limit,
            "remaining": round(self.remaining, 3),
            "exhausted": self.exhausted,
        }


def budget_statuses(
    usage: Mapping[str, float], limits: VerificationBudgetLimits
) -> tuple[BudgetStatus, ...]:
    return tuple(
        BudgetStatus(
            dimension=dimension,
            used=float(usage.get(dimension, 0)),
            limit=float(limits.limit(dimension) or 0),
        )
        for dimension in VERIFICATION_BUDGET_DIMENSIONS
    )


def exhausted_dimensions(
    usage: Mapping[str, float],
    limits: VerificationBudgetLimits,
    *,
    amounts: Mapping[str, float] | None = None,
) -> list[dict[str, object]]:
    """返回已耗尽或本次申请后即将超限的预算维度。"""

    problems: list[dict[str, object]] = []
    for status in budget_statuses(usage, limits):
        amount = float((amounts or {}).get(status.dimension, 0))
        if status.used + amount > status.limit:
            problems.append(status.to_dict())
    return problems
