"""Agent Team Budget（E7-T18）。

预算分配只能由 Orchestrator 在 Task 授权范围内进行，任何重新分配都必须记录原因。
Team 预算不得突破 Task 预算；运行期用量按维度累计，超出上限时失败关闭（fail-closed）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import AgentBudgetExceeded, AgentTeamInvalid, NotFoundError, VersionConflict
from core.security.tokens import isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.models import BUDGET_EXCEED_FAIL, BUDGET_EXCEED_POLICIES
from modules.multi_agent.models import (
    AUTHORITY_ORCHESTRATOR,
    TEAM_BUDGET_ACTIVE,
    TEAM_BUDGET_EXHAUSTED,
    AgentTeamBudgetModel,
)
from modules.multi_agent.repository import AgentTeamBudgetRepository

__all__ = [
    "TEAM_BUDGET_KEYS",
    "TeamBudgetService",
    "TeamBudgetView",
    "usage_dimensions",
]

TEAM_BUDGET_KEYS = frozenset(
    {
        "max_model_calls",
        "max_tool_calls",
        "max_input_tokens",
        "max_output_tokens",
        "max_cost",
        "max_execution_seconds",
        "max_retries",
        "max_agents",
        "max_parallel",
    }
)
_REQUIRED_LIMIT = frozenset(
    {"max_model_calls", "max_tool_calls", "max_input_tokens", "max_output_tokens", "max_cost"}
)
_USAGE_LIMITS = {
    "model_calls": "max_model_calls",
    "tool_calls": "max_tool_calls",
    "input_tokens": "max_input_tokens",
    "output_tokens": "max_output_tokens",
    "cost": "max_cost",
    "execution_seconds": "max_execution_seconds",
    "retries": "max_retries",
    "agents": "max_agents",
    "parallel": "max_parallel",
}


def usage_dimensions() -> frozenset[str]:
    return frozenset(_USAGE_LIMITS)


@dataclass(frozen=True, slots=True)
class TeamBudgetView:
    budget_id: str
    team_id: str
    budget: dict[str, Any]
    usage: dict[str, Any]
    remaining: dict[str, Any]
    allocation_log: tuple[dict[str, Any], ...]
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    on_exceed: str


def _parse(document: str | None) -> dict[str, Any]:
    if not document:
        return {}
    try:
        loaded = json.loads(document)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _parse_log(document: str | None) -> list[dict[str, Any]]:
    if not document:
        return []
    try:
        loaded = json.loads(document)
    except json.JSONDecodeError:
        return []
    return [item for item in loaded if isinstance(item, dict)] if isinstance(loaded, list) else []


def _view(entity: AgentTeamBudgetModel) -> TeamBudgetView:
    budget = _parse(entity.budget_json)
    usage = _parse(entity.usage_json)
    remaining: dict[str, Any] = {}
    for dimension, key in _USAGE_LIMITS.items():
        limit = budget.get(key)
        if limit is None:
            continue
        remaining[dimension] = max(0, limit - usage.get(dimension, 0))
    return TeamBudgetView(
        budget_id=entity.budget_id,
        team_id=entity.team_id,
        budget=budget,
        usage=usage,
        remaining=remaining,
        allocation_log=tuple(_parse_log(entity.allocation_log_json)),
        status=entity.status,
        version=entity.version,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        on_exceed=str(budget.get("on_exceed", BUDGET_EXCEED_FAIL)),
    )


class TeamBudgetService:
    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def get(self, team_id: str) -> TeamBudgetView:
        async with self._database.session() as session:
            entity = await AgentTeamBudgetRepository(session).get_by_team(team_id)
        if entity is None:
            raise NotFoundError("Team 预算不存在", details={"team_id": team_id})
        return _view(entity)

    async def find(self, team_id: str) -> TeamBudgetView | None:
        async with self._database.session() as session:
            entity = await AgentTeamBudgetRepository(session).get_by_team(team_id)
        return _view(entity) if entity is not None else None

    async def allocate(
        self,
        *,
        team_id: str,
        budget: Mapping[str, Any],
        task_budget: Mapping[str, Any] | None = None,
        reason: str | None = None,
        authorized_by: str = AUTHORITY_ORCHESTRATOR,
        expected_version: int | None = None,
    ) -> TeamBudgetView:
        """分配或重新分配团队预算；重分配必须提供原因。"""

        if authorized_by != AUTHORITY_ORCHESTRATOR:
            raise AgentTeamInvalid(
                "预算分配必须由 Orchestrator 发起",
                details={"reasons": ["UNAUTHORIZED_BUDGET_CHANGE"], "authorized_by": authorized_by},
            )
        normalized = _normalize_budget(budget)
        if task_budget is not None:
            _assert_within_task_budget(normalized, task_budget)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentTeamBudgetRepository(session)
            entity = await repository.get_by_team(team_id)
            if entity is None:
                if expected_version not in (None, 0):
                    raise VersionConflict(
                        "Team 预算尚未创建",
                        details={"expected": expected_version, "actual": 0},
                    )
                entity = AgentTeamBudgetModel(
                    budget_id="budget_" + team_id,
                    team_id=team_id,
                    budget_json=json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    usage_json="{}",
                    allocation_log_json=json.dumps(
                        [_log_entry(now, reason or "INITIAL_ALLOCATION", normalized)],
                        ensure_ascii=False,
                    ),
                    status=TEAM_BUDGET_ACTIVE,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(entity)
            else:
                if expected_version is not None and entity.version != expected_version:
                    raise VersionConflict(
                        "Team 预算版本已变化",
                        details={"expected": expected_version, "actual": entity.version},
                    )
                if not (reason or "").strip():
                    raise AgentTeamInvalid(
                        "重新分配预算必须记录原因",
                        details={"reasons": ["REASON_REQUIRED"]},
                    )
                log = _parse_log(entity.allocation_log_json)
                log.append(_log_entry(now, reason or "", normalized))
                entity.budget_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
                entity.allocation_log_json = json.dumps(log, ensure_ascii=False)
                entity.version += 1
                entity.updated_at = now
            await session.flush()
            return _view(entity)

    async def record_usage(
        self, team_id: str, *, dimension: str, amount: float
    ) -> TeamBudgetView:
        """累计用量；超出上限时持久化 EXHAUSTED 并失败关闭。"""

        if dimension not in _USAGE_LIMITS:
            raise AgentTeamInvalid(
                "未知预算用量维度",
                details={"reasons": ["UNKNOWN_DIMENSION"], "dimension": dimension},
            )
        if amount < 0:
            raise AgentTeamInvalid(
                "用量不能为负数", details={"reasons": ["NEGATIVE_AMOUNT"]}
            )
        now = self._clock()
        exceeded: dict[str, Any] | None = None
        async with self._database.session() as session, transaction(session):
            repository = AgentTeamBudgetRepository(session)
            entity = await repository.get_by_team(team_id)
            if entity is None:
                raise NotFoundError("Team 预算不存在", details={"team_id": team_id})
            budget = _parse(entity.budget_json)
            usage = _parse(entity.usage_json)
            usage[dimension] = usage.get(dimension, 0) + amount
            limit = budget.get(_USAGE_LIMITS[dimension])
            if limit is not None and usage[dimension] > limit:
                exceeded = {
                    "dimension": dimension,
                    "limit": limit,
                    "usage": usage[dimension],
                }
                entity.status = TEAM_BUDGET_EXHAUSTED
            entity.usage_json = json.dumps(usage, ensure_ascii=False, sort_keys=True)
            entity.version += 1
            entity.updated_at = now
            await session.flush()
            view = _view(entity)
        if exceeded is not None:
            raise AgentBudgetExceeded("Team 预算已耗尽", details=exceeded)
        return view


def _normalize_budget(budget: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(budget, Mapping):
        raise AgentTeamInvalid("预算必须是对象", details={"reasons": ["INVALID_BUDGET"]})
    normalized: dict[str, Any] = {}
    for key, value in budget.items():
        if key == "on_exceed":
            if value not in BUDGET_EXCEED_POLICIES:
                raise AgentTeamInvalid(
                    "预算超限策略非法",
                    details={"reasons": ["UNKNOWN_ON_EXCEED"], "on_exceed": value},
                )
            normalized[key] = value
            continue
        if key not in TEAM_BUDGET_KEYS:
            raise AgentTeamInvalid(
                "未知预算项",
                details={"reasons": ["UNKNOWN_BUDGET_KEY"], "key": key},
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AgentTeamInvalid(
                "预算项必须是数字",
                details={"reasons": ["INVALID_BUDGET_VALUE"], "key": key},
            )
        if value < 0:
            raise AgentTeamInvalid(
                "预算项不能为负数",
                details={"reasons": ["NEGATIVE_BUDGET"], "key": key},
            )
        normalized[key] = value
    missing = _REQUIRED_LIMIT - set(normalized)
    if missing:
        raise AgentTeamInvalid(
            "预算缺少必需项",
            details={"reasons": ["MISSING_BUDGET_KEYS"], "keys": sorted(missing)},
        )
    return normalized


def _assert_within_task_budget(
    budget: Mapping[str, Any], task_budget: Mapping[str, Any]
) -> None:
    exceeded = [
        key
        for key, value in budget.items()
        if key in TEAM_BUDGET_KEYS
        and task_budget.get(key) is not None
        and value > task_budget[key]
    ]
    if exceeded:
        raise AgentTeamInvalid(
            "Team 预算不得突破 Task 预算",
            details={"reasons": ["TASK_BUDGET_EXCEEDED"], "keys": sorted(exceeded)},
        )


def _log_entry(now: datetime, reason: str, budget: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "at": isoformat(now),
        "reason": reason,
        "budget": dict(budget),
    }
