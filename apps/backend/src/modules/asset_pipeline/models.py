"""Asset Pipeline 领域模型（E8-T01）。

状态所有权：

- Asset / AssetVersion / AssetVariant / AssetBrief 由 ``asset_pipeline`` 模块维护；
- Generation / Processing / Import / Quality / License / Delivery 各自拥有独立状态，
  禁止跨模块直接更新；
- AssetVersion 创建后内容不可变，任何内容变化必须创建新版本；
- Project 由 ``project_registry`` 拥有，Task 由 ``task`` 拥有，ChangeSet / Approval
  由 E4 拥有，本模块只保存引用；
- 资产内部暂存区与 Godot 项目目录隔离，只有通过门禁的版本才允许进入项目。
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

# ---- 分类体系（可扩展，不写入数据库约束）----

CATEGORY_IMAGE = "IMAGE"
CATEGORY_AUDIO = "AUDIO"
CATEGORY_MODEL_3D = "MODEL_3D"
CATEGORY_RESOURCE = "RESOURCE"

ASSET_CATEGORIES = frozenset(
    {CATEGORY_IMAGE, CATEGORY_AUDIO, CATEGORY_MODEL_3D, CATEGORY_RESOURCE}
)

ASSET_TYPES: dict[str, frozenset[str]] = {
    CATEGORY_IMAGE: frozenset(
        {
            "CHARACTER",
            "ENEMY",
            "TILESET",
            "BACKGROUND",
            "UI",
            "ICON",
            "VFX",
            "TEXTURE",
        }
    ),
    CATEGORY_AUDIO: frozenset({"SFX", "MUSIC", "AMBIENCE", "VOICE"}),
    CATEGORY_MODEL_3D: frozenset({"STATIC_MESH", "SKELETAL_MESH", "MATERIAL", "TEXTURE"}),
    CATEGORY_RESOURCE: frozenset({"FONT", "SHADER", "OTHER"}),
}

# ---- Asset 生命周期 ----

ASSET_DRAFT = "DRAFT"
ASSET_ACTIVE = "ACTIVE"
ASSET_DEPRECATED = "DEPRECATED"
ASSET_ARCHIVED = "ARCHIVED"
ASSET_STATUSES = frozenset({ASSET_DRAFT, ASSET_ACTIVE, ASSET_DEPRECATED, ASSET_ARCHIVED})
ASSET_TRANSITIONS: dict[str, frozenset[str]] = {
    ASSET_DRAFT: frozenset({ASSET_ACTIVE, ASSET_ARCHIVED}),
    ASSET_ACTIVE: frozenset({ASSET_DEPRECATED, ASSET_ARCHIVED}),
    ASSET_DEPRECATED: frozenset({ASSET_ACTIVE, ASSET_ARCHIVED}),
    ASSET_ARCHIVED: frozenset(),
}

# ---- Brief 状态 ----

BRIEF_DRAFT = "DRAFT"
BRIEF_PROPOSED = "PROPOSED"
BRIEF_APPROVED = "APPROVED"
BRIEF_REJECTED = "REJECTED"
BRIEF_SUPERSEDED = "SUPERSEDED"
BRIEF_STATUSES = frozenset(
    {BRIEF_DRAFT, BRIEF_PROPOSED, BRIEF_APPROVED, BRIEF_REJECTED, BRIEF_SUPERSEDED}
)
BRIEF_TRANSITIONS: dict[str, frozenset[str]] = {
    BRIEF_DRAFT: frozenset({BRIEF_PROPOSED, BRIEF_SUPERSEDED}),
    BRIEF_PROPOSED: frozenset({BRIEF_APPROVED, BRIEF_REJECTED, BRIEF_SUPERSEDED}),
    BRIEF_APPROVED: frozenset({BRIEF_SUPERSEDED}),
    BRIEF_REJECTED: frozenset({BRIEF_SUPERSEDED}),
    BRIEF_SUPERSEDED: frozenset(),
}

# ---- Generation 状态 ----

GENERATION_CREATED = "CREATED"
GENERATION_SUBMITTED = "SUBMITTED"
GENERATION_RUNNING = "RUNNING"
GENERATION_SUCCEEDED = "SUCCEEDED"
GENERATION_FAILED = "FAILED"
GENERATION_UNKNOWN = "UNKNOWN"
GENERATION_CANCELLED = "CANCELLED"
GENERATION_STATUSES = frozenset(
    {
        GENERATION_CREATED,
        GENERATION_SUBMITTED,
        GENERATION_RUNNING,
        GENERATION_SUCCEEDED,
        GENERATION_FAILED,
        GENERATION_UNKNOWN,
        GENERATION_CANCELLED,
    }
)
GENERATION_TRANSITIONS: dict[str, frozenset[str]] = {
    GENERATION_CREATED: frozenset(
        {GENERATION_SUBMITTED, GENERATION_CANCELLED, GENERATION_FAILED}
    ),
    GENERATION_SUBMITTED: frozenset(
        {
            GENERATION_RUNNING,
            GENERATION_SUCCEEDED,
            GENERATION_FAILED,
            GENERATION_UNKNOWN,
            GENERATION_CANCELLED,
        }
    ),
    GENERATION_RUNNING: frozenset(
        {
            GENERATION_SUCCEEDED,
            GENERATION_FAILED,
            GENERATION_UNKNOWN,
            GENERATION_CANCELLED,
        }
    ),
    GENERATION_SUCCEEDED: frozenset(),
    GENERATION_FAILED: frozenset(),
    GENERATION_UNKNOWN: frozenset({GENERATION_SUCCEEDED, GENERATION_FAILED, GENERATION_CANCELLED}),
    GENERATION_CANCELLED: frozenset(),
}

# ---- Processing 状态 ----

PROCESSING_QUEUED = "QUEUED"
PROCESSING_RUNNING = "RUNNING"
PROCESSING_SUCCEEDED = "SUCCEEDED"
PROCESSING_FAILED = "FAILED"
PROCESSING_UNKNOWN = "UNKNOWN"
PROCESSING_STATUSES = frozenset(
    {PROCESSING_QUEUED, PROCESSING_RUNNING, PROCESSING_SUCCEEDED, PROCESSING_FAILED, PROCESSING_UNKNOWN}
)
PROCESSING_TRANSITIONS: dict[str, frozenset[str]] = {
    PROCESSING_QUEUED: frozenset({PROCESSING_RUNNING, PROCESSING_FAILED, PROCESSING_UNKNOWN}),
    PROCESSING_RUNNING: frozenset(
        {PROCESSING_SUCCEEDED, PROCESSING_FAILED, PROCESSING_UNKNOWN}
    ),
    PROCESSING_SUCCEEDED: frozenset(),
    PROCESSING_FAILED: frozenset(),
    PROCESSING_UNKNOWN: frozenset({PROCESSING_SUCCEEDED, PROCESSING_FAILED}),
}

# ---- Import 状态 ----

IMPORT_NOT_IMPORTED = "NOT_IMPORTED"
IMPORT_REQUESTED = "IMPORT_REQUESTED"
IMPORT_IMPORTING = "IMPORTING"
IMPORT_IMPORTED = "IMPORTED"
IMPORT_FAILED = "FAILED"
IMPORT_UNKNOWN = "UNKNOWN"
IMPORT_STATUSES = frozenset(
    {
        IMPORT_NOT_IMPORTED,
        IMPORT_REQUESTED,
        IMPORT_IMPORTING,
        IMPORT_IMPORTED,
        IMPORT_FAILED,
        IMPORT_UNKNOWN,
    }
)
IMPORT_TRANSITIONS: dict[str, frozenset[str]] = {
    IMPORT_NOT_IMPORTED: frozenset({IMPORT_REQUESTED, IMPORT_FAILED}),
    IMPORT_REQUESTED: frozenset({IMPORT_IMPORTING, IMPORT_FAILED, IMPORT_UNKNOWN}),
    IMPORT_IMPORTING: frozenset({IMPORT_IMPORTED, IMPORT_FAILED, IMPORT_UNKNOWN}),
    IMPORT_IMPORTED: frozenset(),
    IMPORT_FAILED: frozenset({IMPORT_REQUESTED}),
    IMPORT_UNKNOWN: frozenset({IMPORT_IMPORTED, IMPORT_FAILED}),
}

# ---- Quality 状态 ----

QUALITY_PENDING = "QC_PENDING"
QUALITY_MACHINE_PASSED = "MACHINE_PASSED"
QUALITY_MACHINE_FAILED = "MACHINE_FAILED"
QUALITY_HUMAN_REQUIRED = "HUMAN_REVIEW_REQUIRED"
QUALITY_HUMAN_APPROVED = "HUMAN_APPROVED"
QUALITY_HUMAN_REJECTED = "HUMAN_REJECTED"
QUALITY_STATUSES = frozenset(
    {
        QUALITY_PENDING,
        QUALITY_MACHINE_PASSED,
        QUALITY_MACHINE_FAILED,
        QUALITY_HUMAN_REQUIRED,
        QUALITY_HUMAN_APPROVED,
        QUALITY_HUMAN_REJECTED,
    }
)
QUALITY_TRANSITIONS: dict[str, frozenset[str]] = {
    QUALITY_PENDING: frozenset({QUALITY_MACHINE_PASSED, QUALITY_MACHINE_FAILED}),
    QUALITY_MACHINE_FAILED: frozenset({QUALITY_PENDING, QUALITY_HUMAN_REQUIRED}),
    QUALITY_MACHINE_PASSED: frozenset(
        {QUALITY_HUMAN_REQUIRED, QUALITY_HUMAN_APPROVED, QUALITY_HUMAN_REJECTED}
    ),
    QUALITY_HUMAN_REQUIRED: frozenset({QUALITY_HUMAN_APPROVED, QUALITY_HUMAN_REJECTED}),
    QUALITY_HUMAN_APPROVED: frozenset(),
    QUALITY_HUMAN_REJECTED: frozenset(),
}

REVIEW_TYPE_MACHINE = "MACHINE"
REVIEW_TYPE_HUMAN = "HUMAN"
REVIEW_TYPES = frozenset({REVIEW_TYPE_MACHINE, REVIEW_TYPE_HUMAN})

# ---- License 状态 ----

LICENSE_UNKNOWN = "UNKNOWN"
LICENSE_PENDING_REVIEW = "PENDING_REVIEW"
LICENSE_VERIFIED = "VERIFIED"
LICENSE_REJECTED = "REJECTED"
LICENSE_EXPIRED = "EXPIRED"
LICENSE_RESTRICTED = "RESTRICTED"
LICENSE_STATUSES = frozenset(
    {
        LICENSE_UNKNOWN,
        LICENSE_PENDING_REVIEW,
        LICENSE_VERIFIED,
        LICENSE_REJECTED,
        LICENSE_EXPIRED,
        LICENSE_RESTRICTED,
    }
)
LICENSE_TRANSITIONS: dict[str, frozenset[str]] = {
    LICENSE_UNKNOWN: frozenset({LICENSE_PENDING_REVIEW, LICENSE_REJECTED}),
    LICENSE_PENDING_REVIEW: frozenset(
        {LICENSE_VERIFIED, LICENSE_REJECTED, LICENSE_RESTRICTED, LICENSE_EXPIRED}
    ),
    LICENSE_VERIFIED: frozenset({LICENSE_EXPIRED, LICENSE_RESTRICTED, LICENSE_REJECTED}),
    LICENSE_REJECTED: frozenset({LICENSE_PENDING_REVIEW}),
    LICENSE_RESTRICTED: frozenset({LICENSE_VERIFIED, LICENSE_EXPIRED}),
    LICENSE_EXPIRED: frozenset({LICENSE_PENDING_REVIEW}),
}

# ---- Provenance ----

SOURCE_USER_CREATED = "USER_CREATED"
SOURCE_USER_UPLOADED = "USER_UPLOADED"
SOURCE_AI_GENERATED = "AI_GENERATED"
SOURCE_EXTERNAL_PURCHASED = "EXTERNAL_PURCHASED"
SOURCE_OPEN_SOURCE = "OPEN_SOURCE"
SOURCE_PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
SOURCE_PROJECT_DERIVED = "PROJECT_DERIVED"
SOURCE_PROCEDURAL_GENERATED = "PROCEDURAL_GENERATED"
SOURCE_UNKNOWN = "UNKNOWN_SOURCE"
SOURCE_TYPES = frozenset(
    {
        SOURCE_USER_CREATED,
        SOURCE_USER_UPLOADED,
        SOURCE_AI_GENERATED,
        SOURCE_EXTERNAL_PURCHASED,
        SOURCE_OPEN_SOURCE,
        SOURCE_PUBLIC_DOMAIN,
        SOURCE_PROJECT_DERIVED,
        SOURCE_PROCEDURAL_GENERATED,
        SOURCE_UNKNOWN,
    }
)

# ---- 依赖类型 ----

DEPENDENCY_DIRECT = "DIRECT_REFERENCE"
DEPENDENCY_INDIRECT = "INDIRECT_REFERENCE"
DEPENDENCY_SCRIPT = "SCRIPT_REFERENCE"
DEPENDENCY_EDITOR = "EDITOR_REFERENCE"
DEPENDENCY_GENERATED = "GENERATED_REFERENCE"
DEPENDENCY_RESOURCE = "RESOURCE_DEPENDENCY"
DEPENDENCY_TYPES = frozenset(
    {
        DEPENDENCY_DIRECT,
        DEPENDENCY_INDIRECT,
        DEPENDENCY_SCRIPT,
        DEPENDENCY_EDITOR,
        DEPENDENCY_GENERATED,
        DEPENDENCY_RESOURCE,
    }
)

# ---- Delivery 状态 ----

DELIVERY_DRAFT = "DRAFT"
DELIVERY_READY = "READY"
DELIVERY_WAITING_APPROVAL = "WAITING_APPROVAL"
DELIVERY_APPROVED = "APPROVED"
DELIVERY_APPLYING = "APPLYING"
DELIVERY_IMPORTING = "IMPORTING"
DELIVERY_VERIFYING = "VERIFYING"
DELIVERY_DELIVERED = "DELIVERED"
DELIVERY_FAILED = "FAILED"
DELIVERY_UNKNOWN = "UNKNOWN"
DELIVERY_CANCELLED = "CANCELLED"
DELIVERY_STATUSES = frozenset(
    {
        DELIVERY_DRAFT,
        DELIVERY_READY,
        DELIVERY_WAITING_APPROVAL,
        DELIVERY_APPROVED,
        DELIVERY_APPLYING,
        DELIVERY_IMPORTING,
        DELIVERY_VERIFYING,
        DELIVERY_DELIVERED,
        DELIVERY_FAILED,
        DELIVERY_UNKNOWN,
        DELIVERY_CANCELLED,
    }
)
DELIVERY_TRANSITIONS: dict[str, frozenset[str]] = {
    DELIVERY_DRAFT: frozenset({DELIVERY_READY, DELIVERY_CANCELLED}),
    DELIVERY_READY: frozenset({DELIVERY_WAITING_APPROVAL, DELIVERY_CANCELLED}),
    DELIVERY_WAITING_APPROVAL: frozenset(
        {DELIVERY_APPROVED, DELIVERY_FAILED, DELIVERY_CANCELLED}
    ),
    DELIVERY_APPROVED: frozenset({DELIVERY_APPLYING, DELIVERY_FAILED, DELIVERY_CANCELLED}),
    DELIVERY_APPLYING: frozenset({DELIVERY_IMPORTING, DELIVERY_FAILED, DELIVERY_UNKNOWN}),
    DELIVERY_IMPORTING: frozenset({DELIVERY_VERIFYING, DELIVERY_FAILED, DELIVERY_UNKNOWN}),
    DELIVERY_VERIFYING: frozenset({DELIVERY_DELIVERED, DELIVERY_FAILED, DELIVERY_UNKNOWN}),
    DELIVERY_DELIVERED: frozenset(),
    DELIVERY_FAILED: frozenset({DELIVERY_DRAFT, DELIVERY_CANCELLED}),
    DELIVERY_UNKNOWN: frozenset({DELIVERY_DELIVERED, DELIVERY_FAILED}),
    DELIVERY_CANCELLED: frozenset(),
}

# ---- 内部存储区域 ----

STORAGE_SOURCE = "source"
STORAGE_GENERATED = "generated"
STORAGE_PROCESSED = "processed"
STORAGE_PREVIEWS = "previews"
STORAGE_MANIFESTS = "manifests"
STORAGE_TEMPORARY = "temporary"
STORAGE_AREAS = (
    STORAGE_SOURCE,
    STORAGE_GENERATED,
    STORAGE_PROCESSED,
    STORAGE_PREVIEWS,
    STORAGE_MANIFESTS,
    STORAGE_TEMPORARY,
)


def transitions_for(kind: str) -> dict[str, frozenset[str]]:
    """按领域类型返回状态迁移表。"""

    table = {
        "asset": ASSET_TRANSITIONS,
        "brief": BRIEF_TRANSITIONS,
        "generation": GENERATION_TRANSITIONS,
        "processing": PROCESSING_TRANSITIONS,
        "import": IMPORT_TRANSITIONS,
        "quality": QUALITY_TRANSITIONS,
        "license": LICENSE_TRANSITIONS,
        "delivery": DELIVERY_TRANSITIONS,
    }.get(kind)
    if table is None:
        raise ValueError(f"未知状态机类型: {kind}")
    return table


class AssetModel(Base):
    __tablename__ = "assets"

    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(24), nullable=False, default=ASSET_DRAFT)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_assets_project_status", "project_id", "lifecycle_status"),
        Index("ix_assets_project_category", "project_id", "category", "asset_type"),
        Index("ix_assets_current_version", "current_version_id"),
    )


class AssetVersionModel(Base):
    __tablename__ = "asset_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_id", "version_number", name="uq_asset_versions_number"),
        Index("ix_asset_versions_hash", "content_hash"),
    )


class AssetVariantModel(Base):
    __tablename__ = "asset_variants"

    variant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    variant_type: Mapped[str] = mapped_column(String(32), nullable=False)
    variant_key: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "asset_id", "variant_type", "variant_key", name="uq_asset_variants_key"
        ),
    )


class AssetBriefModel(Base):
    __tablename__ = "asset_briefs"

    brief_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_category: Mapped[str] = mapped_column(String(64), nullable=False)
    visual_direction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    style_reference: Mapped[str] = mapped_column(Text, nullable=False, default="")
    technical_constraints_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    animation_requirements_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    delivery_requirements_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    license_requirements_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    acceptance_criteria_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=BRIEF_DRAFT)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_asset_briefs_project_status", "project_id", "status"),
        Index("ix_asset_briefs_task", "task_id"),
    )


class AssetGenerationModel(Base):
    __tablename__ = "asset_generations"

    generation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    brief_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_briefs.brief_id", ondelete="SET NULL"), nullable=True
    )
    requested_spec_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=GENERATION_CREATED
    )
    result_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    budget_reservation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_asset_generations_idempotency"),
        Index("ix_asset_generations_asset_status", "asset_id", "generation_status"),
        Index("ix_asset_generations_provider_job", "provider_id", "provider_job_id"),
    )


class AssetGenerationOutputModel(Base):
    __tablename__ = "asset_generation_outputs"

    output_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_generations.generation_id", ondelete="CASCADE"), nullable=False
    )
    temporary_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_asset_generation_outputs_generation", "generation_id"),)


class AssetProcessingJobModel(Base):
    __tablename__ = "asset_processing_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    input_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="RESTRICT"), nullable=False
    )
    output_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_graph_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    processing_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PROCESSING_QUEUED
    )
    execution_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_asset_processing_jobs_idempotency"),
        Index("ix_asset_processing_jobs_asset_status", "asset_id", "processing_status"),
    )


class AssetProcessingStepModel(Base):
    __tablename__ = "asset_processing_steps"

    step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("asset_processing_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    processor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    processor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    execution_status: Mapped[str] = mapped_column(String(24), nullable=False)
    resource_usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_asset_processing_steps_job", "job_id", "node_id"),)


class AssetImportJobModel(Base):
    __tablename__ = "asset_import_jobs"

    import_job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="RESTRICT"), nullable=False
    )
    target_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    godot_resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=IMPORT_NOT_IMPORTED
    )
    godot_uid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    import_evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    editor_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_asset_import_jobs_idempotency"),
        Index("ix_asset_import_jobs_project_status", "project_id", "import_status"),
        Index("ix_asset_import_jobs_version", "asset_version_id"),
    )


class AssetImportEvidenceModel(Base):
    __tablename__ = "asset_import_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    import_job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_import_jobs.import_job_id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    editor_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    import_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    import_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    godot_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    import_result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    resource_uid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evidence_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_asset_import_evidence_job", "import_job_id"),)


class AssetProvenanceModel(Base):
    __tablename__ = "asset_provenance"

    provenance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    prompt_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seed: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_hashes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_hashes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    processing_graph_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    processor_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    operator_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_source_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_version_id", name="uq_asset_provenance_version"),
        Index("ix_asset_provenance_asset", "asset_id"),
    )


class AssetLicenseModel(Base):
    __tablename__ = "asset_licenses"

    license_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="CASCADE"), nullable=False
    )
    license_name: Mapped[str] = mapped_column(String(128), nullable=False)
    license_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    commercial_use: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    modification_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    redistribution_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attribution_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attribution_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    expiration_policy: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expiration_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    territory: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    verification_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default=LICENSE_UNKNOWN)
    reviewer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_asset_licenses_version", "asset_version_id", "verification_status"),
        Index("ix_asset_licenses_asset", "asset_id"),
    )


class AssetLicenseEvidenceModel(Base):
    __tablename__ = "asset_license_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    license_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_licenses.license_id", ondelete="CASCADE"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_asset_license_evidence_license", "license_id"),)


class AssetQualityReviewModel(Base):
    __tablename__ = "asset_quality_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="CASCADE"), nullable=False
    )
    review_type: Mapped[str] = mapped_column(String(16), nullable=False)
    machine_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default=QUALITY_PENDING)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    reviewer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_asset_quality_reviews_version", "asset_version_id", "review_status"),
        Index("ix_asset_quality_reviews_asset", "asset_id"),
    )


class AssetQualityFindingModel(Base):
    __tablename__ = "asset_quality_findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_quality_reviews.review_id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_asset_quality_findings_review", "review_id"),)


class AssetDependencyModel(Base):
    __tablename__ = "asset_dependencies"

    dependency_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="CASCADE"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    dependency_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_asset_dependencies_project_target", "project_id", "target_reference"),
        Index("ix_asset_dependencies_version", "asset_version_id"),
    )


class AssetDeliveryModel(Base):
    __tablename__ = "asset_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    changeset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_import_jobs.import_job_id", ondelete="SET NULL"), nullable=True
    )
    delivery_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=DELIVERY_DRAFT
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_asset_deliveries_project_status", "project_id", "delivery_status"),
        Index("ix_asset_deliveries_version", "asset_version_id"),
    )


class AssetStorageObjectModel(Base):
    __tablename__ = "asset_storage_objects"

    object_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_versions.version_id", ondelete="SET NULL"), nullable=True
    )
    storage_area: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "relative_path", name="uq_asset_storage_objects_path"),
        Index("ix_asset_storage_objects_hash", "content_hash"),
    )


class AssetProviderJobModel(Base):
    __tablename__ = "asset_provider_jobs"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_generations.generation_id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    result_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider_id", "provider_job_id", name="uq_asset_provider_jobs_external"),
        Index("ix_asset_provider_jobs_generation", "generation_id"),
    )
