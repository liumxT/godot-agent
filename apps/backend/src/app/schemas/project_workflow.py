"""E4 Project / Task / Workflow / ChangeSet / Approval 请求模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROJECT_TYPE_LITERAL = Literal["GODOT_2D", "GODOT_3D", "GODOT_HYBRID", "GODOT_UNKNOWN"]
TASK_TYPE_LITERAL = Literal[
    "GAME_DEVELOPMENT",
    "BUG_FIX",
    "REFACTORING",
    "ASSET_CREATION",
    "LEVEL_DESIGN",
    "UI_DEVELOPMENT",
    "TESTING",
    "OPTIMIZATION",
    "RESEARCH",
    "GENERAL",
]
PRIORITY_LITERAL = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
TASK_STATUS_LITERAL = Literal[
    "CREATED",
    "READY",
    "QUEUED",
    "RUNNING",
    "PAUSING",
    "PAUSED",
    "RESUMING",
    "WAITING_APPROVAL",
    "WAITING_USER",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "REVIEW_PENDING",
    "COMPLETED",
    "REJECTED",
    "NEEDS_REVISION",
]
DEPENDENCY_TYPE_LITERAL = Literal[
    "FINISH_TO_START", "START_TO_START", "FINISH_TO_FINISH", "BLOCKS", "RELATED"
]
CHECKPOINT_TYPE_LITERAL = Literal[
    "EXECUTION_STARTED",
    "PHASE_COMPLETED",
    "WAITING_APPROVAL",
    "SAFE_PAUSE",
    "RECOVERY_POINT",
    "EXECUTION_INTERRUPTED",
]
OPERATION_LITERAL = Literal["CREATE", "UPDATE", "DELETE", "MOVE", "COPY"]
RISK_LITERAL = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
APPROVAL_DECISION_LITERAL = Literal["approve", "reject", "cancel"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectCreateRequest(StrictModel):
    project_root: str = Field(min_length=1, max_length=1024)
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    project_type: PROJECT_TYPE_LITERAL = "GODOT_UNKNOWN"
    godot_version: str | None = Field(default=None, max_length=32)


class ProjectUpdateRequest(StrictModel):
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    project_type: PROJECT_TYPE_LITERAL | None = None
    expected_version: int | None = Field(default=None, ge=1)


class ProjectArchiveRequest(StrictModel):
    force: bool = False


class ConfigurationUpdateRequest(StrictModel):
    configuration: dict[str, Any]
    expected_version: int | None = Field(default=None, ge=1)


class TaskCreateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=20000)
    task_type: TASK_TYPE_LITERAL = "GENERAL"
    priority: PRIORITY_LITERAL = "MEDIUM"
    parent_task_id: str | None = Field(default=None, max_length=64)


class TaskTransitionRequest(StrictModel):
    status: TASK_STATUS_LITERAL
    reason: str | None = Field(default=None, max_length=2000)
    expected_version: int | None = Field(default=None, ge=1)


class TaskRejectRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=2000)


class AttemptCreateRequest(StrictModel):
    agent_instance_id: str | None = Field(default=None, max_length=64)
    workflow_instance_id: str | None = Field(default=None, max_length=64)


class AttemptFinishRequest(StrictModel):
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"] = "SUCCEEDED"
    summary: str | None = Field(default=None, max_length=20000)
    failure_code: str | None = Field(default=None, max_length=64)
    failure_reason: str | None = Field(default=None, max_length=4000)
    resource_usage: str | None = Field(default=None, max_length=4000)


class DependencyCreateRequest(StrictModel):
    source_task_id: str = Field(min_length=1, max_length=64)
    target_task_id: str = Field(min_length=1, max_length=64)
    dependency_type: DEPENDENCY_TYPE_LITERAL = "FINISH_TO_START"


class CheckpointCreateRequest(StrictModel):
    checkpoint_type: CHECKPOINT_TYPE_LITERAL = "SAFE_PAUSE"
    attempt_id: str | None = Field(default=None, max_length=64)
    workflow_state_ref: str | None = Field(default=None, max_length=128)
    context_ref: str | None = Field(default=None, max_length=128)
    changeset_ref: str | None = Field(default=None, max_length=128)


class WorkflowDefinitionCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=4000)
    definition: dict[str, Any]


class WorkflowDefinitionVersionRequest(StrictModel):
    definition: dict[str, Any]


class WorkflowInstanceCreateRequest(StrictModel):
    definition_id: str = Field(min_length=1, max_length=64)
    definition_version: int | None = Field(default=None, ge=1)


class NodeOutputRequest(StrictModel):
    output_ref: str | None = Field(default=None, max_length=128)


class NodeErrorRequest(StrictModel):
    error_ref: str | None = Field(default=None, max_length=128)


class PhaseReviewSubmitRequest(StrictModel):
    summary: str | None = Field(default=None, max_length=20000)
    deliverables: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    verification_summary: str | None = Field(default=None, max_length=4000)


class PhaseReviewReasonRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=2000)


class ManifestItemRequest(StrictModel):
    resource_path: str = Field(min_length=1, max_length=1024)
    operation_type: OPERATION_LITERAL
    old_content_hash: str | None = Field(default=None, max_length=64)
    new_content_hash: str | None = Field(default=None, max_length=64)
    resource_type: str | None = Field(default=None, max_length=32)
    risk_level: RISK_LITERAL = "MEDIUM"


class ChangeSetCreateRequest(StrictModel):
    project_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    task_id: str | None = Field(default=None, max_length=64)
    attempt_id: str | None = Field(default=None, max_length=64)
    base_revision: str | None = Field(default=None, max_length=64)
    items: list[ManifestItemRequest] = Field(min_length=1)


class ManifestReplaceRequest(StrictModel):
    items: list[ManifestItemRequest] = Field(min_length=1)


class ChangeSetApprovalRequest(StrictModel):
    approval_id: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=2000)


class ChangeSetApplyRequest(StrictModel):
    approval_id: str = Field(min_length=1, max_length=64)


class ChangeSetFinishRequest(StrictModel):
    status: Literal["APPLIED", "FAILED", "UNKNOWN"]


class ApprovalDecisionRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=2000)


class RequirementCreateRequest(StrictModel):
    project_id: str = Field(min_length=1, max_length=128)
    requirement_key: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=20000)
    category: Literal["FUNCTIONAL", "NON_FUNCTIONAL", "CONSTRAINT", "ASSET"] = "FUNCTIONAL"
    priority: PRIORITY_LITERAL = "MEDIUM"
    source: str | None = Field(default=None, max_length=64)
    criteria: list[dict[str, Any]] = Field(default_factory=list)


class CriterionStatusRequest(StrictModel):
    status: Literal["PENDING", "MET", "NOT_MET", "WAIVED"]
    evidence: str | None = Field(default=None, max_length=2000)


class RequirementStatusRequest(StrictModel):
    status: Literal["DRAFT", "ACTIVE", "IMPLEMENTED", "VERIFIED", "REJECTED", "DEFERRED"]


class RequirementTraceRequest(StrictModel):
    task_id: str | None = Field(default=None, max_length=64)
    phase_id: str | None = Field(default=None, max_length=64)
    changeset_id: str | None = Field(default=None, max_length=64)
    verification_result_id: str | None = Field(default=None, max_length=64)
