"""Multi-Agent Observability（E7-T19）。

只读视图：Team Dashboard、Agent Team Graph、Assignment Dashboard 与事件时间线。
所有方法不修改 Team/Assignment/Workflow 状态，不触碰 Task 状态。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from core.errors import NotFoundError
from core.security.tokens import isoformat
from infrastructure.database.service import DatabaseService
from modules.multi_agent.budget import TeamBudgetService
from modules.multi_agent.conflicts import ConflictService
from modules.multi_agent.lead import IntegrationService, LeadAgentService
from modules.multi_agent.repository import AgentResourceLockRepository
from modules.multi_agent.review import ReviewService
from modules.multi_agent.service import (
    AgentTeamService,
    AssignmentService,
    HandoffService,
    HandoffView,
)

__all__ = ["TeamObservabilityService", "to_jsonable"]


def to_jsonable(value: Any) -> Any:
    """把 dataclass / datetime / tuple 递归转换为可 JSON 序列化结构。"""

    if isinstance(value, datetime):
        return isoformat(value)
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return value


class TeamObservabilityService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        teams: AgentTeamService,
        assignments: AssignmentService,
        handoffs: HandoffService,
        conflicts: ConflictService,
        integrations: IntegrationService,
        reviews: ReviewService,
        budgets: TeamBudgetService,
        lead: LeadAgentService,
    ) -> None:
        self._database = database
        self._teams = teams
        self._assignments = assignments
        self._handoffs = handoffs
        self._conflicts = conflicts
        self._integrations = integrations
        self._reviews = reviews
        self._budgets = budgets
        self._lead = lead

    async def team_dashboard(self, team_id: str) -> dict[str, Any]:
        team = await self._teams.get(team_id)
        members = await self._teams.get_members(team_id)
        assignments = await self._assignments.list_for_team(team_id)
        conflicts = await self._conflicts.list_for_team(team_id)
        integrations = await self._integrations.list_for_team(team_id)
        budget = await self._budgets.find(team_id)
        board = await self._lead.status_board(team_id)
        interface_conflicts = await self._lead.detect_interface_conflicts(team_id)
        handoffs = await self._handoffs_for_team(team_id)
        counts: dict[str, int] = {}
        for assignment in assignments:
            counts[assignment.status] = counts.get(assignment.status, 0) + 1
        return {
            "team": to_jsonable(team),
            "members": to_jsonable(members),
            "assignment_counts": counts,
            "assignments": to_jsonable(assignments),
            "handoffs": to_jsonable(handoffs),
            "conflicts": to_jsonable(conflicts),
            "integrations": to_jsonable(integrations),
            "budget": to_jsonable(budget),
            "missing_outputs": list(board.missing_outputs),
            "interface_conflicts": to_jsonable(interface_conflicts),
            "graph": self._graph(assignments),
        }

    async def team_graph(self, team_id: str) -> dict[str, Any]:
        assignments = await self._assignments.list_for_team(team_id)
        return self._graph(assignments)

    async def assignment_dashboard(self, assignment_id: str) -> dict[str, Any]:
        assignment = await self._assignments.get(assignment_id)
        async with self._database.session() as session:
            locks = await AgentResourceLockRepository(session).list_for_assignment(assignment_id)
        dependencies = []
        for dependency_id in assignment.dependencies:
            try:
                dependency = await self._assignments.get(dependency_id)
            except NotFoundError:
                dependencies.append({"assignment_id": dependency_id, "status": "MISSING"})
                continue
            dependencies.append(
                {
                    "assignment_id": dependency.assignment_id,
                    "status": dependency.status,
                    "output_reference": dependency.output_reference,
                }
            )
        return {
            "assignment": to_jsonable(assignment),
            "dependencies": dependencies,
            "locks": to_jsonable(locks),
            "handoffs": to_jsonable(await self._handoffs.list_for_source(assignment_id)),
            "reviews": to_jsonable(await self._reviews.list_for_target(assignment_id)),
            "blocked": [
                item["assignment_id"] for item in dependencies if item["status"] != "COMPLETED"
            ],
        }

    async def team_events(self, team_id: str) -> list[dict[str, Any]]:
        """事件时间线：Handoff、冲突与集成状态，按创建时间排序。"""

        events: list[dict[str, Any]] = []
        for handoff in await self._handoffs_for_team(team_id):
            events.append(
                {
                    "event_type": "HANDOFF",
                    "event_id": handoff.handoff_id,
                    "status": handoff.status,
                    "at": isoformat(handoff.created_at),
                    "detail": {
                        "source_assignment_id": handoff.source_assignment_id,
                        "target_assignment_id": handoff.target_assignment_id,
                    },
                }
            )
        for conflict in await self._conflicts.list_for_team(team_id):
            events.append(
                {
                    "event_type": "CONFLICT",
                    "event_id": conflict.conflict_id,
                    "status": conflict.resolution_status,
                    "at": isoformat(conflict.created_at),
                    "detail": {"severity": conflict.severity, "type": conflict.conflict_type},
                }
            )
        for integration in await self._integrations.list_for_team(team_id):
            events.append(
                {
                    "event_type": "INTEGRATION",
                    "event_id": integration.integration_id,
                    "status": integration.status,
                    "at": isoformat(integration.created_at),
                    "detail": {"sources": list(integration.source_assignment_ids)},
                }
            )
        events.sort(key=lambda item: item["at"])
        return events

    async def overview(self, project_id: str) -> dict[str, Any]:
        teams = await self._teams.list(project_id=project_id, limit=100)
        items = []
        for team in teams["items"]:
            assignments = await self._assignments.list_for_team(team.team_id)
            conflicts = await self._conflicts.list_for_team(team.team_id)
            items.append(
                {
                    "team_id": team.team_id,
                    "task_id": team.task_id,
                    "status": team.status,
                    "assignment_count": len(assignments),
                    "completed_count": sum(1 for item in assignments if item.status == "COMPLETED"),
                    "open_conflicts": sum(
                        1
                        for item in conflicts
                        if item.resolution_status not in {"RESOLVED", "CANCELLED"}
                    ),
                }
            )
        return {"project_id": project_id, "teams": items}

    async def _handoffs_for_team(self, team_id: str) -> list[HandoffView]:
        handoffs: list[HandoffView] = []
        for assignment in await self._assignments.list_for_team(team_id):
            handoffs.extend(await self._handoffs.list_for_source(assignment.assignment_id))
        return handoffs

    @staticmethod
    def _graph(assignments) -> dict[str, Any]:
        nodes = [
            {
                "assignment_id": item.assignment_id,
                "agent_definition_id": item.agent_definition_id,
                "status": item.status,
                "objective": item.assigned_objective,
                "risk_level": item.risk_level,
                "priority": item.priority,
            }
            for item in assignments
        ]
        edges = [
            {"from": dependency_id, "to": item.assignment_id}
            for item in assignments
            for dependency_id in item.dependencies
        ]
        return {"nodes": nodes, "edges": edges}
