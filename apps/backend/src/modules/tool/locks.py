"""项目资源锁服务（E5-T24）。

锁的服务端是唯一权威：锁的有效期、冲突与 Fencing Token 都由服务端判定，
客户端断线不等于锁已释放。冲突规则：

- ``READ_LOCK`` 之间不冲突；
- ``WRITE_LOCK`` 与 ``READ_LOCK`` / ``WRITE_LOCK`` 冲突；
- ``EXCLUSIVE_LOCK`` 与任何锁冲突。

Fencing Token 按 ``(project_id, resource_key)`` 单调递增，执行前必须重新校验。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from core.errors import (
    FencingTokenStale,
    ResourceLockConflict,
    ResourceLockExpired,
    ValidationFailed,
)
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.tool.models import (
    LOCK_OWNER_TYPES,
    LOCK_STATUS_ACTIVE,
    LOCK_STATUS_EXPIRED,
    LOCK_STATUS_RELEASED,
    LOCK_TYPE_EXCLUSIVE,
    LOCK_TYPE_READ,
    LOCK_TYPE_WRITE,
    LOCK_TYPES,
    ResourceLockModel,
)
from modules.tool.repository import ResourceLockRepository

DEFAULT_RESOURCE_LOCK_TTL_SECONDS = 300
MAX_RESOURCE_LOCK_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class ResourceLockView:
    lock_id: str
    project_id: str
    resource_key: str
    owner_type: str
    owner_id: str
    lock_type: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime
    status: str


def _view(entity: ResourceLockModel) -> ResourceLockView:
    return ResourceLockView(
        lock_id=entity.lock_id,
        project_id=entity.project_id,
        resource_key=entity.resource_key,
        owner_type=entity.owner_type,
        owner_id=entity.owner_id,
        lock_type=entity.lock_type,
        fencing_token=entity.fencing_token,
        acquired_at=ensure_utc(entity.acquired_at),
        expires_at=ensure_utc(entity.expires_at),
        status=entity.status,
    )


class ResourceLockService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        ttl_seconds: int = DEFAULT_RESOURCE_LOCK_TTL_SECONDS,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._ttl = min(ttl_seconds, MAX_RESOURCE_LOCK_TTL_SECONDS)
        self._clock = clock
        self._logger = get_logger("backend.tool")

    async def acquire(
        self,
        *,
        project_id: str,
        resource_key: str,
        owner_type: str,
        owner_id: str,
        lock_type: str,
        ttl_seconds: int | None = None,
    ) -> ResourceLockView:
        if not project_id.strip() or not owner_id.strip():
            raise ValidationFailed("project_id 与 owner_id 不能为空")
        if not resource_key.strip():
            raise ValidationFailed("resource_key 不能为空")
        if lock_type not in LOCK_TYPES:
            raise ValidationFailed(
                "锁类型非法", details={"lock_type": lock_type, "allowed": sorted(LOCK_TYPES)}
            )
        if owner_type not in LOCK_OWNER_TYPES:
            raise ValidationFailed("owner_type 非法", details={"owner_type": owner_type})
        now = self._clock()
        expiry = now + timedelta(seconds=self._ttl_seconds(ttl_seconds))

        async with self._database.session() as session, transaction(session):
            repository = ResourceLockRepository(session)
            await repository.expire_due(now)
            active = await repository.list_active(project_id, resource_key, now)
            conflicts = [
                lock
                for lock in active
                if lock.owner_id != owner_id and _conflicts(lock.lock_type, lock_type)
            ]
            if conflicts:
                raise ResourceLockConflict(
                    "资源已被锁定",
                    details={
                        "resource_key": resource_key,
                        "conflicts": [
                            {"lock_id": lock.lock_id, "lock_type": lock.lock_type}
                            for lock in conflicts
                        ],
                    },
                )
            entity = ResourceLockModel(
                lock_id="lck_" + uuid4().hex[:12],
                project_id=project_id,
                resource_key=resource_key,
                owner_type=owner_type,
                owner_id=owner_id,
                lock_type=lock_type,
                fencing_token=await repository.max_fencing_token(project_id, resource_key) + 1,
                acquired_at=now,
                expires_at=expiry,
                status=LOCK_STATUS_ACTIVE,
            )
            await repository.add(entity)
            view = _view(entity)

        log_event(self._logger, logging.INFO, "resource_lock_acquired", component="tool")
        return view

    async def acquire_many(
        self,
        resource_keys: Sequence[str],
        *,
        project_id: str,
        owner_type: str,
        owner_id: str,
        lock_type: str,
        ttl_seconds: int | None = None,
    ) -> tuple[ResourceLockView, ...]:
        acquired: list[ResourceLockView] = []
        try:
            for resource_key in dict.fromkeys(resource_keys):
                acquired.append(
                    await self.acquire(
                        project_id=project_id,
                        resource_key=resource_key,
                        owner_type=owner_type,
                        owner_id=owner_id,
                        lock_type=lock_type,
                        ttl_seconds=ttl_seconds,
                    )
                )
        except Exception:
            for lock in acquired:
                await self.release(lock.lock_id, owner_id=owner_id)
            raise
        return tuple(acquired)

    async def validate(
        self,
        lock_id: str,
        *,
        fencing_token: int | None = None,
        owner_id: str | None = None,
    ) -> ResourceLockView:
        """执行前校验锁仍有效、归属一致且 Fencing Token 匹配。"""

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ResourceLockRepository(session).get(lock_id)
            if entity is None or entity.status != LOCK_STATUS_ACTIVE:
                raise ResourceLockExpired("资源锁不存在或已释放", details={"lock_id": lock_id})
            if ensure_utc(entity.expires_at) <= now:
                entity.status = LOCK_STATUS_EXPIRED
                raise ResourceLockExpired("资源锁已过期", details={"lock_id": lock_id})
            if owner_id is not None and entity.owner_id != owner_id:
                raise ResourceLockConflict(
                    "资源锁归属不一致",
                    details={"lock_id": lock_id, "owner_id": entity.owner_id},
                )
            if fencing_token is not None and entity.fencing_token != fencing_token:
                raise FencingTokenStale(
                    "Fencing Token 已过期",
                    details={"lock_id": lock_id, "fencing_token": entity.fencing_token},
                )
            return _view(entity)

    async def renew(
        self,
        lock_id: str,
        *,
        owner_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> ResourceLockView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ResourceLockRepository(session).get(lock_id)
            if entity is None or entity.status != LOCK_STATUS_ACTIVE:
                raise ResourceLockExpired("资源锁不存在或已释放", details={"lock_id": lock_id})
            if ensure_utc(entity.expires_at) <= now:
                entity.status = LOCK_STATUS_EXPIRED
                raise ResourceLockExpired("资源锁已过期", details={"lock_id": lock_id})
            if owner_id is not None and entity.owner_id != owner_id:
                raise ResourceLockConflict("资源锁归属不一致", details={"lock_id": lock_id})
            entity.expires_at = now + timedelta(seconds=self._ttl_seconds(ttl_seconds))
            await session.flush()
            return _view(entity)

    async def release(
        self, lock_id: str, *, owner_id: str | None = None
    ) -> ResourceLockView | None:
        async with self._database.session() as session, transaction(session):
            entity = await ResourceLockRepository(session).get(lock_id)
            if entity is None:
                return None
            if owner_id is not None and entity.owner_id != owner_id:
                raise ResourceLockConflict("资源锁归属不一致", details={"lock_id": lock_id})
            if entity.status == LOCK_STATUS_ACTIVE:
                entity.status = LOCK_STATUS_RELEASED
                await session.flush()
            return _view(entity)

    async def expire_stale(self) -> int:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            return await ResourceLockRepository(session).expire_due(now)

    async def active_for_resource(
        self, project_id: str, resource_key: str
    ) -> tuple[ResourceLockView, ...]:
        now = self._clock()
        async with self._database.session() as session:
            entities = await ResourceLockRepository(session).list_active(
                project_id, resource_key, now
            )
        return tuple(_view(entity) for entity in entities)

    def _ttl_seconds(self, ttl_seconds: int | None) -> int:
        if ttl_seconds is None:
            return self._ttl
        if ttl_seconds <= 0:
            raise ValidationFailed("ttl_seconds 必须为正整数")
        return min(ttl_seconds, MAX_RESOURCE_LOCK_TTL_SECONDS)


def _conflicts(existing: str, requested: str) -> bool:
    if existing == LOCK_TYPE_EXCLUSIVE or requested == LOCK_TYPE_EXCLUSIVE:
        return True
    if existing == LOCK_TYPE_READ and requested == LOCK_TYPE_READ:
        return False
    return LOCK_TYPE_WRITE in (existing, requested)


def format_lock(view: ResourceLockView) -> dict[str, object]:
    return {
        "lock_id": view.lock_id,
        "project_id": view.project_id,
        "resource_key": view.resource_key,
        "owner_type": view.owner_type,
        "owner_id": view.owner_id,
        "lock_type": view.lock_type,
        "fencing_token": view.fencing_token,
        "acquired_at": isoformat(view.acquired_at),
        "expires_at": isoformat(view.expires_at),
        "status": view.status,
    }


__all__ = ["ResourceLockService", "ResourceLockView", "format_lock"]
