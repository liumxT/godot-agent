"""Multi-Agent 领域服务（E7-T01 / T02）。

本文件当前覆盖 Sprint 1 的范围：

- Capability Registry：能力登记、查询与两阶段匹配；
- Team / Assignment / Handoff / Collaboration 的创建与查询。

写入约束：Assignment 只能由 ``AUTHORITY_ORCHESTRATOR`` 创建，Team 状态
不能替代 Task 状态，Handoff 只是请求，执行由 Orchestrator 在后续任务完成。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    AgentAssignmentInvalid,
    AgentAssignmentUnauthorized,
    AgentCapabilityUnsupported,
    AgentCollaborationInvalid,
    AgentHandoffInvalid,
    AgentTeamInvalid,
    NotFoundError,
    VersionConflict,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.multi_agent.capabilities import (
    BUILTIN_CAPABILITIES,
    CandidateProfile,
    CapabilityRequirement,
    CapabilitySpec,
    MatchOutcome,
    match_candidates,
)
from modules.multi_agent.models import (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_BLOCKED,
    ASSIGNMENT_CREATED,
    ASSIGNMENT_FAILED,
    ASSIGNMENT_HANDOFF_PENDING,
    ASSIGNMENT_INTEGRATING,
    ASSIGNMENT_READY,
    ASSIGNMENT_RUNNING,
    ASSIGNMENT_STARTING,
    ASSIGNMENT_TERMINAL_STATUSES,
    ASSIGNMENT_TRANSITIONS,
    AUTHORITY_ORCHESTRATOR,
    CAPABILITY_CATEGORIES,
    COLLABORATION_ACTIVE,
    DEFAULT_RISK_PROFILE,
    HANDOFF_REQUESTED,
    HANDOFF_TYPES,
    RISK_PROFILES,
    TEAM_COMPLETED,
    TEAM_CREATED,
    TEAM_MEMBER_LEAD,
    TEAM_MEMBER_ROLES,
    TEAM_MEMBER_WORKER,
    TEAM_STATUSES,
    TEAM_TERMINAL_STATUSES,
    TEAM_TRANSITIONS,
    AgentAssignmentDependencyModel,
    AgentAssignmentModel,
    AgentCapabilityModel,
    AgentCollaborationModel,
    AgentHandoffModel,
    AgentTeamMemberModel,
    AgentTeamModel,
)
from modules.multi_agent.repository import (
    AgentAssignmentDependencyRepository,
    AgentAssignmentRepository,
    AgentCollaborationRepository,
    AgentHandoffRepository,
    AgentTeamMemberRepository,
    AgentTeamRepository,
    CapabilityRepository,
)

_MAX_DEPENDENCY_DEPTH = 50


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


@dataclass(frozen=True, slots=True)
class CapabilityView:
    capability_id: str
    name: str
    description: str
    category: str
    input_contract: str | None
    output_contract: str | None
    required_tools: tuple[str, ...]
    required_model_capabilities: tuple[str, ...]
    dependencies: tuple[str, ...]
    risk_profile: str
    validation_method: str | None
    version: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TeamView:
    team_id: str
    task_id: str
    attempt_id: str
    workflow_id: str | None
    project_id: str
    lead_agent_instance_id: str | None
    status: str
    team_policy_id: str
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class TeamMemberView:
    member_id: str
    team_id: str
    assignment_id: str
    agent_instance_id: str | None
    role: str
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class AssignmentView:
    assignment_id: str
    team_id: str
    agent_definition_id: str
    agent_definition_version: str
    agent_instance_id: str | None
    task_id: str
    attempt_id: str
    parent_assignment_id: str | None
    assigned_objective: str
    scope: str | None
    input_reference: str | None
    output_reference: str | None
    acceptance_criteria: tuple[str, ...]
    dependencies: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    required_tools: tuple[str, ...]
    permission_requirements: tuple[str, ...]
    budget: dict[str, Any]
    estimated_duration_seconds: int | None
    risk_level: str
    priority: int
    status: str
    assigned_by: str
    version: int
    assigned_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class HandoffView:
    handoff_id: str
    source_assignment_id: str
    target_assignment_id: str | None
    source_agent_instance_id: str | None
    target_agent_definition_id: str
    handoff_type: str
    handoff_payload_reference: str
    context_snapshot_id: str | None
    approval_reference: str | None
    status: str
    requested_by_assignment_id: str | None
    version: int
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CollaborationView:
    collaboration_id: str
    team_id: str
    objective: str
    participant_assignments: tuple[str, ...]
    shared_context_id: str | None
    status: str
    version: int
    created_at: datetime
    completed_at: datetime | None


def _capability_view(entity: AgentCapabilityModel) -> CapabilityView:
    return CapabilityView(
        capability_id=entity.capability_id,
        name=entity.name,
        description=entity.description,
        category=entity.category,
        input_contract=entity.input_contract,
        output_contract=entity.output_contract,
        required_tools=tuple(json.loads(entity.required_tools)),
        required_model_capabilities=tuple(json.loads(entity.required_model_capabilities)),
        dependencies=tuple(json.loads(entity.dependencies)),
        risk_profile=entity.risk_profile,
        validation_method=entity.validation_method,
        version=entity.version,
        enabled=entity.enabled,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _team_view(entity: AgentTeamModel) -> TeamView:
    return TeamView(
        team_id=entity.team_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        workflow_id=entity.workflow_id,
        project_id=entity.project_id,
        lead_agent_instance_id=entity.lead_agent_instance_id,
        status=entity.status,
        team_policy_id=entity.team_policy_id,
        version=entity.version,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        completed_at=entity.completed_at,
    )


def _member_view(entity: AgentTeamMemberModel) -> TeamMemberView:
    return TeamMemberView(
        member_id=entity.member_id,
        team_id=entity.team_id,
        assignment_id=entity.assignment_id,
        agent_instance_id=entity.agent_instance_id,
        role=entity.role,
        joined_at=entity.joined_at,
    )


def _assignment_view(entity: AgentAssignmentModel) -> AssignmentView:
    return AssignmentView(
        assignment_id=entity.assignment_id,
        team_id=entity.team_id,
        agent_definition_id=entity.agent_definition_id,
        agent_definition_version=entity.agent_definition_version,
        agent_instance_id=entity.agent_instance_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        parent_assignment_id=entity.parent_assignment_id,
        assigned_objective=entity.assigned_objective,
        scope=entity.scope,
        input_reference=entity.input_reference,
        output_reference=entity.output_reference,
        acceptance_criteria=tuple(json.loads(entity.acceptance_criteria)),
        dependencies=tuple(json.loads(entity.dependencies)),
        required_capabilities=tuple(json.loads(entity.required_capabilities)),
        required_tools=tuple(json.loads(entity.required_tools)),
        permission_requirements=tuple(json.loads(entity.permission_requirements)),
        budget=json.loads(entity.budget_json),
        estimated_duration_seconds=entity.estimated_duration_seconds,
        risk_level=entity.risk_level,
        priority=entity.priority,
        status=entity.status,
        assigned_by=entity.assigned_by,
        version=entity.version,
        assigned_at=entity.assigned_at,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
    )


def _handoff_view(entity: AgentHandoffModel) -> HandoffView:
    return HandoffView(
        handoff_id=entity.handoff_id,
        source_assignment_id=entity.source_assignment_id,
        target_assignment_id=entity.target_assignment_id,
        source_agent_instance_id=entity.source_agent_instance_id,
        target_agent_definition_id=entity.target_agent_definition_id,
        handoff_type=entity.handoff_type,
        handoff_payload_reference=entity.handoff_payload_reference,
        context_snapshot_id=entity.context_snapshot_id,
        approval_reference=entity.approval_reference,
        status=entity.status,
        requested_by_assignment_id=entity.requested_by_assignment_id,
        version=entity.version,
        created_at=entity.created_at,
        completed_at=entity.completed_at,
    )


def _collaboration_view(entity: AgentCollaborationModel) -> CollaborationView:
    return CollaborationView(
        collaboration_id=entity.collaboration_id,
        team_id=entity.team_id,
        objective=entity.objective,
        participant_assignments=tuple(json.loads(entity.participant_assignments)),
        shared_context_id=entity.shared_context_id,
        status=entity.status,
        version=entity.version,
        created_at=entity.created_at,
        completed_at=entity.completed_at,
    )


class CapabilityRegistryService:
    """Agent 能力注册、查询与候选匹配。"""

    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def ensure_builtin_capabilities(self) -> int:
        """幂等登记内置能力；返回本次新增数量。"""

        added = 0
        async with self._database.session() as session, transaction(session):
            repository = CapabilityRepository(session)
            for spec in BUILTIN_CAPABILITIES:
                if await repository.get_by_name(spec.name) is not None:
                    continue
                await repository.add(self._entity(spec))
                added += 1
        return added

    async def register(self, spec: CapabilitySpec) -> CapabilityView:
        self._validate_spec(spec)
        async with self._database.session() as session, transaction(session):
            repository = CapabilityRepository(session)
            if await repository.get_by_name(spec.name) is not None:
                raise AgentCapabilityUnsupported(
                    "能力已登记",
                    details={"reasons": ["DUPLICATE_CAPABILITY"], "name": spec.name},
                )
            entity = await repository.add(self._entity(spec))
            return _capability_view(entity)

    async def get(self, capability_id: str) -> CapabilityView:
        async with self._database.session() as session:
            entity = await CapabilityRepository(session).get(capability_id)
        if entity is None:
            raise NotFoundError("能力不存在", details={"capability_id": capability_id})
        return _capability_view(entity)

    async def get_by_name(self, name: str) -> CapabilityView:
        async with self._database.session() as session:
            entity = await CapabilityRepository(session).get_by_name(name)
        if entity is None:
            raise NotFoundError("能力不存在", details={"name": name})
        return _capability_view(entity)

    async def list(
        self,
        *,
        category: str | None = None,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if category is not None and category not in CAPABILITY_CATEGORIES:
            raise AgentCapabilityUnsupported(
                "能力分类非法",
                details={"reasons": ["UNKNOWN_CATEGORY"], "category": category},
            )
        async with self._database.session() as session:
            page = await CapabilityRepository(session).list_page(
                category=category, enabled=enabled, limit=limit, offset=offset
            )
        return {
            "items": [_capability_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def match(
        self, requirement: CapabilityRequirement, candidates: Iterable[CandidateProfile]
    ) -> MatchOutcome:
        """先校验所需能力已登记且启用，再执行两阶段匹配。"""

        async with self._database.session() as session:
            repository = CapabilityRepository(session)
            for name in requirement.capabilities:
                entity = await repository.get_by_name(name)
                if entity is None:
                    raise AgentCapabilityUnsupported(
                        "能力不存在",
                        details={"reasons": ["UNKNOWN_CAPABILITY"], "name": name},
                    )
                if not entity.enabled:
                    raise AgentCapabilityUnsupported(
                        "能力已停用",
                        details={"reasons": ["CAPABILITY_DISABLED"], "name": name},
                    )
        return match_candidates(requirement, candidates)

    def _entity(self, spec: CapabilitySpec) -> AgentCapabilityModel:
        now = self._clock()
        return AgentCapabilityModel(
            capability_id=_new_id("cap_"),
            name=spec.name,
            description=spec.description,
            category=spec.category,
            input_contract=spec.input_contract or None,
            output_contract=spec.output_contract or None,
            required_tools=json.dumps(list(spec.required_tools)),
            required_model_capabilities=json.dumps(list(spec.required_model_capabilities)),
            dependencies=json.dumps(list(spec.dependencies)),
            risk_profile=spec.risk_profile,
            validation_method=spec.validation_method or None,
            version="1.0.0",
            enabled=True,
            created_at=now,
            updated_at=now,
        )

    def _validate_spec(self, spec: CapabilitySpec) -> None:
        if not spec.name.strip():
            raise AgentCapabilityUnsupported(
                "能力名称不能为空", details={"reasons": ["NAME_REQUIRED"]}
            )
        if spec.category not in CAPABILITY_CATEGORIES:
            raise AgentCapabilityUnsupported(
                "能力分类非法",
                details={"reasons": ["UNKNOWN_CATEGORY"], "category": spec.category},
            )
        if spec.risk_profile not in RISK_PROFILES:
            raise AgentCapabilityUnsupported(
                "风险等级非法",
                details={"reasons": ["INVALID_RISK_PROFILE"], "risk_profile": spec.risk_profile},
            )


class AgentTeamService:
    """Team 的创建与查询。状态迁移在 E7 Sprint 2 的 Team Manager 中实现。"""

    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def create(
        self,
        *,
        task_id: str,
        attempt_id: str,
        project_id: str,
        workflow_id: str | None = None,
        team_policy_id: str = "default",
        lead_agent_instance_id: str | None = None,
    ) -> TeamView:
        if not task_id or not attempt_id or not project_id:
            raise AgentTeamInvalid(
                "Team 必须绑定 Task、Attempt 与 Project",
                details={"reasons": ["BINDING_REQUIRED"]},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentTeamRepository(session)
            existing = await repository.get_by_task(task_id)
            if (
                existing is not None
                and existing.attempt_id == attempt_id
                and existing.status not in {"COMPLETED", "FAILED", "CANCELLED"}
            ):
                raise AgentTeamInvalid(
                    "该 Attempt 已有活动 Team",
                    details={"reasons": ["TEAM_ALREADY_ACTIVE"], "team_id": existing.team_id},
                )
            entity = AgentTeamModel(
                team_id=_new_id("team_"),
                task_id=task_id,
                attempt_id=attempt_id,
                workflow_id=workflow_id,
                project_id=project_id,
                lead_agent_instance_id=lead_agent_instance_id,
                status=TEAM_CREATED,
                team_policy_id=team_policy_id,
                version=1,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            await repository.add(entity)
            return _team_view(entity)

    async def get(self, team_id: str) -> TeamView:
        async with self._database.session() as session:
            entity = await AgentTeamRepository(session).get(team_id)
        if entity is None:
            raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
        return _team_view(entity)

    async def list(
        self,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in TEAM_STATUSES:
            raise AgentTeamInvalid(
                "Team 状态非法", details={"reasons": ["UNKNOWN_STATUS"], "status": status}
            )
        async with self._database.session() as session:
            page = await AgentTeamRepository(session).list_page(
                project_id=project_id,
                task_id=task_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_team_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def transition(
        self, team_id: str, to_status: str, *, expected_version: int
    ) -> TeamView:
        if to_status not in TEAM_STATUSES:
            raise AgentTeamInvalid(
                "Team 状态非法", details={"reasons": ["UNKNOWN_STATUS"], "status": to_status}
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentTeamRepository(session)
            entity = await repository.get(team_id)
            if entity is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            if entity.version != expected_version:
                raise VersionConflict(
                    "Agent Team 版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            if to_status not in TEAM_TRANSITIONS.get(entity.status, frozenset()):
                raise AgentTeamInvalid(
                    "Team 状态迁移非法",
                    details={
                        "reasons": ["INVALID_TRANSITION"],
                        "from": entity.status,
                        "to": to_status,
                    },
                )
            completed_at = now if to_status in TEAM_TERMINAL_STATUSES else None
            updated = await repository.transition_status(
                team_id,
                from_statuses=frozenset({entity.status}),
                to_status=to_status,
                expected_version=expected_version,
                now=now,
                completed_at=completed_at,
            )
            if not updated:
                raise VersionConflict(
                    "Agent Team 版本已变化", details={"expected": expected_version}
                )
            await session.refresh(entity)
            return _team_view(entity)

    async def add_member(
        self, team_id: str, assignment_id: str, *, role: str = TEAM_MEMBER_WORKER
    ) -> TeamMemberView:
        if role not in TEAM_MEMBER_ROLES:
            raise AgentTeamInvalid(
                "Team 成员角色非法", details={"reasons": ["UNKNOWN_ROLE"], "role": role}
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            assignment = await AgentAssignmentRepository(session).get(assignment_id)
            if assignment is None or assignment.team_id != team_id:
                raise AgentTeamInvalid(
                    "Assignment 不属于该 Team",
                    details={"reasons": ["UNKNOWN_ASSIGNMENT"], "assignment_id": assignment_id},
                )
            members = AgentTeamMemberRepository(session)
            if await members.get_by_assignment(assignment_id) is not None:
                raise AgentTeamInvalid(
                    "Assignment 已加入 Team",
                    details={"reasons": ["MEMBER_EXISTS"], "assignment_id": assignment_id},
                )
            if role == TEAM_MEMBER_LEAD:
                for existing in await members.list_for_team(team_id):
                    existing.role = TEAM_MEMBER_WORKER
                team.lead_agent_instance_id = assignment.agent_instance_id
                team.version += 1
                team.updated_at = now
            member = AgentTeamMemberModel(
                member_id=_new_id("mem_"),
                team_id=team_id,
                assignment_id=assignment_id,
                agent_instance_id=assignment.agent_instance_id,
                role=role,
                joined_at=now,
            )
            await members.add(member)
            return _member_view(member)

    async def get_members(self, team_id: str) -> list[TeamMemberView]:
        async with self._database.session() as session:
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            rows = await AgentTeamMemberRepository(session).list_for_team(team_id)
        return [_member_view(row) for row in rows]

    async def set_lead(
        self, team_id: str, assignment_id: str, *, expected_version: int
    ) -> TeamView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentTeamRepository(session)
            team = await repository.get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            if team.version != expected_version:
                raise VersionConflict(
                    "Agent Team 版本已变化",
                    details={"expected": expected_version, "actual": team.version},
                )
            members = AgentTeamMemberRepository(session)
            member = await members.get_by_assignment(assignment_id)
            if member is None or member.team_id != team_id:
                raise AgentTeamInvalid(
                    "Assignment 未加入 Team",
                    details={"reasons": ["MEMBER_NOT_FOUND"], "assignment_id": assignment_id},
                )
            for existing in await members.list_for_team(team_id):
                existing.role = TEAM_MEMBER_LEAD if existing.member_id == member.member_id else (
                    TEAM_MEMBER_WORKER
                )
            team.lead_agent_instance_id = member.agent_instance_id
            team.version += 1
            team.updated_at = now
            await session.flush()
            return _team_view(team)

    async def remove_member(self, team_id: str, member_id: str) -> None:
        async with self._database.session() as session, transaction(session):
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            members = AgentTeamMemberRepository(session)
            member = await members.get(member_id)
            if member is None or member.team_id != team_id:
                raise NotFoundError("Team 成员不存在", details={"member_id": member_id})
            assignment = await AgentAssignmentRepository(session).get(member.assignment_id)
            if assignment is not None and assignment.status not in {
                ASSIGNMENT_CREATED,
                ASSIGNMENT_READY,
                "BLOCKED",
            }:
                raise AgentTeamInvalid(
                    "Assignment 已开始，不能移出 Team",
                    details={
                        "reasons": ["ASSIGNMENT_STARTED"],
                        "assignment_id": member.assignment_id,
                        "status": assignment.status,
                    },
                )
            if member.role == TEAM_MEMBER_LEAD:
                team.lead_agent_instance_id = None
                team.version += 1
                team.updated_at = self._clock()
            await members.delete(member)

    async def close(
        self, team_id: str, *, status: str = TEAM_COMPLETED, expected_version: int
    ) -> TeamView:
        if status not in TEAM_TERMINAL_STATUSES:
            raise AgentTeamInvalid(
                "Team 关闭状态非法", details={"reasons": ["TERMINAL_STATUS_REQUIRED"]}
            )
        async with self._database.session() as session:
            unfinished = await AgentAssignmentRepository(session).count_unfinished(
                team_id, ASSIGNMENT_TERMINAL_STATUSES
            )
        if unfinished:
            raise AgentTeamInvalid(
                "仍有未完成的 Assignment，不能关闭 Team",
                details={"reasons": ["TEAM_HAS_UNFINISHED_ASSIGNMENTS"], "count": unfinished},
            )
        return await self.transition(team_id, status, expected_version=expected_version)


class AssignmentService:
    """Assignment 创建与依赖维护；只有 Orchestrator 可以创建。"""

    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def create(
        self,
        *,
        team_id: str,
        agent_definition_id: str,
        agent_definition_version: str,
        task_id: str,
        attempt_id: str,
        assigned_objective: str,
        authorized_by: str,
        acceptance_criteria: Iterable[str] = (),
        required_capabilities: Iterable[str] = (),
        required_tools: Iterable[str] = (),
        permission_requirements: Iterable[str] = (),
        budget: Mapping[str, Any] | None = None,
        priority: int = 0,
        risk_level: str = DEFAULT_RISK_PROFILE,
        scope: str | None = None,
        input_reference: str | None = None,
        parent_assignment_id: str | None = None,
        agent_instance_id: str | None = None,
        estimated_duration_seconds: int | None = None,
        dependencies: Iterable[str] = (),
    ) -> AssignmentView:
        if authorized_by != AUTHORITY_ORCHESTRATOR:
            raise AgentAssignmentUnauthorized(
                "Assignment 只能由 Multi-Agent Orchestrator 创建",
                details={"reasons": ["ORCHESTRATOR_REQUIRED"], "authorized_by": authorized_by},
            )
        objective = (assigned_objective or "").strip()
        if not objective:
            raise AgentAssignmentInvalid(
                "Assignment 必须声明目标", details={"reasons": ["OBJECTIVE_REQUIRED"]}
            )
        if not agent_definition_id or not agent_definition_version:
            raise AgentAssignmentInvalid(
                "Assignment 必须绑定 Agent Definition 与版本",
                details={"reasons": ["DEFINITION_REQUIRED"]},
            )
        if risk_level not in RISK_PROFILES:
            raise AgentAssignmentInvalid(
                "风险等级非法",
                details={"reasons": ["INVALID_RISK_LEVEL"], "risk_level": risk_level},
            )
        now = self._clock()
        dependency_ids = tuple(dict.fromkeys(dependencies))
        async with self._database.session() as session, transaction(session):
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            if team.task_id != task_id or team.attempt_id != attempt_id:
                raise AgentAssignmentInvalid(
                    "Assignment 的 Task/Attempt 与 Team 不一致",
                    details={
                        "reasons": ["SCOPE_MISMATCH"],
                        "team_task_id": team.task_id,
                        "team_attempt_id": team.attempt_id,
                    },
                )
            assignments = AgentAssignmentRepository(session)
            for dependency_id in dependency_ids:
                dependency = await assignments.get(dependency_id)
                if dependency is None or dependency.team_id != team_id:
                    raise AgentAssignmentInvalid(
                        "依赖的 Assignment 不属于同一 Team",
                        details={
                            "reasons": ["UNKNOWN_DEPENDENCY"],
                            "dependency_id": dependency_id,
                        },
                    )
            entity = AgentAssignmentModel(
                assignment_id=_new_id("asg_"),
                team_id=team_id,
                agent_definition_id=agent_definition_id,
                agent_definition_version=agent_definition_version,
                agent_instance_id=agent_instance_id,
                task_id=task_id,
                attempt_id=attempt_id,
                parent_assignment_id=parent_assignment_id,
                assigned_objective=objective,
                scope=scope,
                input_reference=input_reference,
                output_reference=None,
                acceptance_criteria=json.dumps(list(acceptance_criteria)),
                dependencies=json.dumps(list(dependency_ids)),
                required_capabilities=json.dumps(list(required_capabilities)),
                required_tools=json.dumps(list(required_tools)),
                permission_requirements=json.dumps(list(permission_requirements)),
                budget_json=json.dumps(dict(budget or {})),
                estimated_duration_seconds=estimated_duration_seconds,
                risk_level=risk_level,
                priority=int(priority),
                status=ASSIGNMENT_CREATED,
                assigned_by=AUTHORITY_ORCHESTRATOR,
                version=1,
                assigned_at=now,
                started_at=None,
                completed_at=None,
            )
            await assignments.add(entity)
            dependency_repository = AgentAssignmentDependencyRepository(session)
            for dependency_id in dependency_ids:
                await dependency_repository.add(
                    AgentAssignmentDependencyModel(
                        dependency_id=_new_id("dep_"),
                        assignment_id=entity.assignment_id,
                        depends_on_assignment_id=dependency_id,
                        created_at=now,
                    )
                )
            return _assignment_view(entity)

    async def get(self, assignment_id: str) -> AssignmentView:
        async with self._database.session() as session:
            entity = await AgentAssignmentRepository(session).get(assignment_id)
        if entity is None:
            raise NotFoundError("Assignment 不存在", details={"assignment_id": assignment_id})
        return _assignment_view(entity)

    async def list_for_team(self, team_id: str) -> list[AssignmentView]:
        async with self._database.session() as session:
            rows = await AgentAssignmentRepository(session).list_for_team(team_id)
        return [_assignment_view(row) for row in rows]

    async def add_dependency(
        self, assignment_id: str, depends_on_assignment_id: str, *, expected_version: int
    ) -> AssignmentView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentAssignmentRepository(session)
            assignment = await repository.get(assignment_id)
            if assignment is None:
                raise NotFoundError("Assignment 不存在", details={"assignment_id": assignment_id})
            if assignment.version != expected_version:
                raise VersionConflict(
                    "Assignment 版本已变化",
                    details={"expected": expected_version, "actual": assignment.version},
                )
            if assignment_id == depends_on_assignment_id:
                raise AgentAssignmentInvalid(
                    "Assignment 不能依赖自身", details={"reasons": ["SELF_DEPENDENCY"]}
                )
            target = await repository.get(depends_on_assignment_id)
            if target is None or target.team_id != assignment.team_id:
                raise AgentAssignmentInvalid(
                    "依赖的 Assignment 不属于同一 Team",
                    details={
                        "reasons": ["UNKNOWN_DEPENDENCY"],
                        "dependency_id": depends_on_assignment_id,
                    },
                )
            dependency_repository = AgentAssignmentDependencyRepository(session)
            if (
                await dependency_repository.get_pair(assignment_id, depends_on_assignment_id)
                is not None
            ):
                raise AgentAssignmentInvalid(
                    "依赖已存在", details={"reasons": ["DUPLICATE_DEPENDENCY"]}
                )
            if await self._has_path(
                session, depends_on_assignment_id, assignment_id, depth=0
            ):
                raise AgentAssignmentInvalid(
                    "依赖关系存在循环", details={"reasons": ["DEPENDENCY_CYCLE"]}
                )
            await dependency_repository.add(
                AgentAssignmentDependencyModel(
                    dependency_id=_new_id("dep_"),
                    assignment_id=assignment_id,
                    depends_on_assignment_id=depends_on_assignment_id,
                    created_at=now,
                )
            )
            existing = json.loads(assignment.dependencies)
            existing.append(depends_on_assignment_id)
            assignment.dependencies = json.dumps(list(dict.fromkeys(existing)))
            assignment.version += 1
            await session.flush()
            return _assignment_view(assignment)

    async def _has_path(
        self, session, start: str, target: str, *, depth: int
    ) -> bool:
        if depth > _MAX_DEPENDENCY_DEPTH:
            return True
        current = await AgentAssignmentRepository(session).get(start)
        if current is None:
            return False
        for dependency_id in json.loads(current.dependencies):
            if dependency_id == target:
                return True
            if await self._has_path(session, dependency_id, target, depth=depth + 1):
                return True
        return False

    async def transition(
        self, assignment_id: str, to_status: str, *, expected_version: int
    ) -> AssignmentView:
        if to_status not in ASSIGNMENT_TRANSITIONS:
            raise AgentAssignmentInvalid(
                "Assignment 状态非法",
                details={"reasons": ["UNKNOWN_STATUS"], "status": to_status},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentAssignmentRepository(session)
            entity = await repository.get(assignment_id)
            if entity is None:
                raise NotFoundError("Assignment 不存在", details={"assignment_id": assignment_id})
            if entity.version != expected_version:
                raise VersionConflict(
                    "Assignment 版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            if to_status not in ASSIGNMENT_TRANSITIONS.get(entity.status, frozenset()):
                raise AgentAssignmentInvalid(
                    "Assignment 状态迁移非法",
                    details={
                        "reasons": ["INVALID_TRANSITION"],
                        "from": entity.status,
                        "to": to_status,
                    },
                )
            updated = await repository.transition_status(
                assignment_id,
                from_statuses=frozenset({entity.status}),
                to_status=to_status,
                expected_version=expected_version,
                now=now,
                started_at=now if to_status == ASSIGNMENT_STARTING else None,
                completed_at=now if to_status in ASSIGNMENT_TERMINAL_STATUSES else None,
            )
            if not updated:
                raise VersionConflict(
                    "Assignment 版本已变化", details={"expected": expected_version}
                )
            await session.refresh(entity)
            return _assignment_view(entity)

    async def claim(
        self, assignment_id: str, agent_instance_id: str, *, expected_version: int
    ) -> AssignmentView:
        async with self._database.session() as session, transaction(session):
            repository = AgentAssignmentRepository(session)
            entity = await repository.get(assignment_id)
            if entity is None:
                raise NotFoundError("Assignment 不存在", details={"assignment_id": assignment_id})
            if entity.version != expected_version:
                raise VersionConflict(
                    "Assignment 版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            if entity.agent_instance_id is not None:
                raise AgentAssignmentInvalid(
                    "Assignment 已有负责人",
                    details={
                        "reasons": ["ASSIGNMENT_ALREADY_CLAIMED"],
                        "agent_instance_id": entity.agent_instance_id,
                    },
                )
            if entity.status not in {ASSIGNMENT_CREATED, ASSIGNMENT_READY}:
                raise AgentAssignmentInvalid(
                    "Assignment 当前状态不可领取",
                    details={"reasons": ["ASSIGNMENT_NOT_CLAIMABLE"], "status": entity.status},
                )
            claimed = await repository.claim(
                assignment_id,
                agent_instance_id=agent_instance_id,
                allowed_statuses=frozenset({ASSIGNMENT_CREATED, ASSIGNMENT_READY}),
                to_status=ASSIGNMENT_ASSIGNED,
                expected_version=expected_version,
            )
            if not claimed:
                raise AgentAssignmentInvalid(
                    "Assignment 领取竞争失败",
                    details={"reasons": ["ASSIGNMENT_ALREADY_CLAIMED"]},
                )
            await session.refresh(entity)
            return _assignment_view(entity)

    async def replace(
        self,
        assignment_id: str,
        *,
        agent_definition_id: str,
        agent_definition_version: str,
        expected_version: int,
        authorized_by: str = AUTHORITY_ORCHESTRATOR,
    ) -> AssignmentView:
        """用新的 Assignment 接替旧负责人；旧记录保留为失败状态。"""

        old = await self.get(assignment_id)
        if old.version != expected_version:
            raise VersionConflict(
                "Assignment 版本已变化",
                details={"expected": expected_version, "actual": old.version},
            )
        if old.status in ASSIGNMENT_TERMINAL_STATUSES:
            raise AgentAssignmentInvalid(
                "已结束的 Assignment 不能替换",
                details={"reasons": ["ASSIGNMENT_TERMINAL"], "status": old.status},
            )
        if old.status in {
            ASSIGNMENT_RUNNING,
            ASSIGNMENT_STARTING,
            ASSIGNMENT_HANDOFF_PENDING,
            ASSIGNMENT_INTEGRATING,
        }:
            raise AgentAssignmentInvalid(
                "运行中的 Assignment 不能直接替换",
                details={"reasons": ["ASSIGNMENT_ACTIVE"], "status": old.status},
            )
        replacement = await self.create(
            team_id=old.team_id,
            agent_definition_id=agent_definition_id,
            agent_definition_version=agent_definition_version,
            task_id=old.task_id,
            attempt_id=old.attempt_id,
            assigned_objective=old.assigned_objective,
            authorized_by=authorized_by,
            acceptance_criteria=old.acceptance_criteria,
            required_capabilities=old.required_capabilities,
            required_tools=old.required_tools,
            permission_requirements=old.permission_requirements,
            budget=old.budget,
            priority=old.priority,
            risk_level=old.risk_level,
            scope=old.scope,
            input_reference=old.input_reference,
            parent_assignment_id=old.assignment_id,
            estimated_duration_seconds=old.estimated_duration_seconds,
            dependencies=old.dependencies,
        )
        target_status = ASSIGNMENT_BLOCKED if replacement.dependencies else ASSIGNMENT_READY
        replacement = await self.transition(
            replacement.assignment_id, target_status, expected_version=replacement.version
        )
        await self.transition(
            assignment_id, ASSIGNMENT_FAILED, expected_version=old.version
        )
        return replacement


class HandoffService:
    """Handoff 请求；执行与目标 Assignment 创建由 Orchestrator 负责。"""

    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def request(
        self,
        *,
        source_assignment_id: str,
        target_agent_definition_id: str,
        handoff_type: str,
        handoff_payload_reference: str,
        context_snapshot_id: str | None = None,
        approval_reference: str | None = None,
        requested_by_assignment_id: str | None = None,
    ) -> HandoffView:
        if handoff_type not in HANDOFF_TYPES:
            raise AgentHandoffInvalid(
                "Handoff 类型非法",
                details={"reasons": ["INVALID_HANDOFF_TYPE"], "handoff_type": handoff_type},
            )
        if not handoff_payload_reference.strip():
            raise AgentHandoffInvalid(
                "Handoff 必须引用 payload", details={"reasons": ["PAYLOAD_REQUIRED"]}
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            source = await AgentAssignmentRepository(session).get(source_assignment_id)
            if source is None:
                raise NotFoundError(
                    "源 Assignment 不存在", details={"assignment_id": source_assignment_id}
                )
            if source.status in ASSIGNMENT_TERMINAL_STATUSES:
                raise AgentHandoffInvalid(
                    "已结束的 Assignment 不能发起 Handoff",
                    details={"reasons": ["SOURCE_TERMINAL"], "status": source.status},
                )
            entity = AgentHandoffModel(
                handoff_id=_new_id("hof_"),
                source_assignment_id=source_assignment_id,
                target_assignment_id=None,
                source_agent_instance_id=source.agent_instance_id,
                target_agent_definition_id=target_agent_definition_id,
                handoff_type=handoff_type,
                handoff_payload_reference=handoff_payload_reference,
                context_snapshot_id=context_snapshot_id,
                approval_reference=approval_reference,
                status=HANDOFF_REQUESTED,
                requested_by_assignment_id=requested_by_assignment_id,
                version=1,
                created_at=now,
                completed_at=None,
            )
            await AgentHandoffRepository(session).add(entity)
            return _handoff_view(entity)

    async def get(self, handoff_id: str) -> HandoffView:
        async with self._database.session() as session:
            entity = await AgentHandoffRepository(session).get(handoff_id)
        if entity is None:
            raise NotFoundError("Handoff 不存在", details={"handoff_id": handoff_id})
        return _handoff_view(entity)

    async def list_for_source(self, assignment_id: str) -> list[HandoffView]:
        async with self._database.session() as session:
            rows = await AgentHandoffRepository(session).list_for_source(assignment_id)
        return [_handoff_view(row) for row in rows]


class CollaborationService:
    """Collaboration 创建与查询；参与者必须属于同一 Team。"""

    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def create(
        self,
        *,
        team_id: str,
        objective: str,
        participant_assignments: Iterable[str],
        shared_context_id: str | None = None,
    ) -> CollaborationView:
        objective = (objective or "").strip()
        if not objective:
            raise AgentCollaborationInvalid(
                "Collaboration 必须声明目标", details={"reasons": ["OBJECTIVE_REQUIRED"]}
            )
        participants = tuple(dict.fromkeys(participant_assignments))
        if len(participants) < 2:
            raise AgentCollaborationInvalid(
                "Collaboration 至少需要两个参与者",
                details={"reasons": ["PARTICIPANTS_REQUIRED"]},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            assignments = AgentAssignmentRepository(session)
            for assignment_id in participants:
                assignment = await assignments.get(assignment_id)
                if assignment is None or assignment.team_id != team_id:
                    raise AgentCollaborationInvalid(
                        "参与者不属于该 Team",
                        details={"reasons": ["UNKNOWN_PARTICIPANT"], "assignment_id": assignment_id},
                    )
            entity = AgentCollaborationModel(
                collaboration_id=_new_id("col_"),
                team_id=team_id,
                objective=objective,
                participant_assignments=json.dumps(list(participants)),
                shared_context_id=shared_context_id,
                status=COLLABORATION_ACTIVE,
                version=1,
                created_at=now,
                completed_at=None,
            )
            await AgentCollaborationRepository(session).add(entity)
            return _collaboration_view(entity)

    async def get(self, collaboration_id: str) -> CollaborationView:
        async with self._database.session() as session:
            entity = await AgentCollaborationRepository(session).get(collaboration_id)
        if entity is None:
            raise NotFoundError("Collaboration 不存在", details={"collaboration_id": collaboration_id})
        return _collaboration_view(entity)


__all__ = [
    "AgentTeamService",
    "AssignmentService",
    "AssignmentView",
    "CapabilityRegistryService",
    "CapabilityView",
    "CollaborationService",
    "CollaborationView",
    "HandoffService",
    "HandoffView",
    "TeamView",
]
