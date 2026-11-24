"""冲突识别与解决（E7-T17）。

冲突记录必须保留参与 Assignment、资源与解决策略；检测到写冲突时先暂停相关
Assignment。设计/接口冲突若影响用户目标，直接升级为等待用户决策；解决策略
不允许“最后写入者获胜”，避免静默覆盖他人结果。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from core.errors import AgentConflictInvalid, NotFoundError, VersionConflict
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.multi_agent.models import (
    ASSIGNMENT_BLOCKED,
    ASSIGNMENT_READY,
    ASSIGNMENT_RUNNING,
    ASSIGNMENT_WAITING,
    CONFLICT_ANALYZING,
    CONFLICT_DETECTED,
    CONFLICT_ESCALATED,
    CONFLICT_INTERFACE,
    CONFLICT_RESOLVED,
    CONFLICT_RESOLVING,
    CONFLICT_SCHEMA,
    CONFLICT_SEVERITIES,
    CONFLICT_TRANSITIONS,
    CONFLICT_TYPES,
    RESOLUTION_STRATEGIES,
    RESOLUTION_USER_DECISION,
    AgentConflictModel,
)
from modules.multi_agent.repository import (
    AgentAssignmentRepository,
    AgentConflictRepository,
    AgentTeamRepository,
)
from modules.multi_agent.service import AssignmentService, AssignmentView


@dataclass(frozen=True, slots=True)
class ConflictView:
    conflict_id: str
    team_id: str
    resource_id: str | None
    conflicting_assignment_ids: tuple[str, ...]
    conflict_type: str
    severity: str
    resolution_status: str
    resolution_strategy: str | None
    resolution_reference: str | None
    resolved_by: str | None
    created_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    conflict: ConflictView
    paused_assignments: tuple[AssignmentView, ...]


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _conflict_view(entity: AgentConflictModel) -> ConflictView:
    return ConflictView(
        conflict_id=entity.conflict_id,
        team_id=entity.team_id,
        resource_id=entity.resource_id,
        conflicting_assignment_ids=tuple(json.loads(entity.conflicting_assignments)),
        conflict_type=entity.conflict_type,
        severity=entity.severity,
        resolution_status=entity.resolution_status,
        resolution_strategy=entity.resolution_strategy,
        resolution_reference=entity.resolution_reference,
        resolved_by=entity.resolved_by,
        created_at=entity.created_at,
        resolved_at=entity.resolved_at,
    )


class ConflictService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        assignments: AssignmentService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._assignments = assignments
        self._clock = clock

    async def report(
        self,
        *,
        team_id: str,
        conflict_type: str,
        conflicting_assignment_ids: Iterable[str],
        severity: str = "MEDIUM",
        resource_id: str | None = None,
        affects_user_goal: bool = False,
        pause: bool = True,
    ) -> ConflictResolution:
        participants = tuple(dict.fromkeys(conflicting_assignment_ids))
        if conflict_type not in CONFLICT_TYPES:
            raise AgentConflictInvalid(
                "冲突类型非法",
                details={"reasons": ["UNKNOWN_CONFLICT_TYPE"], "conflict_type": conflict_type},
            )
        if severity not in CONFLICT_SEVERITIES:
            raise AgentConflictInvalid(
                "冲突严重级别非法",
                details={"reasons": ["UNKNOWN_SEVERITY"], "severity": severity},
            )
        if not participants:
            raise AgentConflictInvalid(
                "冲突必须指定参与 Assignment",
                details={"reasons": ["ASSIGNMENT_REQUIRED"]},
            )
        async with self._database.session() as session:
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            repository = AgentAssignmentRepository(session)
            for assignment_id in participants:
                assignment = await repository.get(assignment_id)
                if assignment is None or assignment.team_id != team_id:
                    raise AgentConflictInvalid(
                        "冲突参与者不属于该 Team",
                        details={
                            "reasons": ["UNKNOWN_PARTICIPANT"],
                            "assignment_id": assignment_id,
                        },
                    )
        paused: list[AssignmentView] = []
        if pause:
            for assignment_id in participants:
                current = await self._assignments.get(assignment_id)
                if current.status == ASSIGNMENT_RUNNING:
                    paused.append(
                        await self._assignments.transition(
                            assignment_id, ASSIGNMENT_WAITING, expected_version=current.version
                        )
                    )
                elif current.status == ASSIGNMENT_READY:
                    paused.append(
                        await self._assignments.transition(
                            assignment_id, ASSIGNMENT_BLOCKED, expected_version=current.version
                        )
                    )
        escalated = affects_user_goal and conflict_type in {
            CONFLICT_INTERFACE,
            CONFLICT_SCHEMA,
        }
        now = self._clock()
        entity = AgentConflictModel(
            conflict_id=_new_id("cfl_"),
            team_id=team_id,
            resource_id=resource_id,
            conflicting_assignments=json.dumps(list(participants)),
            conflict_type=conflict_type,
            severity=severity,
            resolution_status=CONFLICT_ESCALATED if escalated else CONFLICT_DETECTED,
            resolution_strategy=None,
            resolution_reference=None,
            resolved_by=None,
            created_at=now,
            resolved_at=None,
        )
        async with self._database.session() as session, transaction(session):
            await AgentConflictRepository(session).add(entity)
        return ConflictResolution(conflict=_conflict_view(entity), paused_assignments=tuple(paused))

    async def get(self, conflict_id: str) -> ConflictView:
        async with self._database.session() as session:
            entity = await AgentConflictRepository(session).get(conflict_id)
        if entity is None:
            raise NotFoundError("冲突记录不存在", details={"conflict_id": conflict_id})
        return _conflict_view(entity)

    async def list_for_team(self, team_id: str) -> list[ConflictView]:
        async with self._database.session() as session:
            rows = await AgentConflictRepository(session).list_for_team(team_id)
        return [_conflict_view(row) for row in rows]

    async def escalate(self, conflict_id: str, *, expected_version: int = 0) -> ConflictView:
        async with self._database.session() as session, transaction(session):
            repository = AgentConflictRepository(session)
            entity = await repository.get(conflict_id)
            if entity is None:
                raise NotFoundError("冲突记录不存在", details={"conflict_id": conflict_id})
            if CONFLICT_ESCALATED not in CONFLICT_TRANSITIONS.get(
                entity.resolution_status, frozenset()
            ):
                raise AgentConflictInvalid(
                    "冲突当前状态不可升级",
                    details={
                        "reasons": ["INVALID_TRANSITION"],
                        "status": entity.resolution_status,
                    },
                )
            entity.resolution_status = CONFLICT_ESCALATED
            await session.flush()
            return _conflict_view(entity)

    async def resolve(
        self,
        conflict_id: str,
        *,
        strategy: str,
        resolution_reference: str,
        resolved_by: str,
        expected_status: str | None = None,
    ) -> ConflictView:
        if strategy not in RESOLUTION_STRATEGIES:
            raise AgentConflictInvalid(
                "解决策略非法",
                details={
                    "reasons": ["UNKNOWN_STRATEGY"],
                    "strategy": strategy,
                    "allowed": sorted(RESOLUTION_STRATEGIES),
                },
            )
        if not (resolution_reference or "").strip():
            raise AgentConflictInvalid(
                "解决冲突必须提供 resolution reference",
                details={"reasons": ["REFERENCE_REQUIRED"]},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentConflictRepository(session)
            entity = await repository.get(conflict_id)
            if entity is None:
                raise NotFoundError("冲突记录不存在", details={"conflict_id": conflict_id})
            if expected_status is not None and entity.resolution_status != expected_status:
                raise VersionConflict(
                    "冲突状态已变化",
                    details={"expected": expected_status, "actual": entity.resolution_status},
                )
            if entity.resolution_status == CONFLICT_RESOLVED:
                return _conflict_view(entity)
            if (
                entity.resolution_status == CONFLICT_ESCALATED
                and strategy != RESOLUTION_USER_DECISION
            ):
                raise AgentConflictInvalid(
                    "已升级的冲突必须由用户决策解决",
                    details={"reasons": ["USER_DECISION_REQUIRED"]},
                )
            if CONFLICT_RESOLVED not in CONFLICT_TRANSITIONS.get(
                entity.resolution_status, frozenset()
            ):
                raise AgentConflictInvalid(
                    "冲突当前状态不可解决",
                    details={
                        "reasons": ["INVALID_TRANSITION"],
                        "status": entity.resolution_status,
                    },
                )
            entity.resolution_status = CONFLICT_RESOLVED
            entity.resolution_strategy = strategy
            entity.resolution_reference = resolution_reference
            entity.resolved_by = resolved_by
            entity.resolved_at = now
            await session.flush()
            return _conflict_view(entity)

    async def start_analysis(self, conflict_id: str) -> ConflictView:
        return await self._transition(conflict_id, CONFLICT_ANALYZING)

    async def start_resolution(self, conflict_id: str) -> ConflictView:
        return await self._transition(conflict_id, CONFLICT_RESOLVING)

    async def _transition(self, conflict_id: str, to_status: str) -> ConflictView:
        async with self._database.session() as session, transaction(session):
            repository = AgentConflictRepository(session)
            entity = await repository.get(conflict_id)
            if entity is None:
                raise NotFoundError("冲突记录不存在", details={"conflict_id": conflict_id})
            if to_status not in CONFLICT_TRANSITIONS.get(entity.resolution_status, frozenset()):
                raise AgentConflictInvalid(
                    "冲突状态迁移非法",
                    details={
                        "reasons": ["INVALID_TRANSITION"],
                        "from": entity.resolution_status,
                        "to": to_status,
                    },
                )
            entity.resolution_status = to_status
            await session.flush()
            return _conflict_view(entity)


__all__ = ["ConflictResolution", "ConflictService", "ConflictView"]
