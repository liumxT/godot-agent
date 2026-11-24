"""Tool Binding & Permission（E6-T11）。

Agent Runtime 不得直接操作项目文件、Scene、Inspector、Shell 或 Godot Editor，
所有工具调用都必须经过 E5 Tool System：

- 工具必须来自 Instance 冻结白名单且处于启用状态；
- 权限上限来自 Instance 快照，不允许请求放宽；
- 风险等级由 ``ToolRiskPolicy`` 评估，高风险由执行循环转入审批等待。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from core.errors import AgentPermissionDenied, NotFoundError
from modules.agent_runtime.instance import ConfigSnapshotView, InstanceView
from modules.model_gateway.schemas import ToolDefinition
from modules.tool.execution import ToolExecutionRequest, ToolExecutionResult, ToolExecutionService
from modules.tool.permissions import AgentPolicy
from modules.tool.registry import ToolRegistryService, ToolView
from modules.tool.risk import RiskAssessment, ToolRiskPolicy

__all__ = ["AgentToolBindingService", "tool_alias"]

_ALIAS_INVALID = re.compile(r"[^A-Za-z0-9_\-]")


def tool_alias(name: str) -> str:
    """模型侧工具名只允许字母、数字、下划线与连字符。"""

    return _ALIAS_INVALID.sub("_", name.strip())[:64]


class AgentToolBindingService:
    def __init__(
        self,
        *,
        tools: ToolRegistryService,
        execution: ToolExecutionService,
        risk_policy: ToolRiskPolicy | None = None,
    ) -> None:
        self._tools = tools
        self._execution = execution
        self._risk = risk_policy or ToolRiskPolicy()

    async def resolve(self, snapshot: ConfigSnapshotView, reference: str) -> ToolView:
        target = (reference or "").strip()
        if not target:
            raise AgentPermissionDenied("工具引用不能为空")
        for tool in await self.whitelist_tools(snapshot):
            if target in {tool.tool_id, tool.name, tool_alias(tool.name)}:
                return tool
        raise AgentPermissionDenied(
            "工具不在 Agent 白名单内",
            details={"tool": reference, "instance_snapshot": snapshot.snapshot_id},
        )

    async def whitelist_tools(self, snapshot: ConfigSnapshotView) -> tuple[ToolView, ...]:
        tools: list[ToolView] = []
        for tool_id in snapshot.tool_whitelist:
            try:
                tool = await self._tools.get(tool_id)
            except NotFoundError as exc:
                raise AgentPermissionDenied(
                    "冻结的工具已不存在", details={"tool_id": tool_id}
                ) from exc
            if not tool.enabled:
                raise AgentPermissionDenied("冻结的工具已停用", details={"tool_id": tool_id})
            tools.append(tool)
        return tuple(tools)

    async def definitions(self, snapshot: ConfigSnapshotView) -> tuple[ToolDefinition, ...]:
        return tuple(
            ToolDefinition(
                name=tool_alias(tool.name),
                description=tool.description,
                parameters=tool.input_schema,
            )
            for tool in await self.whitelist_tools(snapshot)
        )

    async def policy(self, snapshot: ConfigSnapshotView) -> AgentPolicy:
        tools = await self.whitelist_tools(snapshot)
        return self.build_policy(snapshot, tools)

    @staticmethod
    def build_policy(snapshot: ConfigSnapshotView, tools: Sequence[ToolView]) -> AgentPolicy:
        capabilities: set[str] = set()
        for tool in tools:
            capabilities.update(tool.required_capabilities)
        return AgentPolicy(
            definition_id=snapshot.agent_definition_id,
            allowed_tool_ids=frozenset(snapshot.tool_whitelist),
            allowed_capabilities=frozenset(capabilities),
            max_risk_level=snapshot.permission_ceiling,
        )

    def assess(self, tool: ToolView) -> RiskAssessment:
        return self._risk.assess(tool)

    async def execute(
        self,
        *,
        instance: InstanceView,
        snapshot: ConfigSnapshotView,
        tool: ToolView,
        tool_input: dict,
        resource_scope: tuple[str, ...] = (),
        approval_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolExecutionResult:
        if not instance.session_id or not instance.client_id:
            raise AgentPermissionDenied(
                "Agent Instance 缺少会话绑定，不能执行工具",
                details={"instance_id": instance.instance_id},
            )
        request = ToolExecutionRequest(
            project_id=instance.project_id,
            tool_id=tool.tool_id,
            input=tool_input,
            idempotency_key=idempotency_key,
            task_id=instance.task_id,
            attempt_id=instance.attempt_id,
            agent_instance_id=instance.instance_id,
            tool_version=tool.version,
            approval_id=approval_id,
            session_id=instance.session_id,
            client_id=instance.client_id,
            actor_id=f"agent:{instance.instance_id}",
            resource_scope=resource_scope,
        )
        return await self._execution.execute(request, agent_policy=await self.policy(snapshot))
