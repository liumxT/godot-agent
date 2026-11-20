"""Session 租约服务（E3-T08）。

受保护操作校验顺序：Session 有效（由调用方保证）→ 绑定 CONNECTED →
Lease 有效未过期 → ``fencing_token`` 等于项目最新值。
审计 ``lease.*`` 默认 fail-closed，由 ``AuditService`` 统一控制。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.errors import FencingTokenStale, LeaseExpired, LeaseRevoked
from core.logging import get_logger, log_event
from core.security.tokens import (
    ensure_utc,
    generate_lease_id,
    isoformat,
    utcnow,
)
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.audit.models import (
    AUDIT_LEASE_EXPIRED,
    AUDIT_LEASE_ISSUED,
    AUDIT_LEASE_REJECTED,
    AUDIT_LEASE_RENEWED,
    AUDIT_LEASE_REVOKED,
)
from modules.audit.service import AuditService
from modules.lease.models import (
    LEASE_STATUS_ACTIVE,
    LEASE_STATUS_EXPIRED,
    LEASE_STATUS_RENEWING,
    LEASE_STATUS_REVOKED,
    LEASE_TRANSITIONS,
    LeaseModel,
    ProjectFencingModel,
)
from modules.lease.repository import LeaseRepository

DEFAULT_LEASE_TTL_SECONDS = 45


@dataclass(frozen=True)
class LeaseView:
    lease_id: str
    session_id: str
    project_id: str
    fencing_token: int
    status: str
    issued_at: datetime
    renewed_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None


def _view(entity: LeaseModel) -> LeaseView:
    return LeaseView(
        lease_id=entity.lease_id,
        session_id=entity.session_id,
        project_id=entity.project_id,
        fencing_token=entity.fencing_token,
        status=entity.status,
        issued_at=ensure_utc(entity.issued_at),
        renewed_at=ensure_utc(entity.renewed_at) if entity.renewed_at else None,
        expires_at=ensure_utc(entity.expires_at),
        revoked_at=ensure_utc(entity.revoked_at) if entity.revoked_at else None,
    )


class LeaseService:
    """租约发放、续期、过期、撤销与 Fencing 校验。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._ttl = ttl_seconds
        self._audit = audit
        self._clock = clock
        self._logger = get_logger("backend.bridge")

    async def issue(self, *, session_id: str, project_id: str) -> LeaseView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = LeaseRepository(session)
            # 同一 Session 重新握手时旧租约立即失效，避免双重有效。
            await repository.revoke_active_for_session(session_id, now)
            fencing_token = await self._allocate_token(session, project_id)
            entity = LeaseModel(
                lease_id=generate_lease_id(),
                session_id=session_id,
                project_id=project_id,
                fencing_token=fencing_token,
                status=LEASE_STATUS_ACTIVE,
                issued_at=now,
                renewed_at=None,
                expires_at=now + timedelta(seconds=self._ttl),
                revoked_at=None,
            )
            await repository.add(entity)
            view = _view(entity)

        await self._record_audit(
            AUDIT_LEASE_ISSUED,
            session_id=session_id,
            resource=f"lease:{view.lease_id}",
            details={"project_id": project_id, "fencing_token": fencing_token},
        )
        log_event(
            self._logger,
            logging.INFO,
            "lease_issued",
            component="bridge",
        )
        return view

    async def renew(self, lease_id: str) -> LeaseView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await LeaseRepository(session).get(lease_id)
            self._ensure_renewable(entity, now)
            assert entity is not None
            self._transition(entity, LEASE_STATUS_RENEWING)
            entity.status = LEASE_STATUS_ACTIVE
            entity.renewed_at = now
            entity.expires_at = now + timedelta(seconds=self._ttl)
            view = _view(entity)

        await self._record_audit(
            AUDIT_LEASE_RENEWED,
            session_id=view.session_id,
            resource=f"lease:{view.lease_id}",
            details={"fencing_token": view.fencing_token},
        )
        return view

    async def revoke(self, lease_id: str, *, reason: str | None = None) -> LeaseView | None:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await LeaseRepository(session).get(lease_id)
            if entity is None:
                return None
            if entity.status != LEASE_STATUS_REVOKED:
                self._transition(entity, LEASE_STATUS_REVOKED)
                entity.revoked_at = now
            view = _view(entity)

        await self._record_audit(
            AUDIT_LEASE_REVOKED,
            session_id=view.session_id,
            resource=f"lease:{view.lease_id}",
            reason=reason,
        )
        return view

    async def revoke_for_session(self, session_id: str, *, reason: str | None = None) -> int:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            count = await LeaseRepository(session).revoke_active_for_session(session_id, now)
        if count:
            await self._record_audit(
                AUDIT_LEASE_REVOKED,
                session_id=session_id,
                resource=f"session:{session_id}",
                reason=reason,
                details={"revoked": count},
            )
        return count

    async def expire_stale(self) -> int:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            count = await LeaseRepository(session).expire_due(now)
        if count:
            await self._record_audit(
                AUDIT_LEASE_EXPIRED,
                resource="lease:sweep",
                details={"expired": count},
            )
        return count

    async def validate(
        self,
        *,
        session_id: str,
        project_id: str,
        fencing_token: int | None = None,
    ) -> LeaseView:
        """校验租约可用；失败按契约抛出 ``LEASE_*`` / ``FENCING_TOKEN_STALE``。"""

        now = self._clock()
        failure: str | None = None
        view: LeaseView | None = None
        async with self._database.session() as session, transaction(session):
            entity = await LeaseRepository(session).get_active(session_id, project_id)
            if entity is None:
                failure = "LEASE_EXPIRED"
            elif entity.status == LEASE_STATUS_REVOKED:
                failure = "LEASE_REVOKED"
            elif entity.status not in (LEASE_STATUS_ACTIVE, LEASE_STATUS_RENEWING):
                failure = "LEASE_EXPIRED"
            elif ensure_utc(entity.expires_at) <= now:
                entity.status = LEASE_STATUS_EXPIRED
                failure = "LEASE_EXPIRED"
            elif fencing_token is not None:
                latest = await self._latest_token(session, project_id)
                if fencing_token != latest:
                    failure = "FENCING_TOKEN_STALE"
            if failure is None:
                view = _view(entity)

        if failure is not None:
            await self._reject(session_id, project_id, failure)
        assert view is not None
        return view

    async def latest_fencing_token(self, project_id: str) -> int:
        async with self._database.session() as session:
            return await self._latest_token(session, project_id)

    async def active_for_session(self, session_id: str) -> LeaseView | None:
        async with self._database.session() as session:
            entity = await LeaseRepository(session).get_active_for_session(session_id)
        return _view(entity) if entity is not None else None

    async def count_active(self) -> int:
        async with self._database.session() as session:
            return await LeaseRepository(session).count_active()

    async def _allocate_token(self, session, project_id: str) -> int:
        entity = await session.get(ProjectFencingModel, project_id)
        if entity is None:
            entity = ProjectFencingModel(project_id=project_id, last_token=1)
            session.add(entity)
            return 1
        entity.last_token += 1
        return entity.last_token

    async def _latest_token(self, session, project_id: str) -> int:
        entity = await session.get(ProjectFencingModel, project_id)
        return entity.last_token if entity is not None else 0

    def _ensure_renewable(self, entity: LeaseModel | None, now: datetime) -> None:
        if entity is None:
            raise LeaseExpired("租约不存在")
        if entity.status == LEASE_STATUS_REVOKED:
            raise LeaseRevoked("租约已被撤销")
        if entity.status == LEASE_STATUS_EXPIRED:
            raise LeaseExpired("租约已过期")
        if ensure_utc(entity.expires_at) <= now:
            entity.status = LEASE_STATUS_EXPIRED
            raise LeaseExpired("租约已过期")

    async def _reject(self, session_id: str, project_id: str, code: str) -> None:
        await self._record_audit(
            AUDIT_LEASE_REJECTED,
            session_id=session_id,
            resource=f"project:{project_id}",
            decision="DENY",
            reason=code.lower(),
        )
        if code == "LEASE_REVOKED":
            raise LeaseRevoked("租约已被撤销")
        if code == "FENCING_TOKEN_STALE":
            raise FencingTokenStale("Fencing Token 已过期")
        raise LeaseExpired("租约已过期")

    def _transition(self, entity: LeaseModel, target: str) -> None:
        if target == entity.status:
            return
        if target not in LEASE_TRANSITIONS.get(entity.status, frozenset()):
            raise LeaseExpired(f"非法租约状态迁移: {entity.status} → {target}")
        entity.status = target

    async def _record_audit(self, action: str, **fields) -> None:
        if self._audit is not None:
            await self._audit.record(action, **fields)


def format_lease(view: LeaseView) -> dict[str, object]:
    """输出符合 ``bridge/lease.schema.json`` 的字段集合。"""

    return {
        "lease_id": view.lease_id,
        "session_id": view.session_id,
        "project_id": view.project_id,
        "fencing_token": view.fencing_token,
        "status": view.status,
        "issued_at": isoformat(view.issued_at),
        "renewed_at": isoformat(view.renewed_at) if view.renewed_at else None,
        "expires_at": isoformat(view.expires_at),
        "revoked_at": isoformat(view.revoked_at) if view.revoked_at else None,
    }
