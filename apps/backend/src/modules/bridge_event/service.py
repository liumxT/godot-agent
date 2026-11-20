"""Bridge 事件发布、确认、补齐与保留策略（E3-T10）。

契约约束（见设计 §5.9）：

- ``sequence`` 按 ``(session_id, direction)`` 单调递增，由 Backend 分配；
- 只持久化 ``PERSISTENT``，``EPHEMERAL`` 仅确认不落库；
- ``bridge.events.since`` 上限 500 条/次，请求位置已被清理时返回
  ``snapshot_required=true``；
- 保留 ``bridge_event_retention_days`` 天，启动时与定期清理。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.errors import ValidationFailed
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.bridge_event.models import (
    DIRECTION_BACKEND_TO_PLUGIN,
    DIRECTION_PLUGIN_TO_BACKEND,
    PERSISTENCE_EPHEMERAL,
    PERSISTENCE_PERSISTENT,
    BridgeEventModel,
)
from modules.bridge_event.repository import BridgeEventRepository

PROTOCOL_VERSION = "1.0"
EVENT_VERSION = 1
MAX_PUBLISH_EVENTS = 100
MAX_SINCE_LIMIT = 500
DEFAULT_SINCE_LIMIT = 200

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_PROTOCOL_PATTERN = re.compile(r"^1\.[0-9]+$")

_REQUIRED_EVENT_FIELDS = (
    "protocol_version",
    "event_id",
    "event_type",
    "timestamp",
    "source",
    "payload",
)


@dataclass(frozen=True)
class PublishResult:
    accepted: list[str]
    latest_sequence: int
    persisted: int


@dataclass(frozen=True)
class SinceResult:
    events: list[dict]
    latest_sequence: int
    snapshot_required: bool


class BridgeEventService:
    """事件流读写；所有写入走事务。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        retention_days: int = 7,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._retention_days = retention_days
        self._clock = clock

    async def publish(
        self,
        *,
        session_id: str,
        project_id: str,
        events: Iterable[dict],
    ) -> PublishResult:
        """接收插件上行事件；重复 ``event_id`` 幂等确认，不重复分配 sequence。"""

        items = list(events)
        if len(items) > MAX_PUBLISH_EVENTS:
            raise ValidationFailed(
                f"单次最多发布 {MAX_PUBLISH_EVENTS} 条事件",
                details={"count": len(items)},
            )
        now = self._clock()
        accepted: list[str] = []
        persisted = 0
        latest = 0

        async with self._database.session() as session, transaction(session):
            repository = BridgeEventRepository(session)
            direction = DIRECTION_PLUGIN_TO_BACKEND
            sequence = await repository.max_sequence(session_id, direction)
            for raw in items:
                event = _validate_event(raw, session_id=session_id, project_id=project_id)
                event_id = event["event_id"]
                existing = await repository.get(event_id)
                if existing is not None:
                    if existing.session_id != session_id:
                        raise ValidationFailed(
                            "event_id 已被其他 Session 使用",
                            details={"event_id": event_id},
                        )
                    accepted.append(event_id)
                    latest = max(latest, existing.sequence)
                    continue
                persistence = _persistence(event)
                if persistence == PERSISTENCE_EPHEMERAL:
                    accepted.append(event_id)
                    continue
                sequence += 1
                payload = dict(event["payload"])
                payload["sequence"] = sequence
                payload["event_version"] = EVENT_VERSION
                await repository.add(
                    BridgeEventModel(
                        event_id=event_id,
                        session_id=session_id,
                        project_id=project_id,
                        direction=direction,
                        event_type=event["event_type"],
                        sequence=sequence,
                        occurred_at=_parse_timestamp(event["timestamp"]),
                        payload=payload,
                        created_at=now,
                        acked_at=None,
                    )
                )
                accepted.append(event_id)
                persisted += 1
            latest = max(latest, sequence)

        return PublishResult(accepted=accepted, latest_sequence=latest, persisted=persisted)

    async def ack(
        self,
        *,
        session_id: str,
        event_ids: Iterable[str] = (),
        last_sequence: int | None = None,
        direction: str = DIRECTION_BACKEND_TO_PLUGIN,
    ) -> int:
        ids = [str(value) for value in event_ids if str(value)]
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            return await BridgeEventRepository(session).mark_acked(
                session_id, direction, ids, last_sequence, now
            )

    async def since(
        self,
        *,
        session_id: str,
        after_sequence: int = 0,
        limit: int = DEFAULT_SINCE_LIMIT,
        direction: str = DIRECTION_BACKEND_TO_PLUGIN,
    ) -> SinceResult:
        if after_sequence < 0:
            raise ValidationFailed("after_sequence 不能为负数")
        resolved_limit = min(max(int(limit), 1), MAX_SINCE_LIMIT)
        async with self._database.session() as session:
            repository = BridgeEventRepository(session)
            latest = await repository.max_sequence(session_id, direction)
            minimum = await repository.min_sequence(session_id, direction)
            rows = await repository.list_since(
                session_id, direction, after_sequence, resolved_limit
            )
        events = [_format_event(row) for row in rows]
        snapshot_required = minimum is not None and after_sequence < minimum - 1
        return SinceResult(
            events=events,
            latest_sequence=latest,
            snapshot_required=snapshot_required,
        )

    async def count_unacked(
        self,
        *,
        session_id: str | None = None,
        direction: str = DIRECTION_BACKEND_TO_PLUGIN,
    ) -> int:
        """统计尚未确认的事件数；用于 ``/bridge/status`` 与诊断摘要。"""

        async with self._database.session() as session:
            return await BridgeEventRepository(session).count_unacked(session_id, direction)

    async def prune(self, *, retention_days: int | None = None) -> int:
        days = self._retention_days if retention_days is None else retention_days
        cutoff = self._clock() - timedelta(days=days)
        async with self._database.session() as session, transaction(session):
            return await BridgeEventRepository(session).delete_before(cutoff)


def _validate_event(raw: dict, *, session_id: str, project_id: str) -> dict:
    if not isinstance(raw, dict):
        raise ValidationFailed("事件必须是对象")
    for field in _REQUIRED_EVENT_FIELDS:
        if field not in raw:
            raise ValidationFailed(f"事件缺少字段: {field}")
    protocol_version = raw["protocol_version"]
    if not isinstance(protocol_version, str) or not _PROTOCOL_PATTERN.match(protocol_version):
        raise ValidationFailed("protocol_version 必须匹配 1.x")
    event_id = raw["event_id"]
    if not isinstance(event_id, str) or not _ID_PATTERN.match(event_id):
        raise ValidationFailed("event_id 格式非法")
    event_type = raw["event_type"]
    if not isinstance(event_type, str) or not _EVENT_TYPE_PATTERN.match(event_type):
        raise ValidationFailed("event_type 格式非法")
    if raw["source"] != "plugin":
        raise ValidationFailed("插件上行事件 source 必须为 plugin")
    if not isinstance(raw["payload"], dict):
        raise ValidationFailed("事件 payload 必须是对象")
    if raw.get("session_id") not in (None, session_id):
        raise ValidationFailed("事件 session_id 与当前连接不一致")
    if raw.get("project_id") not in (None, project_id):
        raise ValidationFailed("事件 project_id 与当前连接不一致")
    _parse_timestamp(raw["timestamp"])
    return raw


def _persistence(event: dict) -> str:
    value = event["payload"].get("persistence", PERSISTENCE_PERSISTENT)
    if value not in (PERSISTENCE_PERSISTENT, PERSISTENCE_EPHEMERAL):
        raise ValidationFailed("payload.persistence 必须是 PERSISTENT 或 EPHEMERAL")
    return str(value)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValidationFailed("事件 timestamp 必须为字符串")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationFailed("事件 timestamp 必须是 ISO-8601") from exc
    return ensure_utc(parsed)


def _format_event(entity: BridgeEventModel) -> dict:
    source = "plugin" if entity.direction == DIRECTION_PLUGIN_TO_BACKEND else "backend"
    return {
        "protocol_version": PROTOCOL_VERSION,
        "event_id": entity.event_id,
        "event_type": entity.event_type,
        "timestamp": isoformat(entity.occurred_at),
        "source": source,
        "session_id": entity.session_id,
        "project_id": entity.project_id,
        "payload": entity.payload,
    }
