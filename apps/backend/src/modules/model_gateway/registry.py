"""Model Registry 与 Capability Registry（E5-T05 / T06）。

- Provider / Model 分离，模型键在同一 Provider 内唯一；
- 价格按生效时间版本化，费用统计可回溯到调用发生时的价格；
- 只有带证据的 ``SUPPORTED`` 能力才会被路由接受，``UNKNOWN`` 不算支持。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from core.errors import (
    ModelAlreadyRegistered,
    NotFoundError,
    ValidationFailed,
)
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.model_gateway.models import (
    CAPABILITIES,
    CAPABILITY_STATUSES,
    CAPABILITY_SUPPORTED,
    MODEL_ACTIVE,
    MODEL_STATUSES,
    PROVIDER_ENABLED,
    PROVIDER_STATUSES,
    PROVIDER_TYPES,
    ModelCapabilityModel,
    ModelModel,
    ModelPriceVersionModel,
    ModelProviderModel,
)
from modules.model_gateway.repository import (
    ModelCapabilityRepository,
    ModelPriceVersionRepository,
    ModelProviderRepository,
    ModelRepository,
)

__all__ = [
    "CapabilitySetting",
    "CapabilityView",
    "ModelRegistryService",
    "ModelView",
    "PriceView",
    "ProviderView",
]


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _as_decimal(value: Decimal | float | str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationFailed("价格必须是合法数字", details={"value": str(value)}) from exc


@dataclass(frozen=True, slots=True)
class CapabilitySetting:
    support_status: str
    max_input: int | None = None
    max_output: int | None = None
    evidence_source: str | None = None
    api_version: str | None = None
    verified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CapabilityView:
    capability: str
    support_status: str
    max_input: int | None
    max_output: int | None
    evidence_source: str | None
    api_version: str | None
    verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class PriceView:
    price_version_id: str
    input_price: Decimal
    output_price: Decimal
    currency: str
    effective_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderView:
    provider_id: str
    name: str
    provider_type: str
    status: str
    configuration_ref: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ModelView:
    model_id: str
    provider_id: str
    model_key: str
    display_name: str
    context_window: int
    max_output_tokens: int | None
    status: str
    source: str | None
    last_verified_at: datetime | None
    price: PriceView | None
    capabilities: tuple[CapabilityView, ...]

    def capability_status(self, capability: str) -> str | None:
        for item in self.capabilities:
            if item.capability == capability:
                return item.support_status
        return None


def _provider_view(entity: ModelProviderModel) -> ProviderView:
    return ProviderView(
        provider_id=entity.provider_id,
        name=entity.name,
        provider_type=entity.provider_type,
        status=entity.status,
        configuration_ref=entity.configuration_ref,
        created_at=ensure_utc(entity.created_at),
        updated_at=ensure_utc(entity.updated_at),
    )


def _capability_view(entity: ModelCapabilityModel) -> CapabilityView:
    return CapabilityView(
        capability=entity.capability,
        support_status=entity.support_status,
        max_input=entity.max_input,
        max_output=entity.max_output,
        evidence_source=entity.evidence_source,
        api_version=entity.api_version,
        verified_at=ensure_utc(entity.verified_at) if entity.verified_at else None,
    )


def _price_view(entity: ModelPriceVersionModel) -> PriceView:
    return PriceView(
        price_version_id=entity.price_version_id,
        input_price=Decimal(entity.input_price),
        output_price=Decimal(entity.output_price),
        currency=entity.currency,
        effective_at=ensure_utc(entity.effective_at),
    )


def _model_view(
    entity: ModelModel,
    capabilities: list[ModelCapabilityModel],
    price: ModelPriceVersionModel | None,
) -> ModelView:
    return ModelView(
        model_id=entity.model_id,
        provider_id=entity.provider_id,
        model_key=entity.model_key,
        display_name=entity.display_name,
        context_window=entity.context_window,
        max_output_tokens=entity.max_output_tokens,
        status=entity.status,
        source=entity.source,
        last_verified_at=ensure_utc(entity.last_verified_at) if entity.last_verified_at else None,
        price=_price_view(price) if price is not None else None,
        capabilities=tuple(_capability_view(item) for item in capabilities),
    )


class ModelRegistryService:
    """模型与能力注册中心。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._clock = clock

    async def register_provider(
        self,
        *,
        name: str,
        provider_type: str,
        status: str = PROVIDER_ENABLED,
    ) -> ProviderView:
        if not name.strip():
            raise ValidationFailed("Provider 名称不能为空")
        if provider_type not in PROVIDER_TYPES:
            raise ValidationFailed(
                "Provider 类型非法", details={"provider_type": provider_type}
            )
        if status not in PROVIDER_STATUSES:
            raise ValidationFailed("Provider 状态非法", details={"status": status})
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = ModelProviderRepository(session)
            if await repository.get_by_name(name) is not None:
                raise ValidationFailed("Provider 名称已存在", details={"name": name})
            entity = ModelProviderModel(
                provider_id=_new_id("mpr_"),
                name=name,
                provider_type=provider_type,
                status=status,
                configuration_ref=None,
                created_at=now,
                updated_at=now,
            )
            await repository.add(entity)
            view = _provider_view(entity)
        return view

    async def get_provider(self, provider_id: str) -> ProviderView:
        async with self._database.session() as session:
            entity = await ModelProviderRepository(session).get(provider_id)
        if entity is None:
            raise NotFoundError("Provider 不存在", details={"provider_id": provider_id})
        return _provider_view(entity)

    async def list_providers(self) -> list[ProviderView]:
        async with self._database.session() as session:
            rows = await ModelProviderRepository(session).list_all()
        return [_provider_view(row) for row in rows]

    async def set_provider_status(self, provider_id: str, status: str) -> ProviderView:
        if status not in PROVIDER_STATUSES:
            raise ValidationFailed("Provider 状态非法", details={"status": status})
        async with self._database.session() as session, transaction(session):
            entity = await ModelProviderRepository(session).get(provider_id)
            if entity is None:
                raise NotFoundError("Provider 不存在", details={"provider_id": provider_id})
            entity.status = status
            entity.updated_at = self._clock()
            await session.flush()
            view = _provider_view(entity)
        return view

    async def register_model(
        self,
        *,
        provider_id: str,
        model_key: str,
        display_name: str,
        context_window: int,
        max_output_tokens: int | None = None,
        capabilities: Mapping[str, CapabilitySetting] | None = None,
        input_price: Decimal | float | str | None = None,
        output_price: Decimal | float | str | None = None,
        currency: str = "USD",
        price_effective_at: datetime | None = None,
        source: str | None = None,
        status: str = MODEL_ACTIVE,
    ) -> ModelView:
        self._validate_model_fields(
            model_key=model_key,
            display_name=display_name,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            status=status,
        )
        settings = dict(capabilities or {})
        for capability, setting in settings.items():
            self._validate_capability(capability, setting)
        price_values = self._validate_price(input_price, output_price, currency)

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            provider = await ModelProviderRepository(session).get(provider_id)
            if provider is None:
                raise NotFoundError("Provider 不存在", details={"provider_id": provider_id})
            repository = ModelRepository(session)
            if await repository.get_by_key(provider_id, model_key) is not None:
                raise ModelAlreadyRegistered(
                    "模型已登记",
                    details={"provider_id": provider_id, "model_key": model_key},
                )
            entity = ModelModel(
                model_id=_new_id("mdl_"),
                provider_id=provider_id,
                model_key=model_key,
                display_name=display_name,
                context_window=context_window,
                max_output_tokens=max_output_tokens,
                status=status,
                source=source,
                last_verified_at=None,
                created_at=now,
                updated_at=now,
            )
            await repository.add(entity)
            capability_repository = ModelCapabilityRepository(session)
            capability_rows: list[ModelCapabilityModel] = []
            for capability, setting in settings.items():
                row = ModelCapabilityModel(
                    model_id=entity.model_id,
                    capability=capability,
                    support_status=setting.support_status,
                    max_input=setting.max_input,
                    max_output=setting.max_output,
                    evidence_source=setting.evidence_source,
                    api_version=setting.api_version,
                    verified_at=setting.verified_at,
                )
                await capability_repository.add(row)
                capability_rows.append(row)
            price_row: ModelPriceVersionModel | None = None
            if price_values is not None:
                price_row = ModelPriceVersionModel(
                    price_version_id=_new_id("mpv_"),
                    model_id=entity.model_id,
                    input_price=price_values[0],
                    output_price=price_values[1],
                    currency=currency.strip().upper(),
                    effective_at=price_effective_at or now,
                    created_at=now,
                )
                await ModelPriceVersionRepository(session).add(price_row)
            view = _model_view(entity, capability_rows, price_row)
        return view

    async def update_model(
        self,
        model_id: str,
        *,
        display_name: str | None = None,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
        source: str | None = None,
        verified_at: datetime | None = None,
    ) -> ModelView:
        async with self._database.session() as session, transaction(session):
            entity = await ModelRepository(session).get(model_id)
            if entity is None:
                raise NotFoundError("模型不存在", details={"model_id": model_id})
            if display_name is not None:
                if not display_name.strip():
                    raise ValidationFailed("模型显示名称不能为空")
                entity.display_name = display_name
            if context_window is not None:
                if context_window <= 0:
                    raise ValidationFailed("上下文窗口必须为正数")
                entity.context_window = context_window
            if max_output_tokens is not None:
                if max_output_tokens <= 0:
                    raise ValidationFailed("最大输出 Token 必须为正数")
                entity.max_output_tokens = max_output_tokens
            if source is not None:
                entity.source = source
            if verified_at is not None:
                entity.last_verified_at = verified_at
            entity.updated_at = self._clock()
            await session.flush()
        return await self.get_model(model_id)

    async def set_model_status(self, model_id: str, status: str) -> ModelView:
        if status not in MODEL_STATUSES:
            raise ValidationFailed("模型状态非法", details={"status": status})
        async with self._database.session() as session, transaction(session):
            entity = await ModelRepository(session).get(model_id)
            if entity is None:
                raise NotFoundError("模型不存在", details={"model_id": model_id})
            entity.status = status
            entity.updated_at = self._clock()
            await session.flush()
        return await self.get_model(model_id)

    async def add_price_version(
        self,
        model_id: str,
        *,
        input_price: Decimal | float | str,
        output_price: Decimal | float | str,
        currency: str = "USD",
        effective_at: datetime | None = None,
    ) -> PriceView:
        price_values = self._validate_price(input_price, output_price, currency)
        if price_values is None:
            raise ValidationFailed("必须提供输入与输出价格")
        effective = effective_at or self._clock()
        async with self._database.session() as session, transaction(session):
            if await ModelRepository(session).get(model_id) is None:
                raise NotFoundError("模型不存在", details={"model_id": model_id})
            repository = ModelPriceVersionRepository(session)
            if await repository.get_at(model_id, effective) is not None:
                raise ValidationFailed(
                    "该生效时间已存在价格版本",
                    details={"model_id": model_id, "effective_at": effective.isoformat()},
                )
            row = ModelPriceVersionModel(
                price_version_id=_new_id("mpv_"),
                model_id=model_id,
                input_price=price_values[0],
                output_price=price_values[1],
                currency=currency.strip().upper(),
                effective_at=effective,
                created_at=self._clock(),
            )
            await repository.add(row)
            view = _price_view(row)
        return view

    async def set_capability(
        self,
        model_id: str,
        capability: str,
        setting: CapabilitySetting,
    ) -> CapabilityView:
        self._validate_capability(capability, setting)
        async with self._database.session() as session, transaction(session):
            if await ModelRepository(session).get(model_id) is None:
                raise NotFoundError("模型不存在", details={"model_id": model_id})
            repository = ModelCapabilityRepository(session)
            existing = await repository.get((model_id, capability))
            if existing is None:
                existing = ModelCapabilityModel(
                    model_id=model_id,
                    capability=capability,
                    support_status=setting.support_status,
                    max_input=setting.max_input,
                    max_output=setting.max_output,
                    evidence_source=setting.evidence_source,
                    api_version=setting.api_version,
                    verified_at=setting.verified_at,
                )
                await repository.add(existing)
            else:
                existing.support_status = setting.support_status
                existing.max_input = setting.max_input
                existing.max_output = setting.max_output
                existing.evidence_source = setting.evidence_source
                existing.api_version = setting.api_version
                existing.verified_at = setting.verified_at
                await session.flush()
            view = _capability_view(existing)
        return view

    async def get_model(self, model_id: str) -> ModelView:
        async with self._database.session() as session:
            entity = await ModelRepository(session).get(model_id)
            if entity is None:
                raise NotFoundError("模型不存在", details={"model_id": model_id})
            capabilities = await ModelCapabilityRepository(session).list_by_model(model_id)
            price = await ModelPriceVersionRepository(session).get_effective(
                model_id, self._clock()
            )
        return _model_view(entity, capabilities, price)

    async def list_models(self, *, provider_id: str | None = None) -> list[ModelView]:
        now = self._clock()
        async with self._database.session() as session:
            repository = ModelRepository(session)
            entities = (
                await repository.list_by_provider(provider_id)
                if provider_id
                else await repository.list_all()
            )
            model_ids = [item.model_id for item in entities]
            capability_rows = await ModelCapabilityRepository(session).list_by_models(model_ids)
            price_rows = await ModelPriceVersionRepository(session).list_by_models(model_ids)

        capabilities_by_model: dict[str, list[ModelCapabilityModel]] = {}
        for row in capability_rows:
            capabilities_by_model.setdefault(row.model_id, []).append(row)

        effective_prices: dict[str, ModelPriceVersionModel] = {}
        for row in price_rows:
            if ensure_utc(row.effective_at) <= now:
                effective_prices[row.model_id] = row

        return [
            _model_view(
                entity,
                capabilities_by_model.get(entity.model_id, []),
                effective_prices.get(entity.model_id),
            )
            for entity in entities
        ]

    def _validate_model_fields(
        self,
        *,
        model_key: str,
        display_name: str,
        context_window: int,
        max_output_tokens: int | None,
        status: str,
    ) -> None:
        if not model_key.strip():
            raise ValidationFailed("模型键不能为空")
        if not display_name.strip():
            raise ValidationFailed("模型显示名称不能为空")
        if context_window <= 0:
            raise ValidationFailed("上下文窗口必须为正数")
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValidationFailed("最大输出 Token 必须为正数")
        if status not in MODEL_STATUSES:
            raise ValidationFailed("模型状态非法", details={"status": status})

    def _validate_capability(self, capability: str, setting: CapabilitySetting) -> None:
        if capability not in CAPABILITIES:
            raise ValidationFailed("未登记的模型能力", details={"capability": capability})
        if setting.support_status not in CAPABILITY_STATUSES:
            raise ValidationFailed(
                "能力状态非法", details={"support_status": setting.support_status}
            )
        if setting.support_status == CAPABILITY_SUPPORTED and not setting.evidence_source:
            raise ValidationFailed(
                "SUPPORTED 能力必须提供证据来源", details={"capability": capability}
            )

    def _validate_price(
        self,
        input_price: Any,
        output_price: Any,
        currency: str,
    ) -> tuple[Decimal, Decimal] | None:
        if input_price is None and output_price is None:
            return None
        if input_price is None or output_price is None:
            raise ValidationFailed("输入与输出价格必须同时提供")
        resolved_input = _as_decimal(input_price)
        resolved_output = _as_decimal(output_price)
        if resolved_input < 0 or resolved_output < 0:
            raise ValidationFailed("价格不能为负数")
        if not currency.strip():
            raise ValidationFailed("币种不能为空")
        return resolved_input, resolved_output
