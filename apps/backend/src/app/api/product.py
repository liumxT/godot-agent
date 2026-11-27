"""E12 产品化 API：信息、安装、配置、授权、更新、迁移、恢复、诊断与发布。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import enforce_rate_limit, require_action, require_authenticated
from app.schemas.product import (
    ConfigurationProfileRequest,
    ContextPreviewRequest,
    CrashReportRequest,
    DeleteDataRequest,
    FirstRunRequest,
    InstallationPreflightRequest,
    InstallationStartRequest,
    InstallationVerifyRequest,
    LicenseFeatureRequest,
    LicenseRegisterRequest,
    MigrationExecuteRequest,
    MigrationPlanRequest,
    PluginInstallApplyRequest,
    PluginInstallPlanRequest,
    RecoveryExecuteRequest,
    RecoveryInspectRequest,
    RecoveryPointRequest,
    ReleaseApproveRequest,
    ReleaseCandidateRequest,
    ReleasePublishRequest,
    ReleaseRejectRequest,
    SupportBundleExportRequest,
    SupportBundlePrepareRequest,
    TelemetryRequest,
    UninstallRequest,
    UpdateManifestRequest,
    UpdateOperationRequest,
)
from core.security.principal import (
    ACTION_E12_PRODUCT_CONFIGURE,
    ACTION_E12_PRODUCT_INSTALL,
    ACTION_E12_PRODUCT_LICENSE_MANAGE,
    ACTION_E12_PRODUCT_MIGRATE,
    ACTION_E12_PRODUCT_PRIVACY_MANAGE,
    ACTION_E12_PRODUCT_READ,
    ACTION_E12_PRODUCT_RECOVER,
    ACTION_E12_PRODUCT_RELEASE_APPROVE,
    ACTION_E12_PRODUCT_RELEASE_PUBLISH,
    ACTION_E12_PRODUCT_SUPPORT_BUNDLE,
    ACTION_E12_PRODUCT_UPDATE,
)
from modules.product.compatibility import check_environment, matrix
from modules.product.configuration import ProductConfigurationService
from modules.product.diagnostics import DiagnosticsService
from modules.product.installer import InstallationService
from modules.product.licensing import LicenseService
from modules.product.migrations import ProductMigrationService
from modules.product.privacy import PrivacyService
from modules.product.recovery import RecoveryService
from modules.product.release_pipeline import ProductReleaseService, build_sbom
from modules.product.service import ProductService
from modules.product.updates import UpdateService
from modules.product.versioning import (
    PRODUCT_VERSION,
    contract_manifest,
    declared_component_versions,
)

router = APIRouter(
    prefix="/product",
    tags=["product"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

READ = [Depends(require_action(ACTION_E12_PRODUCT_READ))]
INSTALL = [Depends(require_action(ACTION_E12_PRODUCT_INSTALL))]
CONFIGURE = [Depends(require_action(ACTION_E12_PRODUCT_CONFIGURE))]
UPDATE = [Depends(require_action(ACTION_E12_PRODUCT_UPDATE))]
MIGRATE = [Depends(require_action(ACTION_E12_PRODUCT_MIGRATE))]
RECOVER = [Depends(require_action(ACTION_E12_PRODUCT_RECOVER))]
LICENSE = [Depends(require_action(ACTION_E12_PRODUCT_LICENSE_MANAGE))]
PRIVACY = [Depends(require_action(ACTION_E12_PRODUCT_PRIVACY_MANAGE))]
DIAGNOSTICS = [Depends(require_action(ACTION_E12_PRODUCT_SUPPORT_BUNDLE))]
APPROVE = [Depends(require_action(ACTION_E12_PRODUCT_RELEASE_APPROVE))]
PUBLISH = [Depends(require_action(ACTION_E12_PRODUCT_RELEASE_PUBLISH))]


def _service(request: Request, name: str, cls: type) -> Any:
    return request.app.state.services.get(name, cls)


def _actor(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    return getattr(principal, "client_id", "unknown")


async def _audit(
    request: Request,
    *,
    action: str,
    target: str = "",
    detail: dict[str, Any] | None = None,
    outcome: str = "SUCCESS",
) -> None:
    service = _service(request, "product_service", ProductService)
    await service.audit(
        action=action, actor_id=_actor(request), outcome=outcome, target=target, detail=detail
    )


# ------------------------------------------------------------------- metadata
@router.get("/info", summary="产品信息", name="product_info", dependencies=READ)
async def product_info(request: Request) -> dict[str, Any]:
    return await _service(request, "product_service", ProductService).info()


@router.get("/version", summary="产品版本", name="product_version", dependencies=READ)
async def product_version() -> dict[str, str]:
    return {"product_version": PRODUCT_VERSION}


@router.get("/components", summary="产品组件版本", name="product_components", dependencies=READ)
async def product_components() -> dict[str, Any]:
    return {
        "components": declared_component_versions(),
    }


@router.get("/contracts", summary="公开契约版本", name="product_contracts", dependencies=READ)
async def product_contracts() -> dict[str, Any]:
    return {"contracts": contract_manifest()}


@router.get(
    "/compatibility", summary="环境兼容性检查", name="product_compatibility", dependencies=READ
)
async def product_compatibility(
    os_name: str | None = Query(default=None, alias="os"),
    architecture: str | None = None,
    godot_version: str | None = None,
    plugin_version: str | None = None,
    protocol_version: str | None = None,
    database_schema: str | None = None,
    credential_store: bool | None = None,
    disk_free_gb: float | None = None,
    python_version: str | None = None,
    network: bool | None = None,
    port_available: bool | None = None,
) -> dict[str, Any]:
    environment = {
        "os": os_name,
        "architecture": architecture,
        "godot_version": godot_version,
        "plugin_version": plugin_version,
        "protocol_version": protocol_version,
        "database_schema": database_schema,
        "credential_store": credential_store,
        "disk_free_gb": disk_free_gb,
        "python_version": python_version,
        "network": network,
        "port_available": port_available,
    }
    return {"matrix": matrix(), "report": check_environment(environment).to_dict()}


@router.get(
    "/capabilities", summary="产品能力与授权", name="product_capabilities", dependencies=READ
)
async def product_capabilities(request: Request) -> dict[str, Any]:
    return await _service(request, "product_service", ProductService).capabilities()


@router.get("/health", summary="产品健康检查", name="product_health", dependencies=READ)
async def product_health(request: Request) -> dict[str, Any]:
    return await _service(request, "product_service", ProductService).health()


# ---------------------------------------------------------------- installation
@router.post(
    "/installations/preflight",
    summary="安装前检查",
    name="product_installation_preflight",
    dependencies=INSTALL,
)
async def installation_preflight(
    request: Request, payload: InstallationPreflightRequest
) -> dict[str, Any]:
    return _service(request, "installation_service", InstallationService).preflight(
        install_dir=payload.install_dir,
        data_dir=payload.data_dir,
        components=payload.components,
        disk_free_gb=payload.disk_free_gb,
        writable=payload.writable,
    )


@router.post(
    "/installations", summary="开始安装", name="product_installation_start", dependencies=INSTALL
)
async def installation_start(request: Request, payload: InstallationStartRequest) -> dict[str, Any]:
    result = await _service(request, "installation_service", InstallationService).start(
        install_dir=payload.install_dir,
        data_dir=payload.data_dir,
        config_dir=payload.config_dir,
        log_dir=payload.log_dir,
        database_path=payload.database_path,
        components=payload.components,
        disk_free_gb=payload.disk_free_gb,
        writable=payload.writable,
    )
    await _audit(request, action="product.install.start", target=result["installation_id"])
    return result


@router.get(
    "/installations/latest",
    summary="最近安装状态",
    name="product_installation_latest",
    dependencies=READ,
)
async def installation_latest(request: Request) -> dict[str, Any]:
    return {
        "installation": await _service(
            request, "installation_service", InstallationService
        ).latest()
    }


@router.get(
    "/installations/{installation_id}",
    summary="安装详情",
    name="product_installation_get",
    dependencies=READ,
)
async def installation_get(request: Request, installation_id: str) -> dict[str, Any]:
    return await _service(request, "installation_service", InstallationService).get(installation_id)


@router.post(
    "/installations/{installation_id}/verify",
    summary="安装后检查",
    name="product_installation_verify",
    dependencies=INSTALL,
)
async def installation_verify(
    request: Request, installation_id: str, payload: InstallationVerifyRequest
) -> dict[str, Any]:
    result = await _service(request, "installation_service", InstallationService).verify(
        installation_id, payload.verification
    )
    await _audit(
        request,
        action="product.install.verify",
        target=installation_id,
        detail={"status": result["status"]},
    )
    return result


@router.post(
    "/installations/{installation_id}/rollback",
    summary="回滚安装",
    name="product_installation_rollback",
    dependencies=INSTALL,
)
async def installation_rollback(request: Request, installation_id: str) -> dict[str, Any]:
    result = await _service(request, "installation_service", InstallationService).rollback(
        installation_id
    )
    await _audit(request, action="product.install.rollback", target=installation_id)
    return result


@router.post(
    "/installations/{installation_id}/uninstall",
    summary="卸载计划",
    name="product_installation_uninstall",
    dependencies=INSTALL,
)
async def installation_uninstall(
    request: Request, installation_id: str, payload: UninstallRequest
) -> dict[str, Any]:
    result = await _service(request, "installation_service", InstallationService).uninstall(
        installation_id, remove_user_data=payload.remove_user_data
    )
    await _audit(
        request,
        action="product.uninstall.plan",
        target=installation_id,
        detail={"remove_user_data": payload.remove_user_data},
    )
    return result


@router.post(
    "/plugin-install/plan",
    summary="Plugin 安装计划",
    name="product_plugin_install_plan",
    dependencies=INSTALL,
)
async def plugin_install_plan(
    request: Request, payload: PluginInstallPlanRequest
) -> dict[str, Any]:
    return _service(request, "installation_service", InstallationService).plugin_install_plan(
        project_dir=payload.project_dir,
        plugin_version=payload.plugin_version,
        existing_version=payload.existing_version,
        modified_files=payload.modified_files,
        source=payload.source,
    )


@router.post(
    "/plugin-install/apply",
    summary="执行 Plugin 安装",
    name="product_plugin_install_apply",
    dependencies=INSTALL,
)
async def plugin_install_apply(
    request: Request, payload: PluginInstallApplyRequest
) -> dict[str, Any]:
    result = _service(request, "installation_service", InstallationService).apply_plugin_install(
        payload.plan,
        confirmed=payload.confirmed,
        overwrite_user_modified=payload.overwrite_user_modified,
    )
    await _audit(
        request,
        action="product.plugin.install",
        target=str(payload.plan.get("project_dir", "")),
        detail={"action": payload.plan.get("action")},
    )
    return result


@router.post("/first-run", summary="首次运行向导", name="product_first_run", dependencies=READ)
async def first_run(request: Request, payload: FirstRunRequest) -> dict[str, Any]:
    return _service(request, "installation_service", InstallationService).first_run_wizard(
        payload.context
    )


# ----------------------------------------------------------------- configuration
@router.get(
    "/configuration", summary="有效产品配置", name="product_configuration", dependencies=READ
)
async def configuration(request: Request) -> dict[str, Any]:
    return await _service(
        request, "configuration_service", ProductConfigurationService
    ).resolve_effective()


@router.get(
    "/configuration/export",
    summary="安全导出配置",
    name="product_configuration_export",
    dependencies=CONFIGURE,
)
async def configuration_export(request: Request) -> dict[str, Any]:
    return await _service(
        request, "configuration_service", ProductConfigurationService
    ).export_safe()


@router.get(
    "/configuration/profiles",
    summary="配置 Profile 列表",
    name="product_configuration_profiles",
    dependencies=READ,
)
async def configuration_profiles(request: Request) -> dict[str, Any]:
    rows = await _service(
        request, "configuration_service", ProductConfigurationService
    ).list_profiles()
    return {"profiles": rows}


@router.put(
    "/configuration/profiles",
    summary="写入配置 Profile",
    name="product_configuration_upsert",
    dependencies=CONFIGURE,
)
async def configuration_upsert(
    request: Request, payload: ConfigurationProfileRequest
) -> dict[str, Any]:
    result = await _service(
        request, "configuration_service", ProductConfigurationService
    ).upsert_profile(
        profile_name=payload.profile_name,
        scope=payload.scope,
        values=payload.values,
        profile_version=payload.profile_version,
        status=payload.status,
    )
    await _audit(
        request,
        action="product.configuration.update",
        target=payload.profile_name,
        detail={"scope": payload.scope},
    )
    return result


# --------------------------------------------------------------------- license
@router.get("/license", summary="授权状态", name="product_license", dependencies=READ)
async def license_state(request: Request) -> dict[str, Any]:
    service = _service(request, "license_service", LicenseService)
    await service.ensure_development_license()
    return await service.evaluate()


@router.post("/license", summary="登记授权", name="product_license_register", dependencies=LICENSE)
async def license_register(request: Request, payload: LicenseRegisterRequest) -> dict[str, Any]:
    service = _service(request, "license_service", LicenseService)
    result = await service.register(
        license_mode=payload.license_mode,
        license_reference=payload.license_reference,
        issued_at=payload.issued_at,
        expires_at=payload.expires_at,
        offline_grace_days=payload.offline_grace_days,
        device_reference=payload.device_reference,
        features=tuple(payload.features),
    )
    await _audit(request, action="product.license.register", target=result["license_id"])
    return result


@router.post(
    "/license/features",
    summary="授予功能使用权",
    name="product_license_grant",
    dependencies=LICENSE,
)
async def license_grant(request: Request, payload: LicenseFeatureRequest) -> dict[str, Any]:
    return await _service(request, "license_service", LicenseService).grant(
        payload.license_id, payload.feature_key
    )


@router.delete(
    "/license/features/{license_id}/{feature_key}",
    summary="撤销功能使用权",
    name="product_license_revoke",
    dependencies=LICENSE,
)
async def license_revoke(request: Request, license_id: str, feature_key: str) -> dict[str, Any]:
    return await _service(request, "license_service", LicenseService).revoke(
        license_id, feature_key
    )


# ---------------------------------------------------------------------- update
@router.get("/updates", summary="检查产品更新", name="product_updates_check", dependencies=READ)
async def updates_check(request: Request, channel: str = Query(default="STABLE")) -> dict[str, Any]:
    return await _service(request, "update_service", UpdateService).check(channel)


@router.post(
    "/updates/manifests",
    summary="登记更新清单",
    name="product_update_manifest",
    dependencies=UPDATE,
)
async def update_manifest(request: Request, payload: UpdateManifestRequest) -> dict[str, Any]:
    result = await _service(request, "update_service", UpdateService).register_manifest(
        payload.payload, signature=payload.signature
    )
    await _audit(
        request,
        action="product.update.manifest",
        target=result["manifest_id"],
        detail={"signature_status": result["signature_status"]},
    )
    return result


@router.post(
    "/updates/operations",
    summary="创建更新操作",
    name="product_update_operation",
    dependencies=UPDATE,
)
async def update_operation(request: Request, payload: UpdateOperationRequest) -> dict[str, Any]:
    return await _service(request, "update_service", UpdateService).create_operation(
        payload.manifest_id, user_approved=payload.user_approved
    )


@router.post(
    "/updates/operations/{operation_id}/approve",
    summary="批准更新",
    name="product_update_approve",
    dependencies=UPDATE,
)
async def update_approve(request: Request, operation_id: str) -> dict[str, Any]:
    result = await _service(request, "update_service", UpdateService).approve(operation_id)
    await _audit(request, action="product.update.approve", target=operation_id)
    return result


@router.post(
    "/updates/operations/{operation_id}/install",
    summary="安装更新",
    name="product_update_install",
    dependencies=UPDATE,
)
async def update_install(request: Request, operation_id: str) -> dict[str, Any]:
    result = await _service(request, "update_service", UpdateService).install(operation_id)
    await _audit(request, action="product.update.install", target=operation_id)
    return result


@router.post(
    "/updates/operations/{operation_id}/reject",
    summary="拒绝更新",
    name="product_update_reject",
    dependencies=UPDATE,
)
async def update_reject(request: Request, operation_id: str) -> dict[str, Any]:
    return await _service(request, "update_service", UpdateService).reject(operation_id)


@router.get(
    "/updates/operations/{operation_id}",
    summary="更新操作状态",
    name="product_update_status",
    dependencies=READ,
)
async def update_status(request: Request, operation_id: str) -> dict[str, Any]:
    return await _service(request, "update_service", UpdateService).status(operation_id)


# -------------------------------------------------------------------- migration
@router.post(
    "/migrations/plan",
    summary="数据库迁移计划",
    name="product_migration_plan",
    dependencies=MIGRATE,
)
async def migration_plan(request: Request, payload: MigrationPlanRequest) -> dict[str, Any]:
    return await _service(request, "product_migration_service", ProductMigrationService).plan(
        current_schema_version=payload.current_schema_version
    )


@router.post(
    "/migrations/{migration_id}/prepare",
    summary="准备迁移执行",
    name="product_migration_prepare",
    dependencies=MIGRATE,
)
async def migration_prepare(request: Request, migration_id: str) -> dict[str, Any]:
    return await _service(request, "product_migration_service", ProductMigrationService).prepare(
        migration_id
    )


@router.post(
    "/migrations/runs/{run_id}/execute",
    summary="执行数据库迁移",
    name="product_migration_execute",
    dependencies=MIGRATE,
)
async def migration_execute(
    request: Request, run_id: str, payload: MigrationExecuteRequest
) -> dict[str, Any]:
    result = await _service(request, "product_migration_service", ProductMigrationService).execute(
        run_id, confirmed=payload.confirmed
    )
    await _audit(
        request,
        action="product.migration.execute",
        target=run_id,
        detail={"status": result.get("status")},
    )
    return result


@router.get(
    "/migrations/status",
    summary="迁移状态",
    name="product_migration_status",
    dependencies=READ,
)
async def migration_status(request: Request) -> dict[str, Any]:
    return await _service(request, "product_migration_service", ProductMigrationService).status()


# --------------------------------------------------------------------- recovery
@router.get(
    "/recovery/points", summary="恢复点列表", name="product_recovery_points", dependencies=READ
)
async def recovery_points(request: Request) -> dict[str, Any]:
    return {"points": await _service(request, "recovery_service", RecoveryService).list_points()}


@router.post(
    "/recovery/points", summary="登记恢复点", name="product_recovery_point", dependencies=RECOVER
)
async def recovery_point(request: Request, payload: RecoveryPointRequest) -> dict[str, Any]:
    result = await _service(request, "recovery_service", RecoveryService).create_point(
        kind=payload.kind,
        path=payload.path,
        integrity_hash=payload.integrity_hash,
        description=payload.description,
        product_version=PRODUCT_VERSION,
    )
    await _audit(request, action="product.recovery.point", target=result["recovery_point_id"])
    return result


@router.post(
    "/recovery/inspect",
    summary="恢复状态检查",
    name="product_recovery_inspect",
    dependencies=RECOVER,
)
async def recovery_inspect(request: Request, payload: RecoveryInspectRequest) -> dict[str, Any]:
    return await _service(request, "recovery_service", RecoveryService).inspect(
        payload.recovery_point_id
    )


@router.post(
    "/recovery/operations/{operation_id}/plan",
    summary="生成恢复计划",
    name="product_recovery_plan",
    dependencies=RECOVER,
)
async def recovery_plan(request: Request, operation_id: str) -> dict[str, Any]:
    return await _service(request, "recovery_service", RecoveryService).plan(operation_id)


@router.post(
    "/recovery/operations/{operation_id}/execute",
    summary="执行恢复",
    name="product_recovery_execute",
    dependencies=RECOVER,
)
async def recovery_execute(
    request: Request, operation_id: str, payload: RecoveryExecuteRequest
) -> dict[str, Any]:
    result = await _service(request, "recovery_service", RecoveryService).execute(
        operation_id,
        confirmed=payload.confirmed,
        manual_verification_done=payload.manual_verification_done,
    )
    await _audit(
        request,
        action="product.recovery.execute",
        target=operation_id,
        detail={"status": result.get("status")},
    )
    return result


# ------------------------------------------------------------------ diagnostics
@router.get(
    "/diagnostics/errors",
    summary="错误码与恢复建议",
    name="product_error_catalog",
    dependencies=READ,
)
async def error_catalog(request: Request) -> dict[str, Any]:
    return {"errors": await _service(request, "diagnostics_service", DiagnosticsService).errors()}


@router.post(
    "/diagnostics/support-bundles/prepare",
    summary="生成支持包预览",
    name="product_support_bundle_prepare",
    dependencies=DIAGNOSTICS,
)
async def support_bundle_prepare(
    request: Request, payload: SupportBundlePrepareRequest
) -> dict[str, Any]:
    return _service(request, "diagnostics_service", DiagnosticsService).prepare_bundle(
        payload.context, logs=payload.logs
    )


@router.post(
    "/diagnostics/support-bundles",
    summary="导出支持包",
    name="product_support_bundle_export",
    dependencies=DIAGNOSTICS,
)
async def support_bundle_export(
    request: Request, payload: SupportBundleExportRequest
) -> dict[str, Any]:
    result = await _service(request, "diagnostics_service", DiagnosticsService).export_bundle(
        payload.context,
        created_by=_actor(request),
        confirmed=payload.confirmed,
        logs=payload.logs,
    )
    await _audit(
        request,
        action="product.support_bundle.export",
        target=result["bundle_id"],
    )
    return result


@router.get(
    "/diagnostics/support-bundles",
    summary="支持包列表",
    name="product_support_bundle_list",
    dependencies=READ,
)
async def support_bundle_list(request: Request) -> dict[str, Any]:
    return {
        "bundles": await _service(request, "diagnostics_service", DiagnosticsService).list_bundles()
    }


@router.post(
    "/diagnostics/crash-reports",
    summary="本地崩溃报告",
    name="product_crash_report",
    dependencies=DIAGNOSTICS,
)
async def crash_report(request: Request, payload: CrashReportRequest) -> dict[str, Any]:
    return await _service(request, "diagnostics_service", DiagnosticsService).report_crash(
        error_code=payload.error_code,
        summary=payload.summary,
        context=payload.context,
    )


# ---------------------------------------------------------------------- privacy
@router.get(
    "/privacy/telemetry", summary="Telemetry 状态", name="product_telemetry", dependencies=READ
)
async def telemetry_state(request: Request) -> dict[str, Any]:
    return await _service(request, "privacy_service", PrivacyService).telemetry_state()


@router.put(
    "/privacy/telemetry",
    summary="设置 Telemetry",
    name="product_telemetry_update",
    dependencies=PRIVACY,
)
async def telemetry_update(request: Request, payload: TelemetryRequest) -> dict[str, Any]:
    result = await _service(request, "privacy_service", PrivacyService).set_telemetry(
        enabled=payload.enabled, categories=payload.categories, actor=_actor(request)
    )
    await _audit(
        request,
        action="product.privacy.telemetry",
        detail={"enabled": payload.enabled, "categories": payload.categories},
    )
    return result


@router.post(
    "/privacy/context-preview",
    summary="上下文预览",
    name="product_context_preview",
    dependencies=PRIVACY,
)
async def context_preview(request: Request, payload: ContextPreviewRequest) -> dict[str, Any]:
    return await _service(request, "privacy_service", PrivacyService).context_preview(
        payload.context
    )


@router.get(
    "/privacy/export-plan",
    summary="数据导出范围",
    name="product_privacy_export_plan",
    dependencies=READ,
)
async def privacy_export_plan(request: Request) -> dict[str, Any]:
    return await _service(request, "privacy_service", PrivacyService).prepare_data_export()


@router.post(
    "/privacy/delete",
    summary="删除本地产品数据",
    name="product_privacy_delete",
    dependencies=PRIVACY,
)
async def privacy_delete(request: Request, payload: DeleteDataRequest) -> dict[str, Any]:
    result = await _service(request, "privacy_service", PrivacyService).delete_user_data(
        scope=payload.scope, confirmed=payload.confirmed
    )
    await _audit(request, action="product.privacy.delete", detail={"scope": payload.scope})
    return result


# --------------------------------------------------------------------- releases
@router.get("/releases", summary="产品发布列表", name="product_releases", dependencies=READ)
async def releases(request: Request, channel: str = Query(default="STABLE")) -> dict[str, Any]:
    return {
        "releases": await _service(
            request, "product_release_service", ProductReleaseService
        ).list_releases(channel)
    }


@router.post(
    "/releases", summary="创建发布候选", name="product_release_candidate", dependencies=APPROVE
)
async def release_candidate(request: Request, payload: ReleaseCandidateRequest) -> dict[str, Any]:
    result = await _service(
        request, "product_release_service", ProductReleaseService
    ).create_candidate(
        product_version=payload.product_version,
        channel=payload.channel,
        component_versions=payload.component_versions,
        package_hash=payload.package_hash,
        signature_status=payload.signature_status,
        release_notes=payload.release_notes,
        evidence=payload.evidence,
        source_revision=payload.source_revision,
    )
    await _audit(request, action="product.release.candidate", target=result["release_id"])
    return result


@router.post(
    "/releases/{release_id}/approve",
    summary="审批发布",
    name="product_release_approve",
    dependencies=APPROVE,
)
async def release_approve(
    request: Request, release_id: str, payload: ReleaseApproveRequest
) -> dict[str, Any]:
    return await _service(request, "product_release_service", ProductReleaseService).approve(
        release_id, approver=payload.approver
    )


@router.post(
    "/releases/{release_id}/reject",
    summary="拒绝发布",
    name="product_release_reject",
    dependencies=APPROVE,
)
async def release_reject(
    request: Request, release_id: str, payload: ReleaseRejectRequest
) -> dict[str, Any]:
    return await _service(request, "product_release_service", ProductReleaseService).reject(
        release_id, approver=payload.approver, reason=payload.reason
    )


@router.post(
    "/releases/{release_id}/publish",
    summary="发布产品版本",
    name="product_release_publish",
    dependencies=PUBLISH,
)
async def release_publish(
    request: Request, release_id: str, payload: ReleasePublishRequest
) -> dict[str, Any]:
    result = await _service(request, "product_release_service", ProductReleaseService).publish(
        release_id, publisher=payload.publisher
    )
    await _audit(request, action="product.release.publish", target=release_id)
    return result


@router.get("/sbom", summary="产品 SBOM", name="product_sbom", dependencies=READ)
async def sbom() -> dict[str, Any]:
    return build_sbom()
