"""资源协调与并行执行（E7-T10 / T11）。

同一 Scene / 文件同一时刻只允许一个写者；读锁可以并行，但写锁会排斥所有
其他锁。锁带单调递增的 Fencing Token，旧 Token 释放或写入都会被拒绝，
避免过期 Agent 覆盖新结果。资源冲突一律失败关闭，不做静默覆盖。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from core.errors import (
    AgentAssignmentInvalid,
    AgentResourceConflict,
    AgentResourceLockInvalid,
    NotFoundError,
)
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.multi_agent.models import (
    ASSIGNMENT_BLOCKED,
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_READY,
    ASSIGNMENT_TERMINAL_STATUSES,
    LOCK_ACTIVE,
    LOCK_MODE_READ,
    LOCK_MODE_WRITE,
    LOCK_MODES,
    LOCK_RELEASED,
    RESOURCE_TYPES,
    AgentResourceLockModel,
)
from modules.multi_agent.repository import (
    AgentAssignmentDependencyRepository,
    AgentAssignmentRepository,
    AgentResourceLockRepository,
    AgentTeamRepository,
)
from modules.multi_agent.service import (
    AgentTeamService,
    AssignmentService,
    AssignmentView,
    _assignment_view,
)


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    resource_type: str
    resource_key: str
    mode: str = LOCK_MODE_WRITE

    def validate(self) -> None:
        if self.resource_type not in RESOURCE_TYPES:
            raise AgentResourceLockInvalid(
                "资源类型非法",
                details={"reasons": ["UNKNOWN_RESOURCE_TYPE"], "resource_type": self.resource_type},
            )
        if not (self.resource_key or "").strip():
            raise AgentResourceLockInvalid(
                "资源键不能为空", details={"reasons": ["RESOURCE_KEY_REQUIRED"]}
            )
        if self.mode not in LOCK_MODES:
            raise AgentResourceLockInvalid(
                "锁模式非法", details={"reasons": ["UNKNOWN_MODE"], "mode": self.mode}
            )

    def identity(self) -> str:
        return f"{self.resource_type}:{self.resource_key}"


@dataclass(frozen=True, slots=True)
class ResourceLockView:
    lock_id: str
    team_id: str
    assignment_id: str
    resource_type: str
    resource_key: str
    mode: str
    fencing_token: int
    status: str
    acquired_at: datetime
    released_at: datetime | None


@dataclass(frozen=True, slots=True)
class ResourceGrant:
    assignment_id: str
    locks: tuple[ResourceLockView, ...]


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _lock_view(entity: AgentResourceLockModel) -> ResourceLockView:
    return ResourceLockView(
        lock_id=entity.lock_id,
        team_id=entity.team_id,
        assignment_id=entity.assignment_id,
        resource_type=entity.resource_type,
        resource_key=entity.resource_key,
        mode=entity.mode,
        fencing_token=entity.fencing_token,
        status=entity.status,
        acquired_at=ensure_utc(entity.acquired_at),
        released_at=ensure_utc(entity.released_at) if entity.released_at else None,
    )


class ResourceCoordinatorService:
    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def acquire(
        self,
        *,
        team_id: str,
        assignment_id: str,
        resources: Iterable[ResourceRequest],
    ) -> ResourceGrant:
        requests = sorted(resources, key=lambda item: item.identity())
        if not requests:
            return ResourceGrant(assignment_id=assignment_id, locks=())
        for request in requests:
            request.validate()
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            assignment = await AgentAssignmentRepository(session).get(assignment_id)
            if assignment is None or assignment.team_id != team_id:
                raise AgentAssignmentInvalid(
                    "Assignment 不属于该 Team",
                    details={"reasons": ["UNKNOWN_ASSIGNMENT"], "assignment_id": assignment_id},
                )
            if assignment.status in ASSIGNMENT_TERMINAL_STATUSES:
                raise AgentAssignmentInvalid(
                    "已结束的 Assignment 不能申请资源",
                    details={"reasons": ["ASSIGNMENT_TERMINAL"], "status": assignment.status},
                )
            repository = AgentResourceLockRepository(session)
            created: list[AgentResourceLockModel] = []
            conflicts: list[dict[str, str]] = []
            seen: set[str] = set()
            for request in requests:
                identity = request.identity()
                if identity in seen:
                    continue
                seen.add(identity)
                active = await repository.list_active_for_resource(identity)
                if request.mode == LOCK_MODE_WRITE and active:
                    conflicts.extend(_conflict_payload(request, active))
                    continue
                if request.mode == LOCK_MODE_READ and any(
                    lock.mode == LOCK_MODE_WRITE for lock in active
                ):
                    conflicts.extend(_conflict_payload(request, active))
                    continue
                token = await repository.max_fencing_token(identity) + 1
                entity = AgentResourceLockModel(
                    lock_id=_new_id("lock_"),
                    team_id=team_id,
                    assignment_id=assignment_id,
                    resource_type=request.resource_type,
                    resource_key=identity,
                    mode=request.mode,
                    fencing_token=token,
                    status=LOCK_ACTIVE,
                    acquired_at=now,
                    released_at=None,
                )
                await repository.add(entity)
                created.append(entity)
            if conflicts:
                raise AgentResourceConflict(
                    "资源已被占用，不能并行写",
                    details={"reasons": ["LOCK_CONFLICT"], "conflicts": conflicts},
                )
            await session.flush()
            return ResourceGrant(
                assignment_id=assignment_id, locks=tuple(_lock_view(item) for item in created)
            )

    async def release(self, lock_id: str, *, fencing_token: int) -> ResourceLockView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentResourceLockRepository(session)
            entity = await repository.get(lock_id)
            if entity is None:
                raise NotFoundError("资源锁不存在", details={"lock_id": lock_id})
            if entity.fencing_token != fencing_token:
                raise AgentResourceLockInvalid(
                    "Fencing Token 已过期",
                    details={"reasons": ["STALE_FENCING_TOKEN"], "expected": entity.fencing_token},
                )
            if entity.status == LOCK_RELEASED:
                return _lock_view(entity)
            entity.status = LOCK_RELEASED
            entity.released_at = now
            await session.flush()
            return _lock_view(entity)

    async def assert_valid(self, lock_id: str, *, fencing_token: int) -> ResourceLockView:
        async with self._database.session() as session:
            entity = await AgentResourceLockRepository(session).get(lock_id)
        if entity is None:
            raise NotFoundError("资源锁不存在", details={"lock_id": lock_id})
        if entity.status != LOCK_ACTIVE:
            raise AgentResourceLockInvalid(
                "资源锁已释放", details={"reasons": ["LOCK_RELEASED"], "lock_id": lock_id}
            )
        if entity.fencing_token != fencing_token:
            raise AgentResourceLockInvalid(
                "Fencing Token 已过期",
                details={"reasons": ["STALE_FENCING_TOKEN"], "expected": entity.fencing_token},
            )
        return _lock_view(entity)

    async def release_for_assignment(self, assignment_id: str) -> int:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentResourceLockRepository(session)
            rows = await repository.list_for_assignment(assignment_id)
            released = 0
            for entity in rows:
                if entity.status == LOCK_ACTIVE:
                    entity.status = LOCK_RELEASED
                    entity.released_at = now
                    released += 1
            await session.flush()
            return released

    async def list_for_team(self, team_id: str) -> list[ResourceLockView]:
        async with self._database.session() as session:
            rows = await AgentResourceLockRepository(session).list_for_team(team_id)
        return [_lock_view(row) for row in rows]


def _conflict_payload(
    request: ResourceRequest, active: Sequence[AgentResourceLockModel]
) -> list[dict[str, str]]:
    return [
        {
            "resource": request.identity(),
            "requested_mode": request.mode,
            "holder_assignment_id": lock.assignment_id,
            "holder_mode": lock.mode,
        }
        for lock in active
    ]


@dataclass(frozen=True, slots=True)
class ParallelBatch:
    assignments: tuple[AssignmentView, ...]


@dataclass(frozen=True, slots=True)
class ParallelPlan:
    team_id: str
    batches: tuple[ParallelBatch, ...]
    deferred: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FailureImpact:
    failed_assignment_id: str
    blocked_assignment_ids: tuple[str, ...]
    unaffected_assignments: int


class ParallelExecutionManager:
    """并行批次规划与失败隔离；实际 Agent 启动由 Runtime 负责。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        teams: AgentTeamService,
        assignments: AssignmentService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._teams = teams
        self._assignments = assignments
        self._clock = clock

    async def refresh_readiness(self, team_id: str) -> tuple[AssignmentView, ...]:
        """依赖全部完成的 BLOCKED Assignment 晋升为 READY。"""

        await self._teams.get(team_id)
        async with self._database.session() as session:
            rows = await AgentAssignmentRepository(session).list_for_team(team_id)
            dependencies = AgentAssignmentDependencyRepository(session)
            statuses = {row.assignment_id: row.status for row in rows}
            promotable: list[str] = []
            for row in rows:
                if row.status != ASSIGNMENT_BLOCKED:
                    continue
                links = await dependencies.list_for_assignment(row.assignment_id)
                if all(statuses.get(link.depends_on_assignment_id) == ASSIGNMENT_COMPLETED for link in links):
                    promotable.append(row.assignment_id)
        promoted: list[AssignmentView] = []
        for assignment_id in promotable:
            current = await self._assignments.get(assignment_id)
            promoted.append(
                await self._assignments.transition(
                    assignment_id, ASSIGNMENT_READY, expected_version=current.version
                )
            )
        return tuple(promoted)

    async def plan_batches(
        self,
        team_id: str,
        *,
        resources_by_assignment: Mapping[str, Iterable[str]] | None = None,
        max_parallel: int = 4,
    ) -> ParallelPlan:
        if max_parallel < 1:
            raise AgentAssignmentInvalid(
                "并行上限必须大于 0", details={"reasons": ["INVALID_MAX_PARALLEL"]}
            )
        await self._teams.get(team_id)
        async with self._database.session() as session:
            rows = await AgentAssignmentRepository(session).list_for_team(team_id)
        ready = sorted(
            (row for row in rows if row.status == ASSIGNMENT_READY),
            key=lambda row: (-row.priority, row.assigned_at),
        )
        resource_map = {
            key: set(value)
            for key, value in (resources_by_assignment or {}).items()
        }
        batches: list[ParallelBatch] = []
        deferred: list[str] = []
        current: list[AssignmentView] = []
        occupied: set[str] = set()
        for row in ready:
            resources = resource_map.get(row.assignment_id, set())
            if current and (
                len(current) >= max_parallel
                or occupied & resources
            ):
                batches.append(ParallelBatch(assignments=tuple(current)))
                current = []
                occupied = set()
            current.append(_assignment_view(row))
            occupied |= resources
        if current:
            batches.append(ParallelBatch(assignments=tuple(current)))
        return ParallelPlan(team_id=team_id, batches=tuple(batches), deferred=tuple(deferred))

    async def handle_failure(
        self, assignment_id: str, *, expected_version: int, failure_reason: str
    ) -> FailureImpact:
        """隔离失败：依赖失败结果的 Assignment 标记 BLOCKED，其他不受影响。"""

        if not (failure_reason or "").strip():
            raise AgentAssignmentInvalid(
                "失败必须说明原因", details={"reasons": ["FAILURE_REASON_REQUIRED"]}
            )
        failed = await self._assignments.get(assignment_id)
        await self._assignments.transition(
            assignment_id, "FAILED", expected_version=expected_version
        )
        async with self._database.session() as session:
            links = await AgentAssignmentDependencyRepository(session).list_dependents(
                assignment_id
            )
            rows = await AgentAssignmentRepository(session).list_for_team(failed.team_id)
        statuses = {row.assignment_id: row.status for row in rows}
        blocked: list[str] = []
        for link in links:
            dependent_id = link.assignment_id
            if dependent_id == assignment_id:
                continue
            if statuses.get(dependent_id) in {ASSIGNMENT_READY, ASSIGNMENT_BLOCKED}:
                if statuses[dependent_id] == ASSIGNMENT_BLOCKED:
                    blocked.append(dependent_id)
                    continue
                current = await self._assignments.get(dependent_id)
                await self._assignments.transition(
                    dependent_id, ASSIGNMENT_BLOCKED, expected_version=current.version
                )
                blocked.append(dependent_id)
        async with self._database.session() as session:
            rows = await AgentAssignmentRepository(session).list_for_team(failed.team_id)
        unaffected = sum(
            1
            for row in rows
            if row.assignment_id != assignment_id and row.assignment_id not in blocked
        )
        return FailureImpact(
            failed_assignment_id=assignment_id,
            blocked_assignment_ids=tuple(blocked),
            unaffected_assignments=unaffected,
        )


def resource_signature(resources: Iterable[str]) -> str:
    """生成稳定的资源集合签名，便于冲突记录与审计。"""

    canonical = json.dumps(sorted(resources), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "FailureImpact",
    "ParallelBatch",
    "ParallelExecutionManager",
    "ParallelPlan",
    "ResourceCoordinatorService",
    "ResourceGrant",
    "ResourceLockView",
    "ResourceRequest",
    "resource_signature",
]
