"""E10 制品、交付包、构建来源与发布证据 API（Batch C）。

制品内容不可变；交付包与来源证据只追加；所有操作按项目授权。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.build_release import (
    ArtifactIntegrityRequest,
    ArtifactRegisterRequest,
    ArtifactTransitionRequest,
    EvidenceAddRequest,
    PackageCreateRequest,
    ProvenanceRecordRequest,
    ReleaseCandidateCreateRequest,
    SmokeTestRecordRequest,
)
from core.security.principal import (
    ACTION_E10_ARTIFACT_READ,
    ACTION_E10_ARTIFACT_VERIFY,
    ACTION_E10_BUILD_CREATE,
    ACTION_E10_BUILD_READ,
    ACTION_E10_PACKAGE_CREATE,
    ACTION_E10_RELEASE_MANAGE,
    ACTION_E10_RELEASE_READ,
)
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.packaging import PackagingService
from modules.build_release.provenance import BuildProvenanceService
from modules.build_release.release_candidates import ReleaseCandidateService
from modules.build_release.smoke_test import ArtifactVerificationService, SmokeTestService

router = APIRouter(
    tags=["artifacts"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足"},
    404: {"description": "制品、交付包或证据不存在"},
    409: {"description": "状态冲突或内容哈希不一致"},
    422: {"description": "请求参数校验失败"},
    429: {"description": "触发限流"},
}


def _artifacts(request: Request) -> ArtifactRegistryService:
    return request.app.state.services.get("artifact_registry_service", ArtifactRegistryService)


def _packages(request: Request) -> PackagingService:
    return request.app.state.services.get("packaging_service", PackagingService)


def _provenance(request: Request) -> BuildProvenanceService:
    return request.app.state.services.get("provenance_service", BuildProvenanceService)


def _candidates(request: Request) -> ReleaseCandidateService:
    return request.app.state.services.get("release_candidate_service", ReleaseCandidateService)


def _verification(request: Request) -> ArtifactVerificationService:
    return request.app.state.services.get(
        "artifact_verification_service", ArtifactVerificationService
    )


def _smoke(request: Request) -> SmokeTestService:
    return request.app.state.services.get("smoke_test_service", SmokeTestService)


async def _authorize_artifact(request: Request, artifact_id: str, action: str) -> str:
    view = await _artifacts(request).get_artifact(artifact_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


async def _authorize_candidate(request: Request, candidate_id: str, action: str) -> str:
    view = await _candidates(request).get_candidate(candidate_id)
    await authorize_project_action(request, view.project_id, action)
    return view.project_id


@router.post(
    "/projects/{project_id}/artifacts",
    status_code=status.HTTP_201_CREATED,
    summary="登记不可变构建制品",
    responses=_ERRORS,
)
async def register_artifact(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: ArtifactRegisterRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_CREATE)
    view = await _artifacts(request).register_artifact(
        project_id=project_id,
        platform=payload.platform,
        architecture=payload.architecture,
        storage_reference=payload.storage_reference,
        files=[item.model_dump() for item in payload.files],
        build_id=payload.build_id,
        attempt_id=payload.attempt_id,
        name=payload.name,
        format=payload.format,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/artifacts",
    summary="列出项目制品",
    responses=_ERRORS,
)
async def list_artifacts(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    platform: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_ARTIFACT_READ)
    page = await _artifacts(request).list_artifacts(
        project_id, platform=platform, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/artifacts/{artifact_id}",
    summary="获取制品",
    responses=_ERRORS,
)
async def get_artifact(
    artifact_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_artifact(request, artifact_id, ACTION_E10_ARTIFACT_READ)
    view = await _artifacts(request).get_artifact(artifact_id)
    return asdict(view)


@router.get(
    "/builds/{build_id}/artifacts",
    summary="列出构建产生的制品",
    responses=_ERRORS,
)
async def list_build_artifacts(
    build_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    build = await request.app.state.services.get("build_orchestrator").get_build(build_id)
    await authorize_project_action(request, build.project_id, ACTION_E10_ARTIFACT_READ)
    items = await _artifacts(request).list_build_artifacts(build_id)
    return {"items": [asdict(item) for item in items]}


@router.post(
    "/artifacts/{artifact_id}/transition",
    summary="迁移制品验证状态",
    responses=_ERRORS,
)
async def transition_artifact_status(
    artifact_id: str = Path(min_length=1, max_length=64),
    payload: ArtifactTransitionRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_artifact(request, artifact_id, ACTION_E10_ARTIFACT_VERIFY)
    view = await _artifacts(request).transition_verification(
        artifact_id, payload.status, reason=payload.reason
    )
    return asdict(view)


@router.post(
    "/artifacts/{artifact_id}/verify-integrity",
    summary="校验制品完整性",
    responses=_ERRORS,
)
async def verify_artifact_integrity(
    artifact_id: str = Path(min_length=1, max_length=64),
    payload: ArtifactIntegrityRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_artifact(request, artifact_id, ACTION_E10_ARTIFACT_VERIFY)
    ok = await _artifacts(request).verify_integrity(
        artifact_id, [item.model_dump() for item in payload.files]
    )
    return {"artifact_id": artifact_id, "verified": ok}


@router.post(
    "/projects/{project_id}/packages",
    status_code=status.HTTP_201_CREATED,
    summary="创建交付包",
    responses=_ERRORS,
)
async def create_package(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: PackageCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_PACKAGE_CREATE)
    view = await _packages(request).create_package(
        project_id=project_id,
        artifact_id=payload.artifact_id,
        format=payload.format,
        storage_reference=payload.storage_reference,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/packages",
    summary="列出交付包",
    responses=_ERRORS,
)
async def list_packages(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_ARTIFACT_READ)
    page = await _packages(request).list_packages(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/packages/{package_id}",
    summary="获取交付包",
    responses=_ERRORS,
)
async def get_package(
    package_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _packages(request).get_package(package_id)
    await authorize_project_action(request, view.project_id, ACTION_E10_ARTIFACT_READ)
    return asdict(view)


@router.post(
    "/packages/{package_id}/verify",
    summary="校验交付包完整性",
    responses=_ERRORS,
)
async def verify_package(
    package_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _packages(request).get_package(package_id)
    await authorize_project_action(request, view.project_id, ACTION_E10_ARTIFACT_VERIFY)
    result = await _packages(request).verify_package(package_id)
    return asdict(result)


@router.post(
    "/projects/{project_id}/build-provenance",
    status_code=status.HTTP_201_CREATED,
    summary="记录构建来源",
    responses=_ERRORS,
)
async def record_provenance(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: ProvenanceRecordRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_BUILD_READ)
    view = await _provenance(request).record_provenance(
        project_id=project_id,
        build_id=payload.build_id,
        attempt_id=payload.attempt_id,
        artifact_id=payload.artifact_id,
        source_revision=payload.source_revision,
        config_snapshot_hash=payload.config_snapshot_hash,
        environment_fingerprint=payload.environment_fingerprint,
        command_template_id=payload.command_template_id,
        executor_id=payload.executor_id,
        inputs=dict(payload.inputs),
        outputs=dict(payload.outputs),
    )
    return asdict(view)


@router.get(
    "/builds/{build_id}/provenance",
    summary="列出构建来源",
    responses=_ERRORS,
)
async def list_build_provenance(
    build_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    build = await request.app.state.services.get("build_orchestrator").get_build(build_id)
    await authorize_project_action(request, build.project_id, ACTION_E10_BUILD_READ)
    items = await _provenance(request).list_provenance(build_id)
    return {"items": [asdict(item) for item in items]}


@router.post(
    "/projects/{project_id}/release-evidence",
    status_code=status.HTTP_201_CREATED,
    summary="追加发布证据",
    responses=_ERRORS,
)
async def add_release_evidence(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: EvidenceAddRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_ARTIFACT_VERIFY)
    view = await _provenance(request).add_evidence(
        project_id=project_id,
        evidence_type=payload.evidence_type,
        artifact_id=payload.artifact_id,
        package_id=payload.package_id,
        release_candidate_id=payload.release_candidate_id,
        reference=payload.reference,
        content_hash=payload.content_hash,
        details=dict(payload.details),
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/release-evidence",
    summary="列出发布证据",
    responses=_ERRORS,
)
async def list_release_evidence(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    evidence_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_ARTIFACT_READ)
    page = await _provenance(request).list_evidence(
        project_id, evidence_type=evidence_type, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.post(
    "/artifacts/{artifact_id}/verify",
    summary="验证制品并标记通过",
    responses=_ERRORS,
)
async def verify_artifact(
    artifact_id: str = Path(min_length=1, max_length=64),
    payload: ArtifactIntegrityRequest = ...,
    request: Request = ...,
) -> dict:
    await _authorize_artifact(request, artifact_id, ACTION_E10_ARTIFACT_VERIFY)
    view = await _verification(request).verify_artifact(
        artifact_id, [item.model_dump() for item in payload.files]
    )
    return asdict(view)


@router.post(
    "/projects/{project_id}/release-candidates",
    status_code=status.HTTP_201_CREATED,
    summary="创建发布候选",
    responses=_ERRORS,
)
async def create_release_candidate(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: ReleaseCandidateCreateRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_RELEASE_MANAGE)
    principal = getattr(request.state, "principal", None)
    created_by = getattr(principal, "client_id", None)
    view = await _candidates(request).create_candidate(
        project_id=project_id,
        version=payload.version,
        artifact_id=payload.artifact_id,
        package_id=payload.package_id,
        verification_campaign_id=payload.verification_campaign_id,
        created_by=created_by,
    )
    return asdict(view)


@router.get(
    "/projects/{project_id}/release-candidates",
    summary="列出发布候选",
    responses=_ERRORS,
)
async def list_release_candidates(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_RELEASE_READ)
    page = await _candidates(request).list_candidates(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [asdict(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/release-candidates/{release_candidate_id}",
    summary="获取发布候选",
    responses=_ERRORS,
)
async def get_release_candidate(
    release_candidate_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    view = await _candidates(request).get_candidate(release_candidate_id)
    await authorize_project_action(request, view.project_id, ACTION_E10_RELEASE_READ)
    return asdict(view)


@router.post(
    "/release-candidates/{release_candidate_id}/validate",
    summary="校验发布候选清单",
    responses=_ERRORS,
)
async def validate_release_candidate(
    release_candidate_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_candidate(request, release_candidate_id, ACTION_E10_RELEASE_MANAGE)
    view = await _candidates(request).validate_candidate(release_candidate_id)
    return asdict(view)


@router.post(
    "/release-candidates/{release_candidate_id}/reject",
    summary="驳回发布候选",
    responses=_ERRORS,
)
async def reject_release_candidate(
    release_candidate_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_candidate(request, release_candidate_id, ACTION_E10_RELEASE_MANAGE)
    view = await _candidates(request).reject_candidate(release_candidate_id)
    return asdict(view)


@router.post(
    "/release-candidates/{release_candidate_id}/invalidate",
    summary="失效发布候选",
    responses=_ERRORS,
)
async def invalidate_release_candidate(
    release_candidate_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_candidate(request, release_candidate_id, ACTION_E10_RELEASE_MANAGE)
    view = await _candidates(request).invalidate_candidate(release_candidate_id)
    return asdict(view)


@router.post(
    "/release-candidates/{release_candidate_id}/supersede",
    summary="标记发布候选被取代",
    responses=_ERRORS,
)
async def supersede_release_candidate(
    release_candidate_id: str = Path(min_length=1, max_length=64),
    superseded_by: str | None = Query(default=None, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_candidate(request, release_candidate_id, ACTION_E10_RELEASE_MANAGE)
    view = await _candidates(request).supersede_candidate(
        release_candidate_id, superseded_by=superseded_by
    )
    return asdict(view)


@router.post(
    "/projects/{project_id}/smoke-tests",
    status_code=status.HTTP_201_CREATED,
    summary="记录冒烟测试结果",
    responses=_ERRORS,
)
async def record_smoke_test(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: SmokeTestRecordRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E10_RELEASE_MANAGE)
    view = await _smoke(request).record_smoke_test(
        project_id=project_id,
        checks=[item.model_dump() for item in payload.checks],
        artifact_id=payload.artifact_id,
        package_id=payload.package_id,
        release_candidate_id=payload.release_candidate_id,
        evidence_reference=payload.evidence_reference,
        duration_ms=payload.duration_ms,
    )
    return asdict(view)


@router.get(
    "/release-candidates/{release_candidate_id}/smoke-tests",
    summary="列出发布候选的冒烟测试",
    responses=_ERRORS,
)
async def list_release_candidate_smoke_tests(
    release_candidate_id: str = Path(min_length=1, max_length=64),
    request: Request = ...,
) -> dict:
    await _authorize_candidate(request, release_candidate_id, ACTION_E10_RELEASE_READ)
    items = await _smoke(request).list_for_candidate(release_candidate_id)
    return {"items": [asdict(item) for item in items]}
