"""Multi-Agent Orchestrator（E7-T03 / T04 / T06）。

Orchestrator 是唯一 Assignment 分配入口：

1. 接收 Task System 授权并校验 Task/Attempt 状态；
2. 校验任务分解与验收覆盖；
3. 通过 Capability Registry 为每个子任务选择已发布的 Agent Definition；
4. 创建 Team、Assignment、依赖与成员，再进入 READY。

本文件不直接修改 Task 状态，也不启动 Agent Runtime；执行由后续 Sprint 接入。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from core.errors import (
    AgentHandoffInvalid,
    AgentOrchestrationInvalid,
    AgentOrchestrationUnauthorized,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.agent_runtime.service import DefinitionRegistryService, DefinitionView
from modules.multi_agent.capabilities import CandidateProfile, CapabilityRequirement
from modules.multi_agent.context import SharedContextService
from modules.multi_agent.decomposition import (
    ComplexityAssessment,
    DecompositionPlan,
    assess_complexity,
)
from modules.multi_agent.models import (
    ASSIGNMENT_BLOCKED,
    ASSIGNMENT_READY,
    ASSIGNMENT_TERMINAL_STATUSES,
    AUTHORITY_ORCHESTRATOR,
    HANDOFF_APPROVED,
    HANDOFF_COMPLETED,
    HANDOFF_EXECUTING,
    HANDOFF_FAILED,
    HANDOFF_VALIDATING,
    TEAM_FAILED,
    TEAM_INITIALIZING,
    TEAM_READY,
    TEAM_TERMINAL_STATUSES,
)
from modules.multi_agent.service import (
    AgentTeamService,
    AssignmentService,
    AssignmentView,
    CapabilityRegistryService,
    HandoffService,
    HandoffView,
    TeamView,
)
from modules.task.models import TERMINAL_TASK_STATUSES
from modules.task.service import AttemptService, TaskService
from modules.tool.models import RISK_RANK
from modules.tool.registry import ToolRegistryService

TASK_SYSTEM_AUTHORITY = "TASK_SYSTEM"

_ATTEMPT_RUNNABLE = frozenset({"CREATED", "STARTING", "RUNNING"})
_DEFINITION_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class OrchestratedAssignment:
    key: str
    assignment: AssignmentView


@dataclass(frozen=True, slots=True)
class HandoffExecution:
    handoff: HandoffView
    assignment: AssignmentView


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    team: TeamView
    assignments: tuple[OrchestratedAssignment, ...]
    complexity: ComplexityAssessment

    @property
    def single_agent(self) -> bool:
        return not self.complexity.requires_multi_agent


class OrchestratorService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        tasks: TaskService,
        attempts: AttemptService,
        definitions: DefinitionRegistryService,
        capabilities: CapabilityRegistryService,
        teams: AgentTeamService,
        assignments: AssignmentService,
        handoffs: HandoffService,
        contexts: SharedContextService,
        tools: ToolRegistryService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._tasks = tasks
        self._attempts = attempts
        self._definitions = definitions
        self._capabilities = capabilities
        self._teams = teams
        self._assignments = assignments
        self._handoffs = handoffs
        self._contexts = contexts
        self._tools = tools
        self._clock = clock

    async def orchestrate(
        self,
        *,
        task_id: str,
        attempt_id: str,
        plan: DecompositionPlan,
        authorized_by: str = TASK_SYSTEM_AUTHORITY,
    ) -> OrchestrationResult:
        if authorized_by != TASK_SYSTEM_AUTHORITY:
            raise AgentOrchestrationUnauthorized(
                "Orchestrator 需要 Task System 授权",
                details={"reasons": ["TASK_SYSTEM_REQUIRED"], "authorized_by": authorized_by},
            )

        validated = plan.validate()
        complexity = assess_complexity(plan)
        task = await self._tasks.get(task_id)
        attempt = await self._attempts.get(attempt_id)
        if attempt.task_id != task_id:
            raise AgentOrchestrationInvalid(
                "Attempt 不属于该 Task",
                details={"reasons": ["ATTEMPT_TASK_MISMATCH"], "task_id": task_id},
            )
        if task.status in TERMINAL_TASK_STATUSES:
            raise AgentOrchestrationInvalid(
                "Task 已结束，不能创建 Team",
                details={"reasons": ["TASK_NOT_RUNNABLE"], "status": task.status},
            )
        if attempt.status not in _ATTEMPT_RUNNABLE:
            raise AgentOrchestrationInvalid(
                "Attempt 当前状态不可编排",
                details={"reasons": ["ATTEMPT_NOT_RUNNABLE"], "status": attempt.status},
            )
        await self._ensure_no_active_team(task_id, attempt_id)

        definitions = await self._active_definitions()
        tool_names = await self._tool_names()
        profiles = [self._profile(item, tool_names) for item in definitions]
        by_id = {item.definition_id: item for item in definitions}
        selected: dict[str, DefinitionView] = {}
        for spec in validated:
            outcome = await self._capabilities.match(
                CapabilityRequirement(
                    capabilities=spec.capabilities,
                    required_tools=spec.required_tools,
                    required_risk_level=spec.risk_level,
                ),
                profiles,
            )
            best = outcome.best
            if best is None:
                raise AgentOrchestrationInvalid(
                    "没有满足子任务能力的 Agent",
                    details={
                        "reasons": ["NO_CANDIDATE"],
                        "subtask": spec.key,
                        "capabilities": list(spec.capabilities),
                    },
                )
            selected[spec.key] = by_id[best.definition_id]

        team = await self._teams.create(
            task_id=task_id,
            attempt_id=attempt_id,
            project_id=task.project_id,
        )
        try:
            team = await self._teams.transition(
                team.team_id, TEAM_INITIALIZING, expected_version=team.version
            )
            created = await self._create_assignments(
                team=team,
                attempt_id=attempt_id,
                task_id=task_id,
                validated=validated,
                selected=selected,
            )
            team = await self._teams.transition(
                team.team_id, TEAM_READY, expected_version=team.version
            )
        except Exception:
            await self._fail_team(team)
            raise
        return OrchestrationResult(
            team=team,
            assignments=tuple(created),
            complexity=complexity,
        )

    async def execute_handoff(
        self,
        handoff_id: str,
        *,
        authorized_by: str = TASK_SYSTEM_AUTHORITY,
    ) -> HandoffExecution:
        """校验并执行已请求的 Handoff；只有 Orchestrator 能落地目标 Assignment。"""

        if authorized_by != TASK_SYSTEM_AUTHORITY:
            raise AgentOrchestrationUnauthorized(
                "Handoff 需要 Task System 授权",
                details={"reasons": ["TASK_SYSTEM_REQUIRED"], "authorized_by": authorized_by},
            )
        handoff = await self._handoffs.get(handoff_id)
        handoff = await self._handoffs.transition(
            handoff_id, HANDOFF_VALIDATING, expected_version=handoff.version
        )
        try:
            source = await self._assignments.get(handoff.source_assignment_id)
            if source.status in ASSIGNMENT_TERMINAL_STATUSES:
                raise AgentHandoffInvalid(
                    "源 Assignment 已结束，不能执行 Handoff",
                    details={"reasons": ["SOURCE_TERMINAL"], "status": source.status},
                )
            team = await self._teams.get(source.team_id)
            if team.status in TEAM_TERMINAL_STATUSES:
                raise AgentHandoffInvalid(
                    "Team 已结束，不能执行 Handoff",
                    details={"reasons": ["TEAM_TERMINAL"], "status": team.status},
                )
            target_definition = await self._definitions.get(handoff.target_agent_definition_id)
            if target_definition.status != "ACTIVE":
                raise AgentHandoffInvalid(
                    "目标 Agent Definition 未发布",
                    details={
                        "reasons": ["TARGET_NOT_ACTIVE"],
                        "status": target_definition.status,
                    },
                )
            missing_capabilities = set(source.required_capabilities) - set(
                target_definition.capabilities
            )
            if missing_capabilities:
                raise AgentHandoffInvalid(
                    "目标 Agent 缺少所需能力",
                    details={
                        "reasons": ["CAPABILITY_MISMATCH"],
                        "capabilities": sorted(missing_capabilities),
                    },
                )
            tool_names = await self._tool_names()
            available_tools = {
                tool_names.get(tool_id, tool_id) for tool_id in target_definition.tool_whitelist
            }
            missing_tools = set(source.required_tools) - available_tools
            if missing_tools:
                raise AgentHandoffInvalid(
                    "目标 Agent 缺少所需工具",
                    details={"reasons": ["TOOL_MISMATCH"], "tools": sorted(missing_tools)},
                )
            if RISK_RANK[target_definition.permission_ceiling] < RISK_RANK[source.risk_level]:
                raise AgentHandoffInvalid(
                    "目标 Agent 权限上限不足",
                    details={
                        "reasons": ["PERMISSION_CEILING"],
                        "required": source.risk_level,
                        "ceiling": target_definition.permission_ceiling,
                    },
                )
            if handoff.context_snapshot_id:
                context = await self._contexts.get(handoff.context_snapshot_id)
                if context.team_id != team.team_id:
                    raise AgentHandoffInvalid(
                        "移交 Context 不属于该 Team",
                        details={"reasons": ["CONTEXT_SCOPE_MISMATCH"]},
                    )
            target = await self._assignments.create(
                team_id=team.team_id,
                agent_definition_id=target_definition.definition_id,
                agent_definition_version=target_definition.current_version or "1.0.0",
                task_id=source.task_id,
                attempt_id=source.attempt_id,
                assigned_objective=source.assigned_objective,
                authorized_by=AUTHORITY_ORCHESTRATOR,
                acceptance_criteria=source.acceptance_criteria,
                required_capabilities=source.required_capabilities,
                required_tools=source.required_tools,
                permission_requirements=source.permission_requirements,
                budget=source.budget,
                priority=source.priority,
                risk_level=source.risk_level,
                scope=source.scope,
                input_reference=handoff.context_snapshot_id or source.input_reference,
                parent_assignment_id=source.assignment_id,
                estimated_duration_seconds=source.estimated_duration_seconds,
            )
            target = await self._assignments.transition(
                target.assignment_id, ASSIGNMENT_READY, expected_version=target.version
            )
            await self._teams.add_member(team.team_id, target.assignment_id)
            handoff = await self._handoffs.transition(
                handoff_id,
                HANDOFF_APPROVED,
                expected_version=handoff.version,
                target_assignment_id=target.assignment_id,
            )
            handoff = await self._handoffs.transition(
                handoff_id, HANDOFF_EXECUTING, expected_version=handoff.version
            )
            handoff = await self._handoffs.transition(
                handoff_id, HANDOFF_COMPLETED, expected_version=handoff.version
            )
        except Exception:
            await self._fail_handoff(handoff_id)
            raise
        return HandoffExecution(handoff=handoff, assignment=target)

    async def _fail_handoff(self, handoff_id: str) -> None:
        try:
            current = await self._handoffs.get(handoff_id)
            await self._handoffs.transition(
                handoff_id, HANDOFF_FAILED, expected_version=current.version
            )
        except Exception:  # noqa: BLE001 - 失败标记不能覆盖原始异常
            return

    async def _create_assignments(
        self,
        *,
        team: TeamView,
        task_id: str,
        attempt_id: str,
        validated,
        selected: dict[str, DefinitionView],
    ) -> list[OrchestratedAssignment]:
        created: list[OrchestratedAssignment] = []
        assignment_ids: dict[str, str] = {}
        for spec in validated:
            definition = selected[spec.key]
            dependency_ids = tuple(assignment_ids[key] for key in spec.dependencies)
            assignment = await self._assignments.create(
                team_id=team.team_id,
                agent_definition_id=definition.definition_id,
                agent_definition_version=definition.current_version or "1.0.0",
                task_id=task_id,
                attempt_id=attempt_id,
                assigned_objective=spec.objective,
                authorized_by=AUTHORITY_ORCHESTRATOR,
                acceptance_criteria=spec.acceptance_criteria,
                required_capabilities=spec.capabilities,
                required_tools=spec.required_tools,
                permission_requirements=spec.permission_requirements,
                budget=spec.budget,
                priority=spec.priority,
                risk_level=spec.risk_level,
                scope=spec.scope,
                input_reference=spec.input_reference,
                estimated_duration_seconds=spec.estimated_duration_seconds,
                dependencies=dependency_ids,
            )
            target_status = ASSIGNMENT_BLOCKED if dependency_ids else ASSIGNMENT_READY
            assignment = await self._assignments.transition(
                assignment.assignment_id, target_status, expected_version=assignment.version
            )
            await self._teams.add_member(team.team_id, assignment.assignment_id)
            assignment_ids[spec.key] = assignment.assignment_id
            created.append(OrchestratedAssignment(key=spec.key, assignment=assignment))
        return created

    async def _active_definitions(self) -> list[DefinitionView]:
        page = await self._definitions.list(
            status="ACTIVE", limit=_DEFINITION_PAGE_SIZE, offset=0
        )
        return list(page["items"])

    def _profile(self, definition: DefinitionView, tool_names: dict[str, str]) -> CandidateProfile:
        return CandidateProfile(
            definition_id=definition.definition_id,
            name=definition.name,
            enabled=True,
            capabilities=definition.capabilities,
            permission_ceiling=definition.permission_ceiling,
            available_tools=frozenset(
                tool_names.get(tool_id, tool_id) for tool_id in definition.tool_whitelist
            ),
            current_load=0,
            max_concurrency=max(definition.max_concurrency, 1),
            success_rate=0.0,
            estimated_cost=0.0,
        )

    async def _tool_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        offset = 0
        while True:
            tools = await self._tools.list(enabled=True, limit=_DEFINITION_PAGE_SIZE, offset=offset)
            names.update({tool.tool_id: tool.name for tool in tools})
            if len(tools) < _DEFINITION_PAGE_SIZE:
                return names
            offset += len(tools)

    async def _ensure_no_active_team(self, task_id: str, attempt_id: str) -> None:
        page = await self._teams.list(task_id=task_id, limit=10)
        for item in page["items"]:
            if item.attempt_id == attempt_id and item.status not in TEAM_TERMINAL_STATUSES:
                raise AgentOrchestrationInvalid(
                    "该 Attempt 已有活动 Team",
                    details={"reasons": ["TEAM_ALREADY_EXISTS"], "team_id": item.team_id},
                )

    async def _fail_team(self, team: TeamView) -> None:
        try:
            current = await self._teams.get(team.team_id)
            if current.status in TEAM_TERMINAL_STATUSES:
                return
            await self._teams.transition(
                team.team_id, TEAM_FAILED, expected_version=current.version
            )
        except Exception:  # noqa: BLE001 - 失败标记不能覆盖原始异常
            return


__all__ = [
    "TASK_SYSTEM_AUTHORITY",
    "HandoffExecution",
    "OrchestratedAssignment",
    "OrchestrationResult",
    "OrchestratorService",
]
