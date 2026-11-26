"""E11 Platformer Demo 请求模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.project_workflow import StrictModel

ACCEPTANCE_DECISION_LITERAL = Literal["ACCEPTED", "ACCEPTED_WITH_NOTES", "REJECTED"]
DEMO_CRITERION_STATUS_LITERAL = Literal["PENDING", "MET", "NOT_MET", "WAIVED"]
DEMO_SCENARIO_STATUS_LITERAL = Literal["PLANNED", "PASSED", "FAILED", "BLOCKED"]


class DemoAcceptanceReviewRequest(StrictModel):
    decision: ACCEPTANCE_DECISION_LITERAL
    summary: str = Field(min_length=1, max_length=2000)
    known_issues: list[str] = Field(default_factory=list, max_length=50)
    remaining_risks: list[str] = Field(default_factory=list, max_length=50)
    follow_up_title: str | None = Field(default=None, max_length=256)


class DemoCriterionStatusRequest(StrictModel):
    requirement_key: str = Field(min_length=1, max_length=64)
    criterion_key: str = Field(min_length=1, max_length=64)
    status: DEMO_CRITERION_STATUS_LITERAL


class DemoScenarioStatusRequest(StrictModel):
    scenario_key: str = Field(min_length=1, max_length=64)
    status: DEMO_SCENARIO_STATUS_LITERAL
