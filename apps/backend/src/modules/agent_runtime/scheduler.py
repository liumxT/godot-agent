"""Agent Scheduler（E6-T05 基础版）。

只负责“选择可运行实例并认领”，不实现操作系统线程或独立事件循环。
实际执行循环在 M3 的 Agent Loop 中消费 ``claim_next``。

并发安全依赖 ``LifecycleService`` 的版本条件更新：多个 worker 同时认领同一实例时，
只有一个能完成 ``READY → RUNNING``，其余收到状态冲突并跳过。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from core.errors import AgentStateInvalid, VersionConflict
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.agent_runtime.instance import InstanceView
from modules.agent_runtime.lifecycle import AgentLifecycleService
from modules.agent_runtime.models import INSTANCE_READY
from modules.agent_runtime.repository import AgentInstanceRepository


class AgentScheduler:
    def __init__(
        self,
        database: DatabaseService,
        *,
        lifecycle: AgentLifecycleService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._lifecycle = lifecycle
        self._clock = clock

    async def claim(self, instance_id: str) -> InstanceView:
        return await self._lifecycle.start(instance_id)

    async def claim_next(self, *, limit: int = 20) -> InstanceView | None:
        async with self._database.session() as session:
            page = await AgentInstanceRepository(session).list_page(
                status=INSTANCE_READY, limit=limit, offset=0
            )
        for candidate in page.items:
            try:
                return await self._lifecycle.start(candidate.instance_id)
            except AgentStateInvalid, VersionConflict:
                continue
        return None
