"""Build & Release 领域模型与状态机（E10-T01）。

状态所有权（冻结规则）：

- Build / Build Attempt / Artifact / Package / Release Candidate / Release
  由 Build & Release 拥有；
- Project / ChangeSet / Workflow / Task / Approval / Verification / Asset 的状态
  由各自模块拥有，本模块只保存引用，绝不直接修改；
- ``UNKNOWN`` 不是失败也不是成功，必须先核对实际执行状态后再收敛；
- 已注册 Artifact 内容不可变，内容变化只能生成新版本与新哈希；
- Release Approval 必须绑定 Artifact / Package / Candidate Manifest 哈希，
  任一内容变化都要重新审批；
- 本地交付不等于线上发布。

本文件先落地 Batch A（T01–T04）的领域表，后续批次继续追加。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

# ---------------------------------------------------------------------------
# Build 状态机
# ---------------------------------------------------------------------------

BUILD_QUEUED = "QUEUED"
BUILD_PREPARING = "PREPARING"
BUILD_RUNNING = "RUNNING"
BUILD_EXPORTING = "EXPORTING"
BUILD_COLLECTING = "COLLECTING"
BUILD_SUCCEEDED = "SUCCEEDED"
BUILD_FAILED = "FAILED"
BUILD_CANCELLED = "CANCELLED"
BUILD_UNKNOWN = "UNKNOWN"
BUILD_STATUSES = frozenset(
    {
        BUILD_QUEUED,
        BUILD_PREPARING,
        BUILD_RUNNING,
        BUILD_EXPORTING,
        BUILD_COLLECTING,
        BUILD_SUCCEEDED,
        BUILD_FAILED,
        BUILD_CANCELLED,
        BUILD_UNKNOWN,
    }
)
BUILD_TRANSITIONS: dict[str, frozenset[str]] = {
    BUILD_QUEUED: frozenset({BUILD_PREPARING, BUILD_CANCELLED}),
    BUILD_PREPARING: frozenset({BUILD_RUNNING, BUILD_FAILED, BUILD_CANCELLED, BUILD_UNKNOWN}),
    BUILD_RUNNING: frozenset({BUILD_EXPORTING, BUILD_FAILED, BUILD_CANCELLED, BUILD_UNKNOWN}),
    BUILD_EXPORTING: frozenset({BUILD_COLLECTING, BUILD_FAILED, BUILD_CANCELLED, BUILD_UNKNOWN}),
    BUILD_COLLECTING: frozenset({BUILD_SUCCEEDED, BUILD_FAILED, BUILD_UNKNOWN}),
    BUILD_SUCCEEDED: frozenset(),
    # 失败后重试必须创建新的 Attempt，Build 回到 QUEUED，旧 Attempt 记录保留。
    BUILD_FAILED: frozenset({BUILD_QUEUED}),
    BUILD_CANCELLED: frozenset(),
    # UNKNOWN 只能经状态核对后收敛，禁止直接再启动一个相同构建。
    BUILD_UNKNOWN: frozenset({BUILD_QUEUED, BUILD_SUCCEEDED, BUILD_FAILED, BUILD_CANCELLED}),
}
BUILD_ACTIVE_STATUSES = frozenset(
    {BUILD_QUEUED, BUILD_PREPARING, BUILD_RUNNING, BUILD_EXPORTING, BUILD_COLLECTING}
)
BUILD_TERMINAL_STATUSES = frozenset({BUILD_SUCCEEDED, BUILD_FAILED, BUILD_CANCELLED, BUILD_UNKNOWN})

ATTEMPT_PENDING = "PENDING"
ATTEMPT_RUNNING = "RUNNING"
ATTEMPT_SUCCEEDED = "SUCCEEDED"
ATTEMPT_FAILED = "FAILED"
ATTEMPT_CANCELLED = "CANCELLED"
ATTEMPT_UNKNOWN = "UNKNOWN"
ATTEMPT_STATUSES = frozenset(
    {
        ATTEMPT_PENDING,
        ATTEMPT_RUNNING,
        ATTEMPT_SUCCEEDED,
        ATTEMPT_FAILED,
        ATTEMPT_CANCELLED,
        ATTEMPT_UNKNOWN,
    }
)

# ---------------------------------------------------------------------------
# Artifact 状态机（内容不可变，仅验证状态可迁移）
# ---------------------------------------------------------------------------

ARTIFACT_REGISTERED = "REGISTERED"
ARTIFACT_VERIFYING = "VERIFYING"
ARTIFACT_VERIFIED = "VERIFIED"
ARTIFACT_REJECTED = "REJECTED"
ARTIFACT_QUARANTINED = "QUARANTINED"
ARTIFACT_STATUSES = frozenset(
    {
        ARTIFACT_REGISTERED,
        ARTIFACT_VERIFYING,
        ARTIFACT_VERIFIED,
        ARTIFACT_REJECTED,
        ARTIFACT_QUARANTINED,
    }
)
ARTIFACT_TRANSITIONS: dict[str, frozenset[str]] = {
    ARTIFACT_REGISTERED: frozenset({ARTIFACT_VERIFYING, ARTIFACT_QUARANTINED}),
    ARTIFACT_VERIFYING: frozenset({ARTIFACT_VERIFIED, ARTIFACT_REJECTED, ARTIFACT_QUARANTINED}),
    ARTIFACT_VERIFIED: frozenset({ARTIFACT_QUARANTINED}),
    ARTIFACT_REJECTED: frozenset(),
    ARTIFACT_QUARANTINED: frozenset(),
}

PACKAGE_CREATED = "CREATED"
PACKAGE_VERIFIED = "VERIFIED"
PACKAGE_REJECTED = "REJECTED"
PACKAGE_STATUSES = frozenset({PACKAGE_CREATED, PACKAGE_VERIFIED, PACKAGE_REJECTED})
PACKAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    PACKAGE_CREATED: frozenset({PACKAGE_VERIFIED, PACKAGE_REJECTED}),
    PACKAGE_VERIFIED: frozenset({PACKAGE_REJECTED}),
    PACKAGE_REJECTED: frozenset(),
}

SMOKE_PASSED = "PASSED"
SMOKE_FAILED = "FAILED"
SMOKE_SKIPPED = "SKIPPED"
SMOKE_UNKNOWN = "UNKNOWN"
SMOKE_STATUSES = frozenset({SMOKE_PASSED, SMOKE_FAILED, SMOKE_SKIPPED, SMOKE_UNKNOWN})

# ---------------------------------------------------------------------------
# Release Candidate 状态机
# ---------------------------------------------------------------------------

RC_DRAFT = "DRAFT"
RC_VALIDATING = "VALIDATING"
RC_READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
RC_APPROVED = "APPROVED"
RC_REJECTED = "REJECTED"
RC_SUPERSEDED = "SUPERSEDED"
RC_INVALIDATED = "INVALIDATED"
RC_STATUSES = frozenset(
    {
        RC_DRAFT,
        RC_VALIDATING,
        RC_READY_FOR_APPROVAL,
        RC_APPROVED,
        RC_REJECTED,
        RC_SUPERSEDED,
        RC_INVALIDATED,
    }
)
RC_TRANSITIONS: dict[str, frozenset[str]] = {
    RC_DRAFT: frozenset({RC_VALIDATING, RC_SUPERSEDED}),
    RC_VALIDATING: frozenset({RC_READY_FOR_APPROVAL, RC_REJECTED, RC_INVALIDATED}),
    RC_READY_FOR_APPROVAL: frozenset({RC_APPROVED, RC_REJECTED, RC_SUPERSEDED, RC_INVALIDATED}),
    RC_APPROVED: frozenset({RC_SUPERSEDED}),
    RC_REJECTED: frozenset({RC_SUPERSEDED}),
    RC_SUPERSEDED: frozenset(),
    RC_INVALIDATED: frozenset(),
}

# ---------------------------------------------------------------------------
# Release 状态机
# ---------------------------------------------------------------------------

RELEASE_PENDING = "PENDING"
RELEASE_AUTHORIZED = "AUTHORIZED"
RELEASE_DISTRIBUTING = "DISTRIBUTING"
RELEASE_PUBLISHED = "PUBLISHED"
RELEASE_POST_VERIFYING = "POST_VERIFYING"
RELEASE_COMPLETED = "COMPLETED"
RELEASE_FAILED = "FAILED"
RELEASE_UNKNOWN = "UNKNOWN"
RELEASE_WITHDRAWN = "WITHDRAWN"
RELEASE_ROLLED_BACK = "ROLLED_BACK"
RELEASE_STATUSES = frozenset(
    {
        RELEASE_PENDING,
        RELEASE_AUTHORIZED,
        RELEASE_DISTRIBUTING,
        RELEASE_PUBLISHED,
        RELEASE_POST_VERIFYING,
        RELEASE_COMPLETED,
        RELEASE_FAILED,
        RELEASE_UNKNOWN,
        RELEASE_WITHDRAWN,
        RELEASE_ROLLED_BACK,
    }
)
RELEASE_TRANSITIONS: dict[str, frozenset[str]] = {
    RELEASE_PENDING: frozenset({RELEASE_AUTHORIZED, RELEASE_FAILED, RELEASE_WITHDRAWN}),
    RELEASE_AUTHORIZED: frozenset(
        {RELEASE_DISTRIBUTING, RELEASE_FAILED, RELEASE_UNKNOWN, RELEASE_WITHDRAWN}
    ),
    RELEASE_DISTRIBUTING: frozenset({RELEASE_PUBLISHED, RELEASE_FAILED, RELEASE_UNKNOWN}),
    RELEASE_PUBLISHED: frozenset({RELEASE_POST_VERIFYING, RELEASE_ROLLED_BACK, RELEASE_WITHDRAWN}),
    RELEASE_POST_VERIFYING: frozenset({RELEASE_COMPLETED, RELEASE_FAILED, RELEASE_UNKNOWN}),
    RELEASE_COMPLETED: frozenset({RELEASE_ROLLED_BACK}),
    RELEASE_FAILED: frozenset(),
    # UNKNOWN 必须核对渠道状态后收敛，禁止仅凭超时重复发布。
    RELEASE_UNKNOWN: frozenset(
        {
            RELEASE_DISTRIBUTING,
            RELEASE_PUBLISHED,
            RELEASE_COMPLETED,
            RELEASE_FAILED,
            RELEASE_WITHDRAWN,
        }
    ),
    RELEASE_WITHDRAWN: frozenset(),
    RELEASE_ROLLED_BACK: frozenset(),
}

# ---------------------------------------------------------------------------
# 环境与平台能力
# ---------------------------------------------------------------------------

ENV_READY = "READY"
ENV_READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
ENV_BLOCKED = "BLOCKED"
ENV_UNKNOWN = "UNKNOWN"
ENVIRONMENT_STATUSES = frozenset({ENV_READY, ENV_READY_WITH_WARNINGS, ENV_BLOCKED, ENV_UNKNOWN})
BUILDABLE_ENVIRONMENT_STATUSES = frozenset({ENV_READY, ENV_READY_WITH_WARNINGS})

CAPABILITY_SUPPORTED = "SUPPORTED"
CAPABILITY_SUPPORTED_WITH_REQUIREMENTS = "SUPPORTED_WITH_REQUIREMENTS"
CAPABILITY_EXPERIMENTAL = "EXPERIMENTAL"
CAPABILITY_UNSUPPORTED = "UNSUPPORTED"
CAPABILITY_UNKNOWN = "UNKNOWN"
PLATFORM_CAPABILITY_STATUSES = frozenset(
    {
        CAPABILITY_SUPPORTED,
        CAPABILITY_SUPPORTED_WITH_REQUIREMENTS,
        CAPABILITY_EXPERIMENTAL,
        CAPABILITY_UNSUPPORTED,
        CAPABILITY_UNKNOWN,
    }
)
# 只有明确支持或带条件支持的平台才允许声明可用导出能力。
EXPORT_ENABLED_CAPABILITY_STATUSES = frozenset(
    {CAPABILITY_SUPPORTED, CAPABILITY_SUPPORTED_WITH_REQUIREMENTS}
)

PLATFORM_WINDOWS = "WINDOWS"
PLATFORM_MACOS = "MACOS"
PLATFORM_LINUX = "LINUX"
DESKTOP_PLATFORMS = (PLATFORM_WINDOWS, PLATFORM_MACOS, PLATFORM_LINUX)

BUILD_MODE_DEBUG = "DEBUG"
BUILD_MODE_RELEASE = "RELEASE"
BUILD_MODES = frozenset({BUILD_MODE_DEBUG, BUILD_MODE_RELEASE})

# ---------------------------------------------------------------------------
# 事件类型（T01）
# ---------------------------------------------------------------------------

EVENT_BUILD_CREATED = "build.created"
EVENT_BUILD_QUEUED = "build.queued"
EVENT_BUILD_STARTED = "build.started"
EVENT_BUILD_ATTEMPT_COMPLETED = "build.attempt.completed"
EVENT_BUILD_FAILED = "build.failed"
EVENT_BUILD_UNKNOWN = "build.unknown"
EVENT_ARTIFACT_REGISTERED = "artifact.registered"
EVENT_ARTIFACT_VERIFIED = "artifact.verified"
EVENT_ARTIFACT_REJECTED = "artifact.rejected"
EVENT_PACKAGE_CREATED = "package.created"
EVENT_SIGNING_STARTED = "signing.started"
EVENT_SIGNING_COMPLETED = "signing.completed"
EVENT_RELEASE_CANDIDATE_CREATED = "release_candidate.created"
EVENT_RELEASE_CANDIDATE_READY = "release_candidate.ready"
EVENT_RELEASE_APPROVAL_REQUESTED = "release.approval.requested"
EVENT_RELEASE_APPROVAL_COMPLETED = "release.approval.completed"
EVENT_RELEASE_STARTED = "release.started"
EVENT_RELEASE_PUBLISHED = "release.published"
EVENT_RELEASE_FAILED = "release.failed"
EVENT_RELEASE_UNKNOWN = "release.unknown"
EVENT_RELEASE_WITHDRAWN = "release.withdrawn"
EVENT_RELEASE_ROLLED_BACK = "release.rolled_back"
BUILD_RELEASE_EVENT_TYPES = (
    EVENT_BUILD_CREATED,
    EVENT_BUILD_QUEUED,
    EVENT_BUILD_STARTED,
    EVENT_BUILD_ATTEMPT_COMPLETED,
    EVENT_BUILD_FAILED,
    EVENT_BUILD_UNKNOWN,
    EVENT_ARTIFACT_REGISTERED,
    EVENT_ARTIFACT_VERIFIED,
    EVENT_ARTIFACT_REJECTED,
    EVENT_PACKAGE_CREATED,
    EVENT_SIGNING_STARTED,
    EVENT_SIGNING_COMPLETED,
    EVENT_RELEASE_CANDIDATE_CREATED,
    EVENT_RELEASE_CANDIDATE_READY,
    EVENT_RELEASE_APPROVAL_REQUESTED,
    EVENT_RELEASE_APPROVAL_COMPLETED,
    EVENT_RELEASE_STARTED,
    EVENT_RELEASE_PUBLISHED,
    EVENT_RELEASE_FAILED,
    EVENT_RELEASE_UNKNOWN,
    EVENT_RELEASE_WITHDRAWN,
    EVENT_RELEASE_ROLLED_BACK,
)


def transitions_for(kind: str) -> dict[str, frozenset[str]]:
    """按领域类型返回状态迁移表。"""

    table = {
        "build": BUILD_TRANSITIONS,
        "artifact": ARTIFACT_TRANSITIONS,
        "release_candidate": RC_TRANSITIONS,
        "release": RELEASE_TRANSITIONS,
    }.get(kind)
    if table is None:
        raise ValueError(f"未知状态机类型: {kind}")
    return table


# ---------------------------------------------------------------------------
# Batch A 领域表（T02 / T03 / T04）
# ---------------------------------------------------------------------------


class BuildConfigurationModel(Base):
    """构建配置身份（T02）。

    ``current_version`` 指向最新版本；已用于构建的历史版本通过
    ``BuildConfigurationVersionModel`` 保留不可变快照。
    """

    __tablename__ = "build_configurations"

    configuration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    target_platform: Mapped[str] = mapped_column(String(16), nullable=False)
    architecture: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_build_configuration_name"),
        Index("ix_build_configurations_project", "project_id", "created_at"),
    )


class BuildConfigurationVersionModel(Base):
    """构建配置版本快照（T02）：一经创建不可修改，修改配置产生新版本。"""

    __tablename__ = "build_configuration_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    configuration_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("build_configurations.configuration_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    godot_version_constraint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    target_platform: Mapped[str] = mapped_column(String(16), nullable=False)
    architecture: Mapped[str] = mapped_column(String(32), nullable=False)
    renderer: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    export_preset_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    build_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=BUILD_MODE_RELEASE)
    feature_tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_format: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    env_allowlist_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    build_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    resource_budget_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    packaging_policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    verification_policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("configuration_id", "version", name="uq_build_config_version"),
        Index("ix_build_config_versions_project_platform", "project_id", "target_platform"),
    )


class ExportPresetModel(Base):
    """Godot Export Preset 快照（T03）：默认只读，变更需经 ChangeSet。"""

    __tablename__ = "export_presets"

    preset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    preset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    export_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=BUILD_MODE_RELEASE)
    export_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    features_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    resource_filters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    template_required: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    template_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="VALID")
    validation_errors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "preset_name", name="uq_export_preset_name"),
        Index("ix_export_presets_project_platform", "project_id", "platform"),
    )


class BuildEnvironmentModel(Base):
    """构建环境指纹（T04）。同名指纹重复检查时复用记录。"""

    __tablename__ = "build_environments"

    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=True
    )
    os_name: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    os_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    cpu_architecture: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    godot_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    godot_executable_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    godot_executable_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    export_template_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    toolchain_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    sdk_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    renderer: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    build_executor_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    environment_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=ENV_UNKNOWN)
    diagnostics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_build_environments_project_fingerprint", "project_id", "environment_fingerprint"),
        Index("ix_build_environments_fingerprint", "environment_fingerprint"),
    )


class PlatformCapabilityModel(Base):
    """平台导出能力登记（T07 的基础数据，T04 使用）。

    未登记或状态非 SUPPORTED 的平台不得显示为具备可用导出能力。
    """

    __tablename__ = "platform_capabilities"

    capability_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform_id: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    platform_name: Mapped[str] = mapped_column(String(64), nullable=False)
    supported_architectures_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    supported_godot_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_export_templates_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_sdks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_signing_tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    supported_package_formats_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    capability_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CAPABILITY_UNKNOWN
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BuildJobModel(Base):
    """逻辑构建任务（T01 / T05）。

    与 Attempt 分离：重试只新增 Attempt，不覆盖旧记录。
    """

    __tablename__ = "build_jobs"

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    build_config_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("build_configurations.configuration_id", ondelete="SET NULL"),
        nullable=True,
    )
    build_config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_revision: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    environment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=BUILD_QUEUED)
    current_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_build_jobs_project_status", "project_id", "status"),
        Index("ix_build_jobs_config", "build_config_id"),
    )


class BuildAttemptModel(Base):
    """单次构建执行尝试（T01 / T06）。"""

    __tablename__ = "build_attempts"

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    build_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("build_jobs.build_id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    executor_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=ATTEMPT_PENDING)
    command_template_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    command_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    environment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    environment_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stdout_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stderr_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("build_id", "attempt_number", name="uq_build_attempt_number"),
        Index("ix_build_attempts_build", "build_id"),
        Index("ix_build_attempts_status", "status"),
    )


class BuildLogModel(Base):
    """已脱敏构建日志片段（T06 日志采集）。"""

    __tablename__ = "build_logs"

    log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("build_attempts.attempt_id", ondelete="CASCADE"), nullable=False
    )
    stream: Mapped[str] = mapped_column(String(16), nullable=False, default="stdout")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_build_logs_attempt_seq", "attempt_id", "sequence"),)


# ---------------------------------------------------------------------------
# Batch C 领域表（T08 / T09 / T13）
# ---------------------------------------------------------------------------


class ArtifactModel(Base):
    """不可变构建制品（T08）。内容变化只能生成新版本与新哈希。"""

    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    build_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("build_jobs.build_id", ondelete="SET NULL"), nullable=True
    )
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    architecture: Mapped[str] = mapped_column(String(32), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ARTIFACT_REGISTERED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "project_id", "build_id", "artifact_version", name="uq_artifact_build_version"
        ),
        Index("ix_artifacts_project", "project_id", "created_at"),
        Index("ix_artifacts_hash", "content_hash"),
    )


class ArtifactManifestModel(Base):
    """制品文件清单。"""

    __tablename__ = "artifact_manifests"

    manifest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("artifacts.artifact_id", ondelete="CASCADE"), nullable=False
    )
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_artifact_manifests_artifact", "artifact_id"),)


class PackageModel(Base):
    """交付包（T09）。"""

    __tablename__ = "artifact_packages"

    package_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    package_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    artifact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("artifacts.artifact_id", ondelete="RESTRICT"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(32), nullable=False, default="zip")
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    package_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=PACKAGE_CREATED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("artifact_id", "package_version", name="uq_package_artifact_version"),
        Index("ix_artifact_packages_project", "project_id", "created_at"),
    )


class PackageManifestModel(Base):
    """交付包清单。"""

    __tablename__ = "package_manifests"

    manifest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    package_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("artifact_packages.package_id", ondelete="CASCADE"),
        nullable=False,
    )
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_package_manifests_package", "package_id"),)


class BuildProvenanceModel(Base):
    """构建来源与可追溯信息（T13）。"""

    __tablename__ = "build_provenance"

    provenance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    build_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_revision: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    config_snapshot_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    environment_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    command_template_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    executor_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    outputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("build_id", "attempt_id", name="uq_provenance_build_attempt"),
        Index("ix_build_provenance_project", "project_id", "created_at"),
    )


class ReleaseEvidenceModel(Base):
    """发布证据（T13）：验证结果、制品校验、审批等引用。"""

    __tablename__ = "release_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    release_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_release_evidence_project", "project_id", "created_at"),
        Index("ix_release_evidence_artifact", "artifact_id"),
        Index("ix_release_evidence_candidate", "release_candidate_id"),
    )


# ---------------------------------------------------------------------------
# Batch D 领域表（T11 / T14）
# ---------------------------------------------------------------------------


class ReleaseCandidateModel(Base):
    """发布候选（T11）。候选清单哈希绑定制品与交付包内容。"""

    __tablename__ = "release_candidates"

    release_candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("artifacts.artifact_id", ondelete="RESTRICT"), nullable=False
    )
    package_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("artifact_packages.package_id", ondelete="RESTRICT"),
        nullable=True,
    )
    verification_campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    candidate_manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RC_DRAFT)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_release_candidates_project", "project_id", "version"),
        Index("ix_release_candidates_status", "status"),
    )


class SmokeTestResultModel(Base):
    """冒烟测试结果（T14）。SKIPPED 不等同于 PASSED。"""

    __tablename__ = "smoke_test_results"

    smoke_test_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=SMOKE_UNKNOWN)
    checks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_reference: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_smoke_test_results_project", "project_id", "created_at"),
        Index("ix_smoke_test_results_artifact", "artifact_id"),
        Index("ix_smoke_test_results_candidate", "release_candidate_id"),
    )


# ---------------------------------------------------------------------------
# Batch E 状态常量（T10 / T12 / T15 / T16）
# ---------------------------------------------------------------------------

SIGNING_ACTIVE = "ACTIVE"
SIGNING_DISABLED = "DISABLED"
SIGNING_EXPIRED = "EXPIRED"
SIGNING_PROFILE_STATUSES = frozenset({SIGNING_ACTIVE, SIGNING_DISABLED, SIGNING_EXPIRED})

SIGNING_PENDING = "PENDING"
SIGNING_SUCCEEDED = "SUCCEEDED"
SIGNING_FAILED = "FAILED"
SIGNING_UNKNOWN = "UNKNOWN"
SIGNING_ATTEMPT_STATUSES = frozenset(
    {SIGNING_PENDING, SIGNING_SUCCEEDED, SIGNING_FAILED, SIGNING_UNKNOWN}
)
SIGNING_ATTEMPT_TRANSITIONS: dict[str, frozenset[str]] = {
    SIGNING_PENDING: frozenset({SIGNING_SUCCEEDED, SIGNING_FAILED, SIGNING_UNKNOWN}),
    # 结果不明确时必须核对签名工具输出后再收敛，不能直接重试。
    SIGNING_UNKNOWN: frozenset({SIGNING_SUCCEEDED, SIGNING_FAILED}),
    SIGNING_SUCCEEDED: frozenset(),
    SIGNING_FAILED: frozenset(),
}

APPROVAL_PENDING = "PENDING"
APPROVAL_APPROVED = "APPROVED"
APPROVAL_REJECTED = "REJECTED"
APPROVAL_INVALIDATED = "INVALIDATED"
APPROVAL_STATUSES = frozenset(
    {APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED, APPROVAL_INVALIDATED}
)
APPROVAL_TRANSITIONS: dict[str, frozenset[str]] = {
    APPROVAL_PENDING: frozenset({APPROVAL_APPROVED, APPROVAL_REJECTED, APPROVAL_INVALIDATED}),
    # 任何关键内容变化都会使原审批失效。
    APPROVAL_APPROVED: frozenset({APPROVAL_INVALIDATED}),
    APPROVAL_REJECTED: frozenset(),
    APPROVAL_INVALIDATED: frozenset(),
}

DIST_PENDING = "PENDING"
DIST_SUCCEEDED = "SUCCEEDED"
DIST_FAILED = "FAILED"
DIST_UNKNOWN = "UNKNOWN"
DIST_WITHDRAWN = "WITHDRAWN"
DISTRIBUTION_OPERATION_STATUSES = frozenset(
    {DIST_PENDING, DIST_SUCCEEDED, DIST_FAILED, DIST_UNKNOWN, DIST_WITHDRAWN}
)

CHANNEL_LOCAL = "LOCAL"
CHANNEL_LOCAL_EXPORT = "LOCAL_EXPORT"
CHANNEL_USER_DOWNLOAD = "USER_DOWNLOAD"
CHANNEL_USER_OUTPUT_DIR = "USER_OUTPUT_DIR"
DISTRIBUTION_CHANNELS = frozenset(
    {CHANNEL_LOCAL, CHANNEL_LOCAL_EXPORT, CHANNEL_USER_DOWNLOAD, CHANNEL_USER_OUTPUT_DIR}
)


class SigningProfileModel(Base):
    """签名配置（T10）。只保存证书/凭证引用，绝不写入密钥本体。"""

    __tablename__ = "signing_profiles"

    signing_profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    signing_method: Mapped[str] = mapped_column(String(32), nullable=False)
    certificate_reference: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    credential_reference: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    allowed_channels_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=SIGNING_ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "project_id", "platform", "signing_method", name="uq_signing_profile_scope"
        ),
        Index("ix_signing_profiles_project", "project_id", "status"),
    )


class SigningAttemptModel(Base):
    """签名尝试（T10）。失败不得覆盖原制品内容。"""

    __tablename__ = "signing_attempts"

    signing_attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    signing_profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("signing_profiles.signing_profile_id", ondelete="RESTRICT"),
        nullable=False,
    )
    artifact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("artifacts.artifact_id", ondelete="RESTRICT"), nullable=False
    )
    artifact_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    certificate_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    signature_reference: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=SIGNING_PENDING)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_signing_attempts_project", "project_id", "created_at"),
        Index("ix_signing_attempts_artifact", "artifact_id"),
        Index("ix_signing_attempts_profile", "signing_profile_id"),
    )


class ReleaseApprovalModel(Base):
    """发布审批（T12）。审批绑定候选清单、制品与包哈希。"""

    __tablename__ = "release_approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    release_candidate_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("release_candidates.release_candidate_id", ondelete="RESTRICT"),
        nullable=False,
    )
    artifact_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    package_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    manifest_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(32), nullable=False)
    distribution_channel: Mapped[str] = mapped_column(String(32), nullable=False)
    release_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=APPROVAL_PENDING)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_release_approvals_project", "project_id", "requested_at"),
        Index("ix_release_approvals_candidate", "release_candidate_id", "status"),
    )


class ReleaseModel(Base):
    """正式发布（T15）。本地交付与线上发布必须区分。"""

    __tablename__ = "releases"

    release_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    release_candidate_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("release_candidates.release_candidate_id", ondelete="RESTRICT"),
        nullable=False,
    )
    approval_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("release_approvals.approval_id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RELEASE_PENDING)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    distribution_reference: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    external_operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_releases_project", "project_id", "version"),
        Index("ix_releases_candidate", "release_candidate_id"),
        Index("ix_releases_status", "status"),
    )


class DistributionOperationModel(Base):
    """分发操作（T16）。以 idempotency_key 保证幂等提交。"""

    __tablename__ = "distribution_operations"

    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    release_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("releases.release_id", ondelete="CASCADE"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    operation_status: Mapped[str] = mapped_column(String(24), nullable=False, default=DIST_PENDING)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    external_operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_reference: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_distribution_operations_project", "project_id", "started_at"),)
