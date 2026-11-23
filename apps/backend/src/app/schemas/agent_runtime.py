"""Agent Runtime API 请求模型（E6-T17）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentDefinitionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category: str = Field(default="GENERAL", min_length=1, max_length=40)
    model_policy_id: str = Field(default="default_agent_policy", min_length=1)
    prompt_profile_id: str = Field(min_length=1)
    prompt_version: int = Field(default=1, ge=1)
    context_profile_id: str = Field(default="DEFAULT", min_length=1)
    context_profile_version: str = Field(default="1", min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    tool_whitelist: list[str] = Field(default_factory=list)
    permission_ceiling: str = Field(default="R0", min_length=1)
    budget_profile_id: str = Field(default="default", min_length=1)
    budget: dict[str, Any] | None = None
    max_concurrency: int = Field(default=1, ge=1, le=20)


class AgentInstanceCreateRequest(BaseModel):
    definition_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    model_id: str | None = None


class AgentInstanceActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class AgentResumeRequest(BaseModel):
    approval_id: str | None = Field(default=None, min_length=1)
    reason: str | None = Field(default=None, max_length=512)
