"""工具操作审计（E5-T25）。

审计记录只追加，不提供修改或删除入口；输入输出先按敏感键脱敏再截断摘要。
历史记录不能被业务逻辑改写，查询必须经过项目访问校验。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.logging import redact_text
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.access.service import ProjectAccessService
from modules.tool.models import ACTOR_TYPE_USER, TOOL_ACTOR_TYPES, ToolAuditRecordModel
from modules.tool.repository import ToolAuditRepository

MAX_SUMMARY_LENGTH = 1024
MAX_VALUE_LENGTH = 256
_SENSITIVE_KEY = re.compile(
    r"password|secret|token|credential|api[_-]?key|private[_-]?key", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class ToolAuditView:
    audit_id: str
    execution_id: str
    project_id: str
    task_id: str | None
    attempt_id: str | None
    actor_type: str
    actor_id: str | None
    tool_id: str
    tool_name: str
    tool_version: int
    risk_level: str
    approval_id: str | None
    input_summary: str
    output_summary: str | None
    execution_status: str
    failure_reason: str | None
    created_at: datetime


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "***" if _SENSITIVE_KEY.search(str(key)) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)[:MAX_VALUE_LENGTH]
    return value


def summarize(payload: Mapping[str, Any] | None) -> str | None:
    """脱敏并截断为可审计摘要；超长时保留前 1024 字符。"""

    if payload is None:
        return None
    text = json.dumps(_sanitize(payload), ensure_ascii=False, sort_keys=True, default=str)
    return text[:MAX_SUMMARY_LENGTH]


def _view(entity: ToolAuditRecordModel) -> ToolAuditView:
    return ToolAuditView(
        audit_id=entity.audit_id,
        execution_id=entity.execution_id,
        project_id=entity.project_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        actor_type=entity.actor_type,
        actor_id=entity.actor_id,
        tool_id=entity.tool_id,
        tool_name=entity.tool_name,
        tool_version=entity.tool_version,
        risk_level=entity.risk_level,
        approval_id=entity.approval_id,
        input_summary=entity.input_summary,
        output_summary=entity.output_summary,
        execution_status=entity.execution_status,
        failure_reason=entity.failure_reason,
        created_at=ensure_utc(entity.created_at),
    )


class ToolAuditService:
    def __init__(self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._database = database
        self._clock = clock

    async def record(
        self,
        *,
        execution_id: str,
        project_id: str,
        actor_type: str = ACTOR_TYPE_USER,
        actor_id: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        tool_id: str,
        tool_name: str,
        tool_version: int,
        risk_level: str,
        execution_status: str,
        approval_id: str | None = None,
        input_payload: Mapping[str, Any] | None = None,
        output_payload: Mapping[str, Any] | None = None,
        failure_reason: str | None = None,
    ) -> ToolAuditView:
        if actor_type not in TOOL_ACTOR_TYPES:
            raise ValueError(f"actor_type 非法: {actor_type}")
        entity = ToolAuditRecordModel(
            audit_id="tau_" + uuid4().hex[:12],
            execution_id=execution_id,
            project_id=project_id,
            task_id=task_id,
            attempt_id=attempt_id,
            actor_type=actor_type,
            actor_id=actor_id,
            tool_id=tool_id,
            tool_name=tool_name,
            tool_version=tool_version,
            risk_level=risk_level,
            approval_id=approval_id,
            input_summary=summarize(input_payload) or "{}",
            output_summary=summarize(output_payload),
            execution_status=execution_status,
            failure_reason=failure_reason[:128] if failure_reason else None,
            created_at=self._clock(),
        )
        async with self._database.session() as session, transaction(session):
            await ToolAuditRepository(session).add(entity)
        return _view(entity)

    async def list_for_project(
        self,
        project_id: str,
        *,
        access: ProjectAccessService,
        session_id: str,
        client_id: str,
        tool_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """审计查询受项目访问控制：调用方必须持有该项目的有效访问。"""

        await access.get_current(project_id=project_id, session_id=session_id, client_id=client_id)
        async with self._database.session() as session:
            page = await ToolAuditRepository(session).list_project_records(
                project_id=project_id, tool_id=tool_id, limit=limit, offset=offset
            )
        return {
            "items": [format_audit(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def list_for_execution(self, execution_id: str) -> list[ToolAuditView]:
        async with self._database.session() as session:
            entities = await ToolAuditRepository(session).list_for_execution(execution_id)
        return [_view(entity) for entity in entities]


def format_audit(view: ToolAuditView) -> dict[str, Any]:
    return {
        "audit_id": view.audit_id,
        "execution_id": view.execution_id,
        "project_id": view.project_id,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "actor_type": view.actor_type,
        "actor_id": view.actor_id,
        "tool_id": view.tool_id,
        "tool_name": view.tool_name,
        "tool_version": view.tool_version,
        "risk_level": view.risk_level,
        "approval_id": view.approval_id,
        "input_summary": view.input_summary,
        "output_summary": view.output_summary,
        "execution_status": view.execution_status,
        "failure_reason": view.failure_reason,
        "created_at": isoformat(view.created_at),
    }


__all__ = ["ToolAuditService", "ToolAuditView", "format_audit", "summarize"]
