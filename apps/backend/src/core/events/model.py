"""事件模型（E1-T09）。

字段对齐 ``packages/contracts/events/event.schema.json``：

- 契约字段：``protocol_version / event_id / event_type / timestamp / source /
  session_id / project_id / correlation_id / payload``；
- 内部字段：``event_version`` 用于版本化消费，``producer`` 映射为契约 ``source``。

事件不得替代业务状态所有权；本模型只负责结构校验与序列化。
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.errors import ValidationFailed

EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
PROTOCOL_VERSION = "1.0"
PRODUCERS = frozenset({"backend", "plugin"})

EventHandler = Callable[["Event"], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class Event:
    """不可变事件对象。"""

    event_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_version: int = 1
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    producer: str = "backend"
    correlation_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not EVENT_ID_PATTERN.match(self.event_id):
            raise ValidationFailed("event_id 格式非法", details={"event_id": self.event_id})
        if not EVENT_TYPE_PATTERN.match(self.event_type):
            raise ValidationFailed(
                "event_type 必须为小写点分命名", details={"event_type": self.event_type}
            )
        if self.event_version < 1:
            raise ValidationFailed(
                "event_version 必须大于等于 1", details={"event_version": self.event_version}
            )
        if self.producer not in PRODUCERS:
            raise ValidationFailed(
                "producer 必须是 backend 或 plugin", details={"producer": self.producer}
            )
        if self.occurred_at.tzinfo is None:
            raise ValidationFailed("occurred_at 必须包含时区")
        if not isinstance(self.payload, dict):
            raise ValidationFailed("payload 必须是 JSON 对象")

    @classmethod
    def create(
        cls,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        event_version: int = 1,
        producer: str = "backend",
        correlation_id: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> Event:
        return cls(
            event_id=event_id or uuid4().hex,
            event_type=event_type,
            payload=payload or {},
            event_version=event_version,
            occurred_at=occurred_at or datetime.now(UTC),
            producer=producer,
            correlation_id=correlation_id,
            session_id=session_id,
            project_id=project_id,
        )

    @classmethod
    def from_storage(
        cls,
        *,
        event_id: str,
        event_type: str,
        event_version: int,
        payload: str,
        correlation_id: str | None,
        occurred_at: datetime | str,
    ) -> Event:
        """从 Outbox 行还原事件；payload 非法时抛 ``ValidationFailed``。"""

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValidationFailed("事件 payload 不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise ValidationFailed("事件 payload 必须是 JSON 对象")
        return cls(
            event_id=event_id,
            event_type=event_type,
            payload=data,
            event_version=event_version,
            occurred_at=_as_datetime(occurred_at),
            correlation_id=correlation_id,
        )

    @property
    def payload_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, sort_keys=True)

    def to_contract(self) -> dict[str, Any]:
        """转为契约 JSON；``event_version`` 不进入契约（schema 禁止额外字段）。"""

        data: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": _iso_z(self.occurred_at),
            "source": self.producer,
            "payload": self.payload,
        }
        for name in ("session_id", "project_id", "correlation_id"):
            value = getattr(self, name)
            if value:
                data[name] = value
        return data


async def invoke_handler(handler: EventHandler, event: Event) -> None:
    """调用处理器，兼容同步与异步函数。"""

    result = handler(event)
    if inspect.isawaitable(result):
        await result


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _as_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
