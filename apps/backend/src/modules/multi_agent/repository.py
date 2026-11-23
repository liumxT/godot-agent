"""Multi-Agent 仓储（E7-T01）。

Repository 只承载查询与写入，不提交事务；跨模块状态通过 ID 引用，
禁止在这里访问其他模块的 Repository。
"""

from __future__ import annotations

from sqlalchemy import func, select, update

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

    async def transition_status(
        self,
        team_id: str,
        *,
        from_statuses: frozenset[str],
        to_status: str,
        expected_version: int,
        now,
        completed_at=None,
    ) -> bool:
        values = {"status": to_status, "version": AgentTeamModel.version + 1, "updated_at": now}
        if completed_at is not None:
            values["completed_at"] = completed_at
        result = await self.session.execute(
            update(AgentTeamModel)
            .where(
                AgentTeamModel.team_id == team_id,
                AgentTeamModel.version == expected_version,
                AgentTeamModel.status.in_(from_statuses),
            )
            .values(**values)
        )
        return result.rowcount == 1

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

    async def get_by_assignment(self, assignment_id: str) -> AgentTeamMemberModel | None:
        return await self.session.scalar(
            select(AgentTeamMemberModel).where(
                AgentTeamMemberModel.assignment_id == assignment_id
            )
        )


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

    async def transition_status(
        self,
        assignment_id: str,
        *,
        from_statuses: frozenset[str],
        to_status: str,
        expected_version: int,
        now,
        started_at=None,
        completed_at=None,
    ) -> bool:
        values = {
            "status": to_status,
            "version": AgentAssignmentModel.version + 1,
        }
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        result = await self.session.execute(
            update(AgentAssignmentModel)
            .where(
                AgentAssignmentModel.assignment_id == assignment_id,
                AgentAssignmentModel.version == expected_version,
                AgentAssignmentModel.status.in_(from_statuses),
            )
            .values(**values)
        )
        return result.rowcount == 1

    async def claim(
        self,
        assignment_id: str,
        *,
        agent_instance_id: str,
        allowed_statuses: frozenset[str],
        to_status: str,
        expected_version: int,
    ) -> bool:
        result = await self.session.execute(
            update(AgentAssignmentModel)
            .where(
                AgentAssignmentModel.assignment_id == assignment_id,
                AgentAssignmentModel.version == expected_version,
                AgentAssignmentModel.status.in_(allowed_statuses),
                AgentAssignmentModel.agent_instance_id.is_(None),
            )
            .values(
                status=to_status,
                agent_instance_id=agent_instance_id,
                version=AgentAssignmentModel.version + 1,
            )
        )
        return result.rowcount == 1


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

    async def list_for_target(
        self, target_assignment_id: str, *, unread_only: bool = False, limit: int = 200
    ) -> list[AgentMessageModel]:
        statement = select(AgentMessageModel).where(
            AgentMessageModel.target_assignment_id == target_assignment_id
        )
        if unread_only:
            statement = statement.where(AgentMessageModel.consumed_at.is_(None))
        rows = await self.session.scalars(
            statement.order_by(AgentMessageModel.sequence_number).limit(limit)
        )
        return list(rows)


class AgentConflictRepository(BaseRepository[AgentConflictModel]):
    model = AgentConflictModel


class AgentIntegrationRepository(BaseRepository[AgentIntegrationModel]):
    model = AgentIntegrationModel

    async def list_for_team(self, team_id: str) -> list[AgentIntegrationModel]:
        rows = await self.session.scalars(
            select(AgentIntegrationModel)
            .where(AgentIntegrationModel.team_id == team_id)
            .order_by(AgentIntegrationModel.created_at)
        )
        return list(rows)


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

    async def list_for_team(self, team_id: str) -> list[AgentSharedContextModel]:
        rows = await self.session.scalars(
            select(AgentSharedContextModel)
            .where(AgentSharedContextModel.team_id == team_id)
            .order_by(AgentSharedContextModel.context_version)
        )
        return list(rows)


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
