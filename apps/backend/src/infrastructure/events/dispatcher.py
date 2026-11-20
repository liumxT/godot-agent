"""事件派发器（E1-T10）。

- 轮询 Outbox 并派发给进程内订阅者（E1-Q5：100 ms，可配置）；
- 投递前检查 Inbox，已处理则跳过（至少一次 + 幂等）；
- 失败写 ``failed``、``retry_count``、``last_error``，有界退避重试；
- 进程启动时把残留 ``publishing`` 复位为 ``pending``，实现中断恢复（E1-FI-006/007）。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass

from core.errors import ShutdownTimeout
from core.events.model import Event, invoke_handler
from core.events.registry import EventRegistry
from core.logging import get_logger, log_event
from infrastructure.database.errors import summarize_error
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.events.inbox import InboxRepository
from infrastructure.events.outbox import OutboxRepository

_ERROR_LIMIT = 500
_MAX_BACKOFF_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class DispatchReport:
    claimed: int = 0
    published: int = 0
    failed: int = 0
    skipped: int = 0


class EventDispatcher:
    def __init__(
        self,
        database: DatabaseService,
        registry: EventRegistry,
        *,
        poll_interval: float = 0.1,
        batch_size: int = 50,
        max_retries: int = 5,
        stop_timeout: float = 5.0,
    ) -> None:
        self._database = database
        self._registry = registry
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._stop_timeout = stop_timeout
        self._outbox = OutboxRepository()
        self._inbox = InboxRepository()
        self._logger = get_logger("backend.events")
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task is not None:
            return

        # 中断恢复：上次进程遗留的 publishing 行重新进入待派发
        async with self._database.session() as session, transaction(session):
            await self._outbox.reset_publishing(session)

        if self._database.is_ephemeral:
            # 内存库无法安全承载后台并发连接，测试请直接调用 dispatch_once()
            log_event(
                self._logger,
                logging.INFO,
                "event_dispatcher_embedded",
                component="events",
            )
            return

        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="event-dispatcher")
        log_event(self._logger, logging.INFO, "event_dispatcher_started", component="events")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return

        self._stopping.set()
        try:
            await asyncio.wait_for(task, timeout=self._stop_timeout)
        except TimeoutError as exc:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise ShutdownTimeout(
                "事件派发停止超时", details={"timeout": self._stop_timeout}
            ) from exc
        log_event(self._logger, logging.INFO, "event_dispatcher_stopped", component="events")

    async def dispatch_once(self) -> DispatchReport:
        """执行一轮派发；供测试与后台循环共用。"""

        messages = await self._claim()
        published = failed = skipped = 0

        for message in messages:
            try:
                event = message.to_event()
            except Exception as exc:  # noqa: BLE001 - 单条坏数据必须标记失败，不能中断整批派发
                await self._mark_failed(message.id, summarize_error(exc))
                failed += 1
                continue

            errors, skipped_handlers = await self._deliver(event)
            skipped += skipped_handlers
            if errors:
                await self._mark_failed(message.id, "; ".join(errors)[:_ERROR_LIMIT])
                failed += 1
                log_event(
                    self._logger,
                    logging.ERROR,
                    "event_dispatch_failed",
                    component="events",
                    correlation_id=event.correlation_id,
                    error_code="EVENT_DISPATCH_FAILED",
                )
            else:
                await self._mark_published(message.id)
                published += 1

        return DispatchReport(
            claimed=len(messages),
            published=published,
            failed=failed,
            skipped=skipped,
        )

    async def _run(self) -> None:
        while not self._stopping.is_set():
            report: DispatchReport | None = None
            try:
                report = await self.dispatch_once()
            except Exception as exc:  # noqa: BLE001 - 后台循环不得因单轮异常退出
                log_event(
                    self._logger,
                    logging.ERROR,
                    "event_dispatch_cycle_failed",
                    component="events",
                    error_code="EVENT_DISPATCH_FAILED",
                )
                self._logger.debug("event_dispatch_cycle_failed: %s", exc)
            delay = self._poll_interval
            if report is not None and report.failed:
                delay = min(
                    self._poll_interval * (2 ** min(report.failed, 5)),
                    _MAX_BACKOFF_SECONDS,
                )
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except TimeoutError:
                continue

    async def _claim(self):
        async with self._database.session() as session, transaction(session):
            messages = await self._outbox.fetch_dispatchable(
                session,
                limit=self._batch_size,
                max_retries=self._max_retries,
            )
            for message in messages:
                await self._outbox.mark_publishing(session, message.id)
        return messages

    async def _deliver(self, event: Event) -> tuple[list[str], int]:
        errors: list[str] = []
        skipped = 0

        for subscription in self._registry.handlers_for(event.event_type):
            if await self._is_processed(event.event_id, subscription.consumer_id):
                skipped += 1
                continue
            try:
                await invoke_handler(subscription.handler, event)
            except Exception as exc:  # noqa: BLE001 - 单处理器失败需记录进 Inbox 后继续投递
                reason = summarize_error(exc)
                await self._record_inbox(event.event_id, subscription.consumer_id, reason)
                errors.append(f"{subscription.consumer_id}: {reason}")
            else:
                await self._record_inbox(event.event_id, subscription.consumer_id, None)
        return errors, skipped

    async def _is_processed(self, event_id: str, consumer_id: str) -> bool:
        async with self._database.session() as session:
            return await self._inbox.is_processed(session, event_id, consumer_id)

    async def _record_inbox(self, event_id: str, consumer_id: str, error: str | None) -> None:
        async with self._database.session() as session, transaction(session):
            if error is None:
                await self._inbox.mark_processed(session, event_id, consumer_id)
            else:
                await self._inbox.mark_failed(session, event_id, consumer_id, error)

    async def _mark_published(self, message_id: int) -> None:
        async with self._database.session() as session, transaction(session):
            await self._outbox.mark_published(session, message_id)

    async def _mark_failed(self, message_id: int, error: str) -> None:
        async with self._database.session() as session, transaction(session):
            await self._outbox.mark_failed(session, message_id, error)
