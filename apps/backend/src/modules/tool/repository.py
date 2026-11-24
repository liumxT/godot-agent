"""工具域仓储（E5-T17 / T22–T26）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from infrastructure.database.repository import BaseRepository, Page
from modules.tool.models import (
    LOCK_STATUS_ACTIVE,
    LOCK_STATUS_EXPIRED,
    ResourceLockModel,
    ToolAuditRecordModel,
    ToolDefinitionModel,
    ToolExecutionModel,
    ToolVerificationRecordModel,
)


class ToolDefinitionRepository(BaseRepository[ToolDefinitionModel]):
    model = ToolDefinitionModel

    async def latest_version(self, name: str) -> int:
        value = await self.session.scalar(
            select(func.max(ToolDefinitionModel.version)).where(ToolDefinitionModel.name == name)
        )
        return int(value or 0)

    async def get_by_name_version(self, name: str, version: int) -> ToolDefinitionModel | None:
        return await self.session.scalar(
            select(ToolDefinitionModel).where(
                ToolDefinitionModel.name == name,
                ToolDefinitionModel.version == version,
            )
        )

    async def list_definitions(
        self,
        *,
        category: str | None,
        enabled: bool | None,
        limit: int,
        offset: int,
    ) -> Page[ToolDefinitionModel]:
        filters = []
        if category is not None:
            filters.append(ToolDefinitionModel.category == category)
        if enabled is not None:
            filters.append(ToolDefinitionModel.enabled == enabled)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    def _order_columns(self):
        return (ToolDefinitionModel.name.asc(), ToolDefinitionModel.version.desc())


class ToolExecutionRepository(BaseRepository[ToolExecutionModel]):
    model = ToolExecutionModel

    async def latest_by_idempotency_key(
        self, project_id: str, idempotency_key: str
    ) -> ToolExecutionModel | None:
        return await self.session.scalar(
            select(ToolExecutionModel)
            .where(
                ToolExecutionModel.project_id == project_id,
                ToolExecutionModel.idempotency_key == idempotency_key,
            )
            .order_by(ToolExecutionModel.created_at.desc(), ToolExecutionModel.execution_id.desc())
            .limit(1)
        )

    async def list_project_executions(
        self,
        *,
        project_id: str,
        status: str | None,
        limit: int,
        offset: int,
    ) -> Page[ToolExecutionModel]:
        filters = [ToolExecutionModel.project_id == project_id]
        if status is not None:
            filters.append(ToolExecutionModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_by_statuses(
        self, statuses: tuple[str, ...], *, limit: int = 100
    ) -> list[ToolExecutionModel]:
        return list(
            (
                await self.session.scalars(
                    select(ToolExecutionModel)
                    .where(ToolExecutionModel.status.in_(statuses))
                    .order_by(ToolExecutionModel.created_at.asc())
                    .limit(limit)
                )
            ).all()
        )

    def _order_columns(self):
        return (ToolExecutionModel.created_at.desc(), ToolExecutionModel.execution_id.desc())


class ResourceLockRepository(BaseRepository[ResourceLockModel]):
    model = ResourceLockModel

    async def list_active(
        self, project_id: str, resource_key: str, now: datetime
    ) -> list[ResourceLockModel]:
        return list(
            (
                await self.session.scalars(
                    select(ResourceLockModel).where(
                        ResourceLockModel.project_id == project_id,
                        ResourceLockModel.resource_key == resource_key,
                        ResourceLockModel.status == LOCK_STATUS_ACTIVE,
                        ResourceLockModel.expires_at > now,
                    )
                )
            ).all()
        )

    async def max_fencing_token(self, project_id: str, resource_key: str) -> int:
        value = await self.session.scalar(
            select(func.max(ResourceLockModel.fencing_token)).where(
                ResourceLockModel.project_id == project_id,
                ResourceLockModel.resource_key == resource_key,
            )
        )
        return int(value or 0)

    async def expire_due(self, now: datetime) -> int:
        rows = list(
            (
                await self.session.scalars(
                    select(ResourceLockModel).where(
                        ResourceLockModel.status == LOCK_STATUS_ACTIVE,
                        ResourceLockModel.expires_at <= now,
                    )
                )
            ).all()
        )
        for row in rows:
            row.status = LOCK_STATUS_EXPIRED
        return len(rows)

    def _order_columns(self):
        return (ResourceLockModel.acquired_at.asc(),)


class ToolAuditRepository(BaseRepository[ToolAuditRecordModel]):
    model = ToolAuditRecordModel

    async def list_project_records(
        self,
        *,
        project_id: str,
        tool_id: str | None,
        limit: int,
        offset: int,
    ) -> Page[ToolAuditRecordModel]:
        filters = [ToolAuditRecordModel.project_id == project_id]
        if tool_id is not None:
            filters.append(ToolAuditRecordModel.tool_id == tool_id)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_for_execution(self, execution_id: str) -> list[ToolAuditRecordModel]:
        return list(
            (
                await self.session.scalars(
                    select(ToolAuditRecordModel)
                    .where(ToolAuditRecordModel.execution_id == execution_id)
                    .order_by(ToolAuditRecordModel.created_at.asc())
                )
            ).all()
        )

    def _order_columns(self):
        return (ToolAuditRecordModel.created_at.desc(),)


class ToolVerificationRepository(BaseRepository[ToolVerificationRecordModel]):
    model = ToolVerificationRecordModel

    async def latest(self, execution_id: str) -> ToolVerificationRecordModel | None:
        return await self.session.scalar(
            select(ToolVerificationRecordModel)
            .where(ToolVerificationRecordModel.execution_id == execution_id)
            .order_by(ToolVerificationRecordModel.verified_at.desc())
            .limit(1)
        )

    async def list_for_execution(self, execution_id: str) -> list[ToolVerificationRecordModel]:
        return list(
            (
                await self.session.scalars(
                    select(ToolVerificationRecordModel)
                    .where(ToolVerificationRecordModel.execution_id == execution_id)
                    .order_by(ToolVerificationRecordModel.verified_at.asc())
                )
            ).all()
        )

    def _order_columns(self):
        return (ToolVerificationRecordModel.verified_at.desc(),)
