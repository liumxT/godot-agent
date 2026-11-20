"""Task / Attempt / Dependency / Checkpoint / Event Log（E4-T06…T11）。

Task 状态只能由本模块修改。Agent、Workflow、Verification 只能提交结果或
请求合法状态转换，不能直接写 ``tasks`` 表。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    DependencyCycle,
    InvalidStateTransition,
    NotFoundError,
    ValidationFailed,
)
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.events.outbox import OutboxRepository
from modules.task.models import (
    ACTOR_SYSTEM,
    ACTOR_TYPES,
    ACTOR_USER,
    ATTEMPT_CANCELLED,
    ATTEMPT_CREATED,
    ATTEMPT_FAILED,
    ATTEMPT_RUNNING,
    ATTEMPT_STARTING,
    ATTEMPT_SUCCEEDED,
    ATTEMPT_TRANSITIONS,
    CHECKPOINT_SAFE_PAUSE,
    CHECKPOINT_TYPES,
    DEPENDENCY_ACTIVE,
    DEPENDENCY_BLOCKS,
    DEPENDENCY_FINISH_TO_START,
    DEPENDENCY_RELATED,
    DEPENDENCY_REMOVED,
    DEPENDENCY_RESOLVED,
    DEPENDENCY_TYPES,
    PRIORITIES,
    PRIORITY_MEDIUM,
    TASK_BLOCKED,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_CREATED,
    TASK_FAILED,
    TASK_NEEDS_REVISION,
    TASK_PAUSED,
    TASK_PAUSING,
    TASK_QUEUED,
    TASK_READY,
    TASK_REJECTED,
    TASK_RESUMING,
    TASK_REVIEW_PENDING,
    TASK_RUNNING,
    TASK_TRANSITIONS,
    TASK_TYPE_GENERAL,
    TASK_TYPES,
    TASK_WAITING_APPROVAL,
    TASK_WAITING_USER,
    TERMINAL_TASK_STATUSES,
    TaskAttemptModel,
    TaskCheckpointModel,
    TaskDependencyModel,
    TaskEventModel,
    TaskModel,
)
from modules.task.repository import (
    TaskAttemptRepository,
    TaskCheckpointRepository,
    TaskDependencyRepository,
    TaskEventRepository,
    TaskRepository,
)

_ID_PREFIX = "tsk_"
_EVENT_TYPES = frozenset(
    {
        "TASK_CREATED",
        "TASK_READY",
        "TASK_QUEUED",
        "TASK_STARTED",
        "TASK_PAUSED",
        "TASK_RESUMED",
        "TASK_BLOCKED",
        "TASK_WAITING_APPROVAL",
        "TASK_WAITING_USER",
        "TASK_FAILED",
        "TASK_CANCELLED",
        "TASK_REVIEW_PENDING",
        "TASK_ACCEPTED",
        "TASK_REJECTED",
        "TASK_COMPLETED",
        "ATTEMPT_CREATED",
        "ATTEMPT_STARTED",
        "ATTEMPT_FAILED",
        "ATTEMPT_SUCCEEDED",
    }
)


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


@dataclass(frozen=True)
class TaskView:
    task_id: str
    project_id: str
    parent_task_id: str | None
    title: str
    description: str | None
    task_type: str
    priority: str
    status: str
    created_by: str | None
    assigned_to: str | None
    workflow_instance_id: str | None
    requirement_set_id: str | None
    current_attempt_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class AttemptView:
    attempt_id: str
    task_id: str
    attempt_number: int
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    agent_instance_id: str | None
    workflow_instance_id: str | None
    checkpoint_id: str | None
    execution_summary: str | None
    failure_code: str | None
    failure_reason: str | None
    resource_usage: str | None
    created_at: datetime


@dataclass(frozen=True)
class DependencyView:
    dependency_id: str
    source_task_id: str
    target_task_id: str
    dependency_type: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class CheckpointView:
    checkpoint_id: str
    task_id: str
    attempt_id: str | None
    checkpoint_type: str
    sequence: int
    workflow_state_ref: str | None
    context_ref: str | None
    changeset_ref: str | None
    checksum: str
    created_at: datetime


@dataclass(frozen=True)
class TaskEventView:
    event_id: str
    task_id: str
    attempt_id: str | None
    sequence: int
    event_type: str
    previous_status: str | None
    new_status: str | None
    actor_type: str
    actor_id: str | None
    payload: dict[str, Any]
    occurred_at: datetime


def _task_view(entity: TaskModel) -> TaskView:
    return TaskView(
        task_id=entity.task_id,
        project_id=entity.project_id,
        parent_task_id=entity.parent_task_id,
        title=entity.title,
        description=entity.description,
        task_type=entity.task_type,
        priority=entity.priority,
        status=entity.status,
        created_by=entity.created_by,
        assigned_to=entity.assigned_to,
        workflow_instance_id=entity.workflow_instance_id,
        requirement_set_id=entity.requirement_set_id,
        current_attempt_id=entity.current_attempt_id,
        version=entity.version,
        created_at=ensure_utc(entity.created_at),
        updated_at=ensure_utc(entity.updated_at),
        completed_at=ensure_utc(entity.completed_at) if entity.completed_at else None,
    )


def _attempt_view(entity: TaskAttemptModel) -> AttemptView:
    return AttemptView(
        attempt_id=entity.attempt_id,
        task_id=entity.task_id,
        attempt_number=entity.attempt_number,
        status=entity.status,
        started_at=ensure_utc(entity.started_at) if entity.started_at else None,
        ended_at=ensure_utc(entity.ended_at) if entity.ended_at else None,
        agent_instance_id=entity.agent_instance_id,
        workflow_instance_id=entity.workflow_instance_id,
        checkpoint_id=entity.checkpoint_id,
        execution_summary=entity.execution_summary,
        failure_code=entity.failure_code,
        failure_reason=entity.failure_reason,
        resource_usage=entity.resource_usage,
        created_at=ensure_utc(entity.created_at),
    )


def _dependency_view(entity: TaskDependencyModel) -> DependencyView:
    return DependencyView(
        dependency_id=entity.dependency_id,
        source_task_id=entity.source_task_id,
        target_task_id=entity.target_task_id,
        dependency_type=entity.dependency_type,
        status=entity.status,
        created_at=ensure_utc(entity.created_at),
    )


def _checkpoint_view(entity: TaskCheckpointModel) -> CheckpointView:
    return CheckpointView(
        checkpoint_id=entity.checkpoint_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        checkpoint_type=entity.checkpoint_type,
        sequence=entity.sequence,
        workflow_state_ref=entity.workflow_state_ref,
        context_ref=entity.context_ref,
        changeset_ref=entity.changeset_ref,
        checksum=entity.checksum,
        created_at=ensure_utc(entity.created_at),
    )


def checkpoint_checksum(
    *,
    attempt_id: str | None,
    workflow_state_ref: str | None,
    context_ref: str | None,
    changeset_ref: str | None,
) -> str:
    payload = json.dumps(
        {
            "attempt_id": attempt_id,
            "workflow_state_ref": workflow_state_ref,
            "context_ref": context_ref,
            "changeset_ref": changeset_ref,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaskEventWriter:
    """Task 事件追加；序号按 Task 单调递增，并与 Outbox 同事务写入。"""

    def __init__(self, *, emit_outbox: bool = True) -> None:
        self._emit_outbox = emit_outbox

    async def append(
        self,
        session,
        *,
        task: TaskModel,
        event_type: str,
        previous_status: str | None,
        new_status: str | None,
        actor_type: str,
        actor_id: str | None,
        attempt_id: str | None = None,
        payload: dict[str, Any] | None = None,
        now: datetime,
    ) -> TaskEventModel:
        if event_type not in _EVENT_TYPES:
            raise ValidationFailed("未登记的 Task 事件类型", details={"event_type": event_type})
        if actor_type not in ACTOR_TYPES:
            raise ValidationFailed("actor_type 非法", details={"actor_type": actor_type})
        repository = TaskEventRepository(session)
        entity = TaskEventModel(
            event_id=_new_id("tev_"),
            task_id=task.task_id,
            attempt_id=attempt_id,
            sequence=await repository.next_sequence(task.task_id),
            event_type=event_type,
            previous_status=previous_status,
            new_status=new_status,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            occurred_at=now,
        )
        await repository.add(entity)
        if self._emit_outbox:
            await OutboxRepository().add(
                session,
                Event.create(
                    f"task.{event_type.lower()}",
                    {
                        "task_id": task.task_id,
                        "previous_status": previous_status,
                        "new_status": new_status,
                        "actor_type": actor_type,
                    },
                    project_id=task.project_id,
                ),
            )
        return entity


class TaskService:
    """Task 生命周期与查询。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        events: TaskEventWriter | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._events = events or TaskEventWriter()
        self._clock = clock
        self._logger = get_logger("backend.task")

    async def create(
        self,
        *,
        project_id: str,
        title: str,
        description: str | None = None,
        task_type: str = TASK_TYPE_GENERAL,
        priority: str = PRIORITY_MEDIUM,
        parent_task_id: str | None = None,
        created_by: str | None = None,
        actor_type: str = ACTOR_USER,
        actor_id: str | None = None,
        ready: bool = True,
    ) -> TaskView:
        if task_type not in TASK_TYPES:
            raise ValidationFailed("task_type 非法", details={"task_type": task_type})
        if priority not in PRIORITIES:
            raise ValidationFailed("priority 非法", details={"priority": priority})
        if not (title or "").strip():
            raise ValidationFailed("任务标题不能为空")
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = TaskModel(
                task_id=_new_id(_ID_PREFIX),
                project_id=project_id,
                parent_task_id=parent_task_id,
                title=title.strip()[:256],
                description=description,
                task_type=task_type,
                priority=priority,
                status=TASK_CREATED,
                created_by=created_by,
                assigned_to=None,
                workflow_instance_id=None,
                requirement_set_id=None,
                current_attempt_id=None,
                version=1,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            await TaskRepository(session).add(entity)
            await self._events.append(
                session,
                task=entity,
                event_type="TASK_CREATED",
                previous_status=None,
                new_status=TASK_CREATED,
                actor_type=actor_type,
                actor_id=actor_id or created_by,
                now=now,
            )
            if ready:
                entity.status = TASK_READY
                entity.updated_at = now
                await self._events.append(
                    session,
                    task=entity,
                    event_type="TASK_READY",
                    previous_status=TASK_CREATED,
                    new_status=TASK_READY,
                    actor_type=actor_type,
                    actor_id=actor_id or created_by,
                    now=now,
                )
            await session.flush()
            view = _task_view(entity)
        log_event(self._logger, logging.INFO, "task_created", component="task")
        return view

    async def get(self, task_id: str) -> TaskView:
        async with self._database.session() as session:
            entity = await TaskRepository(session).get(task_id)
        if entity is None:
            raise NotFoundError("任务不存在", details={"task_id": task_id})
        return _task_view(entity)

    async def list(
        self, project_id: str, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await TaskRepository(session).list_page(
                project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_task_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def attach_workflow(self, task_id: str, workflow_instance_id: str) -> TaskView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await TaskRepository(session).get(task_id)
            if entity is None:
                raise NotFoundError("任务不存在", details={"task_id": task_id})
            entity.workflow_instance_id = workflow_instance_id
            entity.updated_at = now
            await session.flush()
            return _task_view(entity)

    async def transition(
        self,
        task_id: str,
        target: str,
        *,
        actor_type: str = ACTOR_USER,
        actor_id: str | None = None,
        reason: str | None = None,
        expected_version: int | None = None,
    ) -> TaskView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = TaskRepository(session)
            entity = await repository.get(task_id)
            if entity is None:
                raise NotFoundError("任务不存在", details={"task_id": task_id})
            if expected_version is not None and entity.version != expected_version:
                from core.errors import VersionConflict

                raise VersionConflict(
                    "任务版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            if target == TASK_RUNNING and await self._is_blocked(session, task_id):
                raise InvalidStateTransition(
                    "任务存在未满足依赖，不能进入 RUNNING",
                    details={"task_id": task_id},
                )
            previous = entity.status
            self._apply_transition(entity, target, now)
            await self._events.append(
                session,
                task=entity,
                event_type=_event_for_transition(target),
                previous_status=previous,
                new_status=target,
                actor_type=actor_type,
                actor_id=actor_id,
                payload={"reason": reason} if reason else None,
                now=now,
            )
            if target == TASK_COMPLETED:
                entity.completed_at = now
            entity.updated_at = now
            await session.flush()
            view = _task_view(entity)
        log_event(self._logger, logging.INFO, "task_status_changed", component="task")
        return view

    async def pause(
        self, task_id: str, *, actor_type: str = ACTOR_USER, actor_id: str | None = None
    ) -> TaskView:
        view = await self.transition(
            task_id, TASK_PAUSING, actor_type=actor_type, actor_id=actor_id
        )
        return await self.transition(
            view.task_id, TASK_PAUSED, actor_type=actor_type, actor_id=actor_id
        )

    async def resume(
        self, task_id: str, *, actor_type: str = ACTOR_USER, actor_id: str | None = None
    ) -> TaskView:
        view = await self.transition(
            task_id, TASK_RESUMING, actor_type=actor_type, actor_id=actor_id
        )
        return await self.transition(
            view.task_id, TASK_RUNNING, actor_type=actor_type, actor_id=actor_id
        )

    async def cancel(
        self, task_id: str, *, actor_type: str = ACTOR_USER, actor_id: str | None = None
    ) -> TaskView:
        return await self.transition(
            task_id, TASK_CANCELLED, actor_type=actor_type, actor_id=actor_id
        )

    async def accept(self, task_id: str, *, actor_id: str | None = None) -> TaskView:
        """用户验收；Agent/Workflow 无权调用。"""

        return await self.transition(
            task_id, TASK_COMPLETED, actor_type=ACTOR_USER, actor_id=actor_id
        )

    async def reject(
        self, task_id: str, *, actor_id: str | None = None, reason: str | None = None
    ) -> TaskView:
        return await self.transition(
            task_id,
            TASK_NEEDS_REVISION,
            actor_type=ACTOR_USER,
            actor_id=actor_id,
            reason=reason,
        )

    async def request_review(self, task_id: str, *, actor_id: str | None = None) -> TaskView:
        return await self.transition(
            task_id,
            TASK_REVIEW_PENDING,
            actor_type=ACTOR_SYSTEM,
            actor_id=actor_id,
        )

    async def mark_blocked(self, task_id: str, *, reason: str | None = None) -> TaskView:
        return await self.transition(task_id, TASK_BLOCKED, actor_type=ACTOR_SYSTEM, reason=reason)

    async def record_completion_to_ready(self, task_id: str) -> None:
        """依赖满足后由 DependencyService 触发的 BLOCKED → READY。"""

        async with self._database.session() as session:
            entity = await TaskRepository(session).get(task_id)
        if entity is not None and entity.status == TASK_BLOCKED:
            await self.transition(
                task_id, TASK_READY, actor_type=ACTOR_SYSTEM, reason="dependencies_satisfied"
            )

    async def list_events(
        self, task_id: str, *, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await TaskEventRepository(session).list_by_task(
                task_id, limit=limit, offset=offset
            )
        return {
            "items": [_event_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    def _apply_transition(self, entity: TaskModel, target: str, now: datetime) -> None:
        if target == entity.status:
            return
        if target not in TASK_TRANSITIONS.get(entity.status, frozenset()):
            raise InvalidStateTransition(
                f"非法任务状态迁移: {entity.status} → {target}",
                details={"task_id": entity.task_id},
            )
        entity.status = target
        entity.version += 1
        entity.updated_at = now

    async def _is_blocked(self, session, task_id: str) -> bool:
        dependencies = await TaskDependencyRepository(session).list_for_target(task_id)
        for dependency in dependencies:
            if dependency.dependency_type not in (
                DEPENDENCY_FINISH_TO_START,
                DEPENDENCY_BLOCKS,
                DEPENDENCY_RELATED,
            ):
                continue
            source = await TaskRepository(session).get(dependency.source_task_id)
            if source is not None and source.status != TASK_COMPLETED:
                return True
        return False


def _event_for_transition(target: str) -> str:
    mapping = {
        TASK_READY: "TASK_READY",
        TASK_QUEUED: "TASK_QUEUED",
        TASK_RUNNING: "TASK_STARTED",
        TASK_PAUSED: "TASK_PAUSED",
        TASK_RESUMING: "TASK_RESUMED",
        TASK_BLOCKED: "TASK_BLOCKED",
        TASK_WAITING_APPROVAL: "TASK_WAITING_APPROVAL",
        TASK_WAITING_USER: "TASK_WAITING_USER",
        TASK_FAILED: "TASK_FAILED",
        TASK_CANCELLED: "TASK_CANCELLED",
        TASK_REVIEW_PENDING: "TASK_REVIEW_PENDING",
        TASK_COMPLETED: "TASK_COMPLETED",
        TASK_REJECTED: "TASK_REJECTED",
    }
    return mapping.get(target, "TASK_READY")


def _event_view(entity: TaskEventModel) -> TaskEventView:
    payload = json.loads(entity.payload) if entity.payload else {}
    return TaskEventView(
        event_id=entity.event_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        sequence=entity.sequence,
        event_type=entity.event_type,
        previous_status=entity.previous_status,
        new_status=entity.new_status,
        actor_type=entity.actor_type,
        actor_id=entity.actor_id,
        payload=payload,
        occurred_at=ensure_utc(entity.occurred_at),
    )


class AttemptService:
    """Attempt 生命周期；重试必须创建新 Attempt。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        events: TaskEventWriter | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._events = events or TaskEventWriter()
        self._clock = clock

    async def create(
        self,
        task_id: str,
        *,
        agent_instance_id: str | None = None,
        workflow_instance_id: str | None = None,
        actor_id: str | None = None,
    ) -> AttemptView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            task = await TaskRepository(session).get(task_id)
            if task is None:
                raise NotFoundError("任务不存在", details={"task_id": task_id})
            if task.status in TERMINAL_TASK_STATUSES:
                raise InvalidStateTransition(
                    "已完成或已取消的任务不能创建 Attempt",
                    details={"task_id": task_id, "status": task.status},
                )
            repository = TaskAttemptRepository(session)
            attempt = TaskAttemptModel(
                attempt_id=_new_id("att_"),
                task_id=task_id,
                attempt_number=await repository.next_number(task_id),
                status=ATTEMPT_CREATED,
                started_at=None,
                ended_at=None,
                agent_instance_id=agent_instance_id,
                workflow_instance_id=workflow_instance_id or task.workflow_instance_id,
                checkpoint_id=None,
                execution_summary=None,
                failure_code=None,
                failure_reason=None,
                resource_usage=None,
                created_at=now,
            )
            await repository.add(attempt)
            task.current_attempt_id = attempt.attempt_id
            task.updated_at = now
            await self._events.append(
                session,
                task=task,
                event_type="ATTEMPT_CREATED",
                previous_status=task.status,
                new_status=task.status,
                actor_type=ACTOR_USER if actor_id else ACTOR_SYSTEM,
                actor_id=actor_id,
                attempt_id=attempt.attempt_id,
                payload={"attempt_number": attempt.attempt_number},
                now=now,
            )
            await session.flush()
            return _attempt_view(attempt)

    async def start(self, attempt_id: str) -> AttemptView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = TaskAttemptRepository(session)
            entity = await repository.get(attempt_id)
            if entity is None:
                raise NotFoundError("Attempt 不存在", details={"attempt_id": attempt_id})
            self._apply_transition(entity, ATTEMPT_STARTING, now)
            self._apply_transition(entity, ATTEMPT_RUNNING, now)
            entity.started_at = now
            task = await TaskRepository(session).get(entity.task_id)
            if task is not None:
                await self._events.append(
                    session,
                    task=task,
                    event_type="ATTEMPT_STARTED",
                    previous_status=task.status,
                    new_status=task.status,
                    actor_type=ACTOR_SYSTEM,
                    actor_id=None,
                    attempt_id=entity.attempt_id,
                    payload={"attempt_status": ATTEMPT_RUNNING},
                    now=now,
                )
            await session.flush()
            return _attempt_view(entity)

    async def finish(
        self,
        attempt_id: str,
        status: str,
        *,
        summary: str | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        resource_usage: str | None = None,
    ) -> AttemptView:
        event = "ATTEMPT_SUCCEEDED" if status == ATTEMPT_SUCCEEDED else "ATTEMPT_FAILED"
        return await self._transition(
            attempt_id,
            status,
            event=event,
            summary=summary,
            failure_code=failure_code,
            failure_reason=failure_reason,
            resource_usage=resource_usage,
        )

    async def cancel(self, attempt_id: str) -> AttemptView:
        return await self._transition(attempt_id, ATTEMPT_CANCELLED, event="ATTEMPT_FAILED")

    async def get(self, attempt_id: str) -> AttemptView:
        async with self._database.session() as session:
            entity = await TaskAttemptRepository(session).get(attempt_id)
        if entity is None:
            raise NotFoundError("Attempt 不存在", details={"attempt_id": attempt_id})
        return _attempt_view(entity)

    async def list(self, task_id: str) -> list[AttemptView]:
        async with self._database.session() as session:
            rows = await TaskAttemptRepository(session).list_by_task(task_id)
        return [_attempt_view(row) for row in rows]

    async def _transition(
        self,
        attempt_id: str,
        target: str,
        *,
        event: str,
        summary: str | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        resource_usage: str | None = None,
    ) -> AttemptView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = TaskAttemptRepository(session)
            entity = await repository.get(attempt_id)
            if entity is None:
                raise NotFoundError("Attempt 不存在", details={"attempt_id": attempt_id})
            self._apply_transition(entity, target, now)
            if target == ATTEMPT_STARTING and entity.started_at is None:
                entity.started_at = now
            if target in (ATTEMPT_SUCCEEDED, ATTEMPT_FAILED, ATTEMPT_CANCELLED):
                entity.ended_at = now
            entity.execution_summary = summary or entity.execution_summary
            entity.failure_code = failure_code or entity.failure_code
            entity.failure_reason = failure_reason or entity.failure_reason
            if resource_usage is not None:
                entity.resource_usage = resource_usage
            task = await TaskRepository(session).get(entity.task_id)
            if task is not None:
                await self._events.append(
                    session,
                    task=task,
                    event_type=event,
                    previous_status=task.status,
                    new_status=task.status,
                    actor_type=ACTOR_SYSTEM,
                    actor_id=None,
                    attempt_id=entity.attempt_id,
                    payload={"attempt_status": target},
                    now=now,
                )
            await session.flush()
            return _attempt_view(entity)

    def _apply_transition(self, entity: TaskAttemptModel, target: str, now: datetime) -> None:
        if target == entity.status:
            return
        if target not in ATTEMPT_TRANSITIONS.get(entity.status, frozenset()):
            raise InvalidStateTransition(
                f"非法 Attempt 状态迁移: {entity.status} → {target}",
                details={"attempt_id": entity.attempt_id},
            )
        entity.status = target


class DependencyService:
    """任务依赖；建立前检测循环，完成后通知 Task System 解除阻塞。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._clock = clock

    async def create(
        self,
        source_task_id: str,
        target_task_id: str,
        *,
        dependency_type: str = DEPENDENCY_FINISH_TO_START,
    ) -> DependencyView:
        if dependency_type not in DEPENDENCY_TYPES:
            raise ValidationFailed("dependency_type 非法")
        if source_task_id == target_task_id:
            raise DependencyCycle("任务不能依赖自身")
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            tasks = TaskRepository(session)
            source = await tasks.get(source_task_id)
            target = await tasks.get(target_task_id)
            if source is None or target is None:
                raise NotFoundError("依赖任务不存在")
            if source.project_id != target.project_id:
                raise ValidationFailed("依赖任务必须属于同一项目")
            repository = TaskDependencyRepository(session)
            existing = await repository.list_active(target.project_id)
            if _would_cycle(existing, source_task_id, target_task_id):
                raise DependencyCycle(
                    "任务依赖会形成循环",
                    details={
                        "source_task_id": source_task_id,
                        "target_task_id": target_task_id,
                    },
                )
            entity = await repository.get_pair(source_task_id, target_task_id)
            if entity is not None:
                entity.dependency_type = dependency_type
                entity.status = DEPENDENCY_ACTIVE
            else:
                entity = TaskDependencyModel(
                    dependency_id=_new_id("dep_"),
                    source_task_id=source_task_id,
                    target_task_id=target_task_id,
                    dependency_type=dependency_type,
                    status=DEPENDENCY_ACTIVE,
                    created_at=now,
                )
                await repository.add(entity)
            await session.flush()
            return _dependency_view(entity)

    async def remove(self, dependency_id: str) -> DependencyView:
        async with self._database.session() as session, transaction(session):
            entity = await TaskDependencyRepository(session).get(dependency_id)
            if entity is None:
                raise NotFoundError("依赖不存在", details={"dependency_id": dependency_id})
            entity.status = DEPENDENCY_REMOVED
            await session.flush()
            return _dependency_view(entity)

    async def list(self, project_id: str) -> list[DependencyView]:
        async with self._database.session() as session:
            rows = await TaskDependencyRepository(session).list_active(project_id)
        return [_dependency_view(row) for row in rows]

    async def is_blocked(self, task_id: str) -> bool:
        async with self._database.session() as session:
            dependencies = await TaskDependencyRepository(session).list_for_target(task_id)
            for dependency in dependencies:
                if dependency.dependency_type == DEPENDENCY_RELATED:
                    continue
                source = await TaskRepository(session).get(dependency.source_task_id)
                if source is not None and source.status != TASK_COMPLETED:
                    return True
        return False

    async def on_task_completed(self, task_id: str, *, tasks: TaskService) -> list[str]:
        """把以该任务为前驱的依赖标记完成，并解除目标任务阻塞。"""

        unblocked: list[str] = []
        async with self._database.session() as session, transaction(session):
            repository = TaskDependencyRepository(session)
            rows = await repository.list_active()
            targets = {row.target_task_id for row in rows if row.source_task_id == task_id}
            for dependency in rows:
                if dependency.source_task_id == task_id:
                    dependency.status = DEPENDENCY_RESOLVED
            await session.flush()
        for target_id in targets:
            if not await self.is_blocked(target_id):
                await tasks.record_completion_to_ready(target_id)
                unblocked.append(target_id)
        return unblocked


def _would_cycle(
    dependencies: list[TaskDependencyModel], source_task_id: str, target_task_id: str
) -> bool:
    """新增 source→target 后，若 target 已能到达 source 则形成环。"""

    graph: dict[str, set[str]] = {}
    for dependency in dependencies:
        graph.setdefault(dependency.source_task_id, set()).add(dependency.target_task_id)
    pending = [target_task_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == source_task_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(graph.get(current, ()))
    return False


class CheckpointService:
    """执行检查点；只保存业务状态引用，不保存隐藏推理。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        keep_per_task: int = 100,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._keep = keep_per_task
        self._clock = clock

    async def create(
        self,
        task_id: str,
        *,
        checkpoint_type: str = CHECKPOINT_SAFE_PAUSE,
        attempt_id: str | None = None,
        workflow_state_ref: str | None = None,
        context_ref: str | None = None,
        changeset_ref: str | None = None,
    ) -> CheckpointView:
        if checkpoint_type not in CHECKPOINT_TYPES:
            raise ValidationFailed("checkpoint_type 非法")
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            task = await TaskRepository(session).get(task_id)
            if task is None:
                raise NotFoundError("任务不存在", details={"task_id": task_id})
            repository = TaskCheckpointRepository(session)
            entity = TaskCheckpointModel(
                checkpoint_id=_new_id("ckp_"),
                task_id=task_id,
                attempt_id=attempt_id or task.current_attempt_id,
                checkpoint_type=checkpoint_type,
                sequence=await repository.next_sequence(task_id),
                workflow_state_ref=workflow_state_ref,
                context_ref=context_ref,
                changeset_ref=changeset_ref,
                checksum=checkpoint_checksum(
                    attempt_id=attempt_id or task.current_attempt_id,
                    workflow_state_ref=workflow_state_ref,
                    context_ref=context_ref,
                    changeset_ref=changeset_ref,
                ),
                created_at=now,
            )
            await repository.add(entity)
            await session.flush()
            await self._prune(session, task_id)
            return _checkpoint_view(entity)

    async def list(self, task_id: str, *, limit: int = 50) -> list[CheckpointView]:
        async with self._database.session() as session:
            rows = await TaskCheckpointRepository(session).list_by_task(task_id, limit=limit)
        return [_checkpoint_view(row) for row in rows]

    async def latest(self, task_id: str) -> CheckpointView | None:
        async with self._database.session() as session:
            entity = await TaskCheckpointRepository(session).latest(task_id)
        return _checkpoint_view(entity) if entity is not None else None

    async def _prune(self, session, task_id: str) -> None:
        rows = await TaskCheckpointRepository(session).list_by_task(task_id, limit=1000)
        if len(rows) <= self._keep:
            return
        for row in rows[self._keep :]:
            await session.delete(row)
        await session.flush()


def format_task(view: TaskView) -> dict[str, Any]:
    return {
        "task_id": view.task_id,
        "project_id": view.project_id,
        "parent_task_id": view.parent_task_id,
        "title": view.title,
        "description": view.description,
        "task_type": view.task_type,
        "priority": view.priority,
        "status": view.status,
        "created_by": view.created_by,
        "assigned_to": view.assigned_to,
        "workflow_instance_id": view.workflow_instance_id,
        "requirement_set_id": view.requirement_set_id,
        "current_attempt_id": view.current_attempt_id,
        "version": view.version,
        "created_at": isoformat(view.created_at),
        "updated_at": isoformat(view.updated_at),
        "completed_at": isoformat(view.completed_at) if view.completed_at else None,
    }


def format_attempt(view: AttemptView) -> dict[str, Any]:
    return {
        "attempt_id": view.attempt_id,
        "task_id": view.task_id,
        "attempt_number": view.attempt_number,
        "status": view.status,
        "started_at": isoformat(view.started_at) if view.started_at else None,
        "ended_at": isoformat(view.ended_at) if view.ended_at else None,
        "agent_instance_id": view.agent_instance_id,
        "workflow_instance_id": view.workflow_instance_id,
        "checkpoint_id": view.checkpoint_id,
        "execution_summary": view.execution_summary,
        "failure_code": view.failure_code,
        "failure_reason": view.failure_reason,
        "resource_usage": view.resource_usage,
        "created_at": isoformat(view.created_at),
    }


def format_dependency(view: DependencyView) -> dict[str, Any]:
    return {
        "dependency_id": view.dependency_id,
        "source_task_id": view.source_task_id,
        "target_task_id": view.target_task_id,
        "dependency_type": view.dependency_type,
        "status": view.status,
        "created_at": isoformat(view.created_at),
    }


def format_checkpoint(view: CheckpointView) -> dict[str, Any]:
    return {
        "checkpoint_id": view.checkpoint_id,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "checkpoint_type": view.checkpoint_type,
        "sequence": view.sequence,
        "workflow_state_ref": view.workflow_state_ref,
        "context_ref": view.context_ref,
        "changeset_ref": view.changeset_ref,
        "checksum": view.checksum,
        "created_at": isoformat(view.created_at),
    }


def format_task_event(view: TaskEventView) -> dict[str, Any]:
    return {
        "event_id": view.event_id,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "sequence": view.sequence,
        "event_type": view.event_type,
        "previous_status": view.previous_status,
        "new_status": view.new_status,
        "actor_type": view.actor_type,
        "actor_id": view.actor_id,
        "payload": view.payload,
        "occurred_at": isoformat(view.occurred_at),
    }
