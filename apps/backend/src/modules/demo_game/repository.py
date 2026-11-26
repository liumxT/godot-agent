"""E11 Platformer Demo 仓储（T01 / T02）。"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository
from modules.demo_game.models import (
    DemoAcceptanceReportModel,
    DemoCriterionModel,
    DemoFeatureModel,
    DemoGameSpecModel,
    DemoLevelModel,
    DemoMechanicModel,
    DemoRequirementModel,
    DemoTestScenarioModel,
)


class DemoSpecRepository(BaseRepository[DemoGameSpecModel]):
    model = DemoGameSpecModel

    async def get_by_project(self, project_id: str) -> DemoGameSpecModel | None:
        return await self.session.scalar(
            select(DemoGameSpecModel).where(DemoGameSpecModel.project_id == project_id)
        )


class DemoRequirementRepository(BaseRepository[DemoRequirementModel]):
    model = DemoRequirementModel

    async def list_by_spec(
        self, spec_id: str, *, priority: str | None = None, system: str | None = None
    ) -> list[DemoRequirementModel]:
        statement = select(DemoRequirementModel).where(DemoRequirementModel.spec_id == spec_id)
        if priority:
            statement = statement.where(DemoRequirementModel.priority == priority)
        if system:
            statement = statement.where(DemoRequirementModel.system == system)
        rows = await self.session.scalars(statement.order_by(DemoRequirementModel.requirement_key))
        return list(rows.all())

    async def get_by_key(self, spec_id: str, requirement_key: str) -> DemoRequirementModel | None:
        return await self.session.scalar(
            select(DemoRequirementModel).where(
                DemoRequirementModel.spec_id == spec_id,
                DemoRequirementModel.requirement_key == requirement_key,
            )
        )


class DemoMechanicRepository(BaseRepository[DemoMechanicModel]):
    model = DemoMechanicModel

    async def list_by_spec(self, spec_id: str) -> list[DemoMechanicModel]:
        rows = await self.session.scalars(
            select(DemoMechanicModel)
            .where(DemoMechanicModel.spec_id == spec_id)
            .order_by(DemoMechanicModel.mechanic_key)
        )
        return list(rows.all())


class DemoLevelRepository(BaseRepository[DemoLevelModel]):
    model = DemoLevelModel

    async def list_by_spec(self, spec_id: str) -> list[DemoLevelModel]:
        rows = await self.session.scalars(
            select(DemoLevelModel)
            .where(DemoLevelModel.spec_id == spec_id)
            .order_by(DemoLevelModel.level_key)
        )
        return list(rows.all())


class DemoFeatureRepository(BaseRepository[DemoFeatureModel]):
    model = DemoFeatureModel

    async def list_by_spec(self, spec_id: str) -> list[DemoFeatureModel]:
        rows = await self.session.scalars(
            select(DemoFeatureModel)
            .where(DemoFeatureModel.spec_id == spec_id)
            .order_by(DemoFeatureModel.feature_key)
        )
        return list(rows.all())


class DemoCriterionRepository(BaseRepository[DemoCriterionModel]):
    model = DemoCriterionModel

    async def list_by_requirement(self, requirement_id: str) -> list[DemoCriterionModel]:
        rows = await self.session.scalars(
            select(DemoCriterionModel).where(
                DemoCriterionModel.demo_requirement_id == requirement_id
            )
        )
        return list(rows.all())

    async def list_by_spec(self, spec_id: str) -> list[DemoCriterionModel]:
        statement = (
            select(DemoCriterionModel)
            .join(
                DemoRequirementModel,
                DemoRequirementModel.demo_requirement_id == DemoCriterionModel.demo_requirement_id,
            )
            .where(DemoRequirementModel.spec_id == spec_id)
        )
        rows = await self.session.scalars(statement)
        return list(rows.all())


class DemoScenarioRepository(BaseRepository[DemoTestScenarioModel]):
    model = DemoTestScenarioModel

    async def list_by_spec(self, spec_id: str) -> list[DemoTestScenarioModel]:
        rows = await self.session.scalars(
            select(DemoTestScenarioModel)
            .where(DemoTestScenarioModel.spec_id == spec_id)
            .order_by(DemoTestScenarioModel.scenario_key)
        )
        return list(rows.all())

    async def get_by_key(self, spec_id: str, scenario_key: str) -> DemoTestScenarioModel | None:
        return await self.session.scalar(
            select(DemoTestScenarioModel).where(
                DemoTestScenarioModel.spec_id == spec_id,
                DemoTestScenarioModel.scenario_key == scenario_key,
            )
        )


class DemoAcceptanceReportRepository(BaseRepository[DemoAcceptanceReportModel]):
    model = DemoAcceptanceReportModel

    async def list_by_spec(self, spec_id: str) -> list[DemoAcceptanceReportModel]:
        rows = await self.session.scalars(
            select(DemoAcceptanceReportModel)
            .where(DemoAcceptanceReportModel.spec_id == spec_id)
            .order_by(DemoAcceptanceReportModel.created_at.desc())
        )
        return list(rows.all())
