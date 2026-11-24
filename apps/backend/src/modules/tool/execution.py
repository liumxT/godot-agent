"""统一工具执行引擎（E5-T22 / T23）。

所有工具调用必须经过本入口：请求校验 → 权限 → 风险 → 审批 → 资源锁 →
幂等 → 执行 → 验证 → 审计 → 事件。任何 Godot 项目写操作都不得绕过。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    NotFoundError,
    PermissionDenied,
    ToolAdapterMissing,
    ToolOutputInvalid,
    ValidationFailed,
)
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.changeset.service import ChangeSetService
from modules.tool.adapters import (
    AdapterResult,
    ToolAdapter,
    ToolAdapterRegistry,
    ToolDispatchContext,
)
from modules.tool.audit import ToolAuditService
from modules.tool.locks import ResourceLockService, ResourceLockView
from modules.tool.models import (
    ACTOR_TYPE_AGENT,
    ACTOR_TYPE_USER,
    EXECUTION_AUTHORIZED,
    EXECUTION_CANCELLED,
    EXECUTION_CREATED,
    EXECUTION_EXECUTING,
    EXECUTION_FAILED,
    EXECUTION_READY,
    EXECUTION_SUCCEEDED,
    EXECUTION_TIMEOUT,
    EXECUTION_UNKNOWN,
    EXECUTION_VALIDATING,
    IDEMPOTENCY_KEYED,
    LOCK_OWNER_EXECUTION,
    LOCK_TYPE_READ,
    LOCK_TYPE_WRITE,
    TOOL_EXECUTION_IN_FLIGHT,
    TOOL_EXECUTION_TERMINAL,
    VERIFICATION_FAILED,
    VERIFICATION_PENDING,
    ToolExecutionModel,
)
from modules.tool.permissions import (
    AgentPolicy,
    ToolPermissionEngine,
    ToolPermissionRequest,
)
from modules.tool.recovery import ToolRecoveryService
from modules.tool.registry import ToolRegistryService, ToolView
from modules.tool.repository import ToolExecutionRepository
from modules.tool.risk import ToolRiskPolicy
from modules.tool.verification import ToolVerificationService

WRITE_PERMISSIONS = frozenset({"project.write", "project.admin"})
_EXECUTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
EXECUTION_TRANSITIONS = {
    EXECUTION_CREATED: frozenset({EXECUTION_VALIDATING, EXECUTION_FAILED, EXECUTION_CANCELLED}),
    EXECUTION_VALIDATING: frozenset({EXECUTION_AUTHORIZED, EXECUTION_FAILED, EXECUTION_CANCELLED}),
    EXECUTION_AUTHORIZED: frozenset({EXECUTION_READY, EXECUTION_FAILED, EXECUTION_CANCELLED}),
    EXECUTION_READY: frozenset({EXECUTION_EXECUTING, EXECUTION_FAILED, EXECUTION_CANCELLED}),
    EXECUTION_EXECUTING: frozenset(
        {
            EXECUTION_SUCCEEDED,
            EXECUTION_FAILED,
            EXECUTION_CANCELLED,
            EXECUTION_TIMEOUT,
            EXECUTION_UNKNOWN,
        }
    ),
}

__all__ = [
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "ToolExecutionService",
    "ToolExecutionView",
]


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    project_id: str
    tool_id: str
    input: Mapping[str, Any]
    execution_id: str = ""
    idempotency_key: str | None = None
    task_id: str | None = None
    attempt_id: str | None = None
    agent_instance_id: str | None = None
    tool_version: int | None = None
    changeset_id: str | None = None
    approval_id: str | None = None
    session_id: str | None = None
    client_id: str | None = None
    actor_id: str | None = None
    resource_scope: tuple[str, ...] = ()
    fencing_token: int | None = None
    requested_risk_level: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    execution_id: str
    status: str
    output: dict[str, Any] | None
    error: dict[str, str | None] | None
    started_at: datetime | None
    completed_at: datetime | None
    evidence_refs: tuple[str, ...]
    verification_status: str
    risk_level: str
    reused: bool = False


@dataclass(frozen=True, slots=True)
class ToolExecutionView:
    execution_id: str
    project_id: str
    tool_id: str
    tool_name: str
    tool_version: int
    status: str
    risk_level: str
    idempotency_key: str | None
    task_id: str | None
    attempt_id: str | None
    agent_instance_id: str | None
    changeset_id: str | None
    approval_id: str | None
    session_id: str | None
    client_id: str | None
    input: dict[str, Any]
    output: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    evidence_refs: tuple[str, ...]
    verification_status: str
    fencing_token: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


def _view(entity: ToolExecutionModel) -> ToolExecutionView:
    return ToolExecutionView(
        execution_id=entity.execution_id,
        project_id=entity.project_id,
        tool_id=entity.tool_id,
        tool_name=entity.tool_name,
        tool_version=entity.tool_version,
        status=entity.status,
        risk_level=entity.risk_level,
        idempotency_key=entity.idempotency_key,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        agent_instance_id=entity.agent_instance_id,
        changeset_id=entity.changeset_id,
        approval_id=entity.approval_id,
        session_id=entity.session_id,
        client_id=entity.client_id,
        input=json.loads(entity.input_payload),
        output=json.loads(entity.output_payload) if entity.output_payload else None,
        error_code=entity.error_code,
        error_message=entity.error_message,
        evidence_refs=tuple(json.loads(entity.evidence_refs)),
        verification_status=entity.verification_status,
        fencing_token=entity.fencing_token,
        started_at=ensure_utc(entity.started_at) if entity.started_at else None,
        completed_at=ensure_utc(entity.completed_at) if entity.completed_at else None,
        created_at=ensure_utc(entity.created_at),
    )


class ToolExecutionService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        tools: ToolRegistryService,
        permissions: ToolPermissionEngine,
        locks: ResourceLockService,
        verifications: ToolVerificationService,
        audits: ToolAuditService,
        recovery: ToolRecoveryService,
        adapters: ToolAdapterRegistry,
        changesets: ChangeSetService | None = None,
        events: EventBus | None = None,
        risk_policy: ToolRiskPolicy | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._tools = tools
        self._permissions = permissions
        self._locks = locks
        self._verifications = verifications
        self._audits = audits
        self._recovery = recovery
        self._adapters = adapters
        self._changesets = changesets
        self._events = events
        self._risk = risk_policy or ToolRiskPolicy()
        self._clock = clock
        self._logger = get_logger("backend.tool")

    async def execute(
        self,
        request: ToolExecutionRequest,
        *,
        agent_policy: AgentPolicy | None = None,
    ) -> ToolExecutionResult:
        self._validate_request(request)
        tool = await self._tools.get(request.tool_id)
        if request.tool_version is not None and tool.version != request.tool_version:
            raise PermissionDenied(
                "工具版本与请求不一致",
                details={"reasons": ["TOOL_VERSION_MISMATCH"], "tool_id": tool.tool_id},
            )

        if request.idempotency_key:
            existing = await self._find_by_idempotency_key(request)
            if existing is not None:
                resolved = await self._resolve_existing(existing)
                if resolved is not None:
                    return resolved
        elif tool.idempotency_policy == IDEMPOTENCY_KEYED:
            raise ValidationFailed(
                "该工具要求 idempotency_key",
                details={"tool_id": tool.tool_id, "tool_name": tool.name},
            )

        return await self._run_new(request, tool, agent_policy=agent_policy)

    async def get(self, execution_id: str) -> ToolExecutionView:
        return _view(await self._load(execution_id))

    async def list_for_project(
        self, project_id: str, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await ToolExecutionRepository(session).list_project_executions(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def cancel(
        self, execution_id: str, *, actor_id: str | None = None, reason: str | None = None
    ) -> ToolExecutionView:
        """取消尚未分发的执行；已分发到编辑器的执行只能等待或走恢复流程。"""

        entity = await self._load(execution_id)
        if entity.status in TOOL_EXECUTION_TERMINAL:
            return _view(entity)
        if entity.status == EXECUTION_EXECUTING:
            raise ValidationFailed(
                "执行中的工具不能直接取消，请等待结果或进入恢复",
                details={"execution_id": execution_id, "status": entity.status},
            )
        view = await self._transition(
            execution_id,
            EXECUTION_CANCELLED,
            error_code="TOOL_EXECUTION_CANCELLED",
            error_message=(reason or "用户取消")[:512],
            completed_at=self._clock(),
        )
        await self._audits.record(
            execution_id=view.execution_id,
            project_id=view.project_id,
            actor_type=ACTOR_TYPE_USER,
            actor_id=actor_id,
            task_id=view.task_id,
            attempt_id=view.attempt_id,
            tool_id=view.tool_id,
            tool_name=view.tool_name,
            tool_version=view.tool_version,
            risk_level=view.risk_level,
            execution_status=view.status,
            approval_id=view.approval_id,
            input_payload=view.input,
            output_payload=None,
            failure_reason=view.error_code,
        )
        await self._publish(view)
        return view

    async def _run_new(
        self,
        request: ToolExecutionRequest,
        tool: ToolView,
        *,
        agent_policy: AgentPolicy | None,
    ) -> ToolExecutionResult:
        risk = self._risk.assess(tool, requested_level=request.requested_risk_level)
        input_payload = dict(request.input)
        entity = ToolExecutionModel(
            execution_id=request.execution_id or "exe_" + uuid4().hex[:12],
            idempotency_key=request.idempotency_key,
            project_id=request.project_id,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            agent_instance_id=request.agent_instance_id,
            tool_id=tool.tool_id,
            tool_name=tool.name,
            tool_version=tool.version,
            risk_level=risk.level,
            input_payload=json.dumps(
                input_payload, ensure_ascii=False, sort_keys=True, default=str
            ),
            input_hash=_hash_payload(input_payload),
            changeset_id=request.changeset_id,
            approval_id=request.approval_id,
            session_id=request.session_id,
            client_id=request.client_id,
            actor_id=request.actor_id,
            resource_scope=json.dumps(list(request.resource_scope), ensure_ascii=False),
            fencing_token=request.fencing_token,
            status=EXECUTION_CREATED,
            output_payload=None,
            error_code=None,
            error_message=None,
            evidence_refs="[]",
            verification_status=VERIFICATION_PENDING,
            started_at=None,
            completed_at=None,
            created_at=ensure_utc(request.created_at) if request.created_at else self._clock(),
            updated_at=self._clock(),
        )
        async with self._database.session() as session, transaction(session):
            await ToolExecutionRepository(session).add(entity)

        held_locks: tuple[ResourceLockView, ...] = ()
        adapter_result: AdapterResult | None = None
        dispatched = False
        try:
            await self._transition(entity.execution_id, EXECUTION_VALIDATING)
            await self._tools.validate_input(tool, input_payload)

            decision = await self._permissions.require(
                ToolPermissionRequest(
                    user_id=request.actor_id or "",
                    project_id=request.project_id,
                    session_id=request.session_id or "",
                    client_id=request.client_id or "",
                    tool_id=tool.tool_id,
                    tool_version=tool.version,
                    resource_scope=request.resource_scope,
                    task_id=request.task_id,
                    agent_instance_id=request.agent_instance_id,
                    approval_id=request.approval_id,
                    requested_risk_level=request.requested_risk_level,
                    input_payload=input_payload,
                ),
                agent_policy=agent_policy,
            )
            await self._transition(entity.execution_id, EXECUTION_AUTHORIZED)
            await self._enforce_changeset(request, decision.risk.changeset_required)

            if request.resource_scope:
                write_tool = bool(set(tool.required_permissions) & WRITE_PERMISSIONS)
                held_locks = await self._locks.acquire_many(
                    request.resource_scope,
                    project_id=request.project_id,
                    owner_type=LOCK_OWNER_EXECUTION,
                    owner_id=entity.execution_id,
                    lock_type=LOCK_TYPE_WRITE if write_tool else LOCK_TYPE_READ,
                    ttl_seconds=tool.timeout_seconds + 60,
                )
            await self._transition(
                entity.execution_id,
                EXECUTION_READY,
                fencing_token=held_locks[0].fencing_token if held_locks else None,
            )
            for lock in held_locks:
                await self._locks.validate(
                    lock.lock_id,
                    fencing_token=lock.fencing_token,
                    owner_id=entity.execution_id,
                )

            adapter = self._adapters.resolve(tool)
            if adapter is None:
                raise ToolAdapterMissing(
                    "没有可执行该工具的 Adapter", details={"tool_id": tool.tool_id}
                )

            context = ToolDispatchContext(
                execution_id=entity.execution_id,
                project_id=request.project_id,
                tool_id=tool.tool_id,
                tool_name=tool.name,
                tool_version=tool.version,
                input=input_payload,
                session_id=request.session_id,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                resource_scope=request.resource_scope,
                fencing_token=held_locks[0].fencing_token if held_locks else None,
                timeout_seconds=tool.timeout_seconds,
            )
            await self._transition(
                entity.execution_id, EXECUTION_EXECUTING, started_at=self._clock()
            )
            dispatched = True
            adapter_result = await self._dispatch(adapter, context, tool)

            output_valid = True
            if adapter_result.status == EXECUTION_SUCCEEDED and adapter_result.output is not None:
                try:
                    await self._tools.validate_output(tool, adapter_result.output)
                except ToolOutputInvalid as exc:
                    output_valid = False
                    adapter_result = AdapterResult(
                        status=EXECUTION_FAILED,
                        output=None,
                        error_code=exc.code,
                        error_message=str(exc),
                        checks=adapter_result.checks,
                        evidence_refs=adapter_result.evidence_refs,
                    )

            verification = await self._verifications.record(
                execution_id=entity.execution_id,
                project_id=request.project_id,
                execution_status=adapter_result.status,
                output_valid=output_valid,
                adapter_result=adapter_result,
            )
            completed_at = self._clock()
            await self._transition(
                entity.execution_id,
                adapter_result.status,
                output_payload=(
                    json.dumps(dict(adapter_result.output), ensure_ascii=False, sort_keys=True)
                    if adapter_result.output is not None
                    else None
                ),
                error_code=adapter_result.error_code,
                error_message=adapter_result.error_message,
                evidence_refs=json.dumps(list(adapter_result.evidence_refs), ensure_ascii=False),
                verification_status=verification.verification_status,
                completed_at=completed_at,
            )
            result = _view(await self._load(entity.execution_id))
            await self._record_audit(result, request=request)
            await self._publish(result)
            return _to_result(result)
        except Exception as exc:
            if not dispatched:
                await self._mark_failed(entity.execution_id, exc)
                failed = _view(await self._load(entity.execution_id))
                await self._record_audit(failed, request=request)
            raise
        finally:
            await self._release_locks(held_locks, entity.execution_id)

    async def _dispatch(
        self, adapter: ToolAdapter, context: ToolDispatchContext, tool: ToolView
    ) -> AdapterResult:
        try:
            return await asyncio.wait_for(adapter.execute(context), timeout=tool.timeout_seconds)
        except TimeoutError:
            return AdapterResult(
                status=EXECUTION_TIMEOUT,
                error_code="TOOL_EXECUTION_TIMEOUT",
                error_message=f"工具执行超过 {tool.timeout_seconds} 秒",
            )
        except Exception as exc:  # noqa: BLE001 - 发送后异常无法判断副作用，必须记 UNKNOWN
            return AdapterResult(
                status=EXECUTION_UNKNOWN,
                error_code="TOOL_ADAPTER_ERROR",
                error_message=f"{type(exc).__name__}: {exc}"[:512],
            )

    async def _resolve_existing(self, existing: ToolExecutionModel) -> ToolExecutionResult | None:
        """按幂等键处理历史执行：成功复用、进行中返回状态、未知先核验。"""

        if existing.status == EXECUTION_SUCCEEDED or existing.status in TOOL_EXECUTION_IN_FLIGHT:
            return _to_result(_view(existing), reused=True)
        if existing.status in (EXECUTION_UNKNOWN, EXECUTION_TIMEOUT):
            outcome = await self._recovery.recover(existing.execution_id)
            if outcome.status != EXECUTION_FAILED:
                return _to_result(_view(await self._load(existing.execution_id)), reused=True)
        return None

    async def _enforce_changeset(
        self, request: ToolExecutionRequest, changeset_required: bool
    ) -> None:
        if not changeset_required:
            return
        if not request.changeset_id:
            raise PermissionDenied(
                "该风险等级的工具执行必须关联 ChangeSet",
                details={"reasons": ["CHANGESET_REQUIRED"], "tool_id": request.tool_id},
            )
        if self._changesets is None:
            return
        try:
            changeset = await self._changesets.get(request.changeset_id)
        except NotFoundError as exc:
            raise PermissionDenied(
                "ChangeSet 不存在",
                details={"reasons": ["CHANGESET_NOT_FOUND"], "changeset_id": request.changeset_id},
            ) from exc
        if changeset.project_id != request.project_id:
            raise PermissionDenied(
                "ChangeSet 不属于该项目",
                details={"reasons": ["CHANGESET_PROJECT_MISMATCH"]},
            )

    async def _record_audit(
        self, view: ToolExecutionView, *, request: ToolExecutionRequest
    ) -> None:
        await self._audits.record(
            execution_id=view.execution_id,
            project_id=view.project_id,
            actor_type=ACTOR_TYPE_AGENT if view.agent_instance_id else ACTOR_TYPE_USER,
            actor_id=request.actor_id,
            task_id=view.task_id,
            attempt_id=view.attempt_id,
            tool_id=view.tool_id,
            tool_name=view.tool_name,
            tool_version=view.tool_version,
            risk_level=view.risk_level,
            execution_status=view.status,
            approval_id=view.approval_id,
            input_payload=view.input,
            output_payload=view.output,
            failure_reason=view.error_code,
        )

    async def _publish(self, view: ToolExecutionView) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(
                Event.create(
                    "tool.execution.completed",
                    {
                        "execution_id": view.execution_id,
                        "status": view.status,
                        "verification_status": view.verification_status,
                        "risk_level": view.risk_level,
                        "tool_id": view.tool_id,
                        "tool_version": view.tool_version,
                        "task_id": view.task_id,
                    },
                    session_id=view.session_id,
                    project_id=view.project_id,
                )
            )
        except Exception:  # noqa: BLE001 - 事件失败不回滚已完成的执行
            log_event(
                self._logger,
                logging.WARNING,
                "tool_execution_event_failed",
                component="tool",
                error_code="EVENT_PUBLISH_FAILED",
            )

    async def _release_locks(self, locks: tuple[ResourceLockView, ...], execution_id: str) -> None:
        for lock in locks:
            try:
                await self._locks.release(lock.lock_id, owner_id=execution_id)
            except Exception:  # noqa: BLE001 - 释放失败不掩盖执行结果
                log_event(
                    self._logger,
                    logging.WARNING,
                    "resource_lock_release_failed",
                    component="tool",
                    error_code="RESOURCE_LOCK_RELEASE_FAILED",
                )

    async def _mark_failed(self, execution_id: str, exc: Exception) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await ToolExecutionRepository(session).get(execution_id)
            if entity is None:
                return
            verification_status = entity.verification_status
            if entity.status == EXECUTION_EXECUTING:
                entity.status = EXECUTION_UNKNOWN
            elif entity.status != EXECUTION_FAILED:
                entity.status = EXECUTION_FAILED
                verification_status = VERIFICATION_FAILED
            entity.error_code = getattr(exc, "code", None) or "TOOL_EXECUTION_FAILED"
            entity.error_message = str(exc)[:512] or None
            entity.verification_status = verification_status
            entity.completed_at = self._clock()
            entity.updated_at = self._clock()
            await session.flush()

    async def _transition(self, execution_id: str, target: str, **fields: Any) -> ToolExecutionView:
        async with self._database.session() as session, transaction(session):
            entity = await ToolExecutionRepository(session).get(execution_id)
            if entity is None:
                raise NotFoundError("工具执行不存在", details={"execution_id": execution_id})
            if target != entity.status:
                allowed = EXECUTION_TRANSITIONS.get(entity.status, frozenset())
                if target not in allowed:
                    raise ValidationFailed(
                        "非法的执行状态迁移",
                        details={"execution_id": execution_id, "from": entity.status, "to": target},
                    )
                entity.status = target
            for key, value in fields.items():
                setattr(entity, key, value)
            entity.updated_at = self._clock()
            await session.flush()
            return _view(entity)

    async def _load(self, execution_id: str) -> ToolExecutionModel:
        async with self._database.session() as session:
            entity = await ToolExecutionRepository(session).get(execution_id)
        if entity is None:
            raise NotFoundError("工具执行不存在", details={"execution_id": execution_id})
        return entity

    async def _find_by_idempotency_key(
        self, request: ToolExecutionRequest
    ) -> ToolExecutionModel | None:
        async with self._database.session() as session:
            return await ToolExecutionRepository(session).latest_by_idempotency_key(
                request.project_id, request.idempotency_key or ""
            )

    @staticmethod
    def _validate_request(request: ToolExecutionRequest) -> None:
        if not request.project_id.strip():
            raise ValidationFailed("project_id 不能为空")
        if not request.tool_id.strip():
            raise ValidationFailed("tool_id 不能为空")
        if request.execution_id and not _EXECUTION_ID_PATTERN.match(request.execution_id):
            raise ValidationFailed(
                "execution_id 格式非法", details={"execution_id": request.execution_id}
            )
        if not isinstance(request.input, Mapping):
            raise ValidationFailed("工具输入必须是 JSON 对象")
        for ref in request.resource_scope:
            if not ref.strip() or ":" not in ref:
                raise ValidationFailed(
                    "resource_scope 格式非法",
                    details={"resource_scope": list(request.resource_scope)},
                )


def _to_result(view: ToolExecutionView, *, reused: bool = False) -> ToolExecutionResult:
    error = (
        {"code": view.error_code, "message": view.error_message}
        if view.error_code or view.error_message
        else None
    )
    return ToolExecutionResult(
        execution_id=view.execution_id,
        status=view.status,
        output=view.output,
        error=error,
        started_at=view.started_at,
        completed_at=view.completed_at,
        evidence_refs=view.evidence_refs,
        verification_status=view.verification_status,
        risk_level=view.risk_level,
        reused=reused,
    )


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
