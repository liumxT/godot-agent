"""Token 费用估算（E5-T12）。

- 价格按百万 Token 计（行业通用单位），计算始终绑定具体价格版本；
- 缺少价格或用量时标记 ``UNAVAILABLE``，不猜测金额；
- 本地计算一律标记 ``ESTIMATED``，不得表述为最终账单；
- Provider 直接上报的费用单独保存，不与本地估算混用。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from modules.model_gateway.registry import PriceView
from modules.model_gateway.schemas import ModelUsage

PRICE_UNIT_TOKENS = Decimal(1_000_000)

CALCULATION_ESTIMATED = "ESTIMATED"
CALCULATION_UNAVAILABLE = "UNAVAILABLE"
CALCULATION_PROVIDER_REPORTED = "PROVIDER_REPORTED"
CALCULATION_STATUSES = frozenset(
    {CALCULATION_ESTIMATED, CALCULATION_UNAVAILABLE, CALCULATION_PROVIDER_REPORTED}
)


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    input_cost: Decimal | None
    output_cost: Decimal | None
    cached_input_cost: Decimal | None
    additional_cost: Decimal | None
    provider_reported_cost: Decimal | None
    currency: str | None
    pricing_version_id: str | None
    calculation_status: str


def calculate_cost(
    usage: ModelUsage | None,
    price: PriceView | None,
    *,
    additional_cost: Decimal | None = None,
) -> CostBreakdown:
    if usage is None or price is None:
        return CostBreakdown(
            input_cost=None,
            output_cost=None,
            cached_input_cost=None,
            additional_cost=additional_cost,
            provider_reported_cost=None,
            currency=price.currency if price is not None else None,
            pricing_version_id=price.price_version_id if price is not None else None,
            calculation_status=CALCULATION_UNAVAILABLE,
        )

    input_cost = _cost_for_tokens(usage.input_tokens, price.input_price)
    output_cost = _cost_for_tokens(usage.output_tokens, price.output_price)
    # 缓存折扣比例由各 Provider 定价决定，未确认折扣时不计算，避免虚构金额。
    cached_input_cost = None
    status = (
        CALCULATION_ESTIMATED
        if any(item is not None for item in (input_cost, output_cost, additional_cost))
        else CALCULATION_UNAVAILABLE
    )
    return CostBreakdown(
        input_cost=input_cost,
        output_cost=output_cost,
        cached_input_cost=cached_input_cost,
        additional_cost=additional_cost,
        provider_reported_cost=None,
        currency=price.currency,
        pricing_version_id=price.price_version_id,
        calculation_status=status,
    )


def _cost_for_tokens(tokens: int | None, price: Decimal) -> Decimal | None:
    if tokens is None:
        return None
    return (Decimal(tokens) * Decimal(price) / PRICE_UNIT_TOKENS).quantize(Decimal("0.000001"))
