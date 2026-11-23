"""内置通用 Agent（E6-T19）。

启动时确保存在一个可直接使用的 ``generic_agent``：

- 只读优先：默认工具集覆盖项目/文件读取与低频安全写入，权限上限 R2；
- 预算保守：限制迭代、模型与工具调用次数，超限暂停等待人工确认；
- 幂等：已存在则不重复创建；已发布则直接复用。

本模块不包含任何厂商 SDK 调用，实际执行仍由 Agent Runtime + Model Gateway 完成。
"""

from __future__ import annotations

from core.errors import NotFoundError
from modules.agent_runtime.service import DefinitionRegistryService, DefinitionView
from modules.prompt.service import PromptService

__all__ = [
    "GENERIC_AGENT_BUDGET",
    "GENERIC_AGENT_NAME",
    "GENERIC_AGENT_PROMPT",
    "GENERIC_AGENT_TOOLS",
    "GenericAgentService",
]

GENERIC_AGENT_NAME = "generic_agent"
GENERIC_AGENT_PROMPT_NAME = "generic_agent_prompt"
GENERIC_AGENT_PROMPT = """你是 Godot AI Agent 的内置通用 Agent。

职责：
1. 先理解 Task 与项目现状，必要时使用只读工具收集证据；
2. 对复杂任务先创建 Plan，再逐步执行，每一步保持可验证；
3. 修改项目文件前先说明意图并遵守权限与审批规则；
4. 完成后汇总实际完成的变更、验证结果与剩余风险。

约束：
- 不猜测项目内容，读取失败时如实报告；
- 不执行超出权限上限或未授权范围的操作；
- 不输出隐藏推理过程或任何密钥信息。"""

GENERIC_AGENT_TOOLS = (
    "godot.project.get_info",
    "godot.project.get_settings",
    "godot.scene.list",
    "godot.scene.get",
    "godot.node.list",
    "file.read",
    "file.list",
    "file.search",
    "file.create",
    "file.write",
    "file.patch",
)

GENERIC_AGENT_BUDGET = {
    "max_iterations": 30,
    "max_model_calls": 40,
    "max_tool_calls": 60,
    "max_input_tokens": 200000,
    "max_output_tokens": 20000,
    "max_execution_seconds": 1800,
    "on_exceed": "PAUSE",
}


class GenericAgentService:
    def __init__(
        self,
        *,
        definitions: DefinitionRegistryService,
        prompts: PromptService,
    ) -> None:
        self._definitions = definitions
        self._prompts = prompts

    async def ensure(self) -> DefinitionView:
        try:
            definition = await self._definitions.get_by_name(GENERIC_AGENT_NAME)
        except NotFoundError:
            definition = None
        if definition is None:
            try:
                await self._prompts.get_active(GENERIC_AGENT_PROMPT_NAME)
            except NotFoundError:
                await self._prompts.create(
                    name=GENERIC_AGENT_PROMPT_NAME,
                    category="AGENT",
                    content=GENERIC_AGENT_PROMPT,
                )
            definition = await self._definitions.create(
                name=GENERIC_AGENT_NAME,
                model_policy_id="default_agent_policy",
                prompt_profile_id=GENERIC_AGENT_PROMPT_NAME,
                prompt_version=1,
                capabilities=(
                    "task_analysis",
                    "planning",
                    "tool_execution",
                    "result_summary",
                ),
                tool_whitelist=GENERIC_AGENT_TOOLS,
                permission_ceiling="R2",
                budget=GENERIC_AGENT_BUDGET,
            )
        if definition.status == "DRAFT":
            await self._definitions.publish(definition.definition_id)
            definition = await self._definitions.get(definition.definition_id)
        return definition
