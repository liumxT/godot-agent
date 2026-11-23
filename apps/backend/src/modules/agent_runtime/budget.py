"""Budget Manager（E6-T12）。

预算维度：Iteration / Model Call / Tool Call / Token / Cost / Time / Retry / Context。
调用前必须 reserve，成功后 settle 实际用量；任何维度不足时失败关闭，
不得自动提高用户预算或扩大上限。

用量持久化在 Execution 上，重启后继续累计，不重置预算。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.errors import AgentBudgetExceeded, NotFoundError
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.models import (
    BUDGET_EXCEED_FAIL,
    BUDGET_EXCEED_POLICIES,
    AgentExecutionModel,
)
from modules.agent_runtime.repository import AgentExecutionRepository

__all__ = ["BudgetManager", "BudgetReservation", "BudgetTracker"]

# 用量维度 -> 预算键
_DIMENSION_LIMITS = {
    "iterations": "max_iterations",
    "model_calls": "max_model_calls",
    "tool_calls": "max_tool_calls",
    "input_tokens": "max_input_tokens",
    "output_tokens": "max_output_tokens",
    "retries": "max_retries",
    "cost": "max_cost",
    "context_tokens": "max_context_tokens",
}
_ELAPSED_LIMIT = "max_execution_seconds"


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    dimension: str
    amount: int | float


@dataclass(slots=True)
class BudgetTracker:
    limits: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    on_exceed: str = BUDGET_EXCEED_FAIL
    _reserved: dict[str, Any] = field(default_factory=dict)
    _exceeded: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.on_exceed not in BUDGET_EXCEED_POLICIES:
            self.on_exceed = BUDGET_EXCEED_FAIL

    def limit(self, dimension: str) -> Any | None:
        key = _DIMENSION_LIMITS.get(dimension)
        if key is None:
            return None
        return self.limits.get(key)

    def used(self, dimension: str) -> Any:
        return self.usage.get(dimension, 0)

    def remaining(self, dimension: str) -> Any | None:
        limit = self.limit(dimension)
        if limit is None:
            return None
        return limit - self.used(dimension) - self._reserved.get(dimension, 0)

    def reserve(self, dimension: str, amount: float = 1) -> BudgetReservation:
        limit = self.limit(dimension)
        if limit is None:
            return BudgetReservation(dimension=dimension, amount=amount)
        available = limit - self.used(dimension) - self._reserved.get(dimension, 0)
        if amount > available:
            detail = {
                "dimension": dimension,
                "limit": limit,
                "usage": self.used(dimension),
                "reserved": self._reserved.get(dimension, 0),
                "requested": amount,
            }
            self._exceeded = detail
            raise AgentBudgetExceeded("Agent 预算不足", details=detail)
        self._reserved[dimension] = self._reserved.get(dimension, 0) + amount
        return BudgetReservation(dimension=dimension, amount=amount)

    def settle(
        self, reservation: BudgetReservation, *, actual: float | None = None
    ) -> None:
        used = reservation.amount if actual is None else actual
        self._reserved[reservation.dimension] = max(
            0, self._reserved.get(reservation.dimension, 0) - reservation.amount
        )
        self.usage[reservation.dimension] = (
            self.used(reservation.dimension) + used
        )

    def release(self, reservation: BudgetReservation) -> None:
        self._reserved[reservation.dimension] = max(
            0, self._reserved.get(reservation.dimension, 0) - reservation.amount
        )

    def record(self, dimension: str, amount: float) -> None:
        self.usage[dimension] = self.used(dimension) + amount

    def check_elapsed(self, elapsed_seconds: float) -> None:
        limit = self.limits.get(_ELAPSED_LIMIT)
        if limit is None:
            return
        if elapsed_seconds > float(limit):
            detail = {
                "dimension": "elapsed_seconds",
                "limit": limit,
                "usage": round(elapsed_seconds, 3),
            }
            self._exceeded = detail
            raise AgentBudgetExceeded("Agent 执行时间超出预算", details=detail)

    def exceeded(self) -> dict[str, Any] | None:
        """返回已经超出上限的维度（Usage 级检查，用于恢复前校验）。"""

        for dimension, key in _DIMENSION_LIMITS.items():
            limit = self.limits.get(key)
            if limit is None:
                continue
            if self.used(dimension) > limit:
                return {
                    "dimension": dimension,
                    "limit": limit,
                    "usage": self.used(dimension),
                }
        return self._exceeded

    def snapshot(self) -> dict[str, Any]:
        return {key: value for key, value in self.usage.items() if value}


class BudgetManager:
    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def load(
        self, execution_id: str, budget: Mapping[str, Any] | None
    ) -> BudgetTracker:
        async with self._database.session() as session:
            entity = await AgentExecutionRepository(session).get(execution_id)
        if entity is None:
            raise NotFoundError(
                "Agent Execution 不存在", details={"execution_id": execution_id}
            )
        payload = dict(budget or {})
        return BudgetTracker(
            limits=payload,
            usage=json.loads(entity.budget_usage_json or "{}"),
            on_exceed=str(payload.get("on_exceed", BUDGET_EXCEED_FAIL)),
        )

    async def persist(self, execution_id: str, tracker: BudgetTracker) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await AgentExecutionRepository(session).get(execution_id)
            if entity is None:
                raise NotFoundError(
                    "Agent Execution 不存在", details={"execution_id": execution_id}
                )
            self._apply(entity, tracker)
            await session.flush()

    async def persist_in_session(
        self, session, execution_id: str, tracker: BudgetTracker
    ) -> AgentExecutionModel | None:
        entity = await AgentExecutionRepository(session).get(execution_id)
        if entity is None:
            return None
        self._apply(entity, tracker)
        return entity

    @staticmethod
    def _apply(entity: AgentExecutionModel, tracker: BudgetTracker) -> None:
        entity.budget_usage_json = json.dumps(
            tracker.snapshot(), ensure_ascii=False, sort_keys=True
        )
