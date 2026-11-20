"""Approval System（E4-T20）。

审批只绑定目标哈希；目标内容变化后旧审批不能继续生效。
审批决策、过期与取消均写入审计事件。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from core.errors import (
    ApprovalExpired,
    ApprovalHashMismatch,
    InvalidStateTransition,
    NotFoundError,
    ValidationFailed,
)
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.approval.models import (
    APPROVAL_APPROVED,
    APPROVAL_CANCELLED,
    APPROVAL_EXPIRED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_TYPES,
    DECISION_APPROVE,
    DECISION_CANCEL,
    DECISION_REJECT,
    DECISIONS,
    TARGET_TYPES,
    ApprovalAuditEventModel,
    ApprovalDecisionModel,
    ApprovalModel,
)
from modules.approval.repository import (
    ApprovalAuditEventRepository,
    ApprovalDecisionRepository,
    ApprovalRepository,
)

_DEFAULT_TTL_SECONDS = 24 * 3600


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


@dataclass(frozen=True)
class ApprovalView:
    approval_id: str
    project_id: str
    task_id: str | None
    attempt_id: str | None
    workflow_instance_id: str | None
    target_type: str
    target_id: str
    target_version: int | None
    target_hash: str
    approval_type: str
    status: str
    requested_by: str | None
    decided_by: str | None
    requested_at: datetime
    expires_at: datetime | None
    decided_at: datetime | None
    decision_reason: str | None
    version: int


@dataclass(frozen=True)
class DecisionView:
    decision_id: str
    approval_id: str
    decision: str
    actor_id: str
    reason: str | None
    target_hash: str
    created_at: datetime


def _approval_view(entity: ApprovalModel) -> ApprovalView:
    return ApprovalView(
        approval_id=entity.approval_id,
        project_id=entity.project_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        workflow_instance_id=entity.workflow_instance_id,
        target_type=entity.target_type,
        target_id=entity.target_id,
        target_version=entity.target_version,
        target_hash=entity.target_hash,
        approval_type=entity.approval_type,
        status=entity.status,
        requested_by=entity.requested_by,
        decided_by=entity.decided_by,
        requested_at=ensure_utc(entity.requested_at),
        expires_at=ensure_utc(entity.expires_at) if entity.expires_at else None,
        decided_at=ensure_utc(entity.decided_at) if entity.decided_at else None,
        decision_reason=entity.decision_reason,
        version=entity.version,
    )


def _decision_view(entity: ApprovalDecisionModel) -> DecisionView:
    return DecisionView(
        decision_id=entity.decision_id,
        approval_id=entity.approval_id,
        decision=entity.decision,
        actor_id=entity.actor_id,
        reason=entity.reason,
        target_hash=entity.target_hash,
        created_at=ensure_utc(entity.created_at),
    )


class ApprovalService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._clock = clock
        self._logger = get_logger("backend.approval")

    async def create(
        self,
        *,
        project_id: str,
        target_type: str,
        target_id: str,
        target_hash: str,
        approval_type: str,
        task_id: str | None = None,
        attempt_id: str | None = None,
        workflow_instance_id: str | None = None,
        target_version: int | None = None,
        requested_by: str | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> ApprovalView:
        if target_type not in TARGET_TYPES:
            raise ValidationFailed("target_type 非法", details={"target_type": target_type})
        if approval_type not in APPROVAL_TYPES:
            raise ValidationFailed("approval_type 非法", details={"approval_type": approval_type})
        if not target_hash:
            raise ValidationFailed("审批必须绑定目标哈希")
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = ApprovalModel(
                approval_id=_new_id("apr_"),
                project_id=project_id,
                task_id=task_id,
                attempt_id=attempt_id,
                workflow_instance_id=workflow_instance_id,
                target_type=target_type,
                target_id=target_id,
                target_version=target_version,
                target_hash=target_hash,
                approval_type=approval_type,
                status=APPROVAL_PENDING,
                requested_by=requested_by,
                decided_by=None,
                requested_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                decided_at=None,
                decision_reason=None,
                version=1,
            )
            await ApprovalRepository(session).add(entity)
            await self._audit(session, entity.approval_id, "REQUESTED", requested_by, {}, now)
            await session.flush()
            view = _approval_view(entity)
        log_event(self._logger, logging.INFO, "approval_requested", component="approval")
        return view

    async def get(self, approval_id: str) -> ApprovalView:
        async with self._database.session() as session:
            entity = await ApprovalRepository(session).get(approval_id)
        if entity is None:
            raise NotFoundError("审批不存在", details={"approval_id": approval_id})
        return _approval_view(entity)

    async def list(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await ApprovalRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_approval_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def list_decisions(self, approval_id: str) -> list[DecisionView]:
        async with self._database.session() as session:
            rows = await ApprovalDecisionRepository(session).list_by_approval(approval_id)
        return [_decision_view(row) for row in rows]

    async def approve(
        self,
        approval_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
        current_target_hash: str | None = None,
    ) -> ApprovalView:
        return await self.decide(
            approval_id,
            DECISION_APPROVE,
            actor_id=actor_id,
            reason=reason,
            current_target_hash=current_target_hash,
        )

    async def reject(
        self,
        approval_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
        current_target_hash: str | None = None,
    ) -> ApprovalView:
        return await self.decide(
            approval_id,
            DECISION_REJECT,
            actor_id=actor_id,
            reason=reason,
            current_target_hash=current_target_hash,
        )

    async def cancel(
        self, approval_id: str, *, actor_id: str, reason: str | None = None
    ) -> ApprovalView:
        return await self.decide(approval_id, DECISION_CANCEL, actor_id=actor_id, reason=reason)

    async def decide(
        self,
        approval_id: str,
        decision: str,
        *,
        actor_id: str,
        reason: str | None = None,
        current_target_hash: str | None = None,
    ) -> ApprovalView:
        if decision not in DECISIONS:
            raise ValidationFailed("审批决策非法", details={"decision": decision})
        now = self._clock()
        view: ApprovalView | None = None
        expired = False
        async with self._database.session() as session, transaction(session):
            repository = ApprovalRepository(session)
            entity = await repository.get(approval_id)
            if entity is None:
                raise NotFoundError("审批不存在", details={"approval_id": approval_id})

            expected_status = {
                DECISION_APPROVE: APPROVAL_APPROVED,
                DECISION_REJECT: APPROVAL_REJECTED,
                DECISION_CANCEL: APPROVAL_CANCELLED,
            }[decision]
            if entity.status == expected_status:
                return _approval_view(entity)
            if entity.status != APPROVAL_PENDING:
                raise InvalidStateTransition(
                    "审批当前状态不能再决策",
                    details={"approval_id": approval_id, "status": entity.status},
                )
            if entity.expires_at is not None and now > ensure_utc(entity.expires_at):
                entity.status = APPROVAL_EXPIRED
                entity.version += 1
                await self._audit(session, approval_id, "EXPIRED", actor_id, {}, now)
                await session.flush()
                expired = True
            elif current_target_hash is not None and current_target_hash != entity.target_hash:
                raise ApprovalHashMismatch(
                    "审批绑定的目标哈希与当前内容不一致",
                    details={"approval_id": approval_id},
                )
            else:
                entity.status = expected_status
                entity.decided_by = actor_id
                entity.decided_at = now
                entity.decision_reason = reason
                entity.version += 1
                await ApprovalDecisionRepository(session).add(
                    ApprovalDecisionModel(
                        decision_id=_new_id("apd_"),
                        approval_id=approval_id,
                        decision=decision,
                        actor_id=actor_id,
                        reason=reason,
                        target_hash=current_target_hash or entity.target_hash,
                        created_at=now,
                    )
                )
                await self._audit(
                    session,
                    approval_id,
                    decision,
                    actor_id,
                    {"reason": reason},
                    now,
                )
                await session.flush()
                view = _approval_view(entity)
        if expired or view is None:
            raise ApprovalExpired("审批已过期", details={"approval_id": approval_id})
        log_event(self._logger, logging.INFO, "approval_decided", component="approval")
        return view

    async def expire_stale(self) -> int:
        now = self._clock()
        expired = 0
        async with self._database.session() as session, transaction(session):
            rows = await ApprovalRepository(session).list_pending()
            for entity in rows:
                if entity.expires_at is not None and now > ensure_utc(entity.expires_at):
                    entity.status = APPROVAL_EXPIRED
                    entity.version += 1
                    await self._audit(session, entity.approval_id, "EXPIRED", "system", {}, now)
                    expired += 1
            await session.flush()
        return expired

    async def _audit(
        self,
        session,
        approval_id: str,
        event_type: str,
        actor_id: str | None,
        details: dict[str, Any],
        now: datetime,
    ) -> None:
        await ApprovalAuditEventRepository(session).add(
            ApprovalAuditEventModel(
                audit_event_id=_new_id("apa_"),
                approval_id=approval_id,
                event_type=event_type,
                actor_id=actor_id,
                details=json.dumps(details, ensure_ascii=False, sort_keys=True),
                occurred_at=now,
            )
        )


def format_approval(view: ApprovalView) -> dict[str, Any]:
    return {
        "approval_id": view.approval_id,
        "project_id": view.project_id,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "workflow_instance_id": view.workflow_instance_id,
        "target_type": view.target_type,
        "target_id": view.target_id,
        "target_version": view.target_version,
        "target_hash": view.target_hash,
        "approval_type": view.approval_type,
        "status": view.status,
        "requested_by": view.requested_by,
        "decided_by": view.decided_by,
        "requested_at": isoformat(view.requested_at),
        "expires_at": isoformat(view.expires_at) if view.expires_at else None,
        "decided_at": isoformat(view.decided_at) if view.decided_at else None,
        "decision_reason": view.decision_reason,
        "version": view.version,
    }


def format_decision(view: DecisionView) -> dict[str, Any]:
    return {
        "decision_id": view.decision_id,
        "approval_id": view.approval_id,
        "decision": view.decision,
        "actor_id": view.actor_id,
        "reason": view.reason,
        "target_hash": view.target_hash,
        "created_at": isoformat(view.created_at),
    }
