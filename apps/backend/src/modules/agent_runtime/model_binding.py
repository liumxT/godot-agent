"""Model Binding & Policy（E6-T10）。

Agent Runtime 只通过 Model Gateway 调用模型：

- 模型选择顺序：Instance 快照显式模型 → Model Policy 默认模型；
- 显式指定模型不可用时不做静默切换，交由执行循环按策略处理；
- 能力未知不视为支持（由 E5 路由保证）；
- 请求携带 Agent Instance / Execution 追踪信息。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.agent_runtime.context_binding import ContextBundle
from modules.agent_runtime.instance import ConfigSnapshotView, InstanceView
from modules.agent_runtime.service import DefinitionRegistryService
from modules.model_gateway.gateway import ModelGatewayService
from modules.model_gateway.routing import ModelRoutingRequest, ModelRoutingService
from modules.model_gateway.schemas import (
    MESSAGE_USER,
    RESPONSE_FORMAT_JSON_OBJECT,
    ModelInvocationRequest,
    ModelMessage,
    ModelResponse,
    ResponseFormat,
    TextPart,
    ToolDefinition,
)

__all__ = ["AgentModelBindingService", "BoundModel"]


@dataclass(frozen=True, slots=True)
class BoundModel:
    provider_id: str
    model_id: str
    model_key: str
    routing_reason: str


class AgentModelBindingService:
    def __init__(
        self,
        *,
        definitions: DefinitionRegistryService,
        routing: ModelRoutingService,
        gateway: ModelGatewayService,
    ) -> None:
        self._definitions = definitions
        self._routing = routing
        self._gateway = gateway

    async def resolve(
        self,
        snapshot: ConfigSnapshotView,
        *,
        context_size: int = 0,
        output_limit: int | None = None,
    ) -> BoundModel:
        policy = self._definitions.model_policy(snapshot.model_policy_id)
        result = await self._routing.select(
            ModelRoutingRequest(
                requested_model=snapshot.model_id or policy.default_model_id,
                required_capabilities=policy.required_capabilities,
                context_size=context_size,
                output_limit=output_limit,
            )
        )
        return BoundModel(
            provider_id=result.selected_provider_id,
            model_id=result.selected_model_id,
            model_key=result.selected_model_key,
            routing_reason=result.routing_reason,
        )

    async def generate(
        self,
        *,
        instance: InstanceView,
        snapshot: ConfigSnapshotView,
        bound: BoundModel,
        bundle: ContextBundle,
        tools: tuple[ToolDefinition, ...] = (),
    ) -> ModelResponse:
        budget: dict[str, Any] = snapshot.budget
        max_output_tokens = budget.get("max_output_tokens")
        request = ModelInvocationRequest(
            project_id=instance.project_id,
            model_id=bound.model_id,
            model_key=bound.model_key,
            messages=(
                ModelMessage(
                    role=MESSAGE_USER,
                    content=(TextPart(text=bundle.context_text),),
                ),
            ),
            task_id=instance.task_id,
            attempt_id=instance.attempt_id,
            agent_instance_id=instance.instance_id,
            system_instructions=bundle.system_prompt,
            tools=tuple(tools),
            response_format=ResponseFormat(kind=RESPONSE_FORMAT_JSON_OBJECT),
            max_output_tokens=(int(max_output_tokens) if max_output_tokens is not None else None),
            metadata={
                "agent_instance_id": instance.instance_id,
                "context_id": bundle.context_id,
                "prompt_id": bundle.prompt_id,
            },
        )
        return await self._gateway.generate(request)
