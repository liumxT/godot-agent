"""Multi-Agent API 请求模型（E7-T20）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SubtaskRequest(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=2000)
    capabilities: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    required_tools: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    required_risk_level: str = Field(default="R0", min_length=1, max_length=8)
    estimated_duration_seconds: int | None = Field(default=None, ge=1)


class AgentTeamCreateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(default_factory=list)
    subtasks: list[SubtaskRequest] = Field(min_length=1)


class AssignmentCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)
    expected_version: int = Field(ge=1)


class HandoffAcceptRequest(BaseModel):
    expected_version: int = Field(ge=1)


class HandoffRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)
    expected_version: int = Field(ge=1)


class ConflictResolveRequest(BaseModel):
    strategy: str = Field(min_length=1, max_length=32)
    resolution_reference: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=512)


class TeamBudgetRequest(BaseModel):
    budget: dict[str, Any]
    task_budget: dict[str, Any] | None = None
    reason: str | None = Field(default=None, max_length=512)
    expected_version: int | None = Field(default=None, ge=0)
