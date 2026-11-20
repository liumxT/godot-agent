"""Model Routing（E5-T07）。

路由规则：

1. 用户明确指定的模型优先；不可用时返回原因与替代项，禁止静默降级；
2. 未被验证为 ``SUPPORTED`` 的能力不能作为满足项；
3. 上下文与输出上限得不到满足时排除候选；
4. 预算检查在 E5-T12 接入，本阶段显式标记为未评估。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.errors import ModelUnavailable, ValidationFailed
from modules.model_gateway.models import (
    CAPABILITIES,
    CAPABILITY_SUPPORTED,
    MODEL_ACTIVE,
    PROVIDER_ENABLED,
)
from modules.model_gateway.registry import ModelRegistryService, ModelView, ProviderView

COST_PREFERENCE_CHEAPEST = "cheapest"
COST_PREFERENCE_BALANCED = "balanced"
COST_PREFERENCE_QUALITY = "quality"
COST_PREFERENCES = frozenset(
    {COST_PREFERENCE_CHEAPEST, COST_PREFERENCE_BALANCED, COST_PREFERENCE_QUALITY}
)

BUDGET_CHECK_NOT_EVALUATED = "NOT_EVALUATED"
_MAX_FALLBACK_OPTIONS = 3


@dataclass(frozen=True, slots=True)
class ModelRoutingRequest:
    requested_model: str | None = None
    required_capabilities: tuple[str, ...] = ()
    context_size: int = 0
    output_limit: int | None = None
    allowed_models: tuple[str, ...] = ()
    cost_preference: str = COST_PREFERENCE_BALANCED


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    provider_id: str
    model_id: str
    model_key: str


@dataclass(frozen=True, slots=True)
class ModelRoutingResult:
    selected_provider_id: str
    selected_model_id: str
    selected_model_key: str
    capability_check: dict[str, str]
    budget_check: str
    fallback_options: tuple[ModelCandidate, ...]
    routing_reason: str


class ModelRoutingService:
    def __init__(self, registry: ModelRegistryService) -> None:
        self._registry = registry

    async def select(self, request: ModelRoutingRequest) -> ModelRoutingResult:
        self._validate(request)
        models = await self._registry.list_models()
        providers = {item.provider_id: item for item in await self._registry.list_providers()}

        evaluated = [self._evaluate(model, request, providers) for model in models]
        eligible = [item for item in evaluated if item[1]]
        ranked = self._rank([item[0] for item in eligible], request.cost_preference)

        if request.requested_model:
            return self._select_requested(request, evaluated, ranked)
        if not ranked:
            raise ModelUnavailable(
                "没有满足条件的可用模型",
                details={
                    "required_capabilities": list(request.required_capabilities),
                    "context_size": request.context_size,
                    "output_limit": request.output_limit,
                },
            )
        return self._result(
            ranked[0],
            request,
            fallback=ranked[1 : _MAX_FALLBACK_OPTIONS + 1],
            reason=f"auto_selected_by_{request.cost_preference}",
        )

    def _select_requested(
        self,
        request: ModelRoutingRequest,
        evaluated: list[tuple[ModelView, bool, tuple[str, ...]]],
        ranked: list[ModelView],
    ) -> ModelRoutingResult:
        reference = request.requested_model or ""
        matched = [item for item in evaluated if self._matches(item[0], reference)]
        if not matched:
            raise ModelUnavailable(
                "指定的模型未登记",
                details={
                    "requested_model": reference,
                    "fallback_options": self._candidate_payload(ranked[:_MAX_FALLBACK_OPTIONS]),
                },
            )
        if len(matched) > 1:
            raise ModelUnavailable(
                "模型引用不唯一，请使用 model_id",
                details={
                    "requested_model": reference,
                    "candidates": self._candidate_payload([item[0] for item in matched]),
                },
            )

        model, usable, reasons = matched[0]
        if not usable:
            alternatives = [item for item in ranked if item.model_id != model.model_id]
            raise ModelUnavailable(
                "指定的模型当前不可用",
                details={
                    "requested_model": reference,
                    "reasons": list(reasons),
                    "fallback_options": self._candidate_payload(
                        alternatives[:_MAX_FALLBACK_OPTIONS]
                    ),
                },
            )
        alternatives = [item for item in ranked if item.model_id != model.model_id]
        return self._result(
            model,
            request,
            fallback=alternatives[:_MAX_FALLBACK_OPTIONS],
            reason="requested_model_available",
        )

    def _result(
        self,
        model: ModelView,
        request: ModelRoutingRequest,
        *,
        fallback: list[ModelView],
        reason: str,
    ) -> ModelRoutingResult:
        return ModelRoutingResult(
            selected_provider_id=model.provider_id,
            selected_model_id=model.model_id,
            selected_model_key=model.model_key,
            capability_check={
                capability: model.capability_status(capability) or "UNKNOWN"
                for capability in request.required_capabilities
            },
            budget_check=BUDGET_CHECK_NOT_EVALUATED,
            fallback_options=tuple(self._candidate(item) for item in fallback),
            routing_reason=reason,
        )

    def _evaluate(
        self,
        model: ModelView,
        request: ModelRoutingRequest,
        providers: dict[str, ProviderView],
    ) -> tuple[ModelView, bool, tuple[str, ...]]:
        reasons: list[str] = []
        provider = providers.get(model.provider_id)
        if provider is None:
            reasons.append("PROVIDER_MISSING")
        elif provider.status != PROVIDER_ENABLED:
            reasons.append("PROVIDER_DISABLED")

        if model.status != MODEL_ACTIVE:
            reasons.append("MODEL_DISABLED")

        if request.allowed_models and not any(
            self._matches(model, item) for item in request.allowed_models
        ):
            reasons.append("NOT_IN_ALLOWED_SCOPE")

        for capability in request.required_capabilities:
            if model.capability_status(capability) != CAPABILITY_SUPPORTED:
                reasons.append(f"CAPABILITY_NOT_VERIFIED:{capability}")

        if model.context_window < request.context_size:
            reasons.append("CONTEXT_WINDOW_TOO_SMALL")

        if request.output_limit is not None:
            if model.max_output_tokens is None:
                reasons.append("OUTPUT_LIMIT_UNKNOWN")
            elif model.max_output_tokens < request.output_limit:
                reasons.append("OUTPUT_LIMIT_TOO_SMALL")

        return model, not reasons, tuple(reasons)

    def _rank(self, models: list[ModelView], preference: str) -> list[ModelView]:
        if preference == COST_PREFERENCE_CHEAPEST:
            return sorted(models, key=self._cheapest_key)
        if preference == COST_PREFERENCE_QUALITY:
            return sorted(
                models,
                key=lambda item: (-item.context_window, -self._total_or_zero(item)),
            )
        return sorted(
            models,
            key=lambda item: (-item.context_window, self._total_or_zero(item)),
        )

    @staticmethod
    def _cheapest_key(model: ModelView) -> tuple[bool, Decimal]:
        price = ModelRoutingService._total_price(model)
        return price is None, price if price is not None else Decimal(0)

    @staticmethod
    def _total_or_zero(model: ModelView) -> Decimal:
        price = ModelRoutingService._total_price(model)
        return price if price is not None else Decimal(0)

    @staticmethod
    def _total_price(model: ModelView) -> Decimal | None:
        if model.price is None:
            return None
        return model.price.input_price + model.price.output_price

    @staticmethod
    def _matches(model: ModelView, reference: str) -> bool:
        return reference in (model.model_id, model.model_key)

    @staticmethod
    def _candidate(model: ModelView) -> ModelCandidate:
        return ModelCandidate(
            provider_id=model.provider_id,
            model_id=model.model_id,
            model_key=model.model_key,
        )

    @staticmethod
    def _candidate_payload(models: list[ModelView]) -> list[dict[str, str]]:
        return [
            {
                "provider_id": item.provider_id,
                "model_id": item.model_id,
                "model_key": item.model_key,
            }
            for item in models
        ]

    def _validate(self, request: ModelRoutingRequest) -> None:
        if request.cost_preference not in COST_PREFERENCES:
            raise ValidationFailed(
                "cost_preference 非法", details={"cost_preference": request.cost_preference}
            )
        if request.context_size < 0:
            raise ValidationFailed("context_size 不能为负数")
        if request.output_limit is not None and request.output_limit <= 0:
            raise ValidationFailed("output_limit 必须为正数")
        for capability in request.required_capabilities:
            if capability not in CAPABILITIES:
                raise ValidationFailed(
                    "未登记的能力", details={"capability": capability}
                )
