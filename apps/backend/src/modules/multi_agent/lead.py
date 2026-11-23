"""Lead Agent 与结果集成（E7-T08）。

Lead 只负责观察、检查和整理：读取 Team/Assignment/Result，规划集成并生成执行
摘要。它不能绕过 Orchestrator 创建 Assignment、修改 Task 状态或自动批准写入。
写权限必须由任务单独授予，默认权限集合中不包含写能力。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from core.errors import AgentTeamInvalid, NotFoundError, VersionConflict
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.multi_agent.models import (
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_FAILED,
    INTEGRATION_APPLYING,
    INTEGRATION_COMPLETED,
    INTEGRATION_FAILED,
    INTEGRATION_PENDING,
    INTEGRATION_READY,
    INTEGRATION_TRANSITIONS,
    INTEGRATION_VERIFYING,
    AgentIntegrationModel,
)
from modules.multi_agent.repository import (
    AgentAssignmentRepository,
    AgentIntegrationRepository,
    AgentTeamRepository,
)
from modules.multi_agent.service import (
    AgentTeamService,
    AssignmentView,
    TeamView,
    _assignment_view,
)

LEAD_PERMISSION_TEAM_READ = "TEAM_READ"
LEAD_PERMISSION_ASSIGNMENT_READ = "ASSIGNMENT_READ"
LEAD_PERMISSION_RESULT_READ = "RESULT_READ"
LEAD_PERMISSION_INTEGRATION_PLANNING = "INTEGRATION_PLANNING"
LEAD_PERMISSION_HANDOFF_REQUEST = "HANDOFF_REQUEST"
LEAD_PERMISSION_CONFLICT_REPORT = "CONFLICT_REPORT"

LEAD_PERMISSIONS = frozenset(
    {
        LEAD_PERMISSION_TEAM_READ,
        LEAD_PERMISSION_ASSIGNMENT_READ,
        LEAD_PERMISSION_RESULT_READ,
        LEAD_PERMISSION_INTEGRATION_PLANNING,
        LEAD_PERMISSION_HANDOFF_REQUEST,
        LEAD_PERMISSION_CONFLICT_REPORT,
    }
)
WRITE_PERMISSIONS = frozenset(
    {
        "PROJECT_WRITE",
        "TOOL_WRITE",
        "CHANGESET_APPROVE",
        "TASK_STATUS_WRITE",
        "PERMISSION_GRANT",
        "ASSIGNMENT_CREATE",
    }
)


@dataclass(frozen=True, slots=True)
class LeadStatusBoard:
    team: TeamView
    assignments: tuple[AssignmentView, ...]
    missing_outputs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InterfaceConflict:
    output_reference: str
    assignment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LeadExecutionSummary:
    team_id: str
    team_status: str
    total_assignments: int
    completed_assignments: int
    failed_assignments: int
    results: tuple[tuple[str, str], ...]
    missing_outputs: tuple[str, ...]
    conflicts: tuple[InterfaceConflict, ...]


@dataclass(frozen=True, slots=True)
class IntegrationPreparation:
    integration: IntegrationView
    sources: tuple[AssignmentView, ...]


@dataclass(frozen=True, slots=True)
class IntegrationView:
    integration_id: str
    team_id: str
    source_assignment_ids: tuple[str, ...]
    integration_owner: str | None
    integration_plan: str | None
    status: str
    verification_reference: str | None
    version: int
    created_at: datetime
    completed_at: datetime | None


def _integration_view(entity: AgentIntegrationModel) -> IntegrationView:
    return IntegrationView(
        integration_id=entity.integration_id,
        team_id=entity.team_id,
        source_assignment_ids=tuple(json.loads(entity.source_assignment_ids)),
        integration_owner=entity.integration_owner,
        integration_plan=entity.integration_plan,
        status=entity.status,
        verification_reference=entity.verification_reference,
        version=entity.version,
        created_at=entity.created_at,
        completed_at=entity.completed_at,
    )


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


class IntegrationService:
    """集成计划的最小生命周期；实际应用与验证由后续 Sprint 接入。"""

    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def create(
        self,
        *,
        team_id: str,
        source_assignment_ids: Iterable[str],
        integration_owner: str | None = None,
        plan: str | None = None,
    ) -> IntegrationView:
        sources = tuple(dict.fromkeys(source_assignment_ids))
        if not sources:
            raise AgentTeamInvalid(
                "集成计划至少需要一个来源 Assignment",
                details={"reasons": ["SOURCE_REQUIRED"]},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            assignments = AgentAssignmentRepository(session)
            for assignment_id in sources:
                assignment = await assignments.get(assignment_id)
                if assignment is None or assignment.team_id != team_id:
                    raise AgentTeamInvalid(
                        "集成来源不属于该 Team",
                        details={"reasons": ["UNKNOWN_SOURCE"], "assignment_id": assignment_id},
                    )
            entity = AgentIntegrationModel(
                integration_id=_new_id("int_"),
                team_id=team_id,
                source_assignment_ids=json.dumps(list(sources)),
                integration_owner=integration_owner,
                integration_plan=plan,
                status=INTEGRATION_PENDING,
                verification_reference=None,
                version=1,
                created_at=now,
                completed_at=None,
            )
            await AgentIntegrationRepository(session).add(entity)
            return _integration_view(entity)

    async def get(self, integration_id: str) -> IntegrationView:
        async with self._database.session() as session:
            entity = await AgentIntegrationRepository(session).get(integration_id)
        if entity is None:
            raise NotFoundError("Integration 不存在", details={"integration_id": integration_id})
        return _integration_view(entity)

    async def list_for_team(self, team_id: str) -> list[IntegrationView]:
        async with self._database.session() as session:
            rows = await AgentIntegrationRepository(session).list_for_team(team_id)
        return [_integration_view(row) for row in rows]

    async def transition(
        self, integration_id: str, to_status: str, *, expected_version: int
    ) -> IntegrationView:
        if to_status not in INTEGRATION_TRANSITIONS:
            raise AgentTeamInvalid(
                "Integration 状态非法",
                details={"reasons": ["UNKNOWN_STATUS"], "status": to_status},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentIntegrationRepository(session)
            entity = await repository.get(integration_id)
            if entity is None:
                raise NotFoundError(
                    "Integration 不存在", details={"integration_id": integration_id}
                )
            if entity.version != expected_version:
                raise VersionConflict(
                    "Integration 版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            if to_status not in INTEGRATION_TRANSITIONS.get(entity.status, frozenset()):
                raise AgentTeamInvalid(
                    "Integration 状态迁移非法",
                    details={
                        "reasons": ["INVALID_TRANSITION"],
                        "from": entity.status,
                        "to": to_status,
                    },
                )
            entity.status = to_status
            entity.version += 1
            if to_status in {INTEGRATION_FAILED, INTEGRATION_COMPLETED}:
                entity.completed_at = now
            await session.flush()
            return _integration_view(entity)

    async def set_plan(
        self, integration_id: str, plan: str, *, expected_version: int
    ) -> IntegrationView:
        if not (plan or "").strip():
            raise AgentTeamInvalid(
                "集成计划不能为空", details={"reasons": ["PLAN_REQUIRED"]}
            )
        async with self._database.session() as session, transaction(session):
            repository = AgentIntegrationRepository(session)
            entity = await repository.get(integration_id)
            if entity is None:
                raise NotFoundError(
                    "Integration 不存在", details={"integration_id": integration_id}
                )
            if entity.version != expected_version:
                raise VersionConflict(
                    "Integration 版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            entity.integration_plan = plan
            entity.status = INTEGRATION_READY
            entity.version += 1
            await session.flush()
            return _integration_view(entity)

    async def prepare(
        self,
        *,
        team_id: str,
        owner_assignment_id: str | None = None,
        plan: str | None = None,
    ) -> IntegrationPreparation:
        """严格集成前检查：所有结果完成、接口唯一、依赖完整。"""

        async with self._database.session() as session:
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            rows = await AgentAssignmentRepository(session).list_for_team(team_id)
        assignments = tuple(_assignment_view(row) for row in rows)
        missing = tuple(
            item.assignment_id
            for item in assignments
            if item.status != ASSIGNMENT_COMPLETED or not item.output_reference
        )
        if missing:
            raise AgentTeamInvalid(
                "存在未完成或缺少输出的 Assignment，不能集成",
                details={"reasons": ["MISSING_RESULTS"], "assignments": list(missing)},
            )
        grouped: dict[str, list[str]] = {}
        for item in assignments:
            grouped.setdefault(item.output_reference or "", []).append(item.assignment_id)
        duplicates = {
            reference: ids for reference, ids in grouped.items() if len(ids) > 1
        }
        if duplicates:
            raise AgentTeamInvalid(
                "集成结果存在接口冲突",
                details={"reasons": ["INTERFACE_CONFLICT"], "conflicts": duplicates},
            )
        integration = await self.create(
            team_id=team_id,
            source_assignment_ids=[item.assignment_id for item in assignments],
            integration_owner=owner_assignment_id,
            plan=plan,
        )
        if plan:
            integration = await self.set_plan(
                integration.integration_id, plan, expected_version=integration.version
            )
        return IntegrationPreparation(integration=integration, sources=assignments)

    async def start_apply(self, integration_id: str, *, expected_version: int) -> IntegrationView:
        return await self.transition(
            integration_id, INTEGRATION_APPLYING, expected_version=expected_version
        )

    async def start_verification(
        self, integration_id: str, *, expected_version: int
    ) -> IntegrationView:
        return await self.transition(
            integration_id, INTEGRATION_VERIFYING, expected_version=expected_version
        )

    async def submit_verification(
        self, integration_id: str, *, verification_reference: str, expected_version: int
    ) -> IntegrationView:
        if not (verification_reference or "").strip():
            raise AgentTeamInvalid(
                "提交验证必须引用验证结果",
                details={"reasons": ["VERIFICATION_REFERENCE_REQUIRED"]},
            )
        await self.assert_sources_complete(integration_id)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentIntegrationRepository(session)
            entity = await repository.get(integration_id)
            if entity is None:
                raise NotFoundError(
                    "Integration 不存在", details={"integration_id": integration_id}
                )
            if entity.version != expected_version:
                raise VersionConflict(
                    "Integration 版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            if INTEGRATION_COMPLETED not in INTEGRATION_TRANSITIONS.get(
                entity.status, frozenset()
            ):
                raise AgentTeamInvalid(
                    "Integration 当前状态不可提交验证",
                    details={"reasons": ["INVALID_TRANSITION"], "status": entity.status},
                )
            if not entity.integration_plan:
                raise AgentTeamInvalid(
                    "缺少集成计划，不能提交验证",
                    details={"reasons": ["PLAN_REQUIRED"]},
                )
            entity.verification_reference = verification_reference
            entity.status = INTEGRATION_COMPLETED
            entity.completed_at = now
            entity.version += 1
            await session.flush()
            return _integration_view(entity)

    async def assert_sources_complete(self, integration_id: str) -> None:
        integration = await self.get(integration_id)
        async with self._database.session() as session:
            repository = AgentAssignmentRepository(session)
            for assignment_id in integration.source_assignment_ids:
                assignment = await repository.get(assignment_id)
                if assignment is None or assignment.status != ASSIGNMENT_COMPLETED:
                    raise AgentTeamInvalid(
                        "集成来源 Assignment 未完成",
                        details={
                            "reasons": ["SOURCE_INCOMPLETE"],
                            "assignment_id": assignment_id,
                        },
                    )


class LeadAgentService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        teams: AgentTeamService,
        integrations: IntegrationService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._teams = teams
        self._integrations = integrations
        self._clock = clock

    @staticmethod
    def default_permissions() -> frozenset[str]:
        return LEAD_PERMISSIONS

    @staticmethod
    def granted_permissions(extra: Iterable[str] = ()) -> frozenset[str]:
        """默认权限 + 显式授予的写权限；未显式授予时 Lead 不能写。"""

        granted = LEAD_PERMISSIONS | frozenset(extra)
        unknown = granted - LEAD_PERMISSIONS - WRITE_PERMISSIONS
        if unknown:
            raise AgentTeamInvalid(
                "Lead 权限未知",
                details={"reasons": ["UNKNOWN_PERMISSION"], "permissions": sorted(unknown)},
            )
        return granted

    @staticmethod
    def can_write(permissions: Iterable[str]) -> bool:
        return bool(frozenset(permissions) & WRITE_PERMISSIONS)

    async def designate_lead(self, team_id: str, assignment_id: str) -> TeamView:
        team = await self._teams.get(team_id)
        members = await self._teams.get_members(team_id)
        if all(member.assignment_id != assignment_id for member in members):
            raise AgentTeamInvalid(
                "Assignment 未加入 Team",
                details={"reasons": ["MEMBER_NOT_FOUND"], "assignment_id": assignment_id},
            )
        return await self._teams.set_lead(
            team_id, assignment_id, expected_version=team.version
        )

    async def status_board(self, team_id: str) -> LeadStatusBoard:
        team = await self._teams.get(team_id)
        async with self._database.session() as session:
            rows = await AgentAssignmentRepository(session).list_for_team(team_id)
        assignments = tuple(_assignment_view(row) for row in rows)
        missing = tuple(
            item.assignment_id
            for item in assignments
            if item.status != ASSIGNMENT_COMPLETED or not item.output_reference
        )
        return LeadStatusBoard(team=team, assignments=assignments, missing_outputs=missing)

    async def detect_interface_conflicts(self, team_id: str) -> tuple[InterfaceConflict, ...]:
        board = await self.status_board(team_id)
        grouped: dict[str, list[str]] = {}
        for assignment in board.assignments:
            if assignment.output_reference:
                grouped.setdefault(assignment.output_reference, []).append(assignment.assignment_id)
        return tuple(
            InterfaceConflict(output_reference=reference, assignment_ids=tuple(ids))
            for reference, ids in sorted(grouped.items())
            if len(ids) > 1
        )

    async def build_integration_plan(
        self,
        team_id: str,
        *,
        owner_assignment_id: str | None = None,
        plan: str | None = None,
    ) -> IntegrationView:
        board = await self.status_board(team_id)
        sources = tuple(
            item.assignment_id
            for item in board.assignments
            if item.status == ASSIGNMENT_COMPLETED
        )
        if not sources:
            raise AgentTeamInvalid(
                "没有可集成的已完成 Assignment",
                details={"reasons": ["NO_COMPLETED_ASSIGNMENT"]},
            )
        integration = await self._integrations.create(
            team_id=team_id,
            source_assignment_ids=sources,
            integration_owner=owner_assignment_id,
            plan=plan,
        )
        if plan:
            return await self._integrations.set_plan(
                integration.integration_id, plan, expected_version=integration.version
            )
        return integration

    async def final_summary(self, team_id: str) -> LeadExecutionSummary:
        board = await self.status_board(team_id)
        conflicts = await self.detect_interface_conflicts(team_id)
        results = tuple(
            (item.assignment_id, item.output_reference)
            for item in board.assignments
            if item.output_reference
        )
        return LeadExecutionSummary(
            team_id=team_id,
            team_status=board.team.status,
            total_assignments=len(board.assignments),
            completed_assignments=sum(
                1 for item in board.assignments if item.status == ASSIGNMENT_COMPLETED
            ),
            failed_assignments=sum(
                1 for item in board.assignments if item.status == ASSIGNMENT_FAILED
            ),
            results=results,
            missing_outputs=board.missing_outputs,
            conflicts=conflicts,
        )


__all__ = [
    "LEAD_PERMISSIONS",
    "WRITE_PERMISSIONS",
    "IntegrationPreparation",
    "IntegrationService",
    "IntegrationView",
    "InterfaceConflict",
    "LeadAgentService",
    "LeadExecutionSummary",
    "LeadStatusBoard",
]
