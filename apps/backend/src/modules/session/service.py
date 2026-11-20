"""Session 服务（E2-T05）。

状态机：``CREATED → ACTIVE → (EXPIRED | REVOKED | CLOSED)``；创建即 ACTIVE。
Session Token 使用 ``gds_`` 前缀，数据库只存 SHA-256 摘要。
Session 与 Client 绑定，但 Session 有效不代表拥有任何 Project 权限。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.errors import SessionExpired, SessionInvalid, SessionRevoked
from core.logging import get_logger, log_event
from core.security.tokens import (
    ensure_utc,
    generate_session_id,
    generate_session_token,
    hash_token,
    isoformat,
    utcnow,
)
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.audit.models import AUDIT_SESSION_CREATED, AUDIT_SESSION_REVOKED
from modules.audit.service import AuditService
from modules.session.models import (
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_EXPIRED,
    SESSION_STATUS_REVOKED,
    SESSION_TRANSITIONS,
    SessionModel,
)
from modules.session.repository import SessionRepository

DEFAULT_SESSION_TTL_SECONDS = 28800
DEFAULT_SESSION_MAX_TTL_SECONDS = 86400
DEFAULT_SESSION_RETENTION_DAYS = 7


@dataclass(frozen=True)
class SessionView:
    session_id: str
    client_id: str
    status: str
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
    closed_at: datetime | None


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    session: SessionView

    @property
    def token_type(self) -> str:
        return "Bearer"

    @property
    def expires_at(self) -> datetime:
        return self.session.expires_at


def _view(entity: SessionModel) -> SessionView:
    return SessionView(
        session_id=entity.session_id,
        client_id=entity.client_id,
        status=entity.status,
        created_at=ensure_utc(entity.created_at),
        last_seen_at=ensure_utc(entity.last_seen_at) if entity.last_seen_at else None,
        expires_at=ensure_utc(entity.expires_at),
        revoked_at=ensure_utc(entity.revoked_at) if entity.revoked_at else None,
        closed_at=ensure_utc(entity.closed_at) if entity.closed_at else None,
    )


class SessionService:
    """Session 创建、查询、续期与撤销。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        max_ttl_seconds: int = DEFAULT_SESSION_MAX_TTL_SECONDS,
        retention_days: int = DEFAULT_SESSION_RETENTION_DAYS,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._ttl = ttl_seconds
        self._max_ttl = max_ttl_seconds
        self._retention_days = retention_days
        self._audit = audit
        self._clock = clock
        self._logger = get_logger("backend.session")

    async def create(self, client_id: str) -> IssuedSession:
        now = self._clock()
        token = generate_session_token()
        entity = SessionModel(
            session_id=generate_session_id(),
            client_id=client_id,
            token_hash=hash_token(token),
            status=SESSION_STATUS_ACTIVE,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=self._effective_ttl(now, now)),
            revoked_at=None,
            closed_at=None,
        )
        async with self._database.session() as session, transaction(session):
            await SessionRepository(session).add(entity)

        await self._record_audit(
            AUDIT_SESSION_CREATED,
            client_id=client_id,
            session_id=entity.session_id,
            resource=f"session:{entity.session_id}",
        )
        log_event(
            self._logger,
            logging.INFO,
            "session_created",
            "session_created",
            component="session",
        )
        return IssuedSession(session_token=token, session=_view(entity))

    async def authenticate(self, session_token: str) -> SessionView:
        """校验 Session Token，并刷新 last_seen_at。"""

        now = self._clock()
        digest = hash_token(session_token)

        async with self._database.session() as session, transaction(session):
            entity = await SessionRepository(session).get_by_hash(digest)
            self._ensure_usable(entity, now)
            entity.last_seen_at = now
            view = _view(entity)
        return view

    async def get_active(self, session_id: str) -> SessionView | None:
        """按 session_id 读取仍有效的 Session；无效时返回 ``None``。"""

        now = self._clock()
        async with self._database.session() as session:
            entity = await SessionRepository(session).get(session_id)
        if entity is None or entity.status != SESSION_STATUS_ACTIVE:
            return None
        if ensure_utc(entity.expires_at) <= now:
            return None
        return _view(entity)

    async def renew(self, session_token: str) -> SessionView:
        """延长 Session，总时长不超过 ``session_max_ttl``。"""

        now = self._clock()
        digest = hash_token(session_token)

        async with self._database.session() as session, transaction(session):
            entity = await SessionRepository(session).get_by_hash(digest)
            self._ensure_usable(entity, now)
            created_at = ensure_utc(entity.created_at)
            renewed = now + timedelta(seconds=self._effective_ttl(created_at, now))
            if renewed > ensure_utc(entity.expires_at):
                entity.expires_at = renewed
            entity.last_seen_at = now
            view = _view(entity)

        log_event(
            self._logger,
            logging.INFO,
            "session_renewed",
            "session_renewed",
            component="session",
        )
        return view

    async def revoke(self, session_token: str) -> SessionView:
        now = self._clock()
        digest = hash_token(session_token)

        async with self._database.session() as session, transaction(session):
            entity = await SessionRepository(session).get_by_hash(digest)
            self._ensure_usable(entity, now)
            self._transition(entity, SESSION_STATUS_REVOKED)
            entity.revoked_at = now
            entity.last_seen_at = now
            view = _view(entity)

        await self._record_audit(
            AUDIT_SESSION_REVOKED,
            client_id=view.client_id,
            session_id=view.session_id,
            resource=f"session:{view.session_id}",
        )
        log_event(
            self._logger,
            logging.INFO,
            "session_revoked",
            "session_revoked",
            component="session",
        )
        return view

    async def expire_stale(self) -> int:
        """把到期但仍为 ACTIVE 的 Session 标记为 EXPIRED。"""

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            return await SessionRepository(session).expire_due(now)

    async def purge_expired(self) -> int:
        cutoff = self._clock() - timedelta(days=self._retention_days)
        async with self._database.session() as session, transaction(session):
            return await SessionRepository(session).delete_older_than(cutoff)

    def _effective_ttl(self, created_at: datetime, now: datetime) -> int:
        """本次有效期的秒数：受配置 TTL 与剩余 max_ttl 双重限制。"""

        remaining = int((created_at + timedelta(seconds=self._max_ttl) - now).total_seconds())
        return max(0, min(self._ttl, remaining))

    def _ensure_usable(self, entity: SessionModel | None, now: datetime) -> None:
        if entity is None:
            raise SessionInvalid("Session 无效")
        if entity.status == SESSION_STATUS_REVOKED:
            raise SessionRevoked("Session 已被撤销")
        if entity.status == SESSION_STATUS_EXPIRED:
            raise SessionExpired("Session 已过期")
        if entity.status != SESSION_STATUS_ACTIVE:
            raise SessionInvalid("Session 状态非法")
        if ensure_utc(entity.expires_at) <= now:
            entity.status = SESSION_STATUS_EXPIRED
            raise SessionExpired("Session 已过期")

    def _transition(self, entity: SessionModel, target: str) -> None:
        if target not in SESSION_TRANSITIONS.get(entity.status, frozenset()):
            raise SessionInvalid(f"非法 Session 状态迁移: {entity.status} → {target}")
        entity.status = target

    async def _record_audit(self, action: str, **fields) -> None:
        if self._audit is not None:
            await self._audit.record(action, **fields)


def format_session(view: SessionView) -> dict[str, str | None]:
    return {
        "session_id": view.session_id,
        "client_id": view.client_id,
        "status": view.status,
        "created_at": isoformat(view.created_at),
        "last_seen_at": isoformat(view.last_seen_at) if view.last_seen_at else None,
        "expires_at": isoformat(view.expires_at),
        "revoked_at": isoformat(view.revoked_at) if view.revoked_at else None,
        "closed_at": isoformat(view.closed_at) if view.closed_at else None,
    }


def format_issued(issued: IssuedSession) -> dict[str, object]:
    return {
        "session_token": issued.session_token,
        "token_type": issued.token_type,
        "expires_at": isoformat(issued.expires_at),
        "session": format_session(issued.session),
    }
