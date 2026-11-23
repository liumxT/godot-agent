"""Agent Instance Manager（E6-T03 / T06）。

职责：

- 从合法的 Task + Attempt 创建 Agent Instance；
- 创建时冻结 Definition Version、Prompt、Model Policy、Context Profile、
  Tool 白名单、Permission Ceiling、Budget 与 Runtime Policy；
- 同一 Attempt 只允许一个活动 Instance（幂等返回已有实例）；
- 不允许直接修改 Task 或 Attempt 状态。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import AgentDefinitionInvalid, AgentStateInvalid, NotFoundError
from core.security.tokens import isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.events import AgentEventService
from modules.agent_runtime.models import (
    EVENT_INSTANCE_CREATED,
    INSTANCE_CREATED,
    INSTANCE_TERMINAL_STATUSES,
    AgentConfigSnapshotModel,
    AgentInstanceModel,
)
from modules.agent_runtime.repository import (
    AgentConfigSnapshotRepository,
    AgentInstanceRepository,
)
from modules.agent_runtime.service import DefinitionRegistryService, DefinitionVersionView
from modules.task.models import (
    ATTEMPT_CANCELLED,
    ATTEMPT_CREATED,
    ATTEMPT_FAILED,
    ATTEMPT_RUNNING,
    ATTEMPT_SUCCEEDED,
    TASK_CANCELLED,
    TASK_COMPLETED,
)
from modules.task.service import AttemptService, AttemptView, TaskService, TaskView

_TASK_STATUSES_ALLOWED = frozenset(
    {
        "QUEUED",
        "READY",
        "RUNNING",
        "PAUSING",
        "PAUSED",
        "RESUMING",
        "WAITING_APPROVAL",
        "WAITING_USER",
        "BLOCKED",
    }
)
_TERMINAL_ATTEMPT_STATUSES = frozenset({ATTEMPT_SUCCEEDED, ATTEMPT_FAILED, ATTEMPT_CANCELLED})
_TERMINAL_TASK_STATUSES = frozenset({TASK_COMPLETED, TASK_CANCELLED})
DEFAULT_RUNTIME_POLICY_VERSION = "1"


@dataclass(frozen=True, slots=True)
class InstanceView:
    instance_id: str
    agent_definition_id: str
    agent_version: str
    task_id: str | None
    attempt_id: str | None
    project_id: str
    session_id: str | None
    client_id: str | None
    status: str
    config_snapshot_id: str
    version: int
    termination_reason: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ConfigSnapshotView:
    snapshot_id: str
    agent_definition_id: str
    agent_version: str
    project_id: str
    session_id: str | None
    client_id: str | None
    model_policy_id: str
    model_id: str | None
    prompt_profile_id: str
    prompt_version: int
    context_profile_id: str
    context_profile_version: str
    tool_whitelist: tuple[str, ...]
    permission_ceiling: str
    budget: dict[str, Any]
    runtime_policy_version: str
    content_hash: str
    created_at: datetime


def instance_view(entity: AgentInstanceModel) -> InstanceView:
    return InstanceView(
        instance_id=entity.instance_id,
        agent_definition_id=entity.agent_definition_id,
        agent_version=entity.agent_version,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        project_id=entity.project_id,
        session_id=entity.session_id,
        client_id=entity.client_id,
        status=entity.status,
        config_snapshot_id=entity.config_snapshot_id,
        version=entity.version,
        termination_reason=entity.termination_reason,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
    )


def _snapshotinstance_view(entity: AgentConfigSnapshotModel) -> ConfigSnapshotView:
    return ConfigSnapshotView(
        snapshot_id=entity.snapshot_id,
        agent_definition_id=entity.agent_definition_id,
        agent_version=entity.agent_version,
        project_id=entity.project_id,
        session_id=entity.session_id,
        client_id=entity.client_id,
        model_policy_id=entity.model_policy_id,
        model_id=entity.model_id,
        prompt_profile_id=entity.prompt_profile_id,
        prompt_version=entity.prompt_version,
        context_profile_id=entity.context_profile_id,
        context_profile_version=entity.context_profile_version,
        tool_whitelist=tuple(json.loads(entity.tool_whitelist)),
        permission_ceiling=entity.permission_ceiling,
        budget=json.loads(entity.budget_json),
        runtime_policy_version=entity.runtime_policy_version,
        content_hash=entity.content_hash,
        created_at=entity.created_at,
    )


def _snapshot_payload(
    *,
    version: DefinitionVersionView,
    project_id: str,
    session_id: str | None,
    client_id: str | None,
    model_id: str | None,
) -> dict[str, Any]:
    frozen = version.definition
    return {
        "agent_definition_id": version.definition_id,
        "agent_version": version.version,
        "content_hash": version.content_hash,
        "project_id": project_id,
        "session_id": session_id,
        "client_id": client_id,
        "model_policy_id": frozen["model_policy"]["policy_id"],
        "model_id": model_id,
        "prompt": frozen["prompt"],
        "context": frozen["context"],
        "tools": frozen["tools"],
        "permissions": frozen["permissions"],
        "budgets": frozen["budgets"],
        "budget_profile_id": frozen["budget_profile_id"],
        "max_concurrency": frozen["max_concurrency"],
        "runtime_policy_version": DEFAULT_RUNTIME_POLICY_VERSION,
    }


def _hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AgentInstanceService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        definitions: DefinitionRegistryService,
        tasks: TaskService,
        attempts: AttemptService,
        events: AgentEventService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._definitions = definitions
        self._tasks = tasks
        self._attempts = attempts
        self._events = events
        self._clock = clock

    # ---- 查询 ----

    async def get(self, instance_id: str) -> InstanceView:
        async with self._database.session() as session:
            entity = await AgentInstanceRepository(session).get(instance_id)
        if entity is None:
            raise NotFoundError("Agent Instance 不存在", details={"instance_id": instance_id})
        return instance_view(entity)

    async def get_snapshot(self, instance_id: str) -> ConfigSnapshotView:
        instance = await self.get(instance_id)
        async with self._database.session() as session:
            entity = await AgentConfigSnapshotRepository(session).get(instance.config_snapshot_id)
        if entity is None:
            raise NotFoundError(
                "Agent 配置快照不存在", details={"snapshot_id": instance.config_snapshot_id}
            )
        return _snapshotinstance_view(entity)

    async def list(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await AgentInstanceRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [instance_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    # ---- 创建 ----

    async def create_for_attempt(
        self,
        *,
        definition_id: str,
        task_id: str,
        attempt_id: str,
        session_id: str | None = None,
        client_id: str | None = None,
        model_id: str | None = None,
    ) -> InstanceView:
        definition = await self._definitions.get(definition_id)
        if definition.status != "ACTIVE" or definition.current_version is None:
            raise AgentDefinitionInvalid(
                "只有已发布且启用的 Definition 才能创建 Instance",
                details={"definition_id": definition_id, "status": definition.status},
            )
        version = await self._definitions.get_version(
            definition_id, definition.current_version
        )

        task = await self._tasks.get(task_id)
        attempt = await self._attempts.get(attempt_id)
        self._validate_binding(task, attempt)

        async with self._database.session() as session, transaction(session):
            instances = AgentInstanceRepository(session)
            if attempt.agent_instance_id:
                existing = await instances.get(attempt.agent_instance_id)
                if existing is not None:
                    if existing.status in INSTANCE_TERMINAL_STATUSES:
                        raise AgentStateInvalid(
                            "该 Attempt 的 Agent Instance 已终止，不能重复创建",
                            details={
                                "attempt_id": attempt_id,
                                "instance_id": existing.instance_id,
                                "status": existing.status,
                            },
                        )
                    return instance_view(existing)
            active = await instances.get_active_for_attempt(attempt_id)
            if active is not None:
                return instance_view(active)

            now = self._clock()
            payload = _snapshot_payload(
                version=version,
                project_id=task.project_id,
                session_id=session_id,
                client_id=client_id,
                model_id=model_id,
            )
            snapshot = AgentConfigSnapshotModel(
                snapshot_id="agcfg_" + uuid4().hex[:12],
                agent_definition_id=definition_id,
                agent_version=version.version,
                project_id=task.project_id,
                session_id=session_id,
                client_id=client_id,
                model_policy_id=payload["model_policy_id"],
                model_id=model_id,
                prompt_profile_id=payload["prompt"]["profile_id"],
                prompt_version=int(payload["prompt"]["version"]),
                context_profile_id=payload["context"]["profile_id"],
                context_profile_version=payload["context"]["version"],
                tool_whitelist=json.dumps(payload["tools"]["allowed"]),
                permission_ceiling=payload["permissions"]["maximum_risk_level"],
                budget_json=json.dumps(payload["budgets"], sort_keys=True),
                runtime_policy_version=DEFAULT_RUNTIME_POLICY_VERSION,
                content_hash=_hash(payload),
                created_at=now,
            )
            await AgentConfigSnapshotRepository(session).add(snapshot)

            instance = AgentInstanceModel(
                instance_id="agin_" + uuid4().hex[:12],
                agent_definition_id=definition_id,
                agent_version=version.version,
                task_id=task_id,
                attempt_id=attempt_id,
                project_id=task.project_id,
                session_id=session_id,
                client_id=client_id,
                status=INSTANCE_CREATED,
                config_snapshot_id=snapshot.snapshot_id,
                version=1,
                termination_reason=None,
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
            )
            await instances.add(instance)
            await self._events.append_in_session(
                session,
                instance_id=instance.instance_id,
                event_type=EVENT_INSTANCE_CREATED,
                payload={
                    "agent_definition_id": definition_id,
                    "agent_version": version.version,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "config_snapshot_id": snapshot.snapshot_id,
                },
                now=now,
            )
            await session.flush()
            return instance_view(instance)

    @staticmethod
    def _validate_binding(task: TaskView, attempt: AttemptView) -> None:
        if task.status in _TERMINAL_TASK_STATUSES:
            raise AgentStateInvalid(
                "任务已终止，不能创建 Agent Instance",
                details={"task_id": task.task_id, "status": task.status},
            )
        if task.status not in _TASK_STATUSES_ALLOWED:
            raise AgentStateInvalid(
                "任务当前状态不允许启动 Agent",
                details={"task_id": task.task_id, "status": task.status},
            )
        if attempt.task_id != task.task_id:
            raise AgentStateInvalid(
                "Attempt 不属于该 Task",
                details={"attempt_id": attempt.attempt_id, "task_id": attempt.task_id},
            )
        if attempt.status in _TERMINAL_ATTEMPT_STATUSES:
            raise AgentStateInvalid(
                "Attempt 已终止，不能创建 Agent Instance",
                details={"attempt_id": attempt.attempt_id, "status": attempt.status},
            )
        if attempt.status not in {ATTEMPT_CREATED, ATTEMPT_RUNNING}:
            raise AgentStateInvalid(
                "Attempt 状态不允许启动 Agent",
                details={"attempt_id": attempt.attempt_id, "status": attempt.status},
            )
        current = task.current_attempt_id
        if current is not None and current != attempt.attempt_id:
            raise AgentStateInvalid(
                "该 Attempt 不是任务当前尝试",
                details={"task_id": task.task_id, "current_attempt_id": current},
            )

    # ---- Task / Attempt 绑定 ----

    async def assert_task_binding(self, instance_id: str) -> InstanceView:
        """读取 Task System 的权威状态并校验实例仍绑定在有效 Task 上。

        Agent 不反向修改 Task；任务终止后的停止动作由生命周期服务执行。
        """

        instance = await self.get(instance_id)
        if instance.task_id is None:
            return instance
        task = await self._tasks.get(instance.task_id)
        if task.status in _TERMINAL_TASK_STATUSES:
            raise AgentStateInvalid(
                "任务已终止，请通过生命周期服务停止实例",
                details={"instance_id": instance_id, "task_status": task.status},
            )
        return instance


def format_instance(view: InstanceView) -> dict[str, Any]:
    return {
        "instance_id": view.instance_id,
        "agent_definition_id": view.agent_definition_id,
        "agent_version": view.agent_version,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "project_id": view.project_id,
        "session_id": view.session_id,
        "client_id": view.client_id,
        "status": view.status,
        "config_snapshot_id": view.config_snapshot_id,
        "version": view.version,
        "termination_reason": view.termination_reason,
        "created_at": isoformat(view.created_at),
        "updated_at": isoformat(view.updated_at),
        "started_at": isoformat(view.started_at) if view.started_at else None,
        "completed_at": isoformat(view.completed_at) if view.completed_at else None,
    }
