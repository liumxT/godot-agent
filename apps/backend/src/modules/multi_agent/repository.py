"""Multi-Agent 仓储（E7-T01）。

Repository 只承载查询与写入，不提交事务；跨模块状态通过 ID 引用，
禁止在这里访问其他模块的 Repository。
"""

from __future__ import annotations

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository, Page
from modules.multi_agent.models import (
    AgentAssignmentDependencyModel,
    AgentAssignmentModel,
    AgentCapabilityModel,
    AgentCollaborationModel,
    AgentConflictModel,
    AgentHandoffModel,
    AgentIntegrationModel,
    AgentMessageModel,
    AgentReviewModel,
    AgentSharedContextModel,
    AgentTeamBudgetModel,
    AgentTeamMemberModel,
    AgentTeamModel,
)


class CapabilityRepository(BaseRepository[AgentCapabilityModel]):
    model = AgentCapabilityModel

    async def get_by_name(self, name: str) -> AgentCapabilityModel | None:
        return await self.session.scalar(
            select(AgentCapabilityModel).where(AgentCapabilityModel.name == name)
        )

    async def list_page(
        self,
        *,
        category: str | None = None,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[AgentCapabilityModel]:
        filters = []
        if category is not None:
            filters.append(AgentCapabilityModel.category == category)
        if enabled is not None:
            filters.append(AgentCapabilityModel.enabled == enabled)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    def _order_columns(self):
        return (AgentCapabilityModel.category, AgentCapabilityModel.name)


class AgentTeamRepository(BaseRepository[AgentTeamModel]):
    model = AgentTeamModel

    async def get_by_task(self, task_id: str) -> AgentTeamModel | None:
        return await self.session.scalar(
            select(AgentTeamModel)
            .where(AgentTeamModel.task_id == task_id)
            .order_by(AgentTeamModel.created_at.desc())
            .limit(1)
        )

    async def list_page(
        self,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[AgentTeamModel]:
        filters = []
        if project_id is not None:
            filters.append(AgentTeamModel.project_id == project_id)
        if task_id is not None:
            filters.append(AgentTeamModel.task_id == task_id)
        if status is not None:
            filters.append(AgentTeamModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    def _order_columns(self):
        return (AgentTeamModel.created_at, AgentTeamModel.team_id)


class AgentTeamMemberRepository(BaseRepository[AgentTeamMemberModel]):
    model = AgentTeamMemberModel

    async def list_for_team(self, team_id: str) -> list[AgentTeamMemberModel]:
        rows = await self.session.scalars(
            select(AgentTeamMemberModel)
            .where(AgentTeamMemberModel.team_id == team_id)
            .order_by(AgentTeamMemberModel.joined_at)
        )
        return list(rows)


class AgentAssignmentRepository(BaseRepository[AgentAssignmentModel]):
    model = AgentAssignmentModel

    async def list_for_team(self, team_id: str) -> list[AgentAssignmentModel]:
        rows = await self.session.scalars(
            select(AgentAssignmentModel)
            .where(AgentAssignmentModel.team_id == team_id)
            .order_by(AgentAssignmentModel.priority.desc(), AgentAssignmentModel.assigned_at)
        )
        return list(rows)

    async def list_for_task(self, task_id: str) -> list[AgentAssignmentModel]:
        rows = await self.session.scalars(
            select(AgentAssignmentModel)
            .where(AgentAssignmentModel.task_id == task_id)
            .order_by(AgentAssignmentModel.assigned_at)
        )
        return list(rows)

    async def count_unfinished(self, team_id: str, terminal_statuses: frozenset[str]) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(AgentAssignmentModel)
                .where(
                    AgentAssignmentModel.team_id == team_id,
                    AgentAssignmentModel.status.notin_(terminal_statuses),
                )
            )
            or 0
        )


class AgentAssignmentDependencyRepository(BaseRepository[AgentAssignmentDependencyModel]):
    model = AgentAssignmentDependencyModel

    async def list_for_assignment(self, assignment_id: str) -> list[AgentAssignmentDependencyModel]:
        rows = await self.session.scalars(
            select(AgentAssignmentDependencyModel)
            .where(AgentAssignmentDependencyModel.assignment_id == assignment_id)
            .order_by(AgentAssignmentDependencyModel.created_at)
        )
        return list(rows)

    async def get_pair(
        self, assignment_id: str, depends_on_assignment_id: str
    ) -> AgentAssignmentDependencyModel | None:
        return await self.session.scalar(
            select(AgentAssignmentDependencyModel).where(
                AgentAssignmentDependencyModel.assignment_id == assignment_id,
                AgentAssignmentDependencyModel.depends_on_assignment_id == depends_on_assignment_id,
            )
        )


class AgentHandoffRepository(BaseRepository[AgentHandoffModel]):
    model = AgentHandoffModel

    async def list_for_source(self, assignment_id: str) -> list[AgentHandoffModel]:
        rows = await self.session.scalars(
            select(AgentHandoffModel)
            .where(AgentHandoffModel.source_assignment_id == assignment_id)
            .order_by(AgentHandoffModel.created_at)
        )
        return list(rows)


class AgentCollaborationRepository(BaseRepository[AgentCollaborationModel]):
    model = AgentCollaborationModel

    async def list_for_team(self, team_id: str) -> list[AgentCollaborationModel]:
        rows = await self.session.scalars(
            select(AgentCollaborationModel)
            .where(AgentCollaborationModel.team_id == team_id)
            .order_by(AgentCollaborationModel.created_at)
        )
        return list(rows)


class AgentMessageRepository(BaseRepository[AgentMessageModel]):
    model = AgentMessageModel

    async def next_sequence(self, team_id: str) -> int:
        current = await self.session.scalar(
            select(func.max(AgentMessageModel.sequence_number)).where(
                AgentMessageModel.team_id == team_id
            )
        )
        return int(current or 0) + 1

    async def list_for_team(self, team_id: str, *, limit: int = 200) -> list[AgentMessageModel]:
        rows = await self.session.scalars(
            select(AgentMessageModel)
            .where(AgentMessageModel.team_id == team_id)
            .order_by(AgentMessageModel.sequence_number)
            .limit(limit)
        )
        return list(rows)


class AgentConflictRepository(BaseRepository[AgentConflictModel]):
    model = AgentConflictModel


class AgentIntegrationRepository(BaseRepository[AgentIntegrationModel]):
    model = AgentIntegrationModel


class AgentReviewRepository(BaseRepository[AgentReviewModel]):
    model = AgentReviewModel


class AgentTeamBudgetRepository(BaseRepository[AgentTeamBudgetModel]):
    model = AgentTeamBudgetModel

    async def get_by_team(self, team_id: str) -> AgentTeamBudgetModel | None:
        return await self.session.scalar(
            select(AgentTeamBudgetModel).where(AgentTeamBudgetModel.team_id == team_id)
        )


class AgentSharedContextRepository(BaseRepository[AgentSharedContextModel]):
    model = AgentSharedContextModel

    async def latest(self, team_id: str) -> AgentSharedContextModel | None:
        return await self.session.scalar(
            select(AgentSharedContextModel)
            .where(AgentSharedContextModel.team_id == team_id)
            .order_by(AgentSharedContextModel.context_version.desc())
            .limit(1)
        )


__all__ = [
    "AgentAssignmentDependencyRepository",
    "AgentAssignmentRepository",
    "AgentCollaborationRepository",
    "AgentConflictRepository",
    "AgentHandoffRepository",
    "AgentIntegrationRepository",
    "AgentMessageRepository",
    "AgentReviewRepository",
    "AgentSharedContextRepository",
    "AgentTeamBudgetRepository",
    "AgentTeamMemberRepository",
    "AgentTeamRepository",
    "CapabilityRepository",
]
