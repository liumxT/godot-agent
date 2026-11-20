"""事件订阅注册表（E1-T09）。

每个处理器绑定唯一 ``consumer_id``，用于 Inbox 幂等去重（T10）。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.errors import StartupError, ValidationFailed
from core.events.model import EVENT_TYPE_PATTERN, EventHandler


@dataclass(frozen=True, slots=True)
class Subscription:
    event_type: str
    consumer_id: str
    handler: EventHandler


class EventRegistry:
    """按 ``event_type`` 维护订阅；重复注册视为装配错误。"""

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[Subscription]] = {}

    def register(
        self,
        event_type: str,
        handler: EventHandler,
        *,
        consumer_id: str | None = None,
    ) -> Subscription:
        if not EVENT_TYPE_PATTERN.match(event_type):
            raise ValidationFailed(
                "event_type 必须为小写点分命名", details={"event_type": event_type}
            )
        resolved = consumer_id or f"{event_type}:{handler.__module__}.{handler.__qualname__}"
        subscriptions = self._subscriptions.setdefault(event_type, [])
        if any(subscription.consumer_id == resolved for subscription in subscriptions):
            raise StartupError(
                "事件处理器重复注册",
                details={"event_type": event_type, "consumer_id": resolved},
            )
        subscription = Subscription(event_type=event_type, consumer_id=resolved, handler=handler)
        subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        subscriptions = self._subscriptions.get(subscription.event_type)
        if not subscriptions or subscription not in subscriptions:
            return
        subscriptions.remove(subscription)
        if not subscriptions:
            self._subscriptions.pop(subscription.event_type, None)

    def handlers_for(self, event_type: str) -> tuple[Subscription, ...]:
        return tuple(self._subscriptions.get(event_type, ()))

    def event_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._subscriptions))

    def consumer_ids(self) -> dict[str, tuple[str, ...]]:
        return {
            event_type: tuple(subscription.consumer_id for subscription in subscriptions)
            for event_type, subscriptions in self._subscriptions.items()
        }

    def clear(self) -> None:
        self._subscriptions.clear()
