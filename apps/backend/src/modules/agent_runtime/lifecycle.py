"""Agent Instance 生命周期（E6-T04）。

状态机严格按 ``INSTANCE_TRANSITIONS`` 执行：
``UNKNOWN`` 不能直接回到 ``RUNNING``，必须先通过恢复检查（恢复服务在 M4 提供）。

所有状态迁移使用 ``version`` 条件更新，避免并发 worker 双重迁移；
每次迁移写入只追加事件。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from core.errors import (
    AgentRecoveryRequired,
    AgentStateInvalid,
    VersionConflict,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.instance import AgentInstanceService, InstanceView, instance_view
from modules.agent_runtime.models import (
    EVENT_CANCEL_REQUESTED,
    EVENT_EXECUTION_COMPLETED,
    EVENT_EXECUTION_FAILED,
    EVENT_EXECUTION_STARTED,
    EVENT_EXECUTION_UNKNOWN,
    EVENT_INSTANCE_INITIALIZED,
    EVENT_PAUSE_REQUESTED,
    EVENT_PAUSED,
    EVENT_RESUME_REQUESTED,
    EVENT_RESUMED,
    EVENT_STOPPED,
    INSTANCE_COMPLETED,
    INSTANCE_CREATED,
    INSTANCE_FAILED,
    INSTANCE_INITIALIZING,
    INSTANCE_PAUSED,
    INSTANCE_PAUSING,
    INSTANCE_READY,
    INSTANCE_RESUMING,
    INSTANCE_RUNNING,
    INSTANCE_STOPPED,
    INSTANCE_STOPPING,
    INSTANCE_TERMINAL_STATUSES,
    INSTANCE_TRANSITIONS,
    INSTANCE_UNKNOWN,
    AgentInstanceModel,
)
from modules.agent_runtime.repository import AgentInstanceRepository
from modules.agent_runtime.service import DefinitionRegistryService
from modules.prompt.service import PromptService
from modules.tool.registry import ToolRegistryService

_TRANSITION_EVENTS = {
    INSTANCE_INITIALIZING: None,
    INSTANCE_READY: EVENT_INSTANCE_INITIALIZED,
    INSTANCE_RUNNING: EVENT_EXECUTION_STARTED,
    INSTANCE_PAUSING: EVENT_PAUSE_REQUESTED,
    INSTANCE_PAUSED: EVENT_PAUSED,
    INSTANCE_RESUMING: EVENT_RESUME_REQUESTED,
    INSTANCE_STOPPING: EVENT_CANCEL_REQUESTED,
    INSTANCE_STOPPED: EVENT_STOPPED,
    INSTANCE_COMPLETED: EVENT_EXECUTION_COMPLETED,
    INSTANCE_FAILED: EVENT_EXECUTION_FAILED,
    INSTANCE_UNKNOWN: EVENT_EXECUTION_UNKNOWN,
}


class AgentLifecycleService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        instances: AgentInstanceService,
        events: AgentEventService,
        definitions: DefinitionRegistryService,
        prompts: PromptService,
        tools: ToolRegistryService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._instances = instances
        self._events = events
        self._definitions = definitions
        self._prompts = prompts
        self._tools = tools
        self._clock = clock

    # ---- 对外操作 ----

    async def initialize(self, instance_id: str) -> InstanceView:
        """CREATED → INITIALIZING → READY；冻结引用不可用时进入 FAILED。"""

        current = await self._instances.get(instance_id)
        if current.status == INSTANCE_READY:
            return current
        if current.status not in {INSTANCE_CREATED, INSTANCE_INITIALIZING}:
            raise AgentStateInvalid(
                "当前状态不允许初始化",
                details={"instance_id": instance_id, "status": current.status},
            )

        snapshot = await self._instances.get_snapshot(instance_id)
        try:
            await self._validate_snapshot(snapshot)
        except Exception:
            await self._transition(instance_id, INSTANCE_FAILED, reason="INITIALIZATION_FAILED")
            raise

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentInstanceRepository(session)
            entity = await repository.get(instance_id)
            if entity is None:
                raise AgentStateInvalid(
                    "Agent Instance 不存在", details={"instance_id": instance_id}
                )
            if entity.status == INSTANCE_CREATED:
                await self._apply(session, entity, INSTANCE_INITIALIZING, now)
            await self._apply(session, entity, INSTANCE_READY, now)
            await session.flush()
            return instance_view(entity)

    async def start(self, instance_id: str) -> InstanceView:
        return await self._transition(instance_id, INSTANCE_RUNNING, event=EVENT_EXECUTION_STARTED)

    async def pause(self, instance_id: str) -> InstanceView:
        current = await self._instances.get(instance_id)
        if current.status == INSTANCE_PAUSED:
            return current
        if current.status not in {
            INSTANCE_RUNNING,
            "WAITING_TOOL",
            "WAITING_APPROVAL",
            "WAITING_INPUT",
        }:
            raise AgentStateInvalid(
                "当前状态不允许暂停",
                details={"instance_id": instance_id, "status": current.status},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await self._load(session, instance_id)
            await self._apply(session, entity, INSTANCE_PAUSING, now)
            await self._apply(session, entity, INSTANCE_PAUSED, now)
            await session.flush()
            return instance_view(entity)

    async def resume(self, instance_id: str) -> InstanceView:
        current = await self._instances.get(instance_id)
        if current.status == INSTANCE_RUNNING:
            return current
        if current.status == INSTANCE_UNKNOWN:
            raise AgentRecoveryRequired(
                "实例处于 UNKNOWN，必须先完成恢复检查",
                details={"instance_id": instance_id},
            )
        if current.status != INSTANCE_PAUSED:
            raise AgentStateInvalid(
                "只有 PAUSED 状态可以恢复",
                details={"instance_id": instance_id, "status": current.status},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await self._load(session, instance_id)
            await self._apply(session, entity, INSTANCE_RESUMING, now)
            await self._apply(session, entity, INSTANCE_RUNNING, now, event=EVENT_RESUMED)
            await session.flush()
            return instance_view(entity)

    async def stop(self, instance_id: str, *, reason: str | None = None) -> InstanceView:
        current = await self._instances.get(instance_id)
        if current.status in INSTANCE_TERMINAL_STATUSES:
            return current
        if current.status == INSTANCE_CREATED:
            return await self._transition(instance_id, INSTANCE_STOPPED, reason=reason)
        if current.status == INSTANCE_STOPPING:
            return await self._transition(instance_id, INSTANCE_STOPPED, reason=reason)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await self._load(session, instance_id)
            await self._apply(session, entity, INSTANCE_STOPPING, now, reason=reason)
            await self._apply(session, entity, INSTANCE_STOPPED, now, reason=reason)
            await session.flush()
            return instance_view(entity)

    async def cancel(self, instance_id: str, *, reason: str = "CANCELLED") -> InstanceView:
        return await self.stop(instance_id, reason=reason)

    async def complete(self, instance_id: str, *, reason: str | None = None) -> InstanceView:
        return await self._transition(
            instance_id, INSTANCE_COMPLETED, reason=reason, event=EVENT_EXECUTION_COMPLETED
        )

    async def fail(self, instance_id: str, *, reason: str | None = None) -> InstanceView:
        return await self._transition(
            instance_id, INSTANCE_FAILED, reason=reason, event=EVENT_EXECUTION_FAILED
        )

    async def mark_unknown(self, instance_id: str, *, reason: str | None = None) -> InstanceView:
        return await self._transition(
            instance_id, INSTANCE_UNKNOWN, reason=reason, event=EVENT_EXECUTION_UNKNOWN
        )

    async def transition(
        self, instance_id: str, target: str, *, reason: str | None = None
    ) -> InstanceView:
        return await self._transition(instance_id, target, reason=reason)

    # ---- 内部 ----

    async def _transition(
        self,
        instance_id: str,
        target: str,
        *,
        reason: str | None = None,
        event: str | None = None,
    ) -> InstanceView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await self._load(session, instance_id)
            await self._apply(session, entity, target, now, reason=reason, event=event)
            await session.flush()
            return instance_view(entity)

    async def _load(self, session, instance_id: str) -> AgentInstanceModel:
        entity = await AgentInstanceRepository(session).get(instance_id)
        if entity is None:
            from core.errors import NotFoundError

            raise NotFoundError("Agent Instance 不存在", details={"instance_id": instance_id})
        return entity

    async def _apply(
        self,
        session,
        entity: AgentInstanceModel,
        target: str,
        now: datetime,
        *,
        reason: str | None = None,
        event: str | None = None,
    ) -> None:
        if target == entity.status:
            return
        allowed = INSTANCE_TRANSITIONS.get(entity.status, frozenset())
        if target not in allowed:
            raise AgentStateInvalid(
                "非法的 Agent Instance 状态迁移",
                details={
                    "instance_id": entity.instance_id,
                    "from_status": entity.status,
                    "to_status": target,
                },
            )
        started_at = now if target == INSTANCE_RUNNING and entity.started_at is None else None
        completed_at = now if target in INSTANCE_TERMINAL_STATUSES else None
        previous_status = entity.status
        rowcount = await AgentInstanceRepository(session).compare_and_set_status(
            entity.instance_id,
            expected_version=entity.version,
            from_status=entity.status,
            to_status=target,
            now=now,
            started_at=started_at,
            completed_at=completed_at,
            termination_reason=reason,
        )
        if rowcount == 0:
            raise VersionConflict(
                "Agent Instance 状态已被并发修改",
                details={"instance_id": entity.instance_id, "expected_version": entity.version},
            )
        entity.status = target
        entity.version += 1
        entity.updated_at = now
        if started_at is not None:
            entity.started_at = started_at
        if completed_at is not None:
            entity.completed_at = completed_at
        if reason is not None:
            entity.termination_reason = reason

        resolved_event = event if event is not None else _TRANSITION_EVENTS.get(target)
        if resolved_event:
            await self._events.append_in_session(
                session,
                instance_id=entity.instance_id,
                event_type=resolved_event,
                payload={
                    "from_status": previous_status,
                    "to_status": target,
                    "reason": reason,
                },
                now=now,
            )

    async def _validate_snapshot(self, snapshot) -> None:
        """校验冻结引用当前仍然可用；不可用时失败关闭。"""

        self._definitions.model_policy(snapshot.model_policy_id)
        await self._prompts.get_version(snapshot.prompt_profile_id, snapshot.prompt_version)
        for tool_id in snapshot.tool_whitelist:
            tool = await self._tools.get(tool_id)
            if not tool.enabled:
                raise AgentStateInvalid(
                    "冻结的工具已停用",
                    details={"tool_id": tool_id, "instance_snapshot": snapshot.snapshot_id},
                )
