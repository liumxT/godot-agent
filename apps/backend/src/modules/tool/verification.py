"""工具结果验证（E5-T26）。

工具返回成功不代表操作成功。验证服务基于执行状态、输出 Schema 与 Adapter
报告的观测检查给出结论；它只记录验证结果，不修改 Task 状态，
也不能由 Agent 自行宣布验证成功。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.tool.adapters import AdapterResult, VerificationCheck
from modules.tool.models import (
    EXECUTION_CANCELLED,
    EXECUTION_FAILED,
    EXECUTION_SUCCEEDED,
    EXECUTION_TIMEOUT,
    EXECUTION_UNKNOWN,
    VERIFICATION_FAILED,
    VERIFICATION_PARTIAL,
    VERIFICATION_PENDING,
    VERIFICATION_UNKNOWN,
    VERIFICATION_VERIFIED,
    ToolVerificationRecordModel,
)
from modules.tool.repository import ToolVerificationRepository

__all__ = ["ToolVerificationResult", "ToolVerificationService"]


@dataclass(frozen=True, slots=True)
class ToolVerificationResult:
    execution_id: str
    verification_status: str
    checks: tuple[VerificationCheck, ...]
    evidence_refs: tuple[str, ...]
    verified_at: datetime | None


def evaluate(
    *,
    execution_status: str,
    output_valid: bool,
    adapter_result: AdapterResult | None,
) -> tuple[str, tuple[VerificationCheck, ...]]:
    """根据执行状态、输出校验与 Adapter 观测给出验证状态与检查项。"""

    checks: list[VerificationCheck] = [
        VerificationCheck(
            name="EXECUTION_STATUS",
            passed=execution_status == EXECUTION_SUCCEEDED,
            detail=execution_status,
        ),
        VerificationCheck(
            name="OUTPUT_SCHEMA",
            passed=output_valid if execution_status == EXECUTION_SUCCEEDED else None,
            detail="output schema validated" if output_valid else "output schema invalid",
        ),
    ]
    if adapter_result is not None:
        checks.extend(adapter_result.checks)

    if execution_status in (EXECUTION_UNKNOWN, EXECUTION_TIMEOUT):
        return VERIFICATION_UNKNOWN, tuple(checks)
    if execution_status in (EXECUTION_FAILED, EXECUTION_CANCELLED):
        return VERIFICATION_FAILED, tuple(checks)
    if adapter_result is None:
        return VERIFICATION_PENDING, tuple(checks)
    if adapter_result.status != EXECUTION_SUCCEEDED and execution_status == EXECUTION_SUCCEEDED:
        return VERIFICATION_FAILED, tuple(checks)
    if not output_valid:
        return VERIFICATION_FAILED, tuple(checks)
    observed = [check.passed for check in adapter_result.checks]
    if observed and any(passed is False for passed in observed):
        return VERIFICATION_FAILED, tuple(checks)
    if not observed:
        return VERIFICATION_PARTIAL, tuple(checks)
    if any(passed is None for passed in observed):
        return VERIFICATION_PARTIAL, tuple(checks)
    return VERIFICATION_VERIFIED, tuple(checks)


def _view(entity: ToolVerificationRecordModel) -> ToolVerificationResult:
    raw_checks = json.loads(entity.checks)
    return ToolVerificationResult(
        execution_id=entity.execution_id,
        verification_status=entity.verification_status,
        checks=tuple(
            VerificationCheck(
                name=item["name"], passed=item.get("passed"), detail=item.get("detail")
            )
            for item in raw_checks
        ),
        evidence_refs=tuple(json.loads(entity.evidence_refs)),
        verified_at=ensure_utc(entity.verified_at),
    )


class ToolVerificationService:
    def __init__(self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._database = database
        self._clock = clock

    async def record(
        self,
        *,
        execution_id: str,
        project_id: str,
        execution_status: str,
        output_valid: bool,
        adapter_result: AdapterResult | None,
    ) -> ToolVerificationResult:
        status, checks = evaluate(
            execution_status=execution_status,
            output_valid=output_valid,
            adapter_result=adapter_result,
        )
        evidence = adapter_result.evidence_refs if adapter_result is not None else ()
        entity = ToolVerificationRecordModel(
            verification_id="ver_" + uuid4().hex[:12],
            execution_id=execution_id,
            project_id=project_id,
            verification_status=status,
            checks=json.dumps(
                [
                    {"name": check.name, "passed": check.passed, "detail": check.detail}
                    for check in checks
                ],
                ensure_ascii=False,
                sort_keys=True,
            ),
            evidence_refs=json.dumps(list(evidence), ensure_ascii=False),
            verified_at=self._clock(),
        )
        async with self._database.session() as session, transaction(session):
            await ToolVerificationRepository(session).add(entity)
        return _view(entity)

    async def latest(self, execution_id: str) -> ToolVerificationResult | None:
        async with self._database.session() as session:
            entity = await ToolVerificationRepository(session).latest(execution_id)
        return _view(entity) if entity is not None else None

    async def history(self, execution_id: str) -> list[ToolVerificationResult]:
        async with self._database.session() as session:
            entities = await ToolVerificationRepository(session).list_for_execution(execution_id)
        return [_view(entity) for entity in entities]


__all__ = ["ToolVerificationResult", "ToolVerificationService", "evaluate"]
