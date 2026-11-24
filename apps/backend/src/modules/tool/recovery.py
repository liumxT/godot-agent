"""工具执行恢复（E5-T27）。

Backend 或 Godot Editor 中断后，只能通过 Adapter 查询实际资源状态判断结果：
已完成则恢复结果记录，未执行允许安全重试，无法判断保持 ``UNKNOWN``。
不能依赖 Backend 内部缓存推断写操作已经成功。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import NotFoundError
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.tool.adapters import AdapterResult, ToolAdapterRegistry, ToolDispatchContext
from modules.tool.audit import ToolAuditService
from modules.tool.models import (
    EXECUTION_EXECUTING,
    EXECUTION_FAILED,
    EXECUTION_SUCCEEDED,
    EXECUTION_TIMEOUT,
    EXECUTION_UNKNOWN,
    VERIFICATION_FAILED,
    VERIFICATION_PARTIAL,
    VERIFICATION_UNKNOWN,
    VERIFICATION_VERIFIED,
    ToolExecutionModel,
)
from modules.tool.registry import ToolRegistryService
from modules.tool.repository import ToolExecutionRepository
from modules.tool.verification import ToolVerificationService

RECOVERABLE_STATUSES = (EXECUTION_EXECUTING, EXECUTION_UNKNOWN, EXECUTION_TIMEOUT)

__all__ = ["RecoveryOutcome", "ToolRecoveryService"]


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    execution_id: str
    status: str
    verification_status: str
    output: dict[str, Any] | None
    error_code: str | None
    evidence_refs: tuple[str, ...]


def _dispatch_context(entity: ToolExecutionModel) -> ToolDispatchContext:
    return ToolDispatchContext(
        execution_id=entity.execution_id,
        project_id=entity.project_id,
        tool_id=entity.tool_id,
        tool_name=entity.tool_name,
        tool_version=entity.tool_version,
        input=json.loads(entity.input_payload),
        session_id=entity.session_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        resource_scope=tuple(json.loads(entity.resource_scope)),
        fencing_token=entity.fencing_token,
    )


class ToolRecoveryService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        tools: ToolRegistryService,
        adapters: ToolAdapterRegistry,
        verifications: ToolVerificationService,
        audits: ToolAuditService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._tools = tools
        self._adapters = adapters
        self._verifications = verifications
        self._audits = audits
        self._clock = clock

    async def recover(self, execution_id: str) -> RecoveryOutcome:
        entity = await self._load(execution_id)
        if entity.status not in RECOVERABLE_STATUSES:
            return _outcome(entity)

        adapter_result: AdapterResult | None = None
        adapter_failure: str | None = None
        try:
            tool = await self._tools.get(entity.tool_id)
        except NotFoundError:
            adapter_failure = "TOOL_NOT_FOUND"
        else:
            adapter = self._adapters.resolve(tool)
            if adapter is None:
                adapter_failure = "TOOL_ADAPTER_MISSING"
            else:
                try:
                    adapter_result = await adapter.inspect(_dispatch_context(entity))
                except Exception:  # noqa: BLE001 - 观测失败只能保持 UNKNOWN
                    adapter_failure = "ADAPTER_INSPECTION_FAILED"

        output_valid = True
        if adapter_result is not None and adapter_result.output is not None:
            try:
                await self._tools.validate_output(tool, adapter_result.output)
            except Exception:  # noqa: BLE001 - 输出非法按未通过验证处理
                output_valid = False

        execution_status = (
            adapter_result.status if adapter_result is not None else EXECUTION_UNKNOWN
        )
        verification = await self._verifications.record(
            execution_id=entity.execution_id,
            project_id=entity.project_id,
            execution_status=execution_status,
            output_valid=output_valid,
            adapter_result=adapter_result,
        )
        status = _resolve_status(execution_status, verification.verification_status)
        evidence = list(json.loads(entity.evidence_refs))
        for ref in verification.evidence_refs:
            if ref not in evidence:
                evidence.append(ref)

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            current = await ToolExecutionRepository(session).get(execution_id)
            if current is None:
                raise NotFoundError("工具执行不存在", details={"execution_id": execution_id})
            current.status = status
            current.verification_status = verification.verification_status
            current.evidence_refs = json.dumps(evidence, ensure_ascii=False)
            current.updated_at = now
            if adapter_result is not None and adapter_result.output is not None:
                current.output_payload = json.dumps(
                    dict(adapter_result.output), ensure_ascii=False, sort_keys=True
                )
            if status == EXECUTION_FAILED:
                current.error_code = (
                    adapter_result.error_code if adapter_result is not None else adapter_failure
                ) or "TOOL_RECOVERY_FAILED"
                current.error_message = (
                    adapter_result.error_message if adapter_result is not None else None
                )
            if status != EXECUTION_UNKNOWN:
                current.completed_at = now
            await session.flush()

        if self._audits is not None:
            await self._audits.record(
                execution_id=entity.execution_id,
                project_id=entity.project_id,
                actor_type="SYSTEM",
                actor_id=None,
                task_id=entity.task_id,
                attempt_id=entity.attempt_id,
                tool_id=entity.tool_id,
                tool_name=entity.tool_name,
                tool_version=entity.tool_version,
                risk_level=entity.risk_level,
                execution_status=status,
                approval_id=entity.approval_id,
                input_payload=json.loads(entity.input_payload),
                output_payload=adapter_result.output if adapter_result is not None else None,
                failure_reason=adapter_failure,
            )
        return RecoveryOutcome(
            execution_id=entity.execution_id,
            status=status,
            verification_status=verification.verification_status,
            output=dict(adapter_result.output)
            if adapter_result and adapter_result.output
            else None,
            error_code=adapter_result.error_code if adapter_result is not None else adapter_failure,
            evidence_refs=tuple(evidence),
        )

    async def recover_pending(self, *, limit: int = 100) -> tuple[RecoveryOutcome, ...]:
        async with self._database.session() as session:
            entities = await ToolExecutionRepository(session).list_by_statuses(
                RECOVERABLE_STATUSES, limit=limit
            )
        return tuple([await self.recover(entity.execution_id) for entity in entities])

    async def _load(self, execution_id: str) -> ToolExecutionModel:
        async with self._database.session() as session:
            entity = await ToolExecutionRepository(session).get(execution_id)
        if entity is None:
            raise NotFoundError("工具执行不存在", details={"execution_id": execution_id})
        return entity


def _resolve_status(execution_status: str, verification_status: str) -> str:
    if verification_status == VERIFICATION_VERIFIED:
        return EXECUTION_SUCCEEDED
    if verification_status == VERIFICATION_FAILED:
        return EXECUTION_FAILED
    if verification_status == VERIFICATION_UNKNOWN:
        return EXECUTION_UNKNOWN
    # 部分完成或无法给出结论时不能宣布成功，保持 UNKNOWN 进入恢复处理。
    return EXECUTION_UNKNOWN if verification_status == VERIFICATION_PARTIAL else execution_status


def _outcome(entity: ToolExecutionModel) -> RecoveryOutcome:
    output = json.loads(entity.output_payload) if entity.output_payload else None
    return RecoveryOutcome(
        execution_id=entity.execution_id,
        status=entity.status,
        verification_status=entity.verification_status,
        output=output,
        error_code=entity.error_code,
        evidence_refs=tuple(json.loads(entity.evidence_refs)),
    )
