"""Requirement Tracking 仓储（E4-T18）。"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository
from modules.requirement.models import (
    AcceptanceCriterionModel,
    RequirementModel,
    RequirementTraceModel,
)


class RequirementRepository(BaseRepository[RequirementModel]):
    model = RequirementModel

    async def list_by_project(
        self, project_id: str, *, status: str | None = None
    ) -> list[RequirementModel]:
        statement = select(RequirementModel).where(RequirementModel.project_id == project_id)
        if status:
            statement = statement.where(RequirementModel.status == status)
        rows = await self.session.scalars(statement.order_by(RequirementModel.created_at))
        return list(rows.all())

    async def get_by_key(self, project_id: str, requirement_key: str) -> RequirementModel | None:
        return await self.session.scalar(
            select(RequirementModel).where(
                RequirementModel.project_id == project_id,
                RequirementModel.requirement_key == requirement_key,
            )
        )


class AcceptanceCriterionRepository(BaseRepository[AcceptanceCriterionModel]):
    model = AcceptanceCriterionModel

    async def list_by_requirement(self, requirement_id: str) -> list[AcceptanceCriterionModel]:
        rows = await self.session.scalars(
            select(AcceptanceCriterionModel).where(
                AcceptanceCriterionModel.requirement_id == requirement_id
            )
        )
        return list(rows.all())

    async def get_by_key(
        self, requirement_id: str, criterion_key: str
    ) -> AcceptanceCriterionModel | None:
        return await self.session.scalar(
            select(AcceptanceCriterionModel).where(
                AcceptanceCriterionModel.requirement_id == requirement_id,
                AcceptanceCriterionModel.criterion_key == criterion_key,
            )
        )


class RequirementTraceRepository(BaseRepository[RequirementTraceModel]):
    model = RequirementTraceModel

    async def list_by_requirement(self, requirement_id: str) -> list[RequirementTraceModel]:
        rows = await self.session.scalars(
            select(RequirementTraceModel).where(
                RequirementTraceModel.requirement_id == requirement_id
            )
        )
        return list(rows.all())
