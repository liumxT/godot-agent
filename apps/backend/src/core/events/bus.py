"""进程内事件发布（E1-T09）。

- 只负责「事件 → 已注册处理器」的同步分发，不做持久化与去重；
- 持久化投递走 Outbox + Inbox（T10）；
- 单个处理器失败不影响同事件的其他订阅者，失败结果显式返回并记录日志。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.events.model import Event, invoke_handler
from core.events.registry import EventRegistry
from core.logging import get_logger, log_event

_REASON_LIMIT = 300


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    event_type: str
    consumer_id: str
    status: str
    error: str | None = None


class EventBus:
    """基于注册表的进程内发布器。"""

    def __init__(self, registry: EventRegistry) -> None:
        self._registry = registry
        self._logger = get_logger("backend.events")

    async def publish(self, event: Event) -> tuple[DeliveryResult, ...]:
        results: list[DeliveryResult] = []
        for subscription in self._registry.handlers_for(event.event_type):
            try:
                await invoke_handler(subscription.handler, event)
            except Exception as exc:  # noqa: BLE001 - 单订阅者失败必须隔离，不能影响其他消费者
                reason = _summarize(exc)
                results.append(
                    DeliveryResult(
                        event_type=event.event_type,
                        consumer_id=subscription.consumer_id,
                        status="failed",
                        error=reason,
                    )
                )
                log_event(
                    self._logger,
                    logging.ERROR,
                    "event_handler_failed",
                    component="events",
                    correlation_id=event.correlation_id,
                    error_code="EVENT_HANDLER_FAILED",
                )
            else:
                results.append(
                    DeliveryResult(
                        event_type=event.event_type,
                        consumer_id=subscription.consumer_id,
                        status="delivered",
                    )
                )
        return tuple(results)


def _summarize(exc: BaseException) -> str:
    message = " ".join(f"{type(exc).__name__}: {exc}".split())
    return message if len(message) <= _REASON_LIMIT else message[: _REASON_LIMIT - 3] + "..."
