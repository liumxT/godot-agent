"""Project Access 服务（E2-T07）。

访问记录把 Client、Session 与 Project 绑定在一起；查询与撤销都要求记录
``ACTIVE`` 且未过期。未知项目没有登记记录，因此默认拒绝（项目注册表在 E4 引入）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.errors import ProjectAccessDenied, ValidationFailed
from core.logging import get_logger, log_event
from core.security.tokens import (
    ensure_utc,
    generate_access_id,
    isoformat,
    utcnow,
)
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.access.models import (
    ACCESS_LEVELS,
    ACCESS_STATUS_ACTIVE,
    ACCESS_STATUS_REVOKED,
    ProjectAccessModel,
)
from modules.access.repository import ProjectAccessRepository
from modules.audit.models import (
    AUDIT_ACCESS_GRANTED,
    AUDIT_ACCESS_REVOKED,
    AUDIT_AUTHORIZATION_DENIED,
)
from modules.audit.service import AuditService

DEFAULT_PROJECT_ACCESS_TTL_SECONDS = 86400


@dataclass(frozen=True)
class AccessView:
    access_id: str
    project_id: str
    client_id: str
    session_id: str
    access_level: str
    granted_by: str
    granted_at: datetime
    expires_at: datetime
    status: str


def _view(entity: ProjectAccessModel) -> AccessView:
    return AccessView(
        access_id=entity.access_id,
        project_id=entity.project_id,
        client_id=entity.client_id,
        session_id=entity.session_id,
        access_level=entity.access_level,
        granted_by=entity.granted_by,
        granted_at=ensure_utc(entity.granted_at),
        expires_at=ensure_utc(entity.expires_at),
        status=entity.status,
    )


class ProjectAccessService:
    """项目访问的授予、校验与撤销。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        ttl_seconds: int = DEFAULT_PROJECT_ACCESS_TTL_SECONDS,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._ttl = ttl_seconds
        self._audit = audit
        self._clock = clock
        self._logger = get_logger("backend.access")

    async def grant(
        self,
        *,
        project_id: str,
        session_id: str,
        client_id: str,
        access_level: str,
        granted_by: str,
        expires_at: datetime | None = None,
    ) -> AccessView:
        if access_level not in ACCESS_LEVELS:
            raise ValidationFailed("access_level 非法", details={"access_level": access_level})
        now = self._clock()
        expiry = (
            ensure_utc(expires_at) if expires_at is not None else now + timedelta(seconds=self._ttl)
        )
        if expiry <= now:
            raise ValidationFailed("expires_at 必须晚于当前时间")

        async with self._database.session() as session, transaction(session):
            repository = ProjectAccessRepository(session)
            entity = await repository.get_active(
                project_id=project_id, session_id=session_id, now=now
            )
            if entity is None:
                entity = ProjectAccessModel(
                    access_id=generate_access_id(),
                    project_id=project_id,
                    client_id=client_id,
                    session_id=session_id,
                    access_level=access_level,
                    granted_by=granted_by,
                    granted_at=now,
                    expires_at=expiry,
                    status=ACCESS_STATUS_ACTIVE,
                )
                await repository.add(entity)
            else:
                entity.access_level = access_level
                entity.granted_by = granted_by
                entity.granted_at = now
                entity.expires_at = expiry
                entity.status = ACCESS_STATUS_ACTIVE
                await session.flush()
            view = _view(entity)

        await self._record_audit(
            AUDIT_ACCESS_GRANTED,
            actor_id=granted_by,
            client_id=client_id,
            session_id=session_id,
            resource=f"project:{project_id}",
            details={
                "project_id": project_id,
                "access_level": access_level,
                "target_session_id": session_id,
            },
            sensitive=True,
        )
        log_event(
            self._logger,
            logging.INFO,
            "access_granted",
            "access_granted",
            component="access",
        )
        return view

    async def get_current(self, *, project_id: str, session_id: str, client_id: str) -> AccessView:
        now = self._clock()
        async with self._database.session() as session:
            entity = await ProjectAccessRepository(session).get_active(
                project_id=project_id, session_id=session_id, now=now
            )
        if entity is None or entity.client_id != client_id:
            await self._record_audit(
                AUDIT_AUTHORIZATION_DENIED,
                actor_id=client_id,
                client_id=client_id,
                session_id=session_id,
                resource=f"project:{project_id}",
                decision="DENY",
                reason="project_access_denied",
                details={"project_id": project_id, "action": "project.access.read"},
            )
            raise ProjectAccessDenied("没有该项目的有效访问")
        return _view(entity)

    async def has_owner(self, *, project_id: str, client_id: str) -> bool:
        now = self._clock()
        async with self._database.session() as session:
            entity = await ProjectAccessRepository(session).get_active_owner(
                project_id=project_id, client_id=client_id, now=now
            )
        return entity is not None

    async def revoke(self, *, project_id: str, session_id: str, client_id: str) -> AccessView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ProjectAccessRepository(session).get_active(
                project_id=project_id, session_id=session_id, now=now
            )
            if entity is None or entity.client_id != client_id:
                raise ProjectAccessDenied("没有该项目的有效访问")
            entity.status = ACCESS_STATUS_REVOKED
            await session.flush()
            view = _view(entity)

        await self._record_audit(
            AUDIT_ACCESS_REVOKED,
            actor_id=client_id,
            client_id=client_id,
            session_id=session_id,
            resource=f"project:{project_id}",
            details={"project_id": project_id, "target_session_id": session_id},
            sensitive=True,
        )
        log_event(
            self._logger,
            logging.INFO,
            "access_revoked",
            "access_revoked",
            component="access",
        )
        return view

    async def expire_stale(self) -> int:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            return await ProjectAccessRepository(session).expire_due(now)

    async def _record_audit(self, action: str, **fields) -> None:
        if self._audit is not None:
            await self._audit.record(action, **fields)


def format_access(view: AccessView) -> dict[str, str]:
    return {
        "access_id": view.access_id,
        "project_id": view.project_id,
        "client_id": view.client_id,
        "session_id": view.session_id,
        "access_level": view.access_level,
        "status": view.status,
        "granted_by": view.granted_by,
        "granted_at": isoformat(view.granted_at),
        "expires_at": isoformat(view.expires_at),
    }
