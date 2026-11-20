"""Project / Configuration / Requirement 接口（E4-T22）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.project_workflow import (
    ConfigurationUpdateRequest,
    CriterionStatusRequest,
    ProjectArchiveRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    RequirementCreateRequest,
    RequirementStatusRequest,
    RequirementTraceRequest,
)
from core.security.principal import (
    ACTION_E4_PROJECT_MANAGE,
    ACTION_E4_PROJECT_READ,
)
from modules.access.service import ProjectAccessService
from modules.project_registry.service import (
    ProjectConfigurationService,
    ProjectLifecycleService,
    ProjectRegistryService,
    format_configuration,
    format_project,
)
from modules.requirement.service import RequirementService, format_requirement

router = APIRouter(
    tags=["projects"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    404: {"description": "资源不存在（NOT_FOUND）"},
    409: {"description": "状态冲突（INVALID_STATE_TRANSITION / VERSION_CONFLICT）"},
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


def _registry(request: Request) -> ProjectRegistryService:
    return request.app.state.services.get("project_registry_service", ProjectRegistryService)


@router.post(
    "/projects",
    status_code=status.HTTP_201_CREATED,
    summary="注册项目",
    description="验证项目路径与指纹并注册业务项目；非 admin 调用者自动获得 owner 访问。",
    responses=_ERRORS,
)
async def create_project(payload: ProjectCreateRequest, request: Request) -> dict:
    principal = request.state.principal
    registry = _registry(request)
    view = await registry.register(
        project_root=payload.project_root,
        name=payload.name,
        description=payload.description,
        project_type=payload.project_type,
        godot_version=payload.godot_version,
        created_by=principal.client_id,
    )
    session = getattr(request.state, "session", None)
    if session is not None and principal.role != "admin":
        access_service = request.app.state.services.get(
            "project_access_service", ProjectAccessService
        )
        await access_service.grant(
            project_id=view.project_id,
            session_id=session.session_id,
            client_id=session.client_id,
            access_level="owner",
            granted_by=principal.client_id,
        )
    return format_project(view)


@router.get(
    "/projects",
    summary="列出项目",
    description="admin 可列出全部项目；普通客户端只返回自己作为成员的项目。",
    responses=_ERRORS,
)
async def list_projects(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    principal = request.state.principal
    page = await _registry(request).list(limit=limit, offset=offset)
    if principal.role == "admin":
        return {
            "items": [format_project(item) for item in page["items"]],
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
        }
    registry = _registry(request)
    visible = []
    for item in page["items"]:
        members = await registry.list_memberships(item.project_id)
        if any(member.client_id == principal.client_id for member in members):
            visible.append(format_project(item))
    return {
        "items": visible,
        "total": len(visible),
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/projects/{project_id}",
    summary="查询项目",
    description="返回项目状态、路径、指纹与版本。",
    responses=_ERRORS,
)
async def get_project(project_id: str, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_READ)
    return format_project(await _registry(request).get(project_id))


@router.patch(
    "/projects/{project_id}",
    summary="更新项目",
    description="更新名称、描述或项目类型；可携带 expected_version 做乐观锁。",
    responses=_ERRORS,
)
async def update_project(project_id: str, payload: ProjectUpdateRequest, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_MANAGE)
    view = await _registry(request).update(
        project_id,
        name=payload.name,
        description=payload.description,
        project_type=payload.project_type,
        expected_version=payload.expected_version,
    )
    return format_project(view)


def _lifecycle(request: Request) -> ProjectLifecycleService:
    return request.app.state.services.get("project_lifecycle_service", ProjectLifecycleService)


@router.post(
    "/projects/{project_id}/suspend",
    summary="暂停项目",
    description="暂停项目；暂停后不再接受新的受保护自动操作。",
    responses=_ERRORS,
)
async def suspend_project(project_id: str, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_MANAGE)
    return format_project(await _lifecycle(request).suspend(project_id))


@router.post(
    "/projects/{project_id}/resume",
    summary="恢复项目",
    description="把暂停项目恢复为 ACTIVE。",
    responses=_ERRORS,
)
async def resume_project(project_id: str, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_MANAGE)
    return format_project(await _lifecycle(request).resume(project_id))


@router.post(
    "/projects/{project_id}/archive",
    summary="归档项目",
    description="归档前检查未完成 Task/Workflow/Approval/ChangeSet；force=true 可显式强制归档。",
    responses=_ERRORS,
)
async def archive_project(
    project_id: str, payload: ProjectArchiveRequest, request: Request
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_MANAGE)
    return format_project(await _lifecycle(request).archive(project_id, force=payload.force))


@router.post(
    "/projects/{project_id}/close",
    summary="关闭项目上下文",
    description="从当前工作上下文关闭项目；不会删除项目记录。",
    responses=_ERRORS,
)
async def close_project(project_id: str, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_MANAGE)
    return format_project(await _lifecycle(request).close(project_id))


@router.get(
    "/projects/{project_id}/configuration",
    summary="查询项目配置",
    description="返回项目级开发配置与版本号。",
    responses=_ERRORS,
)
async def get_project_configuration(project_id: str, request: Request) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_READ)
    service = request.app.state.services.get(
        "project_configuration_service", ProjectConfigurationService
    )
    return format_configuration(await service.get(project_id))


@router.patch(
    "/projects/{project_id}/configuration",
    summary="更新项目配置",
    description="更新项目配置并写入版本历史；配置变更不会静默改变已启动 Task 的快照。",
    responses=_ERRORS,
)
async def update_project_configuration(
    project_id: str, payload: ConfigurationUpdateRequest, request: Request
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_MANAGE)
    service = request.app.state.services.get(
        "project_configuration_service", ProjectConfigurationService
    )
    view = await service.update(
        project_id,
        payload.configuration,
        actor=request.state.principal.client_id,
        expected_version=payload.expected_version,
    )
    return format_configuration(view)


def _requirements(request: Request) -> RequirementService:
    return request.app.state.services.get("requirement_service", RequirementService)


@router.post(
    "/requirements",
    status_code=status.HTTP_201_CREATED,
    summary="创建需求",
    description="创建需求与验收标准；需求是 Task 与 Phase 的追踪依据。",
    responses=_ERRORS,
)
async def create_requirement(payload: RequirementCreateRequest, request: Request) -> dict:
    await authorize_project_action(request, payload.project_id, ACTION_E4_PROJECT_MANAGE)
    view = await _requirements(request).create(
        project_id=payload.project_id,
        requirement_key=payload.requirement_key,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        priority=payload.priority,
        source=payload.source,
        criteria=payload.criteria,
    )
    return format_requirement(view)


@router.get(
    "/requirements",
    summary="列出项目需求",
    description="按项目列出需求与验收标准。",
    responses=_ERRORS,
)
async def list_requirements(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E4_PROJECT_READ)
    rows = await _requirements(request).list(project_id, status=status_filter)
    return {"items": [format_requirement(item) for item in rows]}


@router.get(
    "/requirements/{requirement_id}",
    summary="查询需求",
    description="返回需求、验收标准与状态。",
    responses=_ERRORS,
)
async def get_requirement(requirement_id: str, request: Request) -> dict:
    view = await _requirements(request).get(requirement_id)
    await authorize_project_action(request, view.project_id, ACTION_E4_PROJECT_READ)
    return format_requirement(view)


@router.patch(
    "/requirements/{requirement_id}/status",
    summary="更新需求状态",
    description="更新需求生命周期状态。",
    responses=_ERRORS,
)
async def update_requirement_status(
    requirement_id: str, payload: RequirementStatusRequest, request: Request
) -> dict:
    current = await _requirements(request).get(requirement_id)
    await authorize_project_action(request, current.project_id, ACTION_E4_PROJECT_MANAGE)
    return format_requirement(
        await _requirements(request).update_status(requirement_id, payload.status)
    )


@router.patch(
    "/requirements/{requirement_id}/criteria/{criterion_key}",
    summary="更新验收标准",
    description="更新验收标准状态；全部 MET/WAIVED 时需求自动进入 VERIFIED。",
    responses=_ERRORS,
)
async def update_criterion_status(
    requirement_id: str,
    criterion_key: str,
    payload: CriterionStatusRequest,
    request: Request,
) -> dict:
    current = await _requirements(request).get(requirement_id)
    await authorize_project_action(request, current.project_id, ACTION_E4_PROJECT_MANAGE)
    return format_requirement(
        await _requirements(request).set_criterion_status(
            requirement_id, criterion_key, payload.status, evidence=payload.evidence
        )
    )


@router.post(
    "/requirements/{requirement_id}/traces",
    status_code=status.HTTP_201_CREATED,
    summary="创建需求追踪",
    description="把需求关联到 Task、Phase、ChangeSet 或验证结果。",
    responses=_ERRORS,
)
async def trace_requirement(
    requirement_id: str, payload: RequirementTraceRequest, request: Request
) -> dict:
    current = await _requirements(request).get(requirement_id)
    await authorize_project_action(request, current.project_id, ACTION_E4_PROJECT_MANAGE)
    return await _requirements(request).trace(
        requirement_id,
        task_id=payload.task_id,
        phase_id=payload.phase_id,
        changeset_id=payload.changeset_id,
        verification_result_id=payload.verification_result_id,
    )


@router.get(
    "/requirements/{requirement_id}/traces",
    summary="列需求追踪",
    description="返回需求的所有追踪关系。",
    responses=_ERRORS,
)
async def list_requirement_traces(requirement_id: str, request: Request) -> dict:
    current = await _requirements(request).get(requirement_id)
    await authorize_project_action(request, current.project_id, ACTION_E4_PROJECT_READ)
    return {"items": await _requirements(request).list_traces(requirement_id)}
