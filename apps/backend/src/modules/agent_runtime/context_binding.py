"""Context Binding（E6-T09）。

把 E5 的 Context Assembly 与 Prompt 接入 Agent Runtime：

- 使用 Instance 冻结的 Prompt 版本与 Context Profile，不读取最新版本；
- Context Budget 超出时失败关闭，不做静默裁剪；
- 输出可直接交给 Model Binding 的上下文文本。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from core.errors import AgentBudgetExceeded
from modules.agent_runtime.instance import ConfigSnapshotView, InstanceView
from modules.context.service import (
    ContextAssemblyRequest,
    ContextAssemblyService,
    ContextLayer,
)
from modules.prompt.service import PromptService


@dataclass(frozen=True, slots=True)
class ContextBundle:
    context_id: str
    context_version: int
    prompt_id: str
    system_prompt: str
    context_text: str
    token_estimate: int
    warnings: tuple[str, ...]


def _render_layers(layers: tuple[ContextLayer, ...]) -> str:
    rendered: list[str] = []
    for layer in layers:
        payload = json.dumps(dict(layer.content), ensure_ascii=False, sort_keys=True)
        rendered.append(f"[{layer.layer}] ({layer.origin}) {payload}")
    return "\n".join(rendered)


class AgentContextBindingService:
    def __init__(
        self,
        *,
        prompts: PromptService,
        contexts: ContextAssemblyService,
    ) -> None:
        self._prompts = prompts
        self._contexts = contexts

    async def build(self, instance: InstanceView, snapshot: ConfigSnapshotView) -> ContextBundle:
        prompt = await self._prompts.get_version(
            snapshot.prompt_profile_id, snapshot.prompt_version
        )
        token_budget = snapshot.budget.get("max_context_tokens")
        request = ContextAssemblyRequest(
            project_id=instance.project_id,
            task_id=instance.task_id,
            attempt_id=instance.attempt_id,
            agent_definition_id=instance.agent_definition_id,
            context_profile=snapshot.context_profile_id,
            token_budget=int(token_budget) if token_budget is not None else None,
        )
        result = await self._contexts.assemble(request)
        if result.budget_exceeded:
            raise AgentBudgetExceeded(
                "Context 超出预算，不能静默裁剪",
                details={
                    "instance_id": instance.instance_id,
                    "context_id": result.context_id,
                    "token_estimate": result.token_estimate,
                    "token_budget": result.token_budget,
                },
            )
        return ContextBundle(
            context_id=result.context_id,
            context_version=result.context_version,
            prompt_id=prompt.prompt_id,
            system_prompt=prompt.content,
            context_text=_render_layers(result.layers),
            token_estimate=result.token_estimate,
            warnings=result.warnings,
        )


__all__ = ["AgentContextBindingService", "ContextBundle"]
