"""客户端注册与认证服务（E2-T06 / T03 / T04）。

应用层只调用本模块的 Service，不接触 SQLAlchemy 会话或 Repository。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.errors import (
    AuthChallengeInvalid,
    AuthInvalid,
    ClientExists,
    NotFoundError,
    RateLimited,
    TokenExpired,
    TokenInvalid,
    TokenRevoked,
)
from core.logging import get_logger, log_event
from core.security.tokens import (
    compute_proof,
    constant_time_equals,
    ensure_utc,
    generate_access_token,
    generate_challenge,
    generate_challenge_id,
    generate_client_id,
    generate_credential_id,
    generate_secret,
    generate_token_id,
    hash_token,
    isoformat,
    secret_name,
    utcnow,
)
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.security.challenge import (
    CHALLENGE_STATUS_ISSUED,
    ChallengeStore,
)
from infrastructure.security.rate_limit import SlidingWindowRateLimiter
from modules.audit.models import AUDIT_AUTH_FAILED, AUDIT_AUTH_SUCCEEDED, AUDIT_CLIENT_REGISTERED
from modules.audit.service import AuditService
from modules.client.models import (
    CLIENT_STATUS_ACTIVE,
    CLIENT_STATUS_REVOKED,
    CREDENTIAL_STATUS_ACTIVE,
    CREDENTIAL_TYPE_CLIENT_SECRET,
    AccessTokenModel,
    ClientCredentialModel,
    ClientModel,
)
from modules.client.repository import (
    AccessTokenRepository,
    ClientRepository,
    CredentialRepository,
)

DEFAULT_CHALLENGE_TTL_SECONDS = 60
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 600
DEFAULT_TOKEN_RETENTION_DAYS = 7
CHALLENGE_CLEANUP_GRACE_SECONDS = 3600


@dataclass(frozen=True)
class ClientRegistration:
    client_id: str
    client_secret: str
    client_type: str
    client_name: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ClientView:
    client_id: str
    client_type: str
    client_name: str
    client_version: str | None
    godot_version: str | None
    platform: str | None
    status: str
    created_at: datetime
    last_seen_at: datetime | None


@dataclass(frozen=True)
class ChallengeIssue:
    challenge_id: str
    challenge: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedToken:
    access_token: str
    token_id: str
    client_id: str
    expires_at: datetime

    @property
    def token_type(self) -> str:
        return "Bearer"


@dataclass(frozen=True)
class AccessTokenInfo:
    token_id: str
    client_id: str
    expires_at: datetime


def _view(entity: ClientModel) -> ClientView:
    return ClientView(
        client_id=entity.client_id,
        client_type=entity.client_type,
        client_name=entity.client_name,
        client_version=entity.client_version,
        godot_version=entity.godot_version,
        platform=entity.platform,
        status=entity.status,
        created_at=ensure_utc(entity.created_at),
        last_seen_at=ensure_utc(entity.last_seen_at) if entity.last_seen_at else None,
    )


class ClientService:
    """客户端注册、查询、更新与注销。"""

    def __init__(
        self,
        database: DatabaseService,
        secrets,
        *,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._secrets = secrets
        self._audit = audit
        self._clock = clock
        self._logger = get_logger("backend.auth")

    async def register(
        self,
        *,
        client_type: str,
        client_name: str,
        client_version: str | None = None,
        godot_version: str | None = None,
        platform: str | None = None,
        client_id: str | None = None,
    ) -> ClientRegistration:
        resolved_id = client_id or generate_client_id()
        secret = generate_secret()
        name = secret_name(resolved_id)
        secret_written = False
        try:
            async with self._database.session() as session, transaction(session):
                repository = ClientRepository(session)
                if await repository.get(resolved_id) is not None:
                    raise ClientExists("客户端已存在", details={"client_id": resolved_id})

                now = self._clock()
                entity = ClientModel(
                    client_id=resolved_id,
                    client_type=client_type,
                    client_name=client_name,
                    client_version=client_version,
                    godot_version=godot_version,
                    platform=platform,
                    status=CLIENT_STATUS_ACTIVE,
                    created_at=now,
                    last_seen_at=None,
                )
                await repository.add(entity)
                await CredentialRepository(session).add(
                    ClientCredentialModel(
                        credential_id=generate_credential_id(),
                        client_id=resolved_id,
                        credential_type=CREDENTIAL_TYPE_CLIENT_SECRET,
                        status=CREDENTIAL_STATUS_ACTIVE,
                        created_at=now,
                        expires_at=None,
                        revoked_at=None,
                    )
                )
                await asyncio.to_thread(self._secrets.set, name, secret)
                secret_written = True
        except BaseException:
            if secret_written:
                await asyncio.to_thread(self._secrets.delete, name)
            raise

        try:
            await self._record_audit(
                AUDIT_CLIENT_REGISTERED,
                client_id=resolved_id,
                actor_id="bootstrap",
                resource=f"client:{resolved_id}",
                details={"client_type": client_type},
                sensitive=True,
            )
        except BaseException:
            await asyncio.to_thread(self._secrets.delete, name)
            raise

        log_event(
            self._logger,
            logging.INFO,
            "client_registered",
            "client_registered",
            component="auth",
        )
        return ClientRegistration(
            client_id=resolved_id,
            client_secret=secret,
            client_type=client_type,
            client_name=client_name,
            status=CLIENT_STATUS_ACTIVE,
            created_at=now,
        )

    async def get(self, client_id: str) -> ClientView | None:
        async with self._database.session() as session:
            entity = await ClientRepository(session).get(client_id)
        return _view(entity) if entity is not None else None

    async def list_clients(
        self, *, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[ClientView]:
        async with self._database.session() as session:
            entities = await ClientRepository(session).list_clients(
                limit=limit, offset=offset, status=status
            )
        return [_view(entity) for entity in entities]

    async def update(
        self,
        client_id: str,
        *,
        client_name: str | None = None,
        client_version: str | None = None,
        godot_version: str | None = None,
        platform: str | None = None,
    ) -> ClientView:
        async with self._database.session() as session, transaction(session):
            entity = await ClientRepository(session).get(client_id)
            if entity is None:
                raise NotFoundError("客户端不存在", details={"client_id": client_id})
            if client_name is not None:
                entity.client_name = client_name
            if client_version is not None:
                entity.client_version = client_version
            if godot_version is not None:
                entity.godot_version = godot_version
            if platform is not None:
                entity.platform = platform
            await session.flush()
            view = _view(entity)
        return view

    async def deactivate(self, client_id: str) -> None:
        """注销：状态置为 revoked，撤销凭证与 Token，并删除 keyring Secret。"""

        async with self._database.session() as session, transaction(session):
            entity = await ClientRepository(session).get(client_id)
            if entity is None:
                raise NotFoundError("客户端不存在", details={"client_id": client_id})
            now = self._clock()
            entity.status = CLIENT_STATUS_REVOKED
            await CredentialRepository(session).revoke_active_for_client(client_id, now)
            await AccessTokenRepository(session).revoke_for_client(client_id, now)
        await asyncio.to_thread(self._secrets.delete, secret_name(client_id))

    async def is_active(self, client_id: str) -> bool:
        view = await self.get(client_id)
        return view is not None and view.status == CLIENT_STATUS_ACTIVE

    async def _record_audit(self, action: str, **fields) -> None:
        if self._audit is not None:
            await self._audit.record(action, **fields)


class AuthService:
    """挑战-响应认证与 Access Token 生命周期。"""

    def __init__(
        self,
        database: DatabaseService,
        secrets,
        *,
        challenge_ttl_seconds: int = DEFAULT_CHALLENGE_TTL_SECONDS,
        access_token_ttl_seconds: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
        token_retention_days: int = DEFAULT_TOKEN_RETENTION_DAYS,
        limiter: SlidingWindowRateLimiter | None = None,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._secrets = secrets
        self._challenge_ttl = challenge_ttl_seconds
        self._access_ttl = access_token_ttl_seconds
        self._retention_days = token_retention_days
        self._limiter = limiter or SlidingWindowRateLimiter(10)
        self._audit = audit
        self._clock = clock
        self._logger = get_logger("backend.auth")
        self._challenges = ChallengeStore()

    async def create_challenge(self, client_id: str) -> ChallengeIssue:
        now = self._clock()
        expires_at = now + timedelta(seconds=self._challenge_ttl)
        challenge_id = generate_challenge_id()
        challenge = generate_challenge()

        async with self._database.session() as session, transaction(session):
            client = await ClientRepository(session).get(client_id)
            if client is None or client.status != CLIENT_STATUS_ACTIVE:
                raise AuthInvalid("客户端无效", details={"client_id": client_id})
            await self._challenges.create(
                session,
                challenge_id=challenge_id,
                client_id=client_id,
                challenge=challenge,
                created_at=now,
                expires_at=expires_at,
            )
        return ChallengeIssue(challenge_id=challenge_id, challenge=challenge, expires_at=expires_at)

    async def verify_challenge(
        self, *, challenge_id: str, client_id: str, proof: str
    ) -> IssuedToken:
        self._guard_rate_limit(client_id)
        now = self._clock()

        try:
            async with self._database.session() as session, transaction(session):
                entity = await self._challenges.get(session, challenge_id)
                if (
                    entity is None
                    or entity.client_id != client_id
                    or entity.status != CHALLENGE_STATUS_ISSUED
                    or entity.used_at is not None
                    or ensure_utc(entity.expires_at) <= now
                ):
                    self._fail_challenge(client_id)

                secret = await asyncio.to_thread(self._secrets.get, secret_name(client_id))
                if secret is None:
                    self._record_failure(client_id)
                    raise AuthInvalid("客户端凭证无效", details={"client_id": client_id})

                expected = compute_proof(secret, challenge_id, entity.challenge)
                if not constant_time_equals(expected, proof):
                    self._fail_challenge(client_id)

                if not await self._challenges.consume(session, challenge_id, now):
                    self._fail_challenge(client_id)

                client = await ClientRepository(session).get(client_id)
                if client is None or client.status != CLIENT_STATUS_ACTIVE:
                    self._record_failure(client_id)
                    raise AuthInvalid("客户端无效", details={"client_id": client_id})

                issued = await self._issue_token(session, client_id, now)
                client.last_seen_at = now
        except (AuthChallengeInvalid, AuthInvalid) as exc:
            await self._audit_auth(
                AUDIT_AUTH_FAILED,
                client_id,
                decision="DENY",
                reason=exc.code.lower(),
            )
            raise

        self._limiter.reset(client_id)
        await self._audit_auth(AUDIT_AUTH_SUCCEEDED, client_id, reason="challenge")
        log_event(
            self._logger,
            logging.INFO,
            "auth_succeeded",
            "auth_succeeded",
            component="auth",
        )
        return issued

    async def refresh(self, access_token: str) -> IssuedToken:
        info = await self.verify_access_token(access_token)
        now = self._clock()

        async with self._database.session() as session, transaction(session):
            repository = AccessTokenRepository(session)
            if not await repository.revoke_if_active(info.token_id, now):
                raise TokenRevoked("Access Token 已被撤销")
            issued = await self._issue_token(session, info.client_id, now)

        log_event(
            self._logger,
            logging.INFO,
            "token_rotated",
            "token_rotated",
            component="auth",
        )
        return issued

    async def verify_access_token(self, access_token: str) -> AccessTokenInfo:
        now = self._clock()
        digest = hash_token(access_token)

        async with self._database.session() as session:
            entity = await AccessTokenRepository(session).get_by_hash(digest)

        if entity is None or not constant_time_equals(entity.token_hash, digest):
            raise TokenInvalid("Access Token 无效")
        if entity.revoked_at is not None:
            raise TokenRevoked("Access Token 已被撤销")
        if ensure_utc(entity.expires_at) <= now:
            raise TokenExpired("Access Token 已过期")
        return AccessTokenInfo(
            token_id=entity.token_id,
            client_id=entity.client_id,
            expires_at=ensure_utc(entity.expires_at),
        )

    async def purge_expired(self) -> dict[str, int]:
        now = self._clock()
        token_cutoff = now - timedelta(days=self._retention_days)
        challenge_cutoff = now - timedelta(
            seconds=self._challenge_ttl + CHALLENGE_CLEANUP_GRACE_SECONDS
        )

        async with self._database.session() as session, transaction(session):
            tokens = await AccessTokenRepository(session).delete_older_than(token_cutoff)
            challenges = await self._challenges.delete_expired(session, challenge_cutoff)
        return {"access_tokens": tokens, "challenges": challenges}

    async def _issue_token(self, session, client_id: str, now: datetime) -> IssuedToken:
        token = generate_access_token()
        token_id = generate_token_id()
        expires_at = now + timedelta(seconds=self._access_ttl)
        await AccessTokenRepository(session).add(
            AccessTokenModel(
                token_id=token_id,
                client_id=client_id,
                token_hash=hash_token(token),
                issued_at=now,
                expires_at=expires_at,
                revoked_at=None,
            )
        )
        return IssuedToken(
            access_token=token,
            token_id=token_id,
            client_id=client_id,
            expires_at=expires_at,
        )

    def _guard_rate_limit(self, client_id: str) -> None:
        decision = self._limiter.check(client_id)
        if decision.allowed:
            return
        log_event(
            self._logger,
            logging.WARNING,
            "auth_rate_limited",
            component="auth",
            error_code="RATE_LIMITED",
        )
        raise RateLimited(
            "认证尝试过于频繁，请稍后重试",
            details={"retry_after": decision.retry_after_seconds},
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    def _record_failure(self, client_id: str) -> None:
        self._limiter.record(client_id)
        log_event(
            self._logger,
            logging.WARNING,
            "auth_failed",
            f"auth_failed client={client_id}",
            component="auth",
            error_code="AUTH_CHALLENGE_INVALID",
        )

    def _fail_challenge(self, client_id: str) -> None:
        self._record_failure(client_id)
        raise AuthChallengeInvalid("认证挑战无效或已过期")

    async def _audit_auth(
        self,
        action: str,
        client_id: str,
        *,
        decision: str = "ALLOW",
        reason: str | None = None,
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            action,
            actor_id=client_id,
            client_id=client_id,
            resource="auth",
            decision=decision,
            reason=reason,
            sensitive=True,
        )


class AuthCleanupTask:
    """启动后清理过期挑战与 Token；每小时一次，关闭时取消。"""

    def __init__(self, service: AuthService, *, interval_seconds: int = 3600) -> None:
        self._service = service
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._logger = get_logger("backend.auth")

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._service.purge_expired()
            except Exception:
                self._logger.exception(
                    "auth_cleanup_failed",
                    extra={
                        "component": "auth",
                        "event": "auth_cleanup_failed",
                        "error_code": "INFRASTRUCTURE_ERROR",
                    },
                )


def format_client(registration: ClientRegistration) -> dict[str, str]:
    return {
        "client_id": registration.client_id,
        "client_secret": registration.client_secret,
        "client_type": registration.client_type,
        "client_name": registration.client_name,
        "status": registration.status,
        "created_at": isoformat(registration.created_at),
    }
