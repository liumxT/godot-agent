"""Workflow 域仓储（E4-T12…T17 / T21）。"""

from __future__ import annotations

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository, Page
from modules.workflow.models import (
    WorkflowDefinitionModel,
    WorkflowDefinitionVersionModel,
    WorkflowInstanceModel,
    WorkflowNodeDefinitionModel,
    WorkflowNodeInstanceModel,
    WorkflowPhaseModel,
    WorkflowPhaseReviewModel,
)


class WorkflowDefinitionRepository(BaseRepository[WorkflowDefinitionModel]):
    model = WorkflowDefinitionModel

    async def list_page(self, *, limit: int, offset: int) -> Page[WorkflowDefinitionModel]:
        return await self.paginate(limit=limit, offset=offset)


class WorkflowDefinitionVersionRepository(BaseRepository[WorkflowDefinitionVersionModel]):
    model = WorkflowDefinitionVersionModel

    async def latest(self, definition_id: str) -> WorkflowDefinitionVersionModel | None:
        return await self.session.scalar(
            select(WorkflowDefinitionVersionModel)
            .where(WorkflowDefinitionVersionModel.definition_id == definition_id)
            .order_by(WorkflowDefinitionVersionModel.version.desc())
            .limit(1)
        )

    async def get_version(
        self, definition_id: str, version: int
    ) -> WorkflowDefinitionVersionModel | None:
        return await self.session.scalar(
            select(WorkflowDefinitionVersionModel).where(
                WorkflowDefinitionVersionModel.definition_id == definition_id,
                WorkflowDefinitionVersionModel.version == version,
            )
        )

    async def next_version(self, definition_id: str) -> int:
        value = await self.session.scalar(
            select(func.max(WorkflowDefinitionVersionModel.version)).where(
                WorkflowDefinitionVersionModel.definition_id == definition_id
            )
        )
        return int(value or 0) + 1


class WorkflowNodeDefinitionRepository(BaseRepository[WorkflowNodeDefinitionModel]):
    model = WorkflowNodeDefinitionModel

    async def list_by_version(self, version_id: str) -> list[WorkflowNodeDefinitionModel]:
        rows = await self.session.scalars(
            select(WorkflowNodeDefinitionModel).where(
                WorkflowNodeDefinitionModel.version_id == version_id
            )
        )
        return list(rows.all())


class WorkflowInstanceRepository(BaseRepository[WorkflowInstanceModel]):
    model = WorkflowInstanceModel

    async def list_by_task(self, task_id: str) -> list[WorkflowInstanceModel]:
        rows = await self.session.scalars(
            select(WorkflowInstanceModel)
            .where(WorkflowInstanceModel.task_id == task_id)
            .order_by(WorkflowInstanceModel.created_at)
        )
        return list(rows.all())

    async def list_page_by_project(
        self, project_id: str, *, limit: int, offset: int
    ) -> Page[WorkflowInstanceModel]:
        return await self.paginate(
            limit=limit,
            offset=offset,
            filters=[WorkflowInstanceModel.project_id == project_id],
        )


class WorkflowNodeInstanceRepository(BaseRepository[WorkflowNodeInstanceModel]):
    model = WorkflowNodeInstanceModel

    async def list_by_instance(self, instance_id: str) -> list[WorkflowNodeInstanceModel]:
        rows = await self.session.scalars(
            select(WorkflowNodeInstanceModel).where(
                WorkflowNodeInstanceModel.workflow_instance_id == instance_id
            )
        )
        return list(rows.all())

    async def get_by_key(self, instance_id: str, node_key: str) -> WorkflowNodeInstanceModel | None:
        return await self.session.scalar(
            select(WorkflowNodeInstanceModel).where(
                WorkflowNodeInstanceModel.workflow_instance_id == instance_id,
                WorkflowNodeInstanceModel.node_key == node_key,
            )
        )


class WorkflowPhaseRepository(BaseRepository[WorkflowPhaseModel]):
    model = WorkflowPhaseModel

    async def list_by_instance(self, instance_id: str) -> list[WorkflowPhaseModel]:
        rows = await self.session.scalars(
            select(WorkflowPhaseModel)
            .where(WorkflowPhaseModel.workflow_instance_id == instance_id)
            .order_by(WorkflowPhaseModel.sequence)
        )
        return list(rows.all())

    async def get_by_key(self, instance_id: str, phase_key: str) -> WorkflowPhaseModel | None:
        return await self.session.scalar(
            select(WorkflowPhaseModel).where(
                WorkflowPhaseModel.workflow_instance_id == instance_id,
                WorkflowPhaseModel.phase_key == phase_key,
            )
        )


class WorkflowPhaseReviewRepository(BaseRepository[WorkflowPhaseReviewModel]):
    model = WorkflowPhaseReviewModel

    async def get_by_phase(self, phase_id: str) -> WorkflowPhaseReviewModel | None:
        return await self.session.scalar(
            select(WorkflowPhaseReviewModel).where(WorkflowPhaseReviewModel.phase_id == phase_id)
        )

    async def list_by_instance(self, instance_id: str) -> list[WorkflowPhaseReviewModel]:
        rows = await self.session.scalars(
            select(WorkflowPhaseReviewModel).where(
                WorkflowPhaseReviewModel.workflow_instance_id == instance_id
            )
        )
        return list(rows.all())
