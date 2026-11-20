"""租约与 Fencing 仓储（E3-T08）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update

from infrastructure.database.repository import BaseRepository
from modules.lease.models import (
    LEASE_STATUS_ACTIVE,
    LEASE_STATUS_EXPIRED,
    LEASE_STATUS_RENEWING,
    LEASE_STATUS_REVOKED,
    LeaseModel,
)


class LeaseRepository(BaseRepository[LeaseModel]):
    model = LeaseModel

    async def get_active(self, session_id: str, project_id: str) -> LeaseModel | None:
        return await self.session.scalar(
            select(LeaseModel)
            .where(
                LeaseModel.session_id == session_id,
                LeaseModel.project_id == project_id,
                LeaseModel.status.in_((LEASE_STATUS_ACTIVE, LEASE_STATUS_RENEWING)),
            )
            .order_by(LeaseModel.issued_at.desc())
            .limit(1)
        )

    async def get_active_for_session(self, session_id: str) -> LeaseModel | None:
        return await self.session.scalar(
            select(LeaseModel)
            .where(
                LeaseModel.session_id == session_id,
                LeaseModel.status.in_((LEASE_STATUS_ACTIVE, LEASE_STATUS_RENEWING)),
            )
            .order_by(LeaseModel.issued_at.desc())
            .limit(1)
        )

    async def count_active(self) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(LeaseModel)
            .where(LeaseModel.status.in_((LEASE_STATUS_ACTIVE, LEASE_STATUS_RENEWING)))
        )
        return int(value or 0)

    async def list_active_by_project(self, project_id: str) -> list[LeaseModel]:
        result = await self.session.execute(
            select(LeaseModel).where(
                LeaseModel.project_id == project_id,
                LeaseModel.status.in_((LEASE_STATUS_ACTIVE, LEASE_STATUS_RENEWING)),
            )
        )
        return list(result.scalars().all())

    async def revoke_active_for_session(self, session_id: str, now: datetime) -> int:
        result = await self.session.execute(
            update(LeaseModel)
            .where(
                LeaseModel.session_id == session_id,
                LeaseModel.status.in_((LEASE_STATUS_ACTIVE, LEASE_STATUS_RENEWING)),
            )
            .values(status=LEASE_STATUS_REVOKED, revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)

    async def expire_due(self, now: datetime) -> int:
        result = await self.session.execute(
            update(LeaseModel)
            .where(
                LeaseModel.status.in_((LEASE_STATUS_ACTIVE, LEASE_STATUS_RENEWING)),
                LeaseModel.expires_at <= now,
            )
            .values(status=LEASE_STATUS_EXPIRED)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)
