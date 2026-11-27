"""E12 产品化请求模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.project_workflow import StrictModel

SCOPE_LITERAL = Literal["SYSTEM_DEFAULT", "USER_GLOBAL", "PROJECT_OVERRIDE", "SESSION_OVERRIDE"]
CHANNEL_LITERAL = Literal["DEV", "BETA", "STABLE"]
SIGNATURE_LITERAL = Literal["SIGNED", "UNSIGNED", "INVALID"]
PLUGIN_SOURCE_LITERAL = Literal["zip", "installer", "project"]
RECOVERY_KIND_LITERAL = Literal["DATABASE", "PLUGIN", "CONFIGURATION", "FULL"]
LICENSE_MODE_LITERAL = Literal["DEVELOPMENT", "LOCAL", "ONLINE", "ENTERPRISE", "SUBSCRIPTION"]
DELETE_SCOPE_LITERAL = Literal["telemetry", "diagnostics"]


class InstallationPreflightRequest(StrictModel):
    install_dir: str = Field(min_length=1, max_length=1024)
    data_dir: str = Field(min_length=1, max_length=1024)
    components: list[str] = Field(min_length=1, max_length=32)
    disk_free_gb: float | None = Field(default=None, ge=0)
    writable: bool | None = None


class InstallationStartRequest(InstallationPreflightRequest):
    config_dir: str = Field(min_length=1, max_length=1024)
    log_dir: str = Field(min_length=1, max_length=1024)
    database_path: str = Field(min_length=1, max_length=1024)


class InstallationVerifyRequest(StrictModel):
    verification: dict[str, Any] = Field(default_factory=dict)


class UninstallRequest(StrictModel):
    remove_user_data: bool = False


class PluginInstallPlanRequest(StrictModel):
    project_dir: str = Field(min_length=1, max_length=1024)
    plugin_version: str = Field(min_length=1, max_length=32)
    existing_version: str | None = Field(default=None, max_length=32)
    modified_files: list[str] = Field(default_factory=list, max_length=200)
    source: PLUGIN_SOURCE_LITERAL = "zip"


class PluginInstallApplyRequest(StrictModel):
    plan: dict[str, Any]
    confirmed: bool = False
    overwrite_user_modified: bool = False


class FirstRunRequest(StrictModel):
    context: dict[str, Any] = Field(default_factory=dict)


class ConfigurationProfileRequest(StrictModel):
    profile_name: str = Field(min_length=1, max_length=64)
    scope: SCOPE_LITERAL
    values: dict[str, Any] = Field(default_factory=dict)
    profile_version: int = Field(default=1, ge=1)
    status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"


class LicenseRegisterRequest(StrictModel):
    license_mode: LICENSE_MODE_LITERAL
    license_reference: str = Field(min_length=1, max_length=128)
    issued_at: datetime
    expires_at: datetime | None = None
    offline_grace_days: int = Field(default=7, ge=0, le=365)
    device_reference: str = Field(default="local", max_length=128)
    features: list[str] = Field(default_factory=list, max_length=64)


class LicenseFeatureRequest(StrictModel):
    license_id: str = Field(min_length=1, max_length=64)
    feature_key: str = Field(min_length=1, max_length=64)


class UpdateManifestRequest(StrictModel):
    payload: dict[str, Any]
    signature: str | None = Field(default=None, max_length=256)


class UpdateOperationRequest(StrictModel):
    manifest_id: str = Field(min_length=1, max_length=64)
    user_approved: bool = False


class MigrationPlanRequest(StrictModel):
    current_schema_version: str = Field(min_length=1, max_length=32)


class MigrationExecuteRequest(StrictModel):
    confirmed: bool = False


class RecoveryPointRequest(StrictModel):
    kind: RECOVERY_KIND_LITERAL
    path: str = Field(min_length=1, max_length=1024)
    integrity_hash: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)


class RecoveryInspectRequest(StrictModel):
    recovery_point_id: str | None = Field(default=None, max_length=64)


class RecoveryExecuteRequest(StrictModel):
    confirmed: bool = False
    manual_verification_done: bool = False


class TelemetryRequest(StrictModel):
    enabled: bool
    categories: list[str] = Field(default_factory=list, max_length=8)


class ContextPreviewRequest(StrictModel):
    context: dict[str, Any] = Field(default_factory=dict)


class SupportBundlePrepareRequest(StrictModel):
    context: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list, max_length=500)


class SupportBundleExportRequest(SupportBundlePrepareRequest):
    confirmed: bool = False


class CrashReportRequest(StrictModel):
    error_code: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class DeleteDataRequest(StrictModel):
    scope: DELETE_SCOPE_LITERAL
    confirmed: bool = False


class ReleaseCandidateRequest(StrictModel):
    product_version: str = Field(min_length=5, max_length=32)
    channel: CHANNEL_LITERAL
    component_versions: dict[str, str] = Field(min_length=1)
    package_hash: str = Field(min_length=16, max_length=128)
    signature_status: SIGNATURE_LITERAL
    release_notes: str = Field(default="", max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    source_revision: str = Field(default="unknown", max_length=128)


class ReleaseApproveRequest(StrictModel):
    approver: str = Field(min_length=1, max_length=64)


class ReleaseRejectRequest(ReleaseApproveRequest):
    reason: str = Field(min_length=1, max_length=1000)


class ReleasePublishRequest(StrictModel):
    publisher: str = Field(min_length=1, max_length=64)
