"""Plan 与 Step 管理（E6-T08）。

规则：

- Plan 不覆盖旧版本：重新规划生成新 Plan，并把旧的 ACTIVE Plan 标记为 SUPERSEDED；
- Step 依赖只能指向更早的 Step，依赖未完成时不会被调度；
- 只有全部 Step 终止且无失败时 Plan 才能完成；
- Plan / Step 状态只由本模块修改，且使用版本条件更新。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from core.errors import AgentActionInvalid, AgentStateInvalid, NotFoundError, VersionConflict
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.models import (
    EVENT_PLAN_CREATED,
    EVENT_PLAN_UPDATED,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_CREATED,
    EVENT_STEP_FAILED,
    EVENT_STEP_STARTED,
    PLAN_ACTIVE,
    PLAN_COMPLETED,
    PLAN_SUPERSEDED,
    STEP_BLOCKED,
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_PENDING,
    STEP_READY,
    STEP_RUNNING,
    STEP_TERMINAL_STATUSES,
    STEP_TRANSITIONS,
    STEP_TYPES,
    STEP_WAITING_APPROVAL,
    STEP_WAITING_TOOL,
    AgentPlanModel,
    AgentStepModel,
)
from modules.agent_runtime.repository import AgentPlanRepository, AgentStepRepository

__all__ = ["PlanView", "PlanningService", "StepView"]


@dataclass(frozen=True, slots=True)
class StepView:
    step_id: str
    plan_id: str
    execution_id: str
    step_number: int
    step_type: str
    description: str
    status: str
    dependencies: tuple[int, ...]
    output_reference: str | None
    tool_execution_id: str | None
    retry_count: int
    version: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PlanView:
    plan_id: str
    agent_instance_id: str
    execution_id: str
    plan_version: int
    objective: str
    status: str
    supersedes_plan_id: str | None
    version: int
    steps: tuple[StepView, ...]
    created_at: datetime


def step_view(entity: AgentStepModel) -> StepView:
    return StepView(
        step_id=entity.step_id,
        plan_id=entity.plan_id,
        execution_id=entity.execution_id,
        step_number=entity.step_number,
        step_type=entity.step_type,
        description=entity.description,
        status=entity.status,
        dependencies=tuple(json.loads(entity.dependencies)),
        output_reference=entity.output_reference,
        tool_execution_id=entity.tool_execution_id,
        retry_count=entity.retry_count,
        version=entity.version,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        created_at=entity.created_at,
    )


def _plan_view(entity: AgentPlanModel, steps: Sequence[AgentStepModel]) -> PlanView:
    return PlanView(
        plan_id=entity.plan_id,
        agent_instance_id=entity.agent_instance_id,
        execution_id=entity.execution_id,
        plan_version=entity.plan_version,
        objective=entity.objective,
        status=entity.status,
        supersedes_plan_id=entity.supersedes_plan_id,
        version=entity.version,
        steps=tuple(step_view(item) for item in steps),
        created_at=entity.created_at,
    )


def _validate_steps(steps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not steps:
        raise AgentActionInvalid("计划必须包含至少一个 Step")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(steps, start=1):
        step_type = str(item.get("type", "")).strip().upper()
        if step_type not in STEP_TYPES:
            raise AgentActionInvalid(
                "未知的 Step 类型", details={"index": index, "step_type": step_type}
            )
        description = str(item.get("description", "")).strip()
        if not description:
            raise AgentActionInvalid("Step 描述不能为空", details={"index": index})
        dependencies: list[int] = []
        for dependency in item.get("dependencies", ()):
            try:
                number = int(dependency)
            except (TypeError, ValueError) as exc:
                raise AgentActionInvalid(
                    "Step 依赖必须是序号", details={"index": index}
                ) from exc
            if number < 1 or number >= index:
                raise AgentActionInvalid(
                    "Step 依赖必须指向更早的 Step",
                    details={"index": index, "dependency": number},
                )
            dependencies.append(number)
        normalized.append(
            {"type": step_type, "description": description, "dependencies": dependencies}
        )
    return normalized


class PlanningService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        events: AgentEventService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._events = events
        self._clock = clock

    # ---- 查询 ----

    async def get_plan(self, plan_id: str) -> PlanView:
        async with self._database.session() as session:
            plan = await AgentPlanRepository(session).get(plan_id)
            if plan is None:
                raise NotFoundError("Agent Plan 不存在", details={"plan_id": plan_id})
            steps = await AgentStepRepository(session).list_by_plan(plan_id)
        return _plan_view(plan, steps)

    async def list_plans(self, execution_id: str) -> list[PlanView]:
        async with self._database.session() as session:
            plans = await self._list_plans(session, execution_id)
            views = [
                _plan_view(plan, await AgentStepRepository(session).list_by_plan(plan.plan_id))
                for plan in plans
            ]
        return views

    async def active_plan(self, execution_id: str) -> PlanView | None:
        async with self._database.session() as session:
            plan = await AgentPlanRepository(session).get_active_for_execution(execution_id)
            if plan is None:
                return None
            steps = await AgentStepRepository(session).list_by_plan(plan.plan_id)
        return _plan_view(plan, steps)

    async def blocking_steps(self, execution_id: str) -> list[StepView]:
        """返回会阻止 Execution 完成的 Step（未终止或失败）。"""

        async with self._database.session() as session:
            steps = await AgentStepRepository(session).list_by_execution(execution_id)
        return [
            step_view(item)
            for item in steps
            if item.status not in STEP_TERMINAL_STATUSES
        ]

    # ---- 创建与推进 ----

    async def create_plan(
        self,
        *,
        instance_id: str,
        execution_id: str,
        objective: str,
        steps: Sequence[Mapping[str, Any]],
        supersedes_plan_id: str | None = None,
    ) -> PlanView:
        objective_text = (objective or "").strip()
        if not objective_text:
            raise AgentActionInvalid("Plan 目标不能为空")
        normalized = _validate_steps(steps)
        now = self._clock()

        async with self._database.session() as session, transaction(session):
            plans = AgentPlanRepository(session)
            if supersedes_plan_id is not None:
                previous = await plans.get(supersedes_plan_id)
                if previous is None:
                    raise NotFoundError(
                        "被替换的 Plan 不存在", details={"plan_id": supersedes_plan_id}
                    )
                if previous.execution_id != execution_id:
                    raise AgentStateInvalid(
                        "Plan 不属于该 Execution",
                        details={"plan_id": supersedes_plan_id},
                    )
            else:
                previous = await plans.get_active_for_execution(execution_id)
            if previous is not None and previous.status == PLAN_ACTIVE:
                previous.status = PLAN_SUPERSEDED
                previous.version += 1
                await self._events.append_in_session(
                    session,
                    instance_id=instance_id,
                    execution_id=execution_id,
                    event_type=EVENT_PLAN_UPDATED,
                    payload={
                        "plan_id": previous.plan_id,
                        "status": PLAN_SUPERSEDED,
                        "reason": "REPLANNED",
                    },
                    now=now,
                )

            plan = AgentPlanModel(
                plan_id="agpln_" + uuid4().hex[:12],
                agent_instance_id=instance_id,
                execution_id=execution_id,
                plan_version=await plans.next_version(execution_id),
                objective=objective_text,
                status=PLAN_ACTIVE,
                supersedes_plan_id=previous.plan_id if previous is not None else None,
                version=1,
                created_at=now,
            )
            await plans.add(plan)
            await self._events.append_in_session(
                session,
                instance_id=instance_id,
                execution_id=execution_id,
                event_type=EVENT_PLAN_CREATED,
                payload={
                    "plan_id": plan.plan_id,
                    "plan_version": plan.plan_version,
                    "objective": objective_text,
                    "step_count": len(normalized),
                },
                now=now,
            )
            steps_repository = AgentStepRepository(session)
            created: list[AgentStepModel] = []
            for item in normalized:
                step = AgentStepModel(
                    step_id="agstp_" + uuid4().hex[:12],
                    plan_id=plan.plan_id,
                    execution_id=execution_id,
                    step_number=await steps_repository.next_number(plan.plan_id),
                    step_type=item["type"],
                    description=item["description"],
                    status=STEP_PENDING,
                    dependencies=json.dumps(item["dependencies"]),
                    input_reference=None,
                    output_reference=None,
                    tool_execution_id=None,
                    retry_count=0,
                    version=1,
                    started_at=None,
                    completed_at=None,
                    created_at=now,
                )
                await steps_repository.add(step)
                await self._events.append_in_session(
                    session,
                    instance_id=instance_id,
                    execution_id=execution_id,
                    event_type=EVENT_STEP_CREATED,
                    payload={
                        "step_id": step.step_id,
                        "plan_id": plan.plan_id,
                        "step_number": step.step_number,
                        "step_type": step.step_type,
                    },
                    now=now,
                )
                created.append(step)
            await session.flush()
            return _plan_view(plan, created)

    async def next_runnable_step(self, plan_id: str) -> StepView | None:
        """返回下一个可执行 Step；依赖满足的 PENDING Step 会被提升为 READY。"""

        async with self._database.session() as session:
            plan = await AgentPlanRepository(session).get(plan_id)
            if plan is None:
                raise NotFoundError("Agent Plan 不存在", details={"plan_id": plan_id})
            if plan.status != PLAN_ACTIVE:
                return None
            steps = await AgentStepRepository(session).list_by_plan(plan_id)

        by_number = {item.step_number: item for item in steps}
        for entity in steps:
            if entity.status in STEP_TERMINAL_STATUSES:
                continue
            if entity.status in {
                STEP_READY,
                STEP_RUNNING,
                STEP_WAITING_TOOL,
                STEP_WAITING_APPROVAL,
            }:
                return step_view(entity)
            if entity.status in {STEP_PENDING, STEP_BLOCKED}:
                dependencies = tuple(json.loads(entity.dependencies))
                if all(
                    number in by_number
                    and by_number[number].status == STEP_COMPLETED
                    for number in dependencies
                ):
                    return await self._promote(entity.step_id)
        return None

    async def start_step(self, step_id: str) -> StepView:
        entity = await self._transition_step(
            step_id,
            target=STEP_RUNNING,
            event=EVENT_STEP_STARTED,
            payload={},
            set_started=True,
        )
        return entity

    async def complete_step(
        self,
        step_id: str,
        *,
        output_reference: str | None = None,
        tool_execution_id: str | None = None,
    ) -> StepView:
        return await self._transition_step(
            step_id,
            target=STEP_COMPLETED,
            event=EVENT_STEP_COMPLETED,
            payload={"tool_execution_id": tool_execution_id},
            set_tool_execution=tool_execution_id is not None,
            tool_execution_id=tool_execution_id,
            set_output_reference=output_reference is not None,
            output_reference=output_reference,
        )

    async def fail_step(self, step_id: str, *, reason: str | None = None) -> StepView:
        return await self._transition_step(
            step_id,
            target=STEP_FAILED,
            event=EVENT_STEP_FAILED,
            payload={"reason": reason},
        )

    async def complete_plan(self, plan_id: str) -> PlanView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            plans = AgentPlanRepository(session)
            plan = await plans.get(plan_id)
            if plan is None:
                raise NotFoundError("Agent Plan 不存在", details={"plan_id": plan_id})
            steps = await AgentStepRepository(session).list_by_plan(plan_id)
            blocked = [item for item in steps if item.status not in STEP_TERMINAL_STATUSES]
            if blocked:
                raise AgentStateInvalid(
                    "仍有未完成的 Step，不能完成 Plan",
                    details={"plan_id": plan_id, "steps": [item.step_id for item in blocked]},
                )
            failed = [item for item in steps if item.status != STEP_COMPLETED]
            if failed:
                raise AgentStateInvalid(
                    "存在未成功完成的 Step，不能完成 Plan",
                    details={"plan_id": plan_id, "steps": [item.step_id for item in failed]},
                )
            plan.status = PLAN_COMPLETED
            plan.version += 1
            await self._events.append_in_session(
                session,
                instance_id=plan.agent_instance_id,
                execution_id=plan.execution_id,
                event_type=EVENT_PLAN_UPDATED,
                payload={"plan_id": plan_id, "status": PLAN_COMPLETED},
                now=now,
            )
            await session.flush()
            return _plan_view(plan, steps)

    # ---- 内部 ----

    @staticmethod
    async def _list_plans(session, execution_id: str) -> list[AgentPlanModel]:
        result = await session.scalars(
            select(AgentPlanModel)
            .where(AgentPlanModel.execution_id == execution_id)
            .order_by(AgentPlanModel.plan_version)
        )
        return list(result)

    async def _promote(self, step_id: str) -> StepView | None:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentStepRepository(session)
            entity = await repository.get(step_id)
            if entity is None:
                raise NotFoundError("Agent Step 不存在", details={"step_id": step_id})
            if entity.status == STEP_READY:
                return step_view(entity)
            rowcount = await repository.compare_and_set_status(
                step_id,
                expected_version=entity.version,
                from_status=entity.status,
                to_status=STEP_READY,
                now=now,
            )
            if rowcount == 0:
                return None
            entity.status = STEP_READY
            entity.version += 1
            await session.flush()
            return step_view(entity)

    async def _transition_step(
        self,
        step_id: str,
        *,
        target: str,
        event: str,
        payload: Mapping[str, Any],
        set_started: bool = False,
        set_tool_execution: bool = False,
        tool_execution_id: str | None = None,
        set_output_reference: bool = False,
        output_reference: str | None = None,
    ) -> StepView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentStepRepository(session)
            entity = await repository.get(step_id)
            if entity is None:
                raise NotFoundError("Agent Step 不存在", details={"step_id": step_id})
            if target == entity.status:
                return step_view(entity)
            if target not in STEP_TRANSITIONS.get(entity.status, frozenset()):
                raise AgentStateInvalid(
                    "非法的 Step 状态迁移",
                    details={
                        "step_id": step_id,
                        "from_status": entity.status,
                        "to_status": target,
                    },
                )
            previous = entity.status
            rowcount = await repository.compare_and_set_status(
                step_id,
                expected_version=entity.version,
                from_status=previous,
                to_status=target,
                now=now,
                set_started=set_started,
                set_tool_execution=set_tool_execution,
                tool_execution_id=tool_execution_id,
                set_output_reference=set_output_reference,
                output_reference=output_reference,
            )
            if rowcount == 0:
                raise VersionConflict(
                    "Agent Step 状态已被并发修改", details={"step_id": step_id}
                )
            entity.status = target
            entity.version += 1
            if set_started:
                entity.started_at = now
            if set_tool_execution:
                entity.tool_execution_id = tool_execution_id
            if set_output_reference:
                entity.output_reference = output_reference
            if target in STEP_TERMINAL_STATUSES:
                entity.completed_at = now
            await self._events.append_in_session(
                session,
                instance_id=await self._instance_id(session, entity.plan_id),
                execution_id=entity.execution_id,
                event_type=event,
                payload={"step_id": step_id, "from_status": previous, **dict(payload)},
                now=now,
            )
            await session.flush()
            return step_view(entity)

    @staticmethod
    async def _instance_id(session, plan_id: str) -> str:
        plan = await AgentPlanRepository(session).get(plan_id)
        if plan is None:
            raise NotFoundError("Agent Plan 不存在", details={"plan_id": plan_id})
        return plan.agent_instance_id
