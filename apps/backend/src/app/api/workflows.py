"""Workflow 定义 / 实例 / Node / Phase 接口（E4-T22）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.project_workflow import (
    NodeErrorRequest,
    NodeOutputRequest,
    PhaseReviewReasonRequest,
    PhaseReviewSubmitRequest,
    WorkflowDefinitionCreateRequest,
    WorkflowDefinitionVersionRequest,
    WorkflowInstanceCreateRequest,
)
from core.security.principal import ACTION_E4_WORKFLOW_MANAGE, ACTION_E4_WORKFLOW_READ
from modules.task.service import TaskService
from modules.workflow.service import (
    WorkflowDefinitionService,
    WorkflowInstanceService,
    WorkflowNodeService,
    WorkflowPhaseService,
    WorkflowScheduler,
    format_definition,
    format_instance,
    format_node,
    format_phase,
    format_review,
)

router = APIRouter(
    tags=["workflows"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    404: {"description": "资源不存在（NOT_FOUND）"},
    409: {"description": "状态冲突（INVALID_STATE_TRANSITION）"},
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


def _definitions(request: Request) -> WorkflowDefinitionService:
    return request.app.state.services.get("workflow_definition_service", WorkflowDefinitionService)


def _instances(request: Request) -> WorkflowInstanceService:
    return request.app.state.services.get("workflow_instance_service", WorkflowInstanceService)


def _nodes(request: Request) -> WorkflowNodeService:
    return request.app.state.services.get("workflow_node_service", WorkflowNodeService)


def _phases(request: Request) -> WorkflowPhaseService:
    return request.app.state.services.get("workflow_phase_service", WorkflowPhaseService)


def _scheduler(request: Request) -> WorkflowScheduler:
    return request.app.state.services.get("workflow_scheduler", WorkflowScheduler)


async def _authorize_instance(request: Request, instance_id: str, action: str) -> str:
    instance = await _instances(request).get(instance_id)
    await authorize_project_action(request, instance.project_id, action)
    return instance.project_id


@router.post(
    "/workflow-definitions",
    status_code=status.HTTP_201_CREATED,
    summary="创建 Workflow 定义",
    description="创建带版本的 Workflow 定义；节点与阶段引用在保存前校验。",
    responses=_ERRORS,
)
async def create_workflow_definition(
    payload: WorkflowDefinitionCreateRequest,
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN, description="用于项目级授权"),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_WORKFLOW_MANAGE)
    view = await _definitions(request).create(
        name=payload.name,
        category=payload.category,
        document=payload.definition,
        description=payload.description,
    )
    return format_definition(view)


@router.get(
    "/workflow-definitions",
    summary="列出 Workflow 定义",
    description="列出 Workflow 定义及其最新版本。",
    responses=_ERRORS,
)
async def list_workflow_definitions(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN, description="用于项目级授权"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_WORKFLOW_READ)
    page = await _definitions(request).list(limit=limit, offset=offset)
    return {
        "items": page["items"],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/workflow-definitions/{definition_id}",
    summary="查询 Workflow 定义",
    description="返回指定版本或最新版本的定义内容。",
    responses=_ERRORS,
)
async def get_workflow_definition(
    definition_id: str,
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN, description="用于项目级授权"),
    version: int | None = Query(default=None, ge=1),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_WORKFLOW_READ)
    return format_definition(await _definitions(request).get(definition_id, version=version))


@router.post(
    "/workflow-definitions/{definition_id}/versions",
    status_code=status.HTTP_201_CREATED,
    summary="新增 Workflow 版本",
    description="为已有定义追加版本；旧版本保持不变。",
    responses=_ERRORS,
)
async def add_workflow_definition_version(
    definition_id: str,
    payload: WorkflowDefinitionVersionRequest,
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN, description="用于项目级授权"),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_WORKFLOW_MANAGE)
    return format_definition(
        await _definitions(request).add_version(definition_id, payload.definition)
    )


@router.post(
    "/tasks/{task_id}/workflow",
    status_code=status.HTTP_201_CREATED,
    summary="为任务创建 Workflow 实例",
    description="按定义版本创建实例与节点/阶段；任务状态由 Workflow 通过公开接口推进。",
    responses=_ERRORS,
)
async def create_workflow_instance(
    task_id: str, payload: WorkflowInstanceCreateRequest, request: Request
) -> dict:
    task = await request.app.state.services.get("task_service", TaskService).get(task_id)
    await authorize_project_action(request, task.project_id, ACTION_E4_WORKFLOW_MANAGE)
    view = await _instances(request).create(
        project_id=task.project_id,
        task_id=task_id,
        definition_id=payload.definition_id,
        definition_version=payload.definition_version,
        actor_id=request.state.principal.client_id,
    )
    return format_instance(view)


@router.get(
    "/tasks/{task_id}/workflow",
    summary="列出任务 Workflow",
    description="返回任务关联的全部 Workflow 实例。",
    responses=_ERRORS,
)
async def list_task_workflows(task_id: str, request: Request) -> dict:
    task = await request.app.state.services.get("task_service", TaskService).get(task_id)
    await authorize_project_action(request, task.project_id, ACTION_E4_WORKFLOW_READ)
    rows = await _instances(request).list_by_task(task_id)
    return {"items": [format_instance(item) for item in rows]}


@router.get(
    "/workflows/{instance_id}",
    summary="查询 Workflow 实例",
    description="返回实例状态与当前节点/阶段。",
    responses=_ERRORS,
)
async def get_workflow_instance(instance_id: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_READ)
    return format_instance(await _instances(request).get(instance_id))


@router.get(
    "/workflows/{instance_id}/nodes",
    summary="列出 Workflow 节点",
    description="返回实例的全部节点状态。",
    responses=_ERRORS,
)
async def list_workflow_nodes(instance_id: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_READ)
    rows = await _nodes(request).list_nodes(instance_id)
    return {"items": [format_node(item) for item in rows]}


@router.get(
    "/workflows/{instance_id}/phases",
    summary="列出 Workflow 阶段",
    description="返回实例的全部阶段与验收状态。",
    responses=_ERRORS,
)
async def list_workflow_phases(instance_id: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_READ)
    rows = await _phases(request).list_phases(instance_id)
    return {"items": [format_phase(item) for item in rows]}


@router.post(
    "/workflows/{instance_id}/pause",
    summary="暂停 Workflow",
    description="RUNNING → PAUSING → PAUSED。",
    responses=_ERRORS,
)
async def pause_workflow(instance_id: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    return format_instance(await _instances(request).pause(instance_id))


@router.post(
    "/workflows/{instance_id}/resume",
    summary="恢复 Workflow",
    description="PAUSED → RESUMING → RUNNING。",
    responses=_ERRORS,
)
async def resume_workflow(instance_id: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    return format_instance(await _instances(request).resume(instance_id))


@router.post(
    "/workflows/{instance_id}/cancel",
    summary="取消 Workflow",
    description="把未完成实例取消。",
    responses=_ERRORS,
)
async def cancel_workflow(instance_id: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    return format_instance(await _instances(request).cancel(instance_id))


@router.post(
    "/workflows/{instance_id}/tick",
    summary="推进 Workflow 调度",
    description="推进 READY 节点并在无运行节点时启动一个节点。",
    responses=_ERRORS,
)
async def tick_workflow(instance_id: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    return await _scheduler(request).tick(instance_id)


@router.post(
    "/workflows/{instance_id}/advance",
    summary="推进节点就绪",
    description="把依赖已满足的 PENDING 节点标记为 READY。",
    responses=_ERRORS,
)
async def advance_workflow(instance_id: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    rows = await _nodes(request).advance(instance_id)
    return {"items": [format_node(item) for item in rows]}


@router.post(
    "/workflows/{instance_id}/nodes/{node_key}/start",
    summary="启动 Workflow 节点",
    description="READY → RUNNING；必要时把实例从 READY 推进到 RUNNING。",
    responses=_ERRORS,
)
async def start_workflow_node(instance_id: str, node_key: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    return format_node(await _nodes(request).start_node(instance_id, node_key))


@router.post(
    "/workflows/{instance_id}/nodes/{node_key}/complete",
    summary="完成 Workflow 节点",
    description="RUNNING → SUCCEEDED；全部节点完成后实例完成并请求任务验收。",
    responses=_ERRORS,
)
async def complete_workflow_node(
    instance_id: str,
    node_key: str,
    payload: NodeOutputRequest,
    request: Request,
) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    view = await _nodes(request).complete_node(instance_id, node_key, output_ref=payload.output_ref)
    return format_node(view)


@router.post(
    "/workflows/{instance_id}/nodes/{node_key}/fail",
    summary="标记 Workflow 节点失败",
    description="RUNNING → FAILED，并把运行中的实例置为 FAILED。",
    responses=_ERRORS,
)
async def fail_workflow_node(
    instance_id: str,
    node_key: str,
    payload: NodeErrorRequest,
    request: Request,
) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    view = await _nodes(request).fail_node(instance_id, node_key, error_ref=payload.error_ref)
    return format_node(view)


@router.post(
    "/workflows/{instance_id}/nodes/{node_key}/skip",
    summary="跳过 Workflow 节点",
    description="PENDING/READY/RUNNING → SKIPPED，并参与实例完成判定。",
    responses=_ERRORS,
)
async def skip_workflow_node(instance_id: str, node_key: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    return format_node(await _nodes(request).skip_node(instance_id, node_key))


@router.post(
    "/workflows/{instance_id}/phases/{phase_key}/review",
    summary="提交阶段验收材料",
    description="提交摘要、交付物与证据引用，阶段进入 REVIEW_PENDING。",
    responses=_ERRORS,
)
async def submit_phase_review(
    instance_id: str,
    phase_key: str,
    payload: PhaseReviewSubmitRequest,
    request: Request,
) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    view = await _phases(request).submit_review(
        instance_id,
        phase_key,
        summary=payload.summary,
        deliverables=payload.deliverables,
        evidence_refs=payload.evidence_refs,
        verification_summary=payload.verification_summary,
    )
    return format_review(view)


@router.get(
    "/workflows/{instance_id}/phases/{phase_key}/review",
    summary="查询阶段验收",
    description="返回阶段验收材料与状态。",
    responses=_ERRORS,
)
async def get_phase_review(instance_id: str, phase_key: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_READ)
    view = await _phases(request).get_review(instance_id, phase_key)
    return {"review": format_review(view) if view else None}


@router.post(
    "/workflows/{instance_id}/phases/{phase_key}/accept",
    summary="验收阶段",
    description="用户接受阶段；全部阶段接受后实例完成并请求任务验收。",
    responses=_ERRORS,
)
async def accept_phase(instance_id: str, phase_key: str, request: Request) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    return format_phase(
        await _phases(request).accept_phase(
            instance_id, phase_key, actor_id=request.state.principal.client_id
        )
    )


@router.post(
    "/workflows/{instance_id}/phases/{phase_key}/request-revision",
    summary="退回阶段修改",
    description="REVIEW_PENDING → NEEDS_REVISION。",
    responses=_ERRORS,
)
async def request_phase_revision(
    instance_id: str,
    phase_key: str,
    payload: PhaseReviewReasonRequest,
    request: Request,
) -> dict:
    await _authorize_instance(request, instance_id, ACTION_E4_WORKFLOW_MANAGE)
    return format_phase(
        await _phases(request).request_revision(
            instance_id,
            phase_key,
            actor_id=request.state.principal.client_id,
            reason=payload.reason,
        )
    )
