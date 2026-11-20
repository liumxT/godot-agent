"""工具审批集成（E5-T21）。

审批必须绑定工具请求的实际内容哈希：工具、版本、输入参数与资源范围。
审批通过后执行前仍需重新校验版本、参数哈希、项目范围与有效期；
内容一旦变化，旧审批立即失效（``ApprovalHashMismatch``）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import ApprovalExpired, ApprovalHashMismatch, PermissionDenied
from core.security.tokens import ensure_utc, utcnow
from modules.approval.models import (
    APPROVAL_APPROVED,
    APPROVAL_EXPIRED,
    APPROVAL_PENDING,
    APPROVAL_TYPE_HIGH_RISK_OPERATION,
    TARGET_TOOL_REQUEST,
)
from modules.approval.service import ApprovalService, ApprovalView

__all__ = ["ToolApprovalGate"]


@dataclass(frozen=True, slots=True)
class ToolApprovalScope:
    project_id: str
    tool_id: str
    tool_version: int
    input_payload: Mapping[str, Any]
    resource_scope: tuple[str, ...]

    @property
    def target_id(self) -> str:
        return f"{self.tool_id}@{self.tool_version}"

    def content_hash(self) -> str:
        payload = {
            "project_id": self.project_id,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "input": dict(self.input_payload),
            "resource_scope": list(self.resource_scope),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ToolApprovalGate:
    def __init__(self, approvals: ApprovalService, *, clock: Any = utcnow) -> None:
        self._approvals = approvals
        self._clock = clock

    async def request(
        self,
        scope: ToolApprovalScope,
        *,
        requested_by: str,
        task_id: str | None = None,
        attempt_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> ApprovalView:
        kwargs = {}
        if ttl_seconds is not None:
            kwargs["ttl_seconds"] = ttl_seconds
        return await self._approvals.create(
            project_id=scope.project_id,
            target_type=TARGET_TOOL_REQUEST,
            target_id=scope.target_id,
            target_hash=scope.content_hash(),
            approval_type=APPROVAL_TYPE_HIGH_RISK_OPERATION,
            task_id=task_id,
            attempt_id=attempt_id,
            target_version=scope.tool_version,
            requested_by=requested_by,
            **kwargs,
        )

    async def ensure_approved(self, approval_id: str, scope: ToolApprovalScope) -> ApprovalView:
        approval = await self._approvals.get(approval_id)
        if approval.status == APPROVAL_EXPIRED:
            raise ApprovalExpired("工具审批已过期", details={"approval_id": approval_id})
        if approval.status == APPROVAL_PENDING:
            raise PermissionDenied(
                "工具审批尚未通过", details={"approval_id": approval_id, "status": approval.status}
            )
        if approval.status != APPROVAL_APPROVED:
            raise PermissionDenied(
                "工具审批未通过", details={"approval_id": approval_id, "status": approval.status}
            )
        expires_at: datetime | None = (
            ensure_utc(approval.expires_at) if approval.expires_at else None
        )
        if expires_at is not None and expires_at <= self._clock():
            raise ApprovalExpired("工具审批已过期", details={"approval_id": approval_id})
        if approval.project_id != scope.project_id:
            raise PermissionDenied(
                "审批绑定的项目不一致",
                details={"approval_id": approval_id, "project_id": approval.project_id},
            )
        if approval.target_type != TARGET_TOOL_REQUEST or approval.target_id != scope.target_id:
            raise ApprovalHashMismatch(
                "审批与当前工具请求不一致",
                details={
                    "approval_target": approval.target_id,
                    "request_target": scope.target_id,
                },
            )
        if approval.target_hash != scope.content_hash():
            raise ApprovalHashMismatch(
                "工具请求内容已变化，必须重新审批",
                details={"approval_id": approval_id},
            )
        return approval
