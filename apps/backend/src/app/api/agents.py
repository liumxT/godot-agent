"""Agent 接口（E6-T17）：定义、实例、执行、事件、指标与追踪。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import (
    authorize_project_action,
    enforce_rate_limit,
    require_authenticated,
)
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.agent_runtime import (
    AgentDefinitionCreateRequest,
    AgentInstanceActionRequest,
    AgentInstanceCreateRequest,
    AgentResumeRequest,
)
from core.errors import NotFoundError, PermissionDenied
from core.security.principal import ACTION_E6_AGENT_MANAGE, ACTION_E6_AGENT_READ
from core.security.tokens import isoformat
from modules.agent_runtime.control import AgentControlService
from modules.agent_runtime.events import AgentEventService, format_event
from modules.agent_runtime.execution import AgentExecutionService, ExecutionView
from modules.agent_runtime.instance import (
    AgentInstanceService,
    ConfigSnapshotView,
    InstanceView,
)
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.observability import AgentObservabilityService
from modules.agent_runtime.planning import PlanningService, PlanView, StepView
from modules.agent_runtime.service import DefinitionRegistryService, DefinitionView
from modules.task.service import TaskService

router = APIRouter(
    tags=["agents"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    404: {"description": "Agent 定义、实例、执行或计划不存在（NOT_FOUND）"},
    409: {"description": "状态不允许该操作或恢复校验失败（INVALID_STATE_TRANSITION）"},
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


def _definitions(request: Request) -> DefinitionRegistryService:
    return request.app.state.services.get(
        "agent_definition_registry_service", DefinitionRegistryService
    )


def _instances(request: Request) -> AgentInstanceService:
    return request.app.state.services.get("agent_instance_service", AgentInstanceService)


def _lifecycle(request: Request) -> AgentLifecycleService:
    return request.app.state.services.get("agent_lifecycle_service", AgentLifecycleService)


def _executions(request: Request) -> AgentExecutionService:
    return request.app.state.services.get("agent_execution_service", AgentExecutionService)


def _planning(request: Request) -> PlanningService:
    return request.app.state.services.get("agent_planning_service", PlanningService)


def _events(request: Request) -> AgentEventService:
    return request.app.state.services.get("agent_event_service", AgentEventService)


def _control(request: Request) -> AgentControlService:
    return request.app.state.services.get("agent_control_service", AgentControlService)


def _observability(request: Request) -> AgentObservabilityService:
    return request.app.state.services.get("agent_observability_service", AgentObservabilityService)


def _tasks(request: Request) -> TaskService:
    return request.app.state.services.get("task_service", TaskService)


async def _authorize_scope(request: Request, project_id: str | None, action: str) -> None:
    """项目级接口按 project_id 授权；管理员可执行全局查询。"""

    if project_id:
        await authorize_project_action(request, project_id, action)
        return
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.role != "admin":
        raise PermissionDenied(
            "该接口需要 project_id", details={"action": action, "reason": "PROJECT_REQUIRED"}
        )


async def _authorized_instance(request: Request, instance_id: str, action: str) -> InstanceView:
    view = await _instances(request).get(instance_id)
    await authorize_project_action(request, view.project_id, action)
    principal = getattr(request.state, "principal", None)
    if (
        principal is not None
        and principal.role != "admin"
        and view.client_id
        and principal.client_id != view.client_id
    ):
        raise PermissionDenied(
            "Instance 不属于当前客户端",
            details={"instance_id": instance_id, "reason": "INSTANCE_OWNERSHIP_DENIED"},
        )
    return view


async def _authorized_execution(
    request: Request, execution_id: str, action: str
) -> tuple[ExecutionView, InstanceView]:
    execution = await _executions(request).get(execution_id)
    instance = await _authorized_instance(request, execution.agent_instance_id, action)
    return execution, instance


def _optional(value: datetime | None) -> str | None:
    return isoformat(value) if value is not None else None


def _format_definition(view: DefinitionView) -> dict[str, Any]:
    return {
        "definition_id": view.definition_id,
        "name": view.name,
        "description": view.description,
        "category": view.category,
        "status": view.status,
        "current_version": view.current_version,
        "capabilities": list(view.capabilities),
        "model_policy_id": view.model_policy_id,
        "prompt_profile_id": view.prompt_profile_id,
        "prompt_version": view.prompt_version,
        "context_profile_id": view.context_profile_id,
        "context_profile_version": view.context_profile_version,
        "tool_whitelist": list(view.tool_whitelist),
        "permission_ceiling": view.permission_ceiling,
        "budget_profile_id": view.budget_profile_id,
        "budget": view.budget,
        "max_concurrency": view.max_concurrency,
        "version": view.version,
        "created_at": isoformat(view.created_at),
        "updated_at": isoformat(view.updated_at),
    }


def _format_instance(view: InstanceView) -> dict[str, Any]:
    return {
        "instance_id": view.instance_id,
        "agent_definition_id": view.agent_definition_id,
        "agent_version": view.agent_version,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "project_id": view.project_id,
        "session_id": view.session_id,
        "client_id": view.client_id,
        "status": view.status,
        "config_snapshot_id": view.config_snapshot_id,
        "version": view.version,
        "termination_reason": view.termination_reason,
        "created_at": isoformat(view.created_at),
        "updated_at": isoformat(view.updated_at),
        "started_at": _optional(view.started_at),
        "completed_at": _optional(view.completed_at),
    }


def _format_snapshot(view: ConfigSnapshotView) -> dict[str, Any]:
    return {
        "snapshot_id": view.snapshot_id,
        "agent_definition_id": view.agent_definition_id,
        "agent_version": view.agent_version,
        "project_id": view.project_id,
        "session_id": view.session_id,
        "client_id": view.client_id,
        "model_policy_id": view.model_policy_id,
        "model_id": view.model_id,
        "prompt_profile_id": view.prompt_profile_id,
        "prompt_version": view.prompt_version,
        "context_profile_id": view.context_profile_id,
        "context_profile_version": view.context_profile_version,
        "tool_whitelist": list(view.tool_whitelist),
        "permission_ceiling": view.permission_ceiling,
        "budget": view.budget,
        "runtime_policy_version": view.runtime_policy_version,
        "content_hash": view.content_hash,
        "created_at": isoformat(view.created_at),
    }


def _format_execution(view: ExecutionView) -> dict[str, Any]:
    return {
        "execution_id": view.execution_id,
        "agent_instance_id": view.agent_instance_id,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "execution_number": view.execution_number,
        "status": view.status,
        "last_checkpoint_id": view.last_checkpoint_id,
        "termination_reason": view.termination_reason,
        "budget_usage": view.budget_usage,
        "version": view.version,
        "started_at": _optional(view.started_at),
        "ended_at": _optional(view.ended_at),
        "created_at": isoformat(view.created_at),
    }


def _format_step(view: StepView) -> dict[str, Any]:
    return {
        "step_id": view.step_id,
        "plan_id": view.plan_id,
        "execution_id": view.execution_id,
        "step_number": view.step_number,
        "step_type": view.step_type,
        "description": view.description,
        "status": view.status,
        "dependencies": list(view.dependencies),
        "output_reference": view.output_reference,
        "tool_execution_id": view.tool_execution_id,
        "retry_count": view.retry_count,
        "version": view.version,
        "started_at": _optional(view.started_at),
        "completed_at": _optional(view.completed_at),
        "created_at": isoformat(view.created_at),
    }


def _format_plan(view: PlanView) -> dict[str, Any]:
    return {
        "plan_id": view.plan_id,
        "agent_instance_id": view.agent_instance_id,
        "execution_id": view.execution_id,
        "plan_version": view.plan_version,
        "objective": view.objective,
        "status": view.status,
        "supersedes_plan_id": view.supersedes_plan_id,
        "version": view.version,
        "steps": [_format_step(step) for step in view.steps],
        "created_at": isoformat(view.created_at),
    }


# ---- Definition ----


@router.get(
    "/agents/definitions",
    summary="列出 Agent 定义",
    description="按状态列出 Agent Definition；非管理员需传 project_id 以完成授权。",
    responses=_ERRORS,
)
async def list_agent_definitions(
    request: Request,
    project_id: str | None = Query(default=None, pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await _authorize_scope(request, project_id, ACTION_E6_AGENT_READ)
    page = await _definitions(request).list(status=status_filter, limit=limit, offset=offset)
    return {
        "items": [_format_definition(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/agents/definitions/{definition_id}",
    summary="查询 Agent 定义",
    description="返回 Agent Definition 及其冻结预算与工具白名单。",
    responses=_ERRORS,
)
async def get_agent_definition(
    definition_id: str,
    request: Request,
    project_id: str | None = Query(default=None, pattern=PROJECT_ID_PATTERN),
) -> dict:
    await _authorize_scope(request, project_id, ACTION_E6_AGENT_READ)
    return _format_definition(await _definitions(request).get(definition_id))


@router.get(
    "/agents/definitions/{definition_id}/versions",
    summary="列出 Agent 定义版本",
    description="返回已发布版本及内容哈希，用于审计与回溯。",
    responses=_ERRORS,
)
async def list_agent_definition_versions(
    definition_id: str,
    request: Request,
    project_id: str | None = Query(default=None, pattern=PROJECT_ID_PATTERN),
) -> dict:
    await _authorize_scope(request, project_id, ACTION_E6_AGENT_READ)
    versions = await _definitions(request).list_versions(definition_id)
    return {
        "items": [
            {
                "version_id": item.version_id,
                "definition_id": item.definition_id,
                "version": item.version,
                "content_hash": item.content_hash,
                "published_at": isoformat(item.published_at),
                "published_by": item.published_by,
                "compatibility_metadata": item.compatibility_metadata,
            }
            for item in versions
        ]
    }


@router.post(
    "/agents/definitions",
    summary="创建 Agent 定义",
    description="创建草稿定义；冻结 Prompt、Model Policy、工具白名单、权限上限与预算。",
    responses=_ERRORS,
)
async def create_agent_definition(
    payload: AgentDefinitionCreateRequest,
    request: Request,
    project_id: str | None = Query(default=None, pattern=PROJECT_ID_PATTERN),
) -> dict:
    await _authorize_scope(request, project_id, ACTION_E6_AGENT_MANAGE)
    principal = request.state.principal
    view = await _definitions(request).create(
        name=payload.name,
        description=payload.description,
        category=payload.category,
        model_policy_id=payload.model_policy_id,
        prompt_profile_id=payload.prompt_profile_id,
        prompt_version=payload.prompt_version,
        context_profile_id=payload.context_profile_id,
        context_profile_version=payload.context_profile_version,
        capabilities=tuple(payload.capabilities),
        tool_whitelist=tuple(payload.tool_whitelist),
        permission_ceiling=payload.permission_ceiling,
        budget_profile_id=payload.budget_profile_id,
        budget=payload.budget,
        max_concurrency=payload.max_concurrency,
        created_by=principal.client_id,
    )
    return _format_definition(view)


@router.post(
    "/agents/definitions/{definition_id}/publish",
    summary="发布 Agent 定义",
    description="发布当前定义版本并激活；发布后配置不可原地修改。",
    responses=_ERRORS,
)
async def publish_agent_definition(
    definition_id: str,
    request: Request,
    project_id: str | None = Query(default=None, pattern=PROJECT_ID_PATTERN),
) -> dict:
    await _authorize_scope(request, project_id, ACTION_E6_AGENT_MANAGE)
    principal = request.state.principal
    await _definitions(request).publish(definition_id, published_by=principal.client_id)
    return _format_definition(await _definitions(request).get(definition_id))


# ---- Instance ----


@router.get(
    "/agents/instances",
    summary="列出 Agent 实例",
    description="按项目列出 Agent 实例，可按状态过滤。",
    responses=_ERRORS,
)
async def list_agent_instances(
    request: Request,
    project_id: str | None = Query(default=None, pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await _authorize_scope(request, project_id, ACTION_E6_AGENT_READ)
    page = await _instances(request).list(
        project_id=project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [_format_instance(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/agents/instances/{instance_id}",
    summary="查询 Agent 实例",
    description="返回实例状态、冻结快照引用与终止原因。",
    responses=_ERRORS,
)
async def get_agent_instance(instance_id: str, request: Request) -> dict:
    view = await _authorized_instance(request, instance_id, ACTION_E6_AGENT_READ)
    return _format_instance(view)


@router.get(
    "/agents/instances/{instance_id}/snapshot",
    summary="查询实例配置快照",
    description="返回实例创建时冻结的不可变配置快照。",
    responses=_ERRORS,
)
async def get_agent_instance_snapshot(instance_id: str, request: Request) -> dict:
    await _authorized_instance(request, instance_id, ACTION_E6_AGENT_READ)
    snapshot = await _instances(request).get_snapshot(instance_id)
    return _format_snapshot(snapshot)


@router.post(
    "/agents/instances",
    summary="创建 Agent 实例",
    description="从已发布 Definition 与合法 Task/Attempt 创建实例；同一 Attempt 幂等。",
    responses=_ERRORS,
)
async def create_agent_instance(payload: AgentInstanceCreateRequest, request: Request) -> dict:
    task = await _tasks(request).get(payload.task_id)
    await authorize_project_action(request, task.project_id, ACTION_E6_AGENT_MANAGE)
    session = getattr(request.state, "session", None)
    principal = request.state.principal
    view = await _instances(request).create_for_attempt(
        definition_id=payload.definition_id,
        task_id=payload.task_id,
        attempt_id=payload.attempt_id,
        session_id=session.session_id if session is not None else None,
        client_id=principal.client_id,
        model_id=payload.model_id,
    )
    return _format_instance(view)


@router.post(
    "/agents/instances/{instance_id}/start",
    summary="启动 Agent 实例",
    description="CREATED → INITIALIZING → READY → RUNNING；引用失效时进入 FAILED。",
    responses=_ERRORS,
)
async def start_agent_instance(instance_id: str, request: Request) -> dict:
    view = await _authorized_instance(request, instance_id, ACTION_E6_AGENT_MANAGE)
    lifecycle = _lifecycle(request)
    if view.status == "CREATED":
        view = await lifecycle.initialize(instance_id)
    if view.status == "READY":
        view = await lifecycle.start(instance_id)
    return _format_instance(view)


@router.post(
    "/agents/instances/{instance_id}/pause",
    summary="暂停 Agent 实例",
    description="写 Checkpoint 后进入 PAUSED；等待审批的动作会被保留。",
    responses=_ERRORS,
)
async def pause_agent_instance(
    instance_id: str,
    request: Request,
    payload: AgentInstanceActionRequest | None = None,
) -> dict:
    await _authorized_instance(request, instance_id, ACTION_E6_AGENT_MANAGE)
    view = await _control(request).pause(instance_id, reason=payload.reason if payload else None)
    return _format_instance(view)


@router.post(
    "/agents/instances/{instance_id}/resume",
    summary="恢复 Agent 实例",
    description="完整校验后恢复；校验失败保持 PAUSED 并返回 AGENT_RECOVERY_REQUIRED。",
    responses=_ERRORS,
)
async def resume_agent_instance(
    instance_id: str,
    request: Request,
    payload: AgentResumeRequest | None = None,
) -> dict:
    await _authorized_instance(request, instance_id, ACTION_E6_AGENT_MANAGE)
    view = await _control(request).resume(
        instance_id,
        approval_id=payload.approval_id if payload else None,
        actor=request.state.principal.client_id,
    )
    return _format_instance(view)


@router.post(
    "/agents/instances/{instance_id}/stop",
    summary="停止 Agent 实例",
    description="放弃未完成计划并进入 STOPPED；不回写 Task 状态。",
    responses=_ERRORS,
)
async def stop_agent_instance(
    instance_id: str,
    request: Request,
    payload: AgentInstanceActionRequest | None = None,
) -> dict:
    await _authorized_instance(request, instance_id, ACTION_E6_AGENT_MANAGE)
    view = await _control(request).stop(instance_id, reason=payload.reason if payload else None)
    return _format_instance(view)


# ---- Execution / Plan / Step / Event ----


@router.get(
    "/agents/instances/{instance_id}/executions",
    summary="列出实例执行",
    description="按实例列出全部 Execution 及其预算用量。",
    responses=_ERRORS,
)
async def list_agent_executions(instance_id: str, request: Request) -> dict:
    await _authorized_instance(request, instance_id, ACTION_E6_AGENT_READ)
    items = await _executions(request).list_for_instance(instance_id)
    return {"items": [_format_execution(item) for item in items]}


@router.get(
    "/agents/executions/{execution_id}",
    summary="查询 Agent 执行",
    description="返回单次 Execution 的状态、预算用量与终止原因。",
    responses=_ERRORS,
)
async def get_agent_execution(execution_id: str, request: Request) -> dict:
    execution, _ = await _authorized_execution(request, execution_id, ACTION_E6_AGENT_READ)
    return _format_execution(execution)


@router.get(
    "/agents/executions/{execution_id}/plan",
    summary="查询执行计划",
    description="返回当前 ACTIVE Plan 与全部 Step；不存在时 404。",
    responses=_ERRORS,
)
async def get_agent_execution_plan(execution_id: str, request: Request) -> dict:
    await _authorized_execution(request, execution_id, ACTION_E6_AGENT_READ)
    plan = await _planning(request).active_plan(execution_id)
    if plan is None:
        raise NotFoundError("Agent Plan 不存在", details={"execution_id": execution_id})
    return _format_plan(plan)


@router.get(
    "/agents/executions/{execution_id}/steps",
    summary="查询执行步骤",
    description="返回执行计划中的 Step 列表与状态。",
    responses=_ERRORS,
)
async def get_agent_execution_steps(execution_id: str, request: Request) -> dict:
    await _authorized_execution(request, execution_id, ACTION_E6_AGENT_READ)
    plan = await _planning(request).active_plan(execution_id)
    steps = [] if plan is None else [_format_step(step) for step in plan.steps]
    return {"items": steps, "total": len(steps)}


@router.get(
    "/agents/instances/{instance_id}/events",
    summary="列出实例事件",
    description="按序号增量返回只追加事件流，支持 after_sequence 与 limit。",
    responses=_ERRORS,
)
async def list_agent_instance_events(
    instance_id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    await _authorized_instance(request, instance_id, ACTION_E6_AGENT_READ)
    events = await _events(request).list_after(
        instance_id, after_sequence=after_sequence, limit=limit
    )
    return {"items": [format_event(event) for event in events]}


@router.get(
    "/agents/executions/{execution_id}/events",
    summary="列出执行事件",
    description="仅返回属于该 Execution 的事件。",
    responses=_ERRORS,
)
async def list_agent_execution_events(
    execution_id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    await _authorized_execution(request, execution_id, ACTION_E6_AGENT_READ)
    events = await _events(request).list_for_execution(
        execution_id, after_sequence=after_sequence, limit=limit
    )
    return {"items": [format_event(event) for event in events]}


# ---- Observability ----


@router.get(
    "/agents/metrics",
    summary="查询 Agent 指标",
    description="返回实例/执行、耗时、调用、Token、成本、失败率与恢复成功率。",
    responses=_ERRORS,
)
async def get_agent_metrics(
    request: Request,
    project_id: str | None = Query(default=None, pattern=PROJECT_ID_PATTERN),
) -> dict:
    await _authorize_scope(request, project_id, ACTION_E6_AGENT_READ)
    metrics = await _observability(request).metrics(project_id=project_id)
    return metrics.as_dict()


@router.get(
    "/agents/executions/{execution_id}/trace",
    summary="查询执行追踪",
    description="返回 Task → Attempt → Instance → Execution → Plan/Step → Model/Tool/Event 的脱敏追踪。",
    responses=_ERRORS,
)
async def get_agent_execution_trace(execution_id: str, request: Request) -> dict:
    await _authorized_execution(request, execution_id, ACTION_E6_AGENT_READ)
    return await _observability(request).trace(execution_id)
