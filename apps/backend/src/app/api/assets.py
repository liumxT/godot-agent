"""E8 资产管线 API（T19）。

所有接口都按项目授权，Agent 与前端只能通过本 Contract 操作资产：

- 生成、处理、审核、导入与交付均为异步 Job，必须带 Job ID；
- License 未知或质量未通过时交付被拒绝；
- 下载不直接读取内部暂存区，必须经授权后的文件接口；
- 事件与状态由领域服务发布，API 不直接改表。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.asset_pipeline import (
    AssetCreateRequest,
    AssetMetadataPatchRequest,
    DeliveryApprovalRequest,
    DeliveryPlanCreateRequest,
    GenerationCreateRequest,
    ImportCreateRequest,
    LicenseDecisionRequest,
    LicenseReviewCreateRequest,
    ProcessingJobCreateRequest,
    QualityDecisionRequest,
    QualityReviewCreateRequest,
)
from core.errors import NotFoundError
from core.security.principal import (
    ACTION_E8_ASSET_CREATE,
    ACTION_E8_ASSET_DELIVER,
    ACTION_E8_ASSET_GENERATE,
    ACTION_E8_ASSET_IMPORT,
    ACTION_E8_ASSET_PROCESS,
    ACTION_E8_ASSET_READ,
    ACTION_E8_ASSET_REVIEW_LICENSE,
    ACTION_E8_ASSET_REVIEW_QUALITY,
    ACTION_E8_ASSET_UPDATE,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.asset_pipeline.dashboard import AssetDashboardService
from modules.asset_pipeline.delivery import AssetDeliveryService, DeliveryRequest
from modules.asset_pipeline.dependencies import AssetDependencyService
from modules.asset_pipeline.generation import GenerationOrchestrator, GenerationRequest
from modules.asset_pipeline.imports import GodotImportService, ImportRequest
from modules.asset_pipeline.license import (
    LicenseEvidenceInput,
    LicenseRequest,
    LicenseService,
)
from modules.asset_pipeline.processing import ProcessingPipelineService, ProcessingRequest
from modules.asset_pipeline.quality import QualityControlService
from modules.asset_pipeline.recovery import AssetRecoveryService
from modules.asset_pipeline.repository import AssetVersionRepository
from modules.asset_pipeline.service import AssetService

router = APIRouter(
    tags=["assets"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足"},
    404: {"description": "资产、版本或 Job 不存在"},
    409: {"description": "状态冲突或审批失效"},
    422: {"description": "请求参数校验失败"},
    429: {"description": "触发限流"},
}


def _services(request: Request):
    return request.app.state.services


def _assets(request: Request) -> AssetService:
    return _services(request).get("asset_service", AssetService)


def _generations(request: Request) -> GenerationOrchestrator:
    return _services(request).get("asset_generation_orchestrator", GenerationOrchestrator)


def _processing(request: Request) -> ProcessingPipelineService:
    return _services(request).get("asset_processing_pipeline", ProcessingPipelineService)


def _quality(request: Request) -> QualityControlService:
    return _services(request).get("asset_quality_control", QualityControlService)


def _licenses(request: Request) -> LicenseService:
    return _services(request).get("asset_license_service", LicenseService)


def _imports(request: Request) -> GodotImportService:
    return _services(request).get("asset_import_service", GodotImportService)


def _deliveries(request: Request) -> AssetDeliveryService:
    return _services(request).get("asset_delivery_service", AssetDeliveryService)


def _dependencies(request: Request) -> AssetDependencyService:
    return _services(request).get("asset_dependency_service", AssetDependencyService)


def _dashboard(request: Request) -> AssetDashboardService:
    return _services(request).get("asset_dashboard_service", AssetDashboardService)


async def _asset_project(request: Request, asset_id: str, action: str) -> str:
    view = await _assets(request).get(asset_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


@router.post(
    "/projects/{project_id}/assets",
    status_code=status.HTTP_201_CREATED,
    summary="创建资产",
    responses=_ERRORS,
)
async def create_asset(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: AssetCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E8_ASSET_CREATE)
    view = await _assets(request).create(
        project_id=project_id,
        name=payload.name,
        category=payload.category,
        asset_type=payload.asset_type,
        description=payload.description,
        tags=tuple(payload.tags),
        created_by=request.state.principal.client_id,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/assets",
    summary="列出项目资产",
    description="支持按类别、类型、生命周期、标签、来源与 License 状态过滤。",
    responses=_ERRORS,
)
async def list_assets(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    category: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    tag: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    license_status: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E8_ASSET_READ)
    page = await _assets(request).list(
        project_id=project_id,
        category=category,
        asset_type=asset_type,
        status=status_filter,
        tag=tag,
        source_type=source_type,
        license_status=license_status,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    page["items"] = [asdict(item) for item in page["items"]]
    return page


@router.get(
    "/projects/{project_id}/assets/dashboard",
    summary="资产仪表盘",
    description="资产浏览器聚合视图：质量、License、导入、交付、依赖与 UNKNOWN 清单。",
    responses=_ERRORS,
)
async def asset_dashboard(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E8_ASSET_READ)
    return await _dashboard(request).snapshot(project_id, limit=limit)


@router.get("/assets/{asset_id}", summary="读取资产", responses=_ERRORS)
async def get_asset(
    asset_id: str = Path(min_length=1, max_length=64),
    include_deleted: bool = Query(default=False),
    request: Request = ...,
) -> dict:
    await _asset_project(request, asset_id, ACTION_E8_ASSET_READ)
    return asdict(await _assets(request).get(asset_id, include_deleted=include_deleted))


@router.patch(
    "/assets/{asset_id}/metadata",
    summary="更新资产元数据",
    responses=_ERRORS,
)
async def update_asset_metadata(
    asset_id: str = Path(min_length=1, max_length=64),
    payload: AssetMetadataPatchRequest = ...,
    request: Request = ...,
) -> dict:
    await _asset_project(request, asset_id, ACTION_E8_ASSET_UPDATE)
    view = await _assets(request).update_metadata(
        asset_id,
        name=payload.name,
        description=payload.description,
        tags=tuple(payload.tags) if payload.tags is not None else None,
        expected_version=payload.expected_version,
    )
    return asdict(view)


@router.get("/assets/{asset_id}/versions", summary="列出资产版本", responses=_ERRORS)
async def list_asset_versions(
    asset_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    await _asset_project(request, asset_id, ACTION_E8_ASSET_READ)
    database: DatabaseService = _services(request).get("database", DatabaseService)
    async with database.session() as session:
        rows = await AssetVersionRepository(session).list_for_asset(asset_id)
        items = [
            {
                "version_id": row.version_id,
                "asset_id": row.asset_id,
                "version_number": row.version_number,
                "parent_version_id": row.parent_version_id,
                "content_hash": row.content_hash,
                "source_type": row.source_type,
                "metadata": row.metadata_json,
                "created_by": row.created_by,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    return {"items": items, "total": len(items)}


@router.get(
    "/assets/{asset_id}/dependencies",
    summary="读取资产依赖",
    responses=_ERRORS,
)
async def list_asset_dependencies(
    asset_id: str = Path(min_length=1, max_length=64),
    version_id: str | None = Query(default=None, max_length=64),
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(request, asset_id, ACTION_E8_ASSET_READ)
    if version_id is None:
        version_id = (await _assets(request).get(asset_id)).current_version_id
    if version_id is None:
        return {"items": [], "total": 0}
    items = await _dependencies(request).list_for_version(project_id, version_id)
    return {"items": [asdict(item) for item in items], "total": len(items)}


@router.post(
    "/assets/{asset_id}/generations",
    status_code=status.HTTP_202_ACCEPTED,
    summary="请求资产生成",
    description="通过 Model Gateway 提交生成任务；幂等键冲突时返回原任务。",
    responses=_ERRORS,
)
async def create_generation(
    asset_id: str = Path(min_length=1, max_length=64),
    payload: GenerationCreateRequest = ...,
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(request, asset_id, ACTION_E8_ASSET_GENERATE)
    view = await _generations(request).submit(
        GenerationRequest(
            project_id=project_id,
            asset_id=asset_id,
            kind=payload.kind,
            prompt=payload.prompt,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
            brief_id=payload.brief_id,
            parameters=payload.parameters,
            output_count=payload.output_count,
            budget=payload.budget,
            timeout_seconds=payload.timeout_seconds,
            idempotency_key=payload.idempotency_key,
            created_by=request.state.principal.client_id,
        )
    )
    return asdict(view)


@router.get("/generations/{generation_id}", summary="读取生成任务", responses=_ERRORS)
async def get_generation(
    generation_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _generations(request).get(generation_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_READ)
    return asdict(view)


@router.post(
    "/generations/{generation_id}/cancel",
    summary="取消生成任务",
    responses=_ERRORS,
)
async def cancel_generation(
    generation_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _generations(request).get(generation_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_GENERATE)
    return asdict(await _generations(request).cancel(generation_id))


@router.post(
    "/generations/{generation_id}/reconcile",
    summary="核对 UNKNOWN 生成",
    description="只查询 Provider 状态，不重复提交生成任务。",
    responses=_ERRORS,
)
async def reconcile_generation(
    generation_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _generations(request).get(generation_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_GENERATE)
    recovery = _services(request).get(
        "asset_recovery_service", AssetRecoveryService
    )
    result = await recovery.resolve_generation(view.project_id, generation_id)
    return asdict(result)


@router.post(
    "/assets/{asset_id}/processing-jobs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="创建资产处理任务",
    responses=_ERRORS,
)
async def create_processing_job(
    asset_id: str = Path(min_length=1, max_length=64),
    payload: ProcessingJobCreateRequest = ...,
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(request, asset_id, ACTION_E8_ASSET_PROCESS)
    view = await _processing(request).submit(
        ProcessingRequest(
            project_id=project_id,
            asset_id=asset_id,
            input_version_id=payload.input_version_id,
            graph=payload.graph,
            idempotency_key=payload.idempotency_key,
            created_by=request.state.principal.client_id,
        )
    )
    return asdict(view)


@router.get(
    "/processing-jobs/{job_id}", summary="读取处理任务", responses=_ERRORS
)
async def get_processing_job(
    job_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _processing(request).get(job_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_READ)
    return asdict(view)


@router.post(
    "/assets/{asset_id}/quality-reviews",
    status_code=status.HTTP_201_CREATED,
    summary="运行机器质量审核",
    responses=_ERRORS,
)
async def create_quality_review(
    asset_id: str = Path(min_length=1, max_length=64),
    payload: QualityReviewCreateRequest = ...,
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(request, asset_id, ACTION_E8_ASSET_REVIEW_QUALITY)
    view = await _quality(request).run_machine_review(
        project_id, asset_id, payload.version_id, rules=payload.rules
    )
    return asdict(view)


@router.post(
    "/quality-reviews/{review_id}/request-human",
    summary="申请人工审核",
    responses=_ERRORS,
)
async def request_human_review(
    review_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _quality(request).get_review(review_id)
    project_id = await _asset_project(
        request, view.asset_id, ACTION_E8_ASSET_REVIEW_QUALITY
    )
    result = await _quality(request).request_human_review(
        project_id,
        view.asset_id,
        view.asset_version_id,
        notes=f"requested from {review_id}",
        reviewer_id=request.state.principal.client_id,
    )
    return asdict(result)


@router.post(
    "/quality-reviews/{review_id}/decision",
    summary="提交人工审核结论",
    responses=_ERRORS,
)
async def decide_quality_review(
    review_id: str = Path(min_length=1, max_length=64),
    payload: QualityDecisionRequest = ...,
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(
        request, payload.asset_id, ACTION_E8_ASSET_REVIEW_QUALITY
    )
    view = await _quality(request).record_human_decision(
        project_id,
        payload.asset_id,
        review_id,
        approved=payload.approved,
        reviewer_id=request.state.principal.client_id,
        notes=payload.notes,
    )
    return asdict(view)


@router.post(
    "/assets/{asset_id}/license-reviews",
    status_code=status.HTTP_201_CREATED,
    summary="登记 License 与授权证据",
    responses=_ERRORS,
)
async def create_license_review(
    asset_id: str = Path(min_length=1, max_length=64),
    payload: LicenseReviewCreateRequest = ...,
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(request, asset_id, ACTION_E8_ASSET_REVIEW_LICENSE)
    view = await _licenses(request).record(
        LicenseRequest(
            project_id=project_id,
            asset_id=asset_id,
            asset_version_id=payload.version_id,
            license_name=payload.license_name,
            source_type=payload.source_type,
            license_family=payload.license_family,
            source_reference=payload.source_reference,
            commercial_use=payload.commercial_use,
            modification_allowed=payload.modification_allowed,
            redistribution_allowed=payload.redistribution_allowed,
            attribution_required=payload.attribution_required,
            attribution_text=payload.attribution_text,
            expiration_at=payload.expiration_at,
            territory=payload.territory,
            evidence=[
                LicenseEvidenceInput(
                    evidence_type=str(item.get("evidence_type", "")),
                    reference=str(item.get("reference", "")),
                    content_hash=item.get("content_hash"),
                    metadata=item.get("metadata") or {},
                )
                for item in payload.evidence
            ],
        )
    )
    return asdict(view)


@router.get("/assets/{asset_id}/license", summary="读取当前 License", responses=_ERRORS)
async def get_asset_license(
    asset_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    project_id = await _asset_project(request, asset_id, ACTION_E8_ASSET_READ)
    asset = await _assets(request).get(asset_id)
    if not asset.current_version_id:
        raise NotFoundError("资产没有可用版本", details={"asset_id": asset_id})
    view = await _licenses(request).latest_for_version(
        project_id, asset.current_version_id
    )
    return asdict(view)


@router.post(
    "/license-reviews/{license_id}/decision",
    summary="核验 License",
    responses=_ERRORS,
)
async def decide_license(
    license_id: str = Path(min_length=1, max_length=64),
    payload: LicenseDecisionRequest = ...,
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(
        request, payload.asset_id, ACTION_E8_ASSET_REVIEW_LICENSE
    )
    view = await _licenses(request).verify(
        project_id,
        license_id,
        reviewer_id=request.state.principal.client_id,
        commercial_use=payload.commercial_use,
        modification_allowed=payload.modification_allowed,
        redistribution_allowed=payload.redistribution_allowed,
        attribution_required=payload.attribution_required,
        attribution_text=payload.attribution_text,
        expiration_at=payload.expiration_at,
        territory=payload.territory,
        verification_method=payload.verification_method,
    )
    return asdict(view)


@router.post(
    "/assets/{asset_id}/imports",
    status_code=status.HTTP_202_ACCEPTED,
    summary="请求 Godot 真实导入",
    responses=_ERRORS,
)
async def create_import_job(
    asset_id: str = Path(min_length=1, max_length=64),
    payload: ImportCreateRequest = ...,
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(request, asset_id, ACTION_E8_ASSET_IMPORT)
    view = await _imports(request).submit(
        ImportRequest(
            project_id=project_id,
            asset_version_id=payload.version_id,
            target_path=payload.target_path,
            session_id=payload.session_id,
            changeset_id=payload.changeset_id,
            resource_type=payload.resource_type,
            idempotency_key=payload.idempotency_key,
            created_by=request.state.principal.client_id,
            timeout_seconds=payload.timeout_seconds,
        )
    )
    return asdict(view)


@router.get("/import-jobs/{import_job_id}", summary="读取导入任务", responses=_ERRORS)
async def get_import_job(
    import_job_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _imports(request).get(import_job_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_READ)
    return asdict(view)


@router.post(
    "/import-jobs/{import_job_id}/reconcile",
    summary="按 Editor 状态核对导入",
    description="只读查询真实导入状态，不重复导入。",
    responses=_ERRORS,
)
async def reconcile_import_job(
    import_job_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _imports(request).get(import_job_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_IMPORT)
    recovery = _services(request).get(
        "asset_recovery_service", AssetRecoveryService
    )
    result = await recovery.resolve_import(view.project_id, import_job_id)
    return asdict(result)


@router.post(
    "/assets/{asset_id}/delivery-plans",
    status_code=status.HTTP_201_CREATED,
    summary="创建资产交付计划",
    description=(
        "校验来源完整性、质量审核与 License 后生成 ChangeSet；"
        "交付本身仍需审批与 Tool System 写入。"
    ),
    responses=_ERRORS,
)
async def create_delivery_plan(
    asset_id: str = Path(min_length=1, max_length=64),
    payload: DeliveryPlanCreateRequest = ...,
    request: Request = ...,
) -> dict:
    project_id = await _asset_project(request, asset_id, ACTION_E8_ASSET_DELIVER)
    view = await _deliveries(request).prepare(
        DeliveryRequest(
            project_id=project_id,
            asset_id=asset_id,
            asset_version_id=payload.version_id,
            target_path=payload.target_path,
            resource_type=payload.resource_type,
            operation_type=payload.operation_type,
            old_content_hash=payload.old_content_hash,
            risk_level=payload.risk_level,
            title=payload.title,
            require_human_review=payload.require_human_review,
            require_commercial_use=payload.require_commercial_use,
            require_redistribution=payload.require_redistribution,
            created_by=request.state.principal.client_id,
            approval_ttl_seconds=payload.approval_ttl_seconds,
        )
    )
    return asdict(view)


@router.get(
    "/deliveries/{delivery_id}", summary="读取交付状态", responses=_ERRORS
)
async def get_delivery(
    delivery_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _deliveries(request).get(delivery_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_READ)
    return asdict(view)


@router.post(
    "/deliveries/{delivery_id}/submit",
    summary="提交交付审批",
    responses=_ERRORS,
)
async def submit_delivery(
    delivery_id: str = Path(min_length=1, max_length=64),
    ttl_seconds: int = Query(default=86400, gt=0, le=7 * 86400),
    request: Request = ...,
) -> dict:
    view = await _deliveries(request).get(delivery_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_DELIVER)
    approval = await _deliveries(request).submit_for_approval(
        delivery_id,
        requested_by=request.state.principal.client_id,
        ttl_seconds=ttl_seconds,
    )
    return asdict(approval)


@router.post(
    "/deliveries/{delivery_id}/approve",
    summary="审批资产交付",
    responses=_ERRORS,
)
async def approve_delivery(
    delivery_id: str = Path(min_length=1, max_length=64),
    payload: DeliveryApprovalRequest = ...,
    request: Request = ...,
) -> dict:
    view = await _deliveries(request).get(delivery_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_DELIVER)
    result = await _deliveries(request).approve(
        delivery_id,
        payload.approval_id,
        actor_id=request.state.principal.client_id,
        reason=payload.reason,
    )
    return asdict(result)


@router.get(
    "/deliveries/{delivery_id}/approval",
    summary="校验交付审批是否仍有效",
    responses=_ERRORS,
)
async def check_delivery_approval(
    delivery_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _deliveries(request).get(delivery_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_READ)
    return await _deliveries(request).check_approval(delivery_id)


@router.get("/deliveries/{delivery_id}/verify", summary="验证交付结果", responses=_ERRORS)
async def verify_delivery(
    delivery_id: str = Path(min_length=1, max_length=64), request: Request = ...
) -> dict:
    view = await _deliveries(request).get(delivery_id)
    await authorize_project_action(request, view.project_id, ACTION_E8_ASSET_READ)
    import_view = None
    if view.import_job_id:
        import_view = asdict(await _imports(request).get(view.import_job_id))
    return {
        "delivery_id": delivery_id,
        "delivery_status": view.delivery_status,
        "delivered_at": view.delivered_at,
        "import": import_view,
        "approval": await _deliveries(request).check_approval(delivery_id),
        "verified_at": utcnow(),
    }
