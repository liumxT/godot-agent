"""Approval 域仓储（E4-T20）。"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository, Page
from modules.approval.models import (
    ApprovalAuditEventModel,
    ApprovalDecisionModel,
    ApprovalModel,
)


class ApprovalRepository(BaseRepository[ApprovalModel]):
    model = ApprovalModel

    async def list_page(
        self,
        *,
        project_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> Page[ApprovalModel]:
        filters = []
        if project_id:
            filters.append(ApprovalModel.project_id == project_id)
        if status:
            filters.append(ApprovalModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_pending(self) -> list[ApprovalModel]:
        rows = await self.session.scalars(
            select(ApprovalModel).where(ApprovalModel.status == "PENDING")
        )
        return list(rows.all())


class ApprovalDecisionRepository(BaseRepository[ApprovalDecisionModel]):
    model = ApprovalDecisionModel

    async def list_by_approval(self, approval_id: str) -> list[ApprovalDecisionModel]:
        rows = await self.session.scalars(
            select(ApprovalDecisionModel)
            .where(ApprovalDecisionModel.approval_id == approval_id)
            .order_by(ApprovalDecisionModel.created_at)
        )
        return list(rows.all())


class ApprovalAuditEventRepository(BaseRepository[ApprovalAuditEventModel]):
    model = ApprovalAuditEventModel

    async def list_by_approval(self, approval_id: str) -> list[ApprovalAuditEventModel]:
        rows = await self.session.scalars(
            select(ApprovalAuditEventModel)
            .where(ApprovalAuditEventModel.approval_id == approval_id)
            .order_by(ApprovalAuditEventModel.occurred_at)
        )
        return list(rows.all())
