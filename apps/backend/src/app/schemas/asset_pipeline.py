"""E8 资产管线请求模型（T19）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.project_workflow import StrictModel

ASSET_CATEGORY_LITERAL = Literal["IMAGE", "AUDIO", "MODEL_3D", "RESOURCE"]
OPERATION_LITERAL = Literal["CREATE", "UPDATE", "DELETE", "MOVE"]
RISK_LITERAL = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class AssetCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=256)
    category: ASSET_CATEGORY_LITERAL
    asset_type: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=32)


class AssetMetadataPatchRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=32)
    expected_version: int | None = Field(default=None, ge=1)


class GenerationCreateRequest(StrictModel):
    version_id: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    prompt: str = Field(min_length=1, max_length=8000)
    provider_id: str | None = Field(default=None, max_length=64)
    model_id: str | None = Field(default=None, max_length=128)
    brief_id: str | None = Field(default=None, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_count: int = Field(default=1, ge=1, le=8)
    budget: dict[str, Any] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ProcessingJobCreateRequest(StrictModel):
    input_version_id: str = Field(min_length=1, max_length=64)
    graph: dict[str, Any]
    idempotency_key: str | None = Field(default=None, max_length=128)


class QualityReviewCreateRequest(StrictModel):
    version_id: str = Field(min_length=1, max_length=64)
    rules: dict[str, Any] = Field(default_factory=dict)


class QualityDecisionRequest(StrictModel):
    asset_id: str = Field(min_length=1, max_length=64)
    approved: bool
    notes: str | None = Field(default=None, max_length=2000)


class LicenseReviewCreateRequest(StrictModel):
    version_id: str = Field(min_length=1, max_length=64)
    license_name: str = Field(min_length=1, max_length=256)
    source_type: str = Field(min_length=1, max_length=32)
    license_family: str | None = Field(default=None, max_length=64)
    source_reference: str | None = Field(default=None, max_length=1024)
    commercial_use: bool | None = None
    modification_allowed: bool | None = None
    redistribution_allowed: bool | None = None
    attribution_required: bool | None = None
    attribution_text: str | None = Field(default=None, max_length=2000)
    expiration_at: datetime | None = None
    territory: str | None = Field(default=None, max_length=256)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class LicenseDecisionRequest(StrictModel):
    asset_id: str = Field(min_length=1, max_length=64)
    commercial_use: bool
    modification_allowed: bool
    redistribution_allowed: bool
    attribution_required: bool = False
    attribution_text: str | None = Field(default=None, max_length=2000)
    expiration_at: datetime | None = None
    territory: str | None = Field(default=None, max_length=256)
    verification_method: str | None = Field(default=None, max_length=64)


class ImportCreateRequest(StrictModel):
    version_id: str = Field(min_length=1, max_length=64)
    target_path: str = Field(min_length=1, max_length=1024)
    session_id: str | None = Field(default=None, max_length=64)
    changeset_id: str | None = Field(default=None, max_length=64)
    resource_type: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=128)
    timeout_seconds: float = Field(default=5.0, gt=0)


class DeliveryPlanCreateRequest(StrictModel):
    version_id: str = Field(min_length=1, max_length=64)
    target_path: str = Field(min_length=1, max_length=1024)
    resource_type: str | None = Field(default=None, max_length=64)
    operation_type: OPERATION_LITERAL = "CREATE"
    old_content_hash: str | None = Field(default=None, max_length=64)
    risk_level: RISK_LITERAL = "MEDIUM"
    title: str | None = Field(default=None, max_length=256)
    require_human_review: bool = True
    require_commercial_use: bool = True
    require_redistribution: bool = False
    approval_ttl_seconds: int = Field(default=86400, gt=0, le=7 * 86400)


class DeliveryApprovalRequest(StrictModel):
    approval_id: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=2000)
