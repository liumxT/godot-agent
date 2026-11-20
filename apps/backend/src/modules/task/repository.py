"""Task 域仓储（E4-T06…T11）。"""

from __future__ import annotations

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository, Page
from modules.task.models import (
    DEPENDENCY_ACTIVE,
    TaskAttemptModel,
    TaskCheckpointModel,
    TaskDependencyModel,
    TaskEventModel,
    TaskModel,
)


class TaskRepository(BaseRepository[TaskModel]):
    model = TaskModel

    async def list_page(
        self,
        project_id: str,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> Page[TaskModel]:
        filters = [TaskModel.project_id == project_id]
        if status:
            filters.append(TaskModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def count_by_status(self, project_id: str, status: str) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(TaskModel)
            .where(TaskModel.project_id == project_id, TaskModel.status == status)
        )
        return int(value or 0)

    async def list_unfinished(self) -> list[TaskModel]:
        rows = await self.session.scalars(
            select(TaskModel)
            .where(
                TaskModel.status.in_(
                    [
                        "QUEUED",
                        "RUNNING",
                        "PAUSING",
                        "PAUSED",
                        "RESUMING",
                        "WAITING_APPROVAL",
                        "WAITING_USER",
                        "BLOCKED",
                        "REVIEW_PENDING",
                    ]
                )
            )
            .order_by(TaskModel.created_at)
        )
        return list(rows.all())


class TaskAttemptRepository(BaseRepository[TaskAttemptModel]):
    model = TaskAttemptModel

    async def list_by_task(self, task_id: str) -> list[TaskAttemptModel]:
        rows = await self.session.scalars(
            select(TaskAttemptModel)
            .where(TaskAttemptModel.task_id == task_id)
            .order_by(TaskAttemptModel.attempt_number)
        )
        return list(rows.all())

    async def latest(self, task_id: str) -> TaskAttemptModel | None:
        return await self.session.scalar(
            select(TaskAttemptModel)
            .where(TaskAttemptModel.task_id == task_id)
            .order_by(TaskAttemptModel.attempt_number.desc())
            .limit(1)
        )

    async def next_number(self, task_id: str) -> int:
        value = await self.session.scalar(
            select(func.max(TaskAttemptModel.attempt_number)).where(
                TaskAttemptModel.task_id == task_id
            )
        )
        return int(value or 0) + 1


class TaskDependencyRepository(BaseRepository[TaskDependencyModel]):
    model = TaskDependencyModel

    async def list_active(self, project_id: str | None = None) -> list[TaskDependencyModel]:
        statement = select(TaskDependencyModel).where(
            TaskDependencyModel.status == DEPENDENCY_ACTIVE
        )
        if project_id is not None:
            statement = statement.join(
                TaskModel, TaskModel.task_id == TaskDependencyModel.target_task_id
            ).where(TaskModel.project_id == project_id)
        rows = await self.session.scalars(statement)
        return list(rows.all())

    async def list_for_target(self, target_task_id: str) -> list[TaskDependencyModel]:
        rows = await self.session.scalars(
            select(TaskDependencyModel).where(
                TaskDependencyModel.target_task_id == target_task_id,
                TaskDependencyModel.status == DEPENDENCY_ACTIVE,
            )
        )
        return list(rows.all())

    async def get_pair(
        self, source_task_id: str, target_task_id: str
    ) -> TaskDependencyModel | None:
        return await self.session.scalar(
            select(TaskDependencyModel).where(
                TaskDependencyModel.source_task_id == source_task_id,
                TaskDependencyModel.target_task_id == target_task_id,
            )
        )


class TaskCheckpointRepository(BaseRepository[TaskCheckpointModel]):
    model = TaskCheckpointModel

    async def next_sequence(self, task_id: str) -> int:
        value = await self.session.scalar(
            select(func.max(TaskCheckpointModel.sequence)).where(
                TaskCheckpointModel.task_id == task_id
            )
        )
        return int(value or 0) + 1

    async def list_by_task(self, task_id: str, *, limit: int = 50) -> list[TaskCheckpointModel]:
        rows = await self.session.scalars(
            select(TaskCheckpointModel)
            .where(TaskCheckpointModel.task_id == task_id)
            .order_by(TaskCheckpointModel.sequence.desc())
            .limit(limit)
        )
        return list(rows.all())

    async def latest(self, task_id: str) -> TaskCheckpointModel | None:
        return await self.session.scalar(
            select(TaskCheckpointModel)
            .where(TaskCheckpointModel.task_id == task_id)
            .order_by(TaskCheckpointModel.sequence.desc())
            .limit(1)
        )


class TaskEventRepository(BaseRepository[TaskEventModel]):
    model = TaskEventModel

    async def next_sequence(self, task_id: str) -> int:
        value = await self.session.scalar(
            select(func.max(TaskEventModel.sequence)).where(TaskEventModel.task_id == task_id)
        )
        return int(value or 0) + 1

    async def list_by_task(
        self,
        task_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[TaskEventModel]:
        statement = select(TaskEventModel).where(TaskEventModel.task_id == task_id)
        total = (
            await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        ) or 0
        rows = await self.session.scalars(
            statement.order_by(TaskEventModel.sequence).limit(limit).offset(offset)
        )
        return Page(items=list(rows.all()), total=int(total), limit=limit, offset=offset)
