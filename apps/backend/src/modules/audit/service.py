"""审计服务（E2-T11）。

- 审计记录与业务日志分离：独立表 + ``backend.audit`` logger；
- 只追加，不提供修改/删除接口；
- ``details`` 只允许白名单键，并对值做脱敏与截断；
- 敏感操作审计失败时默认拒绝（``AUDIT_FAILED``），普通操作 fail-open 并记 ERROR。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from core.errors import AuditFailed
from core.logging import context_values, get_logger, log_event, redact_text
from core.security.tokens import ensure_utc, generate_audit_id, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.audit.models import (
    DECISION_ALLOW,
    DECISION_DENY,
    AuditEventModel,
)
from modules.audit.repository import AuditRepository

DEFAULT_AUDIT_FAIL_CLOSED = True
MAX_DETAIL_VALUE_LENGTH = 128

# ``details`` 白名单：只允许与授权判定、资源定位相关的非敏感键。
ALLOWED_DETAIL_KEYS = frozenset(
    {
        "access_level",
        "action",
        "client_type",
        "decision",
        "endpoint",
        "method",
        "policy_id",
        "project_id",
        "role",
        "status_code",
        "target_session_id",
        "token_id",
    }
)


@dataclass(frozen=True)
class AuditView:
    audit_id: str
    actor_id: str | None
    client_id: str | None
    session_id: str | None
    action: str
    resource: str | None
    decision: str
    reason: str | None
    timestamp: datetime
    correlation_id: str | None
    details: dict[str, object] = field(default_factory=dict)


def sanitize_details(details: dict[str, object] | None) -> dict[str, object]:
    """丢弃非白名单键，并对字符串值脱敏、截断。"""

    if not details:
        return {}
    cleaned: dict[str, object] = {}
    for key, value in details.items():
        if key not in ALLOWED_DETAIL_KEYS or value is None:
            continue
        if isinstance(value, bool | int | float):
            cleaned[key] = value
        elif isinstance(value, str):
            cleaned[key] = redact_text(value)[:MAX_DETAIL_VALUE_LENGTH]
    return cleaned


def _view(entity: AuditEventModel) -> AuditView:
    return AuditView(
        audit_id=entity.audit_id,
        actor_id=entity.actor_id,
        client_id=entity.client_id,
        session_id=entity.session_id,
        action=entity.action,
        resource=entity.resource,
        decision=entity.decision,
        reason=entity.reason,
        timestamp=ensure_utc(entity.timestamp),
        correlation_id=entity.correlation_id,
        details=json.loads(entity.details) if entity.details else {},
    )


class AuditService:
    """写入与查询审计事件。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        fail_closed: bool = DEFAULT_AUDIT_FAIL_CLOSED,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._fail_closed = fail_closed
        self._clock = clock
        self._logger = get_logger("backend.audit")

    async def record(
        self,
        action: str,
        *,
        actor_id: str | None = None,
        client_id: str | None = None,
        session_id: str | None = None,
        resource: str | None = None,
        decision: str = DECISION_ALLOW,
        reason: str | None = None,
        details: dict[str, object] | None = None,
        sensitive: bool = False,
        correlation_id: str | None = None,
    ) -> AuditView | None:
        """写入一条审计事件；敏感操作失败时抛出 ``AuditFailed``。"""

        entity = AuditEventModel(
            audit_id=generate_audit_id(),
            actor_id=actor_id,
            client_id=client_id,
            session_id=session_id,
            action=action,
            resource=resource,
            decision=decision,
            reason=reason,
            timestamp=self._clock(),
            correlation_id=correlation_id or context_values().get("correlation_id"),
            details=json.dumps(sanitize_details(details), ensure_ascii=False, sort_keys=True),
        )
        try:
            async with self._database.session() as session, transaction(session):
                await AuditRepository(session).add(entity)
        except Exception as exc:
            log_event(
                self._logger,
                logging.ERROR,
                "audit_write_failed",
                component="audit",
                error_code="AUDIT_FAILED",
            )
            if self._fail_closed and sensitive:
                raise AuditFailed("审计写入失败，操作已拒绝") from exc
            return None

        log_event(
            self._logger,
            logging.INFO,
            action.replace(".", "_"),
            component="audit",
            error_code=reason if decision == DECISION_DENY else None,
        )
        return _view(entity)

    async def recent(self, *, limit: int = 50) -> list[AuditView]:
        async with self._database.session() as session:
            entities = await AuditRepository(session).recent(limit=limit)
        return [_view(entity) for entity in entities]

    async def for_action(self, action: str, *, limit: int = 50) -> list[AuditView]:
        async with self._database.session() as session:
            entities = await AuditRepository(session).for_action(action, limit=limit)
        return [_view(entity) for entity in entities]


__all__ = [
    "ALLOWED_DETAIL_KEYS",
    "DECISION_ALLOW",
    "DECISION_DENY",
    "AuditService",
    "AuditView",
    "sanitize_details",
]
