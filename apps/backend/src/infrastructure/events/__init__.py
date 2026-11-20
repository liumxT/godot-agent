"""事件持久化基础设施（E1-T10）。"""

from infrastructure.events.dispatcher import DispatchReport, EventDispatcher
from infrastructure.events.inbox import InboxRepository
from infrastructure.events.outbox import OutboxMessage, OutboxRepository

__all__ = [
    "DispatchReport",
    "EventDispatcher",
    "InboxRepository",
    "OutboxMessage",
    "OutboxRepository",
]
