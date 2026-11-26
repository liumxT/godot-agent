"""E10 构建与发布 API（Batch A：T02 / T03 / T04）。

构建配置、Export Preset 与构建环境均按项目授权。Agent 与前端只能通过本
Contract 操作，不得直接读写 Build & Release 内部表。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.build_release import (
    BuildConfigurationCreateRequest,
    BuildConfigurationUpdateRequest,
    BuildCreateRequest,
    BuildEnvironmentRegisterRequest,
    ExportPresetRegisterRequest,
)
from core.security.principal import (
    ACTION_E10_BUILD_CANCEL,
    ACTION_E10_BUILD_CREATE,
    ACTION_E10_BUILD_READ,
    ACTION_E10_BUILD_RECOVER,
    ACTION_E10_BUILD_RUN,
)
from modules.build_release.orchestrator import BuildOrchestrator
from modules.build_release.service import BuildReleaseService

router = APIRouter(
    tags=["builds"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足"},
    404: {"description": "构建配置、Preset 或环境不存在"},
    409: {"description": "状态冲突、重复或环境未就绪"},
    422: {"description": "请求参数校验失败"},
    429: {"description": "触发限流"},
}


def _service(request: Request) -> BuildReleaseService:
    return request.app.state.services.get("build_release_service", BuildReleaseService)


def _orchestrator(request: Request) -> BuildOrchestrator:
    return request.app.state.services.get("build_orchestrator", BuildOrchestrator)


async def _authorize_build(request: Request, build_id: str, action: str) -> str:
    view = await _orchestrator(request).get_build(build_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


async def _authorize_configuration(request: Request, configuration_id: str, action: str) -> str:
    view = await _service(request).get_configuration(configuration_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


@router.post(
    "/projects/{project_id}/build-configurations",
    status_code=status.HTTP_201_CREATED,
    summary="创建构建配置",
    responses=_ERRORS,
)
async def create_build_configuration(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: BuildConfigurationCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_CREATE)
    view = await _service(request).create_configuration(
        project_id=project_id,
        name=payload.name,
        target_platform=payload.target_platform,
        architecture=payload.architecture,
        created_by=request.state.principal.client_id,
        godot_version_constraint=payload.godot_version_constraint,
        renderer=payload.renderer,
        export_preset_name=payload.export_preset_name,
        build_mode=payload.build_mode,
        feature_tags=list(payload.feature_tags),
        output_format=payload.output_format,
        env_allowlist=list(payload.env_allowlist),
        build_timeout_seconds=payload.build_timeout_seconds,
        resource_budget=dict(payload.resource_budget),
        packaging_policy=dict(payload.packaging_policy),
        verification_policy=dict(payload.verification_policy),
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/build-configurations",
    summary="列出项目构建配置",
    responses=_ERRORS,
)
async def list_build_configurations(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_READ)
    page = await _service(request).list_configurations(project_id, limit=limit, offset=offset)
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/build-configurations/{configuration_id}",
    summary="获取构建配置",
    responses=_ERRORS,
)
async def get_build_configuration(
    configuration_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_configuration(request, configuration_id, ACTION_E10_BUILD_READ)
    view = await _service(request).get_configuration(configuration_id)
    return asdict(view)


@router.patch(
    "/build-configurations/{configuration_id}",
    summary="修改构建配置（生成新版本）",
    responses=_ERRORS,
)
async def update_build_configuration(
    configuration_id: str = Path(min_length=1, max_length=64),
    payload: BuildConfigurationUpdateRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_configuration(request, configuration_id, ACTION_E10_BUILD_CREATE)
    changes = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    view = await _service(request).update_configuration(
        configuration_id,
        created_by=request.state.principal.client_id,
        **changes,
    )
    return asdict(view)


@router.get(
    "/build-configurations/{configuration_id}/versions/{version}",
    summary="获取构建配置版本快照",
    responses=_ERRORS,
)
async def get_build_configuration_version(
    configuration_id: str = Path(min_length=1, max_length=64),
    version: int = Path(ge=1),
    request: Request = ...,
) -> dict:
    await _authorize_configuration(request, configuration_id, ACTION_E10_BUILD_READ)
    view = await _service(request).get_configuration_version(configuration_id, version)
    return asdict(view)


@router.get(
    "/build-configurations/{configuration_id}/validation",
    summary="校验构建配置",
    responses=_ERRORS,
)
async def validate_build_configuration(
    configuration_id: str = Path(min_length=1, max_length=64),
    version: int | None = Query(default=None, ge=1),
    request: Request = ...,
) -> dict:
    await _authorize_configuration(request, configuration_id, ACTION_E10_BUILD_READ)
    result = await _service(request).validate_configuration(configuration_id, version=version)
    return asdict(result)


@router.post(
    "/projects/{project_id}/export-presets",
    status_code=status.HTTP_201_CREATED,
    summary="导入 Export Preset 快照",
    responses=_ERRORS,
)
async def register_export_preset(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: ExportPresetRegisterRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_CREATE)
    view = await _service(request).register_export_preset(
        project_id=project_id,
        preset_name=payload.preset_name,
        platform=payload.platform,
        export_path=payload.export_path,
        export_mode=payload.export_mode,
        features=list(payload.features),
        resource_filters=dict(payload.resource_filters),
        template_required=payload.template_required,
        template_available=payload.template_available,
        raw=dict(payload.raw),
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/export-presets",
    summary="列出项目 Export Preset",
    responses=_ERRORS,
)
async def list_export_presets(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    platform: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_READ)
    page = await _service(request).list_export_presets(
        project_id, platform=platform, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/export-presets/{preset_id}",
    summary="获取 Export Preset",
    responses=_ERRORS,
)
async def get_export_preset(
    preset_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _service(request).get_export_preset(preset_id)
    await authorize_project_action(request, view.project_id, ACTION_E10_BUILD_READ)
    return asdict(view)


@router.post(
    "/projects/{project_id}/build-environments",
    status_code=status.HTTP_201_CREATED,
    summary="登记构建环境",
    responses=_ERRORS,
)
async def register_build_environment(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: BuildEnvironmentRegisterRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_CREATE)
    view = await _service(request).register_environment(
        project_id=project_id,
        os_name=payload.os_name,
        os_version=payload.os_version,
        cpu_architecture=payload.cpu_architecture,
        godot_version=payload.godot_version,
        godot_executable_path=payload.godot_executable_path,
        godot_executable_hash=payload.godot_executable_hash,
        export_template_version=payload.export_template_version,
        toolchain_versions=dict(payload.toolchain_versions),
        sdk_versions=dict(payload.sdk_versions),
        renderer=payload.renderer,
        build_executor_version=payload.build_executor_version,
        target_platform=payload.target_platform,
        required_platforms=list(payload.required_platforms),
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/build-environments",
    summary="列出构建环境",
    responses=_ERRORS,
)
async def list_build_environments(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_READ)
    page = await _service(request).list_environments(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/build-environments/{environment_id}",
    summary="获取构建环境",
    responses=_ERRORS,
)
async def get_build_environment(
    environment_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _service(request).get_environment(environment_id)
    if view.project_id:
        await authorize_project_action(request, view.project_id, ACTION_E10_BUILD_READ)
    return asdict(view)


@router.get(
    "/platform-capabilities",
    summary="列出平台导出能力",
    responses=_ERRORS,
)
async def list_platform_capabilities(request: Request = ...) -> dict:
    items = await _service(request).list_platform_capabilities()
    return {"items": [asdict(item) for item in items]}


# ---------------------------------------------------------------------------
# Build 生命周期（T05 / T17）
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/builds",
    status_code=status.HTTP_201_CREATED,
    summary="创建构建任务",
    responses=_ERRORS,
)
async def create_build_job(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: BuildCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_CREATE)
    view = await _orchestrator(request).create_build(
        project_id=project_id,
        build_config_id=payload.build_config_id,
        environment_id=payload.environment_id,
        source_revision=payload.source_revision,
        changeset_id=payload.changeset_id,
        requested_by=request.state.principal.client_id,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/builds",
    summary="列出项目构建任务",
    responses=_ERRORS,
)
async def list_build_jobs(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_READ)
    page = await _orchestrator(request).list_builds(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/builds/{build_id}",
    summary="获取构建任务",
    responses=_ERRORS,
)
async def get_build_job(
    build_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_build(request, build_id, ACTION_E10_BUILD_READ)
    view = await _orchestrator(request).get_build(build_id)
    return asdict(view)


@router.get(
    "/builds/{build_id}/attempts",
    summary="列出构建执行尝试",
    responses=_ERRORS,
)
async def list_build_attempts(
    build_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_build(request, build_id, ACTION_E10_BUILD_READ)
    attempts = await _orchestrator(request).list_attempts(build_id)
    return {"items": [asdict(item) for item in attempts]}


@router.post(
    "/builds/{build_id}/start",
    summary="启动构建（受控执行）",
    responses=_ERRORS,
)
async def start_build_job(
    build_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_build(request, build_id, ACTION_E10_BUILD_RUN)
    view = await _orchestrator(request).start_build(build_id)
    return asdict(view)


@router.post(
    "/builds/{build_id}/retry",
    summary="重试构建（创建新 Attempt）",
    responses=_ERRORS,
)
async def retry_build_job(
    build_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_build(request, build_id, ACTION_E10_BUILD_RUN)
    view = await _orchestrator(request).retry_build(build_id)
    return asdict(view)


@router.post(
    "/builds/{build_id}/cancel",
    summary="取消构建",
    responses=_ERRORS,
)
async def cancel_build_job(
    build_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_build(request, build_id, ACTION_E10_BUILD_CANCEL)
    view = await _orchestrator(request).cancel_build(build_id)
    return asdict(view)


@router.post(
    "/builds/{build_id}/recover",
    summary="恢复 UNKNOWN 构建（核对产物后收敛）",
    responses=_ERRORS,
)
async def recover_build_job(
    build_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_build(request, build_id, ACTION_E10_BUILD_RECOVER)
    view = await _orchestrator(request).recover_build(build_id)
    return asdict(view)
