"""工具权限检查（E5-T19）。

检查顺序：身份 → 项目访问 → 任务状态 → Agent 上限 → 工具状态与权限 →
资源范围 → 会话 → 审批 → 风险策略。任何未知条件默认拒绝。

Agent Instance 的权限不能超过 Agent Definition 上限；请求参数不能自行扩大资源范围。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.errors import (
    AppError,
    NotFoundError,
    PermissionDenied,
    ProjectAccessDenied,
    ValidationFailed,
)
from modules.access.service import ProjectAccessService
from modules.approval.service import ApprovalView
from modules.task.models import TERMINAL_TASK_STATUSES
from modules.task.service import TaskService
from modules.tool.approval import ToolApprovalGate, ToolApprovalScope
from modules.tool.models import RISK_NORMAL_WRITE, RISK_RANK, TOOL_RISK_LEVELS
from modules.tool.registry import ToolRegistryService, ToolView
from modules.tool.risk import RiskAssessment, ToolRiskPolicy

__all__ = [
    "AgentPolicy",
    "PermissionDecision",
    "ToolPermissionEngine",
    "ToolPermissionRequest",
]

PERMISSION_PROJECT_READ = "project.read"
PERMISSION_PROJECT_WRITE = "project.write"
PERMISSION_PROJECT_ADMIN = "project.admin"
ACCESS_LEVEL_PERMISSIONS = {
    "viewer": frozenset({PERMISSION_PROJECT_READ}),
    "editor": frozenset({PERMISSION_PROJECT_READ, PERMISSION_PROJECT_WRITE}),
    "owner": frozenset(
        {PERMISSION_PROJECT_READ, PERMISSION_PROJECT_WRITE, PERMISSION_PROJECT_ADMIN}
    ),
}
_WRITE_PERMISSIONS = frozenset({PERMISSION_PROJECT_WRITE, PERMISSION_PROJECT_ADMIN})

OPERATION_EXECUTE = "EXECUTE"


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    definition_id: str
    allowed_tool_ids: frozenset[str]
    allowed_capabilities: frozenset[str]
    max_risk_level: str = RISK_NORMAL_WRITE


@dataclass(frozen=True, slots=True)
class ToolPermissionRequest:
    user_id: str
    project_id: str
    session_id: str
    client_id: str
    tool_id: str
    tool_version: int | None = None
    operation: str = OPERATION_EXECUTE
    resource_scope: tuple[str, ...] = ()
    task_id: str | None = None
    agent_instance_id: str | None = None
    approval_id: str | None = None
    requested_risk_level: str | None = None
    input_payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reasons: tuple[str, ...]
    access_level: str | None
    risk: RiskAssessment | None
    approval: ApprovalView | None
    tool: ToolView | None


class ToolPermissionEngine:
    def __init__(
        self,
        *,
        access: ProjectAccessService,
        tasks: TaskService,
        tools: ToolRegistryService,
        approvals: ToolApprovalGate,
        risk_policy: ToolRiskPolicy | None = None,
    ) -> None:
        self._access = access
        self._tasks = tasks
        self._tools = tools
        self._approvals = approvals
        self._risk = risk_policy or ToolRiskPolicy()

    async def check(
        self,
        request: ToolPermissionRequest,
        *,
        agent_policy: AgentPolicy | None = None,
    ) -> PermissionDecision:
        reasons: list[str] = []
        tool = await self._load_tool(request, reasons)
        risk = None
        if tool is not None and tool.enabled:
            risk = self._risk.assess(tool, requested_level=request.requested_risk_level)

        if not request.user_id.strip():
            reasons.append("USER_REQUIRED")

        access_level = await self._check_access(request, reasons)
        await self._check_task(request, reasons)
        if agent_policy is not None and tool is not None:
            self._check_agent_policy(agent_policy, tool, risk, reasons)
        if tool is not None and access_level is not None:
            self._check_permissions(tool, access_level, reasons)
        if tool is not None:
            self._check_resource_scope(tool, request, reasons)
        if tool is None or not tool.enabled:
            reasons.append("TOOL_UNAVAILABLE")

        approval = None
        if risk is not None and risk.approval_required:
            approval = await self._check_approval(request, tool, reasons)

        return PermissionDecision(
            allowed=not reasons,
            reasons=tuple(dict.fromkeys(reasons)),
            access_level=access_level,
            risk=risk,
            approval=approval,
            tool=tool,
        )

    async def require(
        self,
        request: ToolPermissionRequest,
        *,
        agent_policy: AgentPolicy | None = None,
    ) -> PermissionDecision:
        decision = await self.check(request, agent_policy=agent_policy)
        if not decision.allowed:
            raise PermissionDenied(
                "工具执行权限检查未通过",
                details={
                    "tool_id": request.tool_id,
                    "project_id": request.project_id,
                    "reasons": list(decision.reasons),
                },
            )
        return decision

    async def _load_tool(
        self, request: ToolPermissionRequest, reasons: list[str]
    ) -> ToolView | None:
        try:
            tool = await self._tools.get(request.tool_id)
        except NotFoundError:
            reasons.append("TOOL_NOT_FOUND")
            return None
        if request.tool_version is not None and tool.version != request.tool_version:
            reasons.append("TOOL_VERSION_MISMATCH")
            return None
        if request.operation != OPERATION_EXECUTE:
            reasons.append("TOOL_OPERATION_UNSUPPORTED")
        return tool

    async def _check_access(self, request: ToolPermissionRequest, reasons: list[str]) -> str | None:
        if not request.session_id or not request.client_id:
            reasons.append("SESSION_REQUIRED")
            return None
        try:
            access = await self._access.get_current(
                project_id=request.project_id,
                session_id=request.session_id,
                client_id=request.client_id,
            )
        except ProjectAccessDenied:
            reasons.append("PROJECT_ACCESS_DENIED")
            return None
        return access.access_level

    async def _check_task(self, request: ToolPermissionRequest, reasons: list[str]) -> None:
        if request.task_id is None:
            return
        try:
            task = await self._tasks.get(request.task_id)
        except NotFoundError:
            reasons.append("TASK_NOT_FOUND")
            return
        if task.project_id != request.project_id:
            reasons.append("TASK_PROJECT_MISMATCH")
        if task.status in TERMINAL_TASK_STATUSES:
            reasons.append("TASK_TERMINAL")

    @staticmethod
    def _check_agent_policy(
        policy: AgentPolicy,
        tool: ToolView,
        risk: RiskAssessment | None,
        reasons: list[str],
    ) -> None:
        if policy.max_risk_level not in TOOL_RISK_LEVELS:
            raise ValidationFailed(
                "AgentPolicy.max_risk_level 非法",
                details={"max_risk_level": policy.max_risk_level},
            )
        if tool.tool_id not in policy.allowed_tool_ids:
            reasons.append("AGENT_TOOL_NOT_ALLOWED")
        missing = set(tool.required_capabilities) - set(policy.allowed_capabilities)
        if missing:
            reasons.append("AGENT_CAPABILITY_DENIED")
        if risk is not None and RISK_RANK[risk.level] > RISK_RANK[policy.max_risk_level]:
            reasons.append("AGENT_RISK_EXCEEDED")

    @staticmethod
    def _check_permissions(tool: ToolView, access_level: str, reasons: list[str]) -> None:
        granted = ACCESS_LEVEL_PERMISSIONS.get(access_level, frozenset())
        if set(tool.required_permissions) - granted:
            reasons.append("MISSING_TOOL_PERMISSION")

    @staticmethod
    def _check_resource_scope(
        tool: ToolView, request: ToolPermissionRequest, reasons: list[str]
    ) -> None:
        for ref in request.resource_scope:
            if not ref.strip() or ":" not in ref:
                reasons.append("RESOURCE_SCOPE_INVALID")
                break
        requires_scope = bool(set(tool.required_permissions) & _WRITE_PERMISSIONS)
        if requires_scope and not request.resource_scope:
            reasons.append("RESOURCE_SCOPE_REQUIRED")

    async def _check_approval(
        self,
        request: ToolPermissionRequest,
        tool: ToolView | None,
        reasons: list[str],
    ) -> ApprovalView | None:
        if tool is None:
            return None
        if request.approval_id is None:
            reasons.append("APPROVAL_REQUIRED")
            return None
        scope = ToolApprovalScope(
            project_id=request.project_id,
            tool_id=tool.tool_id,
            tool_version=tool.version,
            input_payload=request.input_payload or {},
            resource_scope=request.resource_scope,
        )
        try:
            return await self._approvals.ensure_approved(request.approval_id, scope)
        except AppError as exc:
            reasons.append(f"APPROVAL_INVALID:{exc.code}")
            return None
