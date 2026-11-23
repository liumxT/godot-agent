"""Multi-Agent 接口（E7-T20）：Team、Assignment、Handoff、Capability、Conflict。

所有接口都要求认证，并按 Project Scope 授权。Team 创建与 Handoff 执行仍由
Orchestrator 统一落地；Agent 不能通过本 API 绕过 Orchestrator 创建 Assignment。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import (
    authorize_project_action,
    enforce_rate_limit,
    require_authenticated,
)
from app.schemas.multi_agent import (
    AgentTeamCreateRequest,
    AssignmentCancelRequest,
    ConflictResolveRequest,
    HandoffAcceptRequest,
    HandoffRejectRequest,
)
from core.errors import InvalidStateTransition, VersionConflict
from core.security.principal import (
    ACTION_E7_MULTI_AGENT_MANAGE,
    ACTION_E7_MULTI_AGENT_READ,
)
from modules.multi_agent.conflicts import ConflictService
from modules.multi_agent.decomposition import DecompositionPlan, SubtaskSpec
from modules.multi_agent.models import (
    ASSIGNMENT_CANCELLED,
    ASSIGNMENT_COMPLETED,
    HANDOFF_COMPLETED,
    HANDOFF_REJECTED,
)
from modules.multi_agent.observability import TeamObservabilityService, to_jsonable
from modules.multi_agent.orchestrator import OrchestratorService
from modules.multi_agent.service import (
    AgentTeamService,
    AssignmentService,
    CapabilityRegistryService,
    HandoffService,
)
from modules.task.service import TaskService

router = APIRouter(
    tags=["multi-agent"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足"},
    404: {"description": "Team / Assignment / Handoff / Conflict / Capability 不存在"},
    409: {"description": "状态迁移冲突或版本已变化"},
    422: {"description": "请求参数校验失败"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


def _teams(request: Request) -> AgentTeamService:
    return request.app.state.services.get("agent_team_service", AgentTeamService)


def _assignments(request: Request) -> AssignmentService:
    return request.app.state.services.get("assignment_service", AssignmentService)


def _handoffs(request: Request) -> HandoffService:
    return request.app.state.services.get("handoff_service", HandoffService)


def _capabilities(request: Request) -> CapabilityRegistryService:
    return request.app.state.services.get(
        "capability_registry_service", CapabilityRegistryService
    )


def _conflicts(request: Request) -> ConflictService:
    return request.app.state.services.get("conflict_service", ConflictService)


def _observability(request: Request) -> TeamObservabilityService:
    return request.app.state.services.get(
        "team_observability_service", TeamObservabilityService
    )


def _orchestrator(request: Request) -> OrchestratorService:
    return request.app.state.services.get("orchestrator_service", OrchestratorService)


def _tasks(request: Request) -> TaskService:
    return request.app.state.services.get("task_service", TaskService)


async def _authorize_team_read(request: Request, team_id: str) -> str:
    team = await _teams(request).get(team_id)
    await authorize_project_action(request, team.project_id, ACTION_E7_MULTI_AGENT_READ)
    return team.project_id


async def _authorize_assignment(
    request: Request, assignment_id: str, action: str
) -> tuple[Any, str]:
    assignment = await _assignments(request).get(assignment_id)
    team = await _teams(request).get(assignment.team_id)
    await authorize_project_action(request, team.project_id, action)
    return assignment, team.project_id


async def _authorize_handoff(request: Request, handoff_id: str, action: str) -> tuple[Any, str]:
    handoff = await _handoffs(request).get(handoff_id)
    assignment = await _assignments(request).get(handoff.source_assignment_id)
    team = await _teams(request).get(assignment.team_id)
    await authorize_project_action(request, team.project_id, action)
    return handoff, team.project_id


@router.get(
    "/agent-teams",
    summary="列出 Agent Team",
    description="按项目/任务过滤 Team；需要项目读取权限。",
    responses=_ERRORS,
)
async def list_agent_teams(
    request: Request,
    project_id: str = Query(min_length=1),
    task_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    await authorize_project_action(request, project_id, ACTION_E7_MULTI_AGENT_READ)
    page = await _teams(request).list(
        project_id=project_id, task_id=task_id, status=status, limit=limit, offset=offset
    )
    return {
        "items": [to_jsonable(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.post(
    "/agent-teams",
    summary="创建 Agent Team",
    description="由 Orchestrator 分解子任务、匹配 Agent 并创建 Assignment；同一 Attempt 不允许重复活动 Team。",
    status_code=201,
    responses=_ERRORS,
)
async def create_agent_team(
    request: Request, payload: AgentTeamCreateRequest
) -> dict[str, Any]:
    task = await _tasks(request).get(payload.task_id)
    await authorize_project_action(request, task.project_id, ACTION_E7_MULTI_AGENT_MANAGE)
    plan = DecompositionPlan(
        task_objective=task.title,
        acceptance_criteria=tuple(payload.acceptance_criteria)
        or tuple(criterion for item in payload.subtasks for criterion in item.acceptance_criteria),
        subtasks=tuple(
            SubtaskSpec(
                key=item.key,
                objective=item.objective,
                capabilities=tuple(item.capabilities),
                acceptance_criteria=tuple(item.acceptance_criteria),
                required_tools=tuple(item.required_tools),
                dependencies=tuple(item.dependencies),
                risk_level=item.required_risk_level,
                estimated_duration_seconds=item.estimated_duration_seconds,
            )
            for item in payload.subtasks
        ),
    )
    result = await _orchestrator(request).orchestrate(
        task_id=payload.task_id,
        attempt_id=payload.attempt_id,
        plan=plan,
    )
    return {
        "team": to_jsonable(result.team),
        "assignments": [
            {"key": item.key, "assignment": to_jsonable(item.assignment)}
            for item in result.assignments
        ],
        "complexity": to_jsonable(result.complexity),
    }


@router.get(
    "/agent-teams/{team_id}",
    summary="获取 Agent Team 概览",
    description="返回 Team、成员、Assignment、Handoff、冲突、集成、预算与依赖图。",
    responses=_ERRORS,
)
async def get_agent_team(request: Request, team_id: str) -> dict[str, Any]:
    await _authorize_team_read(request, team_id)
    return await _observability(request).team_dashboard(team_id)


@router.get(
    "/agent-teams/{team_id}/members",
    summary="列出 Agent Team 成员",
    responses=_ERRORS,
)
async def list_agent_team_members(request: Request, team_id: str) -> dict[str, Any]:
    await _authorize_team_read(request, team_id)
    members = await _teams(request).get_members(team_id)
    return {"items": [to_jsonable(item) for item in members]}


@router.get(
    "/agent-teams/{team_id}/events",
    summary="列出 Agent Team 事件",
    description="按时间顺序返回 Handoff、冲突与集成事件。",
    responses=_ERRORS,
)
async def list_agent_team_events(request: Request, team_id: str) -> dict[str, Any]:
    await _authorize_team_read(request, team_id)
    return {"items": await _observability(request).team_events(team_id)}


@router.get(
    "/agent-teams/{team_id}/graph",
    summary="获取 Agent Team 依赖图",
    responses=_ERRORS,
)
async def get_agent_team_graph(request: Request, team_id: str) -> dict[str, Any]:
    await _authorize_team_read(request, team_id)
    return await _observability(request).team_graph(team_id)


@router.get(
    "/agent-assignments/{assignment_id}",
    summary="获取 Agent Assignment 详情",
    description="返回 Assignment、依赖状态、资源锁、Handoff 与评审。",
    responses=_ERRORS,
)
async def get_agent_assignment(request: Request, assignment_id: str) -> dict[str, Any]:
    await _authorize_assignment(request, assignment_id, ACTION_E7_MULTI_AGENT_READ)
    return await _observability(request).assignment_dashboard(assignment_id)


@router.get(
    "/agent-assignments/{assignment_id}/result",
    summary="获取 Agent Assignment 结果",
    description="仅已完成的 Assignment 有可读取结果；未完成返回 409。",
    responses=_ERRORS,
)
async def get_agent_assignment_result(
    request: Request, assignment_id: str
) -> dict[str, Any]:
    assignment, _ = await _authorize_assignment(
        request, assignment_id, ACTION_E7_MULTI_AGENT_READ
    )
    if assignment.status != ASSIGNMENT_COMPLETED or not assignment.output_reference:
        raise InvalidStateTransition(
            "Assignment 尚未产出可读取结果",
            details={"assignment_id": assignment_id, "status": assignment.status},
        )
    return {
        "assignment_id": assignment.assignment_id,
        "status": assignment.status,
        "output_reference": assignment.output_reference,
        "acceptance_criteria": list(assignment.acceptance_criteria),
        "agent_definition_id": assignment.agent_definition_id,
        "completed_at": to_jsonable(assignment.completed_at),
    }


@router.post(
    "/agent-assignments/{assignment_id}/cancel",
    summary="取消 Agent Assignment",
    description="取消必须提供原因与当前版本，避免覆盖并发修改。",
    responses=_ERRORS,
)
async def cancel_agent_assignment(
    request: Request, assignment_id: str, payload: AssignmentCancelRequest
) -> dict[str, Any]:
    assignment, _ = await _authorize_assignment(
        request, assignment_id, ACTION_E7_MULTI_AGENT_MANAGE
    )
    if assignment.status == ASSIGNMENT_CANCELLED:
        return to_jsonable(assignment)
    cancelled = await _assignments(request).transition(
        assignment_id, ASSIGNMENT_CANCELLED, expected_version=payload.expected_version
    )
    return to_jsonable(cancelled)


@router.get(
    "/agent-handoffs",
    summary="列出 Agent Handoff",
    description="按 Team 过滤 Handoff；需要项目读取权限。",
    responses=_ERRORS,
)
async def list_agent_handoffs(
    request: Request, team_id: str = Query(min_length=1)
) -> dict[str, Any]:
    await _authorize_team_read(request, team_id)
    handoffs = await _observability(request).team_dashboard(team_id)
    return {"items": handoffs["handoffs"]}


@router.get(
    "/agent-handoffs/{handoff_id}",
    summary="获取 Agent Handoff",
    responses=_ERRORS,
)
async def get_agent_handoff(request: Request, handoff_id: str) -> dict[str, Any]:
    handoff, _ = await _authorize_handoff(
        request, handoff_id, ACTION_E7_MULTI_AGENT_READ
    )
    return to_jsonable(handoff)


@router.post(
    "/agent-handoffs/{handoff_id}/accept",
    summary="接受并执行 Agent Handoff",
    description="由 Orchestrator 校验并创建目标 Assignment；重复接受返回已完成记录。",
    responses=_ERRORS,
)
async def accept_agent_handoff(
    request: Request, handoff_id: str, payload: HandoffAcceptRequest
) -> dict[str, Any]:
    handoff, _ = await _authorize_handoff(
        request, handoff_id, ACTION_E7_MULTI_AGENT_MANAGE
    )
    if handoff.status == HANDOFF_COMPLETED:
        return {"handoff": to_jsonable(handoff)}
    if handoff.version != payload.expected_version:
        raise VersionConflict(
            "Handoff 版本已变化",
            details={"expected": payload.expected_version, "actual": handoff.version},
        )
    execution = await _orchestrator(request).execute_handoff(handoff_id)
    return {
        "handoff": to_jsonable(execution.handoff),
        "assignment": to_jsonable(execution.assignment),
    }


@router.post(
    "/agent-handoffs/{handoff_id}/reject",
    summary="拒绝 Agent Handoff",
    description="拒绝必须记录原因；已拒绝的 Handoff 直接返回。",
    responses=_ERRORS,
)
async def reject_agent_handoff(
    request: Request, handoff_id: str, payload: HandoffRejectRequest
) -> dict[str, Any]:
    handoff, _ = await _authorize_handoff(
        request, handoff_id, ACTION_E7_MULTI_AGENT_MANAGE
    )
    if handoff.status == HANDOFF_REJECTED:
        return to_jsonable(handoff)
    rejected = await _handoffs(request).transition(
        handoff_id,
        HANDOFF_REJECTED,
        expected_version=payload.expected_version,
        rejection_reason=payload.reason,
    )
    return to_jsonable(rejected)


@router.get(
    "/agent-capabilities",
    summary="列出 Agent 能力",
    description="能力目录为全局数据；仍要求项目读取权限以限制可见范围。",
    responses=_ERRORS,
)
async def list_agent_capabilities(
    request: Request,
    project_id: str = Query(min_length=1),
    category: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    await authorize_project_action(request, project_id, ACTION_E7_MULTI_AGENT_READ)
    page = await _capabilities(request).list(
        category=category, enabled=enabled, limit=limit, offset=offset
    )
    return {
        "items": [to_jsonable(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/agent-capabilities/{name}",
    summary="获取 Agent 能力",
    responses=_ERRORS,
)
async def get_agent_capability(
    request: Request, name: str, project_id: str = Query(min_length=1)
) -> dict[str, Any]:
    await authorize_project_action(request, project_id, ACTION_E7_MULTI_AGENT_READ)
    return to_jsonable(await _capabilities(request).get_by_name(name))


@router.get(
    "/agent-conflicts",
    summary="列出 Agent 冲突",
    responses=_ERRORS,
)
async def list_agent_conflicts(
    request: Request, team_id: str = Query(min_length=1)
) -> dict[str, Any]:
    await _authorize_team_read(request, team_id)
    conflicts = await _conflicts(request).list_for_team(team_id)
    return {"items": [to_jsonable(item) for item in conflicts]}


@router.get(
    "/agent-conflicts/{conflict_id}",
    summary="获取 Agent 冲突",
    responses=_ERRORS,
)
async def get_agent_conflict(request: Request, conflict_id: str) -> dict[str, Any]:
    conflict = await _conflicts(request).get(conflict_id)
    team = await _teams(request).get(conflict.team_id)
    await authorize_project_action(request, team.project_id, ACTION_E7_MULTI_AGENT_READ)
    return to_jsonable(conflict)


@router.post(
    "/agent-conflicts/{conflict_id}/resolve",
    summary="解决 Agent 冲突",
    description="已升级冲突必须使用 USER_DECISION 策略；解决必须提供引用。",
    responses=_ERRORS,
)
async def resolve_agent_conflict(
    request: Request, conflict_id: str, payload: ConflictResolveRequest
) -> dict[str, Any]:
    conflict = await _conflicts(request).get(conflict_id)
    team = await _teams(request).get(conflict.team_id)
    await authorize_project_action(request, team.project_id, ACTION_E7_MULTI_AGENT_MANAGE)
    principal = getattr(request.state, "principal", None)
    resolved = await _conflicts(request).resolve(
        conflict_id,
        strategy=payload.strategy,
        resolution_reference=payload.resolution_reference,
        resolved_by=principal.client_id if principal is not None else "unknown",
    )
    return to_jsonable(resolved)
