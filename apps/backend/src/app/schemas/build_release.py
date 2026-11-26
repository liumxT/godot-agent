"""E10 构建与发布请求模型（Batch A：T02 / T03 / T04）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.project_workflow import StrictModel

PLATFORM_LITERAL = Literal["WINDOWS", "MACOS", "LINUX"]
BUILD_MODE_LITERAL = Literal["DEBUG", "RELEASE"]
CHANNEL_LITERAL = Literal["LOCAL", "LOCAL_EXPORT", "USER_DOWNLOAD", "USER_OUTPUT_DIR"]


class BuildConfigurationCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    target_platform: PLATFORM_LITERAL
    architecture: str = Field(min_length=1, max_length=32)
    godot_version_constraint: str = Field(default="", max_length=64)
    renderer: str = Field(default="", max_length=32)
    export_preset_name: str = Field(default="", max_length=128)
    build_mode: BUILD_MODE_LITERAL = "RELEASE"
    feature_tags: list[str] = Field(default_factory=list, max_length=32)
    output_format: str = Field(default="", max_length=32)
    env_allowlist: list[str] = Field(default_factory=list, max_length=64)
    build_timeout_seconds: int = Field(default=1800, ge=1, le=7200)
    resource_budget: dict[str, Any] = Field(default_factory=dict)
    packaging_policy: dict[str, Any] = Field(default_factory=dict)
    verification_policy: dict[str, Any] = Field(default_factory=dict)


class BuildConfigurationUpdateRequest(StrictModel):
    target_platform: PLATFORM_LITERAL | None = None
    architecture: str | None = Field(default=None, min_length=1, max_length=32)
    godot_version_constraint: str | None = Field(default=None, max_length=64)
    renderer: str | None = Field(default=None, max_length=32)
    export_preset_name: str | None = Field(default=None, max_length=128)
    build_mode: BUILD_MODE_LITERAL | None = None
    feature_tags: list[str] | None = Field(default=None, max_length=32)
    output_format: str | None = Field(default=None, max_length=32)
    env_allowlist: list[str] | None = Field(default=None, max_length=64)
    build_timeout_seconds: int | None = Field(default=None, ge=1, le=7200)
    resource_budget: dict[str, Any] | None = None
    packaging_policy: dict[str, Any] | None = None
    verification_policy: dict[str, Any] | None = None


class ExportPresetRegisterRequest(StrictModel):
    preset_name: str = Field(min_length=1, max_length=128)
    platform: PLATFORM_LITERAL
    export_path: str = Field(default="", max_length=512)
    export_mode: BUILD_MODE_LITERAL = "RELEASE"
    features: list[str] = Field(default_factory=list, max_length=64)
    resource_filters: dict[str, Any] = Field(default_factory=dict)
    template_required: str = Field(default="", max_length=64)
    template_available: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class BuildCreateRequest(StrictModel):
    build_config_id: str = Field(min_length=1, max_length=64)
    environment_id: str = Field(min_length=1, max_length=64)
    source_revision: str = Field(default="", max_length=128)
    changeset_id: str | None = Field(default=None, max_length=64)


class BuildEnvironmentRegisterRequest(StrictModel):
    os_name: str = Field(min_length=1, max_length=32)
    os_version: str = Field(default="", max_length=64)
    cpu_architecture: str = Field(min_length=1, max_length=32)
    godot_version: str = Field(min_length=1, max_length=32)
    godot_executable_path: str = Field(default="", max_length=512)
    godot_executable_hash: str = Field(default="", max_length=64)
    export_template_version: str = Field(default="", max_length=32)
    toolchain_versions: dict[str, Any] = Field(default_factory=dict)
    sdk_versions: dict[str, Any] = Field(default_factory=dict)
    renderer: str = Field(default="", max_length=32)
    build_executor_version: str = Field(default="", max_length=32)
    target_platform: PLATFORM_LITERAL | None = None
    required_platforms: list[PLATFORM_LITERAL] = Field(default_factory=list, max_length=8)


ARTIFACT_STATUS_LITERAL = Literal["REGISTERED", "VERIFYING", "VERIFIED", "REJECTED", "QUARANTINED"]


class ArtifactFileModel(StrictModel):
    path: str = Field(min_length=1, max_length=512)
    size: int = Field(ge=0)
    hash: str = Field(default="", max_length=80)


class ArtifactRegisterRequest(StrictModel):
    platform: PLATFORM_LITERAL
    architecture: str = Field(min_length=1, max_length=32)
    storage_reference: str = Field(min_length=1, max_length=512)
    files: list[ArtifactFileModel] = Field(min_length=1, max_length=10_000)
    build_id: str | None = Field(default=None, max_length=64)
    attempt_id: str | None = Field(default=None, max_length=64)
    name: str = Field(default="", max_length=128)
    format: str = Field(default="", max_length=32)


class ArtifactTransitionRequest(StrictModel):
    status: ARTIFACT_STATUS_LITERAL
    reason: str = Field(default="", max_length=256)


class ArtifactIntegrityRequest(StrictModel):
    files: list[ArtifactFileModel] = Field(min_length=1, max_length=10_000)


class PackageCreateRequest(StrictModel):
    artifact_id: str = Field(min_length=1, max_length=64)
    format: str = Field(default="zip", max_length=32)
    storage_reference: str = Field(default="", max_length=512)


class ProvenanceRecordRequest(StrictModel):
    build_id: str = Field(min_length=1, max_length=64)
    attempt_id: str = Field(min_length=1, max_length=64)
    artifact_id: str | None = Field(default=None, max_length=64)
    source_revision: str = Field(default="", max_length=128)
    config_snapshot_hash: str = Field(default="", max_length=80)
    environment_fingerprint: str = Field(default="", max_length=64)
    command_template_id: str = Field(default="", max_length=64)
    executor_id: str = Field(default="", max_length=64)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class EvidenceAddRequest(StrictModel):
    evidence_type: Literal[
        "verification",
        "artifact_integrity",
        "smoke_test",
        "approval",
        "signing",
        "distribution",
    ]
    artifact_id: str | None = Field(default=None, max_length=64)
    package_id: str | None = Field(default=None, max_length=64)
    release_candidate_id: str | None = Field(default=None, max_length=64)
    reference: str = Field(default="", max_length=512)
    content_hash: str = Field(default="", max_length=80)
    details: dict[str, Any] = Field(default_factory=dict)


class ReleaseCandidateCreateRequest(StrictModel):
    version: str = Field(min_length=1, max_length=64)
    artifact_id: str = Field(min_length=1, max_length=64)
    package_id: str | None = Field(default=None, max_length=64)
    verification_campaign_id: str | None = Field(default=None, max_length=64)


class SmokeCheckModel(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    status: Literal["PASSED", "FAILED", "SKIPPED", "UNKNOWN"]
    details: dict[str, Any] = Field(default_factory=dict)


class SmokeTestRecordRequest(StrictModel):
    artifact_id: str | None = Field(default=None, max_length=64)
    package_id: str | None = Field(default=None, max_length=64)
    release_candidate_id: str | None = Field(default=None, max_length=64)
    checks: list[SmokeCheckModel] = Field(default_factory=list, max_length=100)
    evidence_reference: str = Field(default="", max_length=512)
    duration_ms: int = Field(default=0, ge=0)


class SigningProfileRegisterRequest(StrictModel):
    platform: PLATFORM_LITERAL
    signing_method: str = Field(min_length=1, max_length=32)
    certificate_reference: str = Field(default="", max_length=512)
    credential_reference: str = Field(default="", max_length=512)
    allowed_channels: list[CHANNEL_LITERAL] = Field(default_factory=list, max_length=8)
    expiration: datetime | None = None


class SigningExecuteRequest(StrictModel):
    signing_profile_id: str = Field(min_length=1, max_length=64)


class SigningReconcileRequest(StrictModel):
    succeeded: bool
    certificate_fingerprint: str = Field(default="", max_length=128)
    detail: str = Field(default="", max_length=1000)


class ReleaseApprovalRequest(StrictModel):
    release_candidate_id: str = Field(min_length=1, max_length=64)
    distribution_channel: CHANNEL_LITERAL
    policy_version: str = Field(default="", max_length=64)


class ReleaseApprovalDecisionRequest(StrictModel):
    approved_by: str = Field(min_length=1, max_length=64)


class ReleaseApprovalRejectRequest(StrictModel):
    rejected_by: str = Field(min_length=1, max_length=64)


class ReleaseApprovalInvalidateRequest(StrictModel):
    reason: str = Field(default="", max_length=1000)


class ReleaseCreateRequest(StrictModel):
    release_candidate_id: str = Field(min_length=1, max_length=64)
    approval_id: str = Field(min_length=1, max_length=64)
    channel: CHANNEL_LITERAL


class ReleaseStartRequest(StrictModel):
    target_reference: str = Field(min_length=1, max_length=1024)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ReleaseReconcileRequest(StrictModel):
    status: Literal["DISTRIBUTING", "PUBLISHED", "COMPLETED", "FAILED", "WITHDRAWN"]
    external_operation_id: str = Field(default="", max_length=128)
