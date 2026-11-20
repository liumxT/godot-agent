"""Editor Session 绑定服务（E3-T07）。

插件只缓存 Session 结果，任何「是否有效」的判断都以 E2 Session 服务为准；
本服务只维护绑定状态与时间戳，不做续期。
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from core.errors import ValidationFailed
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.editor_session.models import (
    BINDING_CLOSED,
    BINDING_CONNECTED,
    BINDING_DISCONNECTED,
    BINDING_RECOVERING,
    BINDING_TRANSITIONS,
    TRANSPORT_WEBSOCKET,
    EditorSessionModel,
)
from modules.editor_session.repository import EditorSessionRepository

_EDITOR_INSTANCE_PATTERN = re.compile(r"^edi_[a-z0-9]{12}$")


@dataclass(frozen=True)
class EditorSessionView:
    session_id: str
    editor_instance_id: str
    project_id: str
    godot_version: str | None
    plugin_version: str | None
    transport: str
    binding_status: str
    connected_at: datetime
    disconnected_at: datetime | None
    last_seen_at: datetime | None
    closed_at: datetime | None


def _view(entity: EditorSessionModel) -> EditorSessionView:
    return EditorSessionView(
        session_id=entity.session_id,
        editor_instance_id=entity.editor_instance_id,
        project_id=entity.project_id,
        godot_version=entity.godot_version,
        plugin_version=entity.plugin_version,
        transport=entity.transport,
        binding_status=entity.binding_status,
        connected_at=ensure_utc(entity.connected_at),
        disconnected_at=ensure_utc(entity.disconnected_at) if entity.disconnected_at else None,
        last_seen_at=ensure_utc(entity.last_seen_at) if entity.last_seen_at else None,
        closed_at=ensure_utc(entity.closed_at) if entity.closed_at else None,
    )


def normalize_editor_instance_id(raw: str) -> str:
    """把插件上报的实例标识规范化为 ``edi_`` + 12 位小写字母数字。

    合法值原样保留；UUID 等自由格式按 SHA-256 派生，保证同一实例稳定复用。
    """

    value = (raw or "").strip().lower()
    if _EDITOR_INSTANCE_PATTERN.match(value):
        return value
    if not value:
        raise ValidationFailed("缺少 editor_instance_id")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return "edi_" + digest[:12]


class EditorSessionService:
    """绑定创建与状态迁移。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._clock = clock
        self._logger = get_logger("backend.bridge")

    async def bind(
        self,
        *,
        session_id: str,
        editor_instance_id: str,
        project_id: str,
        godot_version: str | None = None,
        plugin_version: str | None = None,
        transport: str = TRANSPORT_WEBSOCKET,
    ) -> EditorSessionView:
        instance_id = normalize_editor_instance_id(editor_instance_id)
        now = self._clock()

        async with self._database.session() as session, transaction(session):
            repository = EditorSessionRepository(session)
            entity = await repository.get(session_id)
            if entity is None:
                entity = EditorSessionModel(
                    session_id=session_id,
                    editor_instance_id=instance_id,
                    project_id=project_id,
                    godot_version=godot_version,
                    plugin_version=plugin_version,
                    transport=transport,
                    binding_status=BINDING_CONNECTED,
                    connected_at=now,
                    disconnected_at=None,
                    last_seen_at=now,
                    closed_at=None,
                )
                await repository.add(entity)
            else:
                if entity.binding_status == BINDING_CLOSED:
                    raise ValidationFailed("Session 绑定已关闭")
                if entity.project_id != project_id:
                    # 项目切换只允许发生在恢复流程中：先置 RECOVERING，再重新绑定。
                    if entity.binding_status != BINDING_RECOVERING:
                        raise ValidationFailed("同一 Session 不允许切换项目")
                    entity.project_id = project_id
                self._transition(entity, BINDING_CONNECTED)
                entity.editor_instance_id = instance_id
                entity.godot_version = godot_version or entity.godot_version
                entity.plugin_version = plugin_version or entity.plugin_version
                entity.transport = transport
                entity.connected_at = now
                entity.disconnected_at = None
                entity.last_seen_at = now
            view = _view(entity)

        log_event(
            self._logger,
            logging.INFO,
            "bridge_session_bound",
            component="bridge",
        )
        return view

    async def mark_disconnected(self, session_id: str) -> EditorSessionView | None:
        return await self._set_binding(session_id, BINDING_DISCONNECTED)

    async def mark_recovering(self, session_id: str) -> EditorSessionView | None:
        return await self._set_binding(session_id, BINDING_RECOVERING)

    async def mark_connected(self, session_id: str) -> EditorSessionView | None:
        return await self._set_binding(session_id, BINDING_CONNECTED)

    async def mark_closed(self, session_id: str) -> EditorSessionView | None:
        return await self._set_binding(session_id, BINDING_CLOSED)

    async def touch(self, session_id: str) -> EditorSessionView | None:
        """心跳成功时刷新 ``last_seen_at``；仅对 CONNECTED 绑定生效。"""

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await EditorSessionRepository(session).get(session_id)
            if entity is None or entity.binding_status != BINDING_CONNECTED:
                return _view(entity) if entity is not None else None
            entity.last_seen_at = now
            return _view(entity)

    async def get(self, session_id: str) -> EditorSessionView | None:
        async with self._database.session() as session:
            entity = await EditorSessionRepository(session).get(session_id)
        return _view(entity) if entity is not None else None

    async def list_by_project(self, project_id: str) -> list[EditorSessionView]:
        async with self._database.session() as session:
            entities = await EditorSessionRepository(session).list_by_project(project_id)
        return [_view(entity) for entity in entities]

    async def list_active(self, project_id: str | None = None) -> list[EditorSessionView]:
        """列出 CONNECTED / RECOVERING 绑定，供 ``/bridge/sessions`` 使用。"""

        async with self._database.session() as session:
            entities = await EditorSessionRepository(session).list_by_statuses(
                [BINDING_CONNECTED, BINDING_RECOVERING]
            )
        views = [_view(entity) for entity in entities]
        if project_id is None:
            return views
        return [view for view in views if view.project_id == project_id]

    async def count_connected(self) -> int:
        async with self._database.session() as session:
            return await EditorSessionRepository(session).count_by_status(BINDING_CONNECTED)

    async def unique_connected_session(self, project_id: str) -> str | None:
        """项目内恰好一个 CONNECTED Editor 时返回其 Session，否则视为不唯一。"""

        connected = [
            view
            for view in await self.list_active(project_id)
            if view.binding_status == BINDING_CONNECTED
        ]
        if len(connected) != 1:
            return None
        return connected[0].session_id

    async def _set_binding(self, session_id: str, target: str) -> EditorSessionView | None:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await EditorSessionRepository(session).get(session_id)
            if entity is None:
                return None
            self._transition(entity, target)
            if target == BINDING_DISCONNECTED:
                entity.disconnected_at = now
            elif target == BINDING_CONNECTED:
                entity.disconnected_at = None
                entity.last_seen_at = now
            elif target == BINDING_CLOSED:
                entity.closed_at = now
            return _view(entity)

    def _transition(self, entity: EditorSessionModel, target: str) -> None:
        if target == entity.binding_status:
            return
        if target not in BINDING_TRANSITIONS.get(entity.binding_status, frozenset()):
            raise ValidationFailed(
                f"非法绑定状态迁移: {entity.binding_status} → {target}",
                details={"session_id": entity.session_id},
            )
        entity.binding_status = target


def format_binding(view: EditorSessionView) -> dict[str, str | None]:
    return {
        "session_id": view.session_id,
        "editor_instance_id": view.editor_instance_id,
        "project_id": view.project_id,
        "godot_version": view.godot_version or "",
        "plugin_version": view.plugin_version or "",
        "transport": view.transport,
        "binding_status": view.binding_status,
        "connected_at": isoformat(view.connected_at),
        "disconnected_at": isoformat(view.disconnected_at) if view.disconnected_at else None,
        "last_seen_at": isoformat(view.last_seen_at) if view.last_seen_at else None,
        "closed_at": isoformat(view.closed_at) if view.closed_at else None,
    }
