"""Agent Runtime 仓储（E6-T01）。

Repository 只承载查询与写入，不提交事务；顺序号生成在同一事务内完成，
由唯一约束兜底并发冲突。
"""

from __future__ import annotations

from sqlalchemy import func, select, update

from infrastructure.database.repository import BaseRepository, Page
from modules.agent_runtime.models import (
    INSTANCE_TERMINAL_STATUSES,
    AgentCheckpointModel,
    AgentConfigSnapshotModel,
    AgentDefinitionModel,
    AgentDefinitionVersionModel,
    AgentEventModel,
    AgentExecutionModel,
    AgentInstanceModel,
    AgentPlanModel,
    AgentStepModel,
)


class AgentDefinitionRepository(BaseRepository[AgentDefinitionModel]):
    model = AgentDefinitionModel

    async def get_by_name(self, name: str) -> AgentDefinitionModel | None:
        return await self.session.scalar(
            select(AgentDefinitionModel).where(AgentDefinitionModel.name == name)
        )

    async def list_page(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> Page[AgentDefinitionModel]:
        filters = []
        if status is not None:
            filters.append(AgentDefinitionModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    def _order_columns(self):
        return (AgentDefinitionModel.created_at, AgentDefinitionModel.definition_id)


class AgentDefinitionVersionRepository(BaseRepository[AgentDefinitionVersionModel]):
    model = AgentDefinitionVersionModel

    async def get_by_version(
        self, definition_id: str, version: str
    ) -> AgentDefinitionVersionModel | None:
        return await self.session.scalar(
            select(AgentDefinitionVersionModel).where(
                AgentDefinitionVersionModel.agent_definition_id == definition_id,
                AgentDefinitionVersionModel.version == version,
            )
        )

    async def list_for_definition(self, definition_id: str) -> list[AgentDefinitionVersionModel]:
        rows = await self.session.scalars(
            select(AgentDefinitionVersionModel)
            .where(AgentDefinitionVersionModel.agent_definition_id == definition_id)
            .order_by(AgentDefinitionVersionModel.published_at)
        )
        return list(rows)

    async def count_for_definition(self, definition_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(AgentDefinitionVersionModel)
                .where(AgentDefinitionVersionModel.agent_definition_id == definition_id)
            )
            or 0
        )


class AgentConfigSnapshotRepository(BaseRepository[AgentConfigSnapshotModel]):
    model = AgentConfigSnapshotModel


class AgentInstanceRepository(BaseRepository[AgentInstanceModel]):
    model = AgentInstanceModel

    async def list_page(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[AgentInstanceModel]:
        filters = []
        if project_id is not None:
            filters.append(AgentInstanceModel.project_id == project_id)
        if status is not None:
            filters.append(AgentInstanceModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_non_terminal(self, *, limit: int = 200) -> list[AgentInstanceModel]:
        rows = await self.session.scalars(
            select(AgentInstanceModel)
            .where(AgentInstanceModel.status.notin_(INSTANCE_TERMINAL_STATUSES))
            .order_by(AgentInstanceModel.created_at)
            .limit(limit)
        )
        return list(rows)

    async def get_active_for_attempt(self, attempt_id: str) -> AgentInstanceModel | None:
        return await self.session.scalar(
            select(AgentInstanceModel)
            .where(
                AgentInstanceModel.attempt_id == attempt_id,
                AgentInstanceModel.status.notin_(INSTANCE_TERMINAL_STATUSES),
            )
            .order_by(AgentInstanceModel.created_at.desc())
            .limit(1)
        )

    async def compare_and_set_status(
        self,
        instance_id: str,
        *,
        expected_version: int,
        from_status: str,
        to_status: str,
        now,
        started_at=None,
        completed_at=None,
        termination_reason: str | None = None,
    ) -> int:
        """条件更新状态，避免并发 worker 同时迁移同一实例。"""

        values: dict[str, object] = {
            "status": to_status,
            "version": expected_version + 1,
            "updated_at": now,
        }
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if termination_reason is not None:
            values["termination_reason"] = termination_reason
        result = await self.session.execute(
            update(AgentInstanceModel)
            .where(
                AgentInstanceModel.instance_id == instance_id,
                AgentInstanceModel.version == expected_version,
                AgentInstanceModel.status == from_status,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)

    def _order_columns(self):
        return (AgentInstanceModel.created_at, AgentInstanceModel.instance_id)


class AgentExecutionRepository(BaseRepository[AgentExecutionModel]):
    model = AgentExecutionModel

    async def next_number(self, instance_id: str) -> int:
        current = await self.session.scalar(
            select(func.max(AgentExecutionModel.execution_number)).where(
                AgentExecutionModel.agent_instance_id == instance_id
            )
        )
        return int(current or 0) + 1

    async def list_for_instance(self, instance_id: str) -> list[AgentExecutionModel]:
        rows = await self.session.scalars(
            select(AgentExecutionModel)
            .where(AgentExecutionModel.agent_instance_id == instance_id)
            .order_by(AgentExecutionModel.execution_number)
        )
        return list(rows)

    async def latest(self, instance_id: str) -> AgentExecutionModel | None:
        return await self.session.scalar(
            select(AgentExecutionModel)
            .where(AgentExecutionModel.agent_instance_id == instance_id)
            .order_by(AgentExecutionModel.execution_number.desc())
            .limit(1)
        )


class AgentPlanRepository(BaseRepository[AgentPlanModel]):
    model = AgentPlanModel

    async def next_version(self, execution_id: str) -> int:
        current = await self.session.scalar(
            select(func.max(AgentPlanModel.plan_version)).where(
                AgentPlanModel.execution_id == execution_id
            )
        )
        return int(current or 0) + 1

    async def latest_for_execution(self, execution_id: str) -> AgentPlanModel | None:
        return await self.session.scalar(
            select(AgentPlanModel)
            .where(AgentPlanModel.execution_id == execution_id)
            .order_by(AgentPlanModel.plan_version.desc())
            .limit(1)
        )


class AgentStepRepository(BaseRepository[AgentStepModel]):
    model = AgentStepModel

    async def next_number(self, plan_id: str) -> int:
        current = await self.session.scalar(
            select(func.max(AgentStepModel.step_number)).where(
                AgentStepModel.plan_id == plan_id
            )
        )
        return int(current or 0) + 1

    async def list_by_plan(self, plan_id: str) -> list[AgentStepModel]:
        rows = await self.session.scalars(
            select(AgentStepModel)
            .where(AgentStepModel.plan_id == plan_id)
            .order_by(AgentStepModel.step_number)
        )
        return list(rows)

    async def list_by_execution(self, execution_id: str) -> list[AgentStepModel]:
        rows = await self.session.scalars(
            select(AgentStepModel)
            .where(AgentStepModel.execution_id == execution_id)
            .order_by(AgentStepModel.step_number)
        )
        return list(rows)


class AgentCheckpointRepository(BaseRepository[AgentCheckpointModel]):
    model = AgentCheckpointModel

    async def latest(self, instance_id: str) -> AgentCheckpointModel | None:
        return await self.session.scalar(
            select(AgentCheckpointModel)
            .where(AgentCheckpointModel.agent_instance_id == instance_id)
            .order_by(AgentCheckpointModel.checkpoint_version.desc())
            .limit(1)
        )

    async def next_version(self, instance_id: str) -> int:
        current = await self.session.scalar(
            select(func.max(AgentCheckpointModel.checkpoint_version)).where(
                AgentCheckpointModel.agent_instance_id == instance_id
            )
        )
        return int(current or 0) + 1


class AgentEventRepository(BaseRepository[AgentEventModel]):
    model = AgentEventModel

    async def next_sequence(self, instance_id: str) -> int:
        current = await self.session.scalar(
            select(func.max(AgentEventModel.sequence_number)).where(
                AgentEventModel.agent_instance_id == instance_id
            )
        )
        return int(current or 0) + 1

    async def list_after(
        self, instance_id: str, *, after_sequence: int = 0, limit: int = 200
    ) -> list[AgentEventModel]:
        rows = await self.session.scalars(
            select(AgentEventModel)
            .where(
                AgentEventModel.agent_instance_id == instance_id,
                AgentEventModel.sequence_number > after_sequence,
            )
            .order_by(AgentEventModel.sequence_number)
            .limit(limit)
        )
        return list(rows)

    async def list_by_execution(
        self, execution_id: str, *, after_sequence: int = 0, limit: int = 200
    ) -> list[AgentEventModel]:
        rows = await self.session.scalars(
            select(AgentEventModel)
            .where(
                AgentEventModel.execution_id == execution_id,
                AgentEventModel.sequence_number > after_sequence,
            )
            .order_by(AgentEventModel.sequence_number)
            .limit(limit)
        )
        return list(rows)
