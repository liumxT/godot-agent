"""Runtime 实例登记与状态上报（E3-T16）。

身份权威在 Backend：Runtime 只上报事实，不继承 Editor Session 或 Lease。
重复注册按 ``runtime_instance_id`` 幂等更新；跨项目复用同一实例 ID 直接拒绝。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.errors import RuntimeUnavailable, ValidationFailed
from core.logging import get_logger
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.runtime.models import (
    RUNTIME_CRASHED,
    RUNTIME_ENDED,
    RUNTIME_RUNNING,
    RUNTIME_STOPPED,
    RuntimeInstanceModel,
)
from modules.runtime.repository import RuntimeInstanceRepository

REPORTABLE_STATUSES = frozenset({RUNTIME_RUNNING, RUNTIME_STOPPED, RUNTIME_CRASHED})


@dataclass(frozen=True)
class RuntimeView:
    runtime_instance_id: str
    project_id: str
    editor_session_id: str | None
    client_id: str | None
    process_id: int
    godot_version: str | None
    build_mode: str | None
    status: str
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None


def _view(entity: RuntimeInstanceModel) -> RuntimeView:
    return RuntimeView(
        runtime_instance_id=entity.runtime_instance_id,
        project_id=entity.project_id,
        editor_session_id=entity.editor_session_id,
        client_id=entity.client_id,
        process_id=entity.process_id,
        godot_version=entity.godot_version,
        build_mode=entity.build_mode,
        status=entity.status,
        started_at=ensure_utc(entity.started_at),
        last_seen_at=ensure_utc(entity.last_seen_at),
        ended_at=ensure_utc(entity.ended_at) if entity.ended_at is not None else None,
    )


class RuntimeService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._clock = clock
        self._logger = get_logger("backend.runtime")

    async def register(
        self,
        *,
        runtime_instance_id: str,
        project_id: str,
        client_id: str | None,
        process_id: int,
        started_at: datetime,
        godot_version: str | None = None,
        build_mode: str | None = None,
        editor_session_id: str | None = None,
    ) -> RuntimeView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = RuntimeInstanceRepository(session)
            entity = await repository.get(runtime_instance_id)
            if entity is None:
                entity = RuntimeInstanceModel(
                    runtime_instance_id=runtime_instance_id,
                    project_id=project_id,
                    editor_session_id=editor_session_id,
                    client_id=client_id,
                    process_id=process_id,
                    godot_version=godot_version,
                    build_mode=build_mode,
                    status=RUNTIME_RUNNING,
                    started_at=ensure_utc(started_at),
                    last_seen_at=now,
                    ended_at=None,
                    created_at=now,
                )
                await repository.add(entity)
            else:
                if entity.project_id != project_id:
                    raise ValidationFailed("Runtime 实例已绑定其他项目")
                entity.process_id = process_id
                entity.client_id = client_id
                entity.godot_version = godot_version or entity.godot_version
                entity.build_mode = build_mode or entity.build_mode
                entity.editor_session_id = editor_session_id
                entity.status = RUNTIME_RUNNING
                entity.started_at = ensure_utc(started_at)
                entity.last_seen_at = now
                entity.ended_at = None
            view = _view(entity)
        return view

    async def report(
        self,
        *,
        runtime_instance_id: str,
        status: str,
    ) -> RuntimeView:
        if status not in REPORTABLE_STATUSES:
            raise ValidationFailed("Runtime 状态非法")
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = RuntimeInstanceRepository(session)
            entity = await repository.get(runtime_instance_id)
            if entity is None:
                raise RuntimeUnavailable("Runtime 实例未注册")
            entity.status = status
            entity.last_seen_at = now
            if status in (RUNTIME_STOPPED, RUNTIME_CRASHED):
                entity.ended_at = now
            elif status == RUNTIME_RUNNING:
                entity.ended_at = None
            view = _view(entity)
        return view

    async def mark_ended(self, runtime_instance_id: str, *, status: str = RUNTIME_ENDED) -> None:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await RuntimeInstanceRepository(session).get(runtime_instance_id)
            if entity is None or entity.status in (RUNTIME_STOPPED, RUNTIME_CRASHED, RUNTIME_ENDED):
                return
            entity.status = status
            entity.last_seen_at = now
            entity.ended_at = now

    async def list_by_project(self, project_id: str) -> list[RuntimeView]:
        async with self._database.session() as session:
            entities = await RuntimeInstanceRepository(session).list_by_project(project_id)
        return [_view(entity) for entity in entities]

    async def count_active(self) -> int:
        async with self._database.session() as session:
            return await RuntimeInstanceRepository(session).count_active()

    async def expire_stale(self, *, timeout_seconds: int) -> int:
        now = self._clock()
        cutoff = now - timedelta(seconds=timeout_seconds)
        async with self._database.session() as session, transaction(session):
            return await RuntimeInstanceRepository(session).expire_stale(cutoff, now)
