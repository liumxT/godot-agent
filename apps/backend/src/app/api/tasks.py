"""Task / Attempt / Dependency / Checkpoint / Event 接口（E4-T22）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.project_workflow import (
    AttemptCreateRequest,
    AttemptFinishRequest,
    CheckpointCreateRequest,
    DependencyCreateRequest,
    TaskCreateRequest,
    TaskRejectRequest,
    TaskTransitionRequest,
)
from core.security.principal import ACTION_E4_TASK_MANAGE, ACTION_E4_TASK_READ
from modules.task.models import (
    TASK_FAILED,
    TASK_NEEDS_REVISION,
    TASK_READY,
    TASK_REJECTED,
)
from modules.task.service import (
    AttemptService,
    CheckpointService,
    DependencyService,
    TaskService,
    TaskView,
    format_attempt,
    format_checkpoint,
    format_dependency,
    format_task,
    format_task_event,
)

router = APIRouter(
    tags=["tasks"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    404: {"description": "资源不存在（NOT_FOUND）"},
    409: {"description": "状态或依赖冲突（INVALID_STATE_TRANSITION / DEPENDENCY_CYCLE）"},
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


def _tasks(request: Request) -> TaskService:
    return request.app.state.services.get("task_service", TaskService)


def _attempts(request: Request) -> AttemptService:
    return request.app.state.services.get("task_attempt_service", AttemptService)


def _checkpoints(request: Request) -> CheckpointService:
    return request.app.state.services.get("task_checkpoint_service", CheckpointService)


def _dependencies(request: Request) -> DependencyService:
    return request.app.state.services.get("task_dependency_service", DependencyService)


async def _authorize_task(request: Request, task_id: str, action: str) -> TaskView:
    task = await _tasks(request).get(task_id)
    await authorize_project_action(request, task.project_id, action)
    return task


@router.post(
    "/projects/{project_id}/tasks",
    status_code=status.HTTP_201_CREATED,
    summary="创建任务",
    description="在项目下创建任务；默认直接进入 READY。",
    responses=_ERRORS,
)
async def create_task(project_id: str, payload: TaskCreateRequest, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_TASK_MANAGE)
    view = await _tasks(request).create(
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        task_type=payload.task_type,
        priority=payload.priority,
        parent_task_id=payload.parent_task_id,
        created_by=request.state.principal.client_id,
        actor_id=request.state.principal.client_id,
    )
    return format_task(view)


@router.get(
    "/projects/{project_id}/tasks",
    summary="列出项目任务",
    description="按项目列出任务，可按状态过滤。",
    responses=_ERRORS,
)
async def list_project_tasks(
    project_id: str,
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_TASK_READ)
    page = await _tasks(request).list(project_id, status=status_filter, limit=limit, offset=offset)
    return {
        "items": [format_task(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/tasks/{task_id}",
    summary="查询任务",
    description="返回任务状态、当前 Attempt 与关联 Workflow。",
    responses=_ERRORS,
)
async def get_task(task_id: str, request: Request) -> dict:
    view = await _authorize_task(request, task_id, ACTION_E4_TASK_READ)
    return format_task(view)


@router.patch(
    "/tasks/{task_id}/status",
    summary="转换任务状态",
    description="按 Task 状态机迁移；非法迁移返回 INVALID_STATE_TRANSITION。",
    responses=_ERRORS,
)
async def transition_task(task_id: str, payload: TaskTransitionRequest, request: Request) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    view = await _tasks(request).transition(
        task_id,
        payload.status,
        actor_id=request.state.principal.client_id,
        reason=payload.reason,
        expected_version=payload.expected_version,
    )
    return format_task(view)


@router.post(
    "/tasks/{task_id}/pause",
    summary="暂停任务",
    description="RUNNING → PAUSING → PAUSED。",
    responses=_ERRORS,
)
async def pause_task(task_id: str, request: Request) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    return format_task(
        await _tasks(request).pause(task_id, actor_id=request.state.principal.client_id)
    )


@router.post(
    "/tasks/{task_id}/resume",
    summary="恢复任务",
    description="PAUSED → RESUMING → RUNNING。",
    responses=_ERRORS,
)
async def resume_task(task_id: str, request: Request) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    return format_task(
        await _tasks(request).resume(task_id, actor_id=request.state.principal.client_id)
    )


@router.post(
    "/tasks/{task_id}/cancel",
    summary="取消任务",
    description="把未完成任务取消；终态任务不能再迁移。",
    responses=_ERRORS,
)
async def cancel_task(task_id: str, request: Request) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    return format_task(
        await _tasks(request).cancel(task_id, actor_id=request.state.principal.client_id)
    )


@router.post(
    "/tasks/{task_id}/retry",
    summary="重试任务",
    description="FAILED / NEEDS_REVISION / REJECTED → READY；重试必须创建新的 Attempt。",
    responses=_ERRORS,
)
async def retry_task(task_id: str, request: Request) -> dict:
    task = await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    if task.status not in (TASK_FAILED, TASK_NEEDS_REVISION, TASK_REJECTED):
        from core.errors import InvalidStateTransition

        raise InvalidStateTransition(
            "当前任务状态不能重试", details={"task_id": task_id, "status": task.status}
        )
    view = await _tasks(request).transition(
        task_id, TASK_READY, actor_id=request.state.principal.client_id, reason="retry"
    )
    return format_task(view)


@router.post(
    "/tasks/{task_id}/accept",
    summary="用户验收任务",
    description="REVIEW_PENDING → COMPLETED；只有用户可执行验收。",
    responses=_ERRORS,
)
async def accept_task(task_id: str, request: Request) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    return format_task(
        await _tasks(request).accept(task_id, actor_id=request.state.principal.client_id)
    )


@router.post(
    "/tasks/{task_id}/reject",
    summary="驳回任务",
    description="REVIEW_PENDING → NEEDS_REVISION；记录驳回原因。",
    responses=_ERRORS,
)
async def reject_task(task_id: str, payload: TaskRejectRequest, request: Request) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    return format_task(
        await _tasks(request).reject(
            task_id, actor_id=request.state.principal.client_id, reason=payload.reason
        )
    )


@router.post(
    "/tasks/{task_id}/attempts",
    status_code=status.HTTP_201_CREATED,
    summary="创建执行尝试",
    description="为任务创建新的 Attempt；已完成或已取消的任务不能创建。",
    responses=_ERRORS,
)
async def create_attempt(task_id: str, payload: AttemptCreateRequest, request: Request) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    view = await _attempts(request).create(
        task_id,
        agent_instance_id=payload.agent_instance_id,
        workflow_instance_id=payload.workflow_instance_id,
        actor_id=request.state.principal.client_id,
    )
    return format_attempt(view)


@router.get(
    "/tasks/{task_id}/attempts",
    summary="列出执行尝试",
    description="按创建顺序返回任务的全部 Attempt。",
    responses=_ERRORS,
)
async def list_attempts(task_id: str, request: Request) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_READ)
    return {"items": [format_attempt(item) for item in await _attempts(request).list(task_id)]}


async def _authorize_attempt(request: Request, attempt_id: str) -> None:
    attempt = await _attempts(request).get(attempt_id)
    task = await _tasks(request).get(attempt.task_id)
    await authorize_project_action(request, task.project_id, ACTION_E4_TASK_MANAGE)


@router.post(
    "/attempts/{attempt_id}/start",
    summary="开始执行尝试",
    description="CREATED → STARTING → RUNNING。",
    responses=_ERRORS,
)
async def start_attempt(attempt_id: str, request: Request) -> dict:
    await _authorize_attempt(request, attempt_id)
    return format_attempt(await _attempts(request).start(attempt_id))


@router.post(
    "/attempts/{attempt_id}/finish",
    summary="结束执行尝试",
    description="以 SUCCEEDED / FAILED / CANCELLED 结束 Attempt。",
    responses=_ERRORS,
)
async def finish_attempt(attempt_id: str, payload: AttemptFinishRequest, request: Request) -> dict:
    await _authorize_attempt(request, attempt_id)
    view = await _attempts(request).finish(
        attempt_id,
        payload.status,
        summary=payload.summary,
        failure_code=payload.failure_code,
        failure_reason=payload.failure_reason,
        resource_usage=payload.resource_usage,
    )
    return format_attempt(view)


@router.get(
    "/tasks/{task_id}/events",
    summary="列出任务事件",
    description="按序号返回任务事件流，用于恢复与审计。",
    responses=_ERRORS,
)
async def list_task_events(
    task_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_READ)
    page = await _tasks(request).list_events(task_id, limit=limit, offset=offset)
    return {
        "items": [format_task_event(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.post(
    "/tasks/{task_id}/checkpoints",
    status_code=status.HTTP_201_CREATED,
    summary="创建检查点",
    description="保存业务状态引用；不保存隐藏推理。",
    responses=_ERRORS,
)
async def create_checkpoint(
    task_id: str, payload: CheckpointCreateRequest, request: Request
) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_MANAGE)
    view = await _checkpoints(request).create(
        task_id,
        checkpoint_type=payload.checkpoint_type,
        attempt_id=payload.attempt_id,
        workflow_state_ref=payload.workflow_state_ref,
        context_ref=payload.context_ref,
        changeset_ref=payload.changeset_ref,
    )
    return format_checkpoint(view)


@router.get(
    "/tasks/{task_id}/checkpoints",
    summary="列出检查点",
    description="返回任务最近的检查点。",
    responses=_ERRORS,
)
async def list_checkpoints(
    task_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    await _authorize_task(request, task_id, ACTION_E4_TASK_READ)
    rows = await _checkpoints(request).list(task_id, limit=limit)
    return {"items": [format_checkpoint(item) for item in rows]}


@router.get(
    "/projects/{project_id}/dependencies",
    summary="列出任务依赖",
    description="返回项目内有效依赖。",
    responses=_ERRORS,
)
async def list_dependencies(project_id: str, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_TASK_READ)
    rows = await _dependencies(request).list(project_id)
    return {"items": [format_dependency(item) for item in rows]}


@router.post(
    "/projects/{project_id}/dependencies",
    status_code=status.HTTP_201_CREATED,
    summary="创建任务依赖",
    description="建立依赖前检测循环；source 未完成时 target 不能进入 RUNNING。",
    responses=_ERRORS,
)
async def create_dependency(
    project_id: str, payload: DependencyCreateRequest, request: Request
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_TASK_MANAGE)
    view = await _dependencies(request).create(
        source_task_id=payload.source_task_id,
        target_task_id=payload.target_task_id,
        dependency_type=payload.dependency_type,
    )
    return format_dependency(view)


@router.delete(
    "/projects/{project_id}/dependencies/{dependency_id}",
    summary="删除任务依赖",
    description="把依赖标记为 REMOVED，不物理删除历史。",
    responses=_ERRORS,
)
async def delete_dependency(project_id: str, dependency_id: str, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_TASK_MANAGE)
    return format_dependency(await _dependencies(request).remove(dependency_id))
