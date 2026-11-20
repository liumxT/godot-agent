"""Model Gateway 仓储（E5-T01）。只处理本模块表，不跨模块访问。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository, Page
from modules.model_gateway.models import (
    ModelCapabilityModel,
    ModelModel,
    ModelPriceVersionModel,
    ModelProviderModel,
    ModelRequestModel,
    ModelResponseModel,
    ProviderConfigurationModel,
)


class ModelProviderRepository(BaseRepository[ModelProviderModel]):
    model = ModelProviderModel

    async def get_by_name(self, name: str) -> ModelProviderModel | None:
        return await self.session.scalar(
            select(ModelProviderModel).where(ModelProviderModel.name == name)
        )

    async def list_all(self) -> list[ModelProviderModel]:
        rows = await self.session.scalars(
            select(ModelProviderModel).order_by(ModelProviderModel.created_at)
        )
        return list(rows.all())


class ProviderConfigurationRepository(BaseRepository[ProviderConfigurationModel]):
    model = ProviderConfigurationModel

    async def get_latest(self, provider_id: str) -> ProviderConfigurationModel | None:
        return await self.session.scalar(
            select(ProviderConfigurationModel)
            .where(ProviderConfigurationModel.provider_id == provider_id)
            .order_by(ProviderConfigurationModel.configuration_version.desc())
            .limit(1)
        )

    async def list_by_provider(self, provider_id: str) -> list[ProviderConfigurationModel]:
        rows = await self.session.scalars(
            select(ProviderConfigurationModel)
            .where(ProviderConfigurationModel.provider_id == provider_id)
            .order_by(ProviderConfigurationModel.configuration_version)
        )
        return list(rows.all())


class ModelRepository(BaseRepository[ModelModel]):
    model = ModelModel

    async def get_by_key(self, provider_id: str, model_key: str) -> ModelModel | None:
        return await self.session.scalar(
            select(ModelModel).where(
                ModelModel.provider_id == provider_id,
                ModelModel.model_key == model_key,
            )
        )

    async def list_by_key(self, model_key: str) -> list[ModelModel]:
        rows = await self.session.scalars(
            select(ModelModel).where(ModelModel.model_key == model_key)
        )
        return list(rows.all())

    async def list_by_provider(self, provider_id: str) -> list[ModelModel]:
        rows = await self.session.scalars(
            select(ModelModel)
            .where(ModelModel.provider_id == provider_id)
            .order_by(ModelModel.model_key)
        )
        return list(rows.all())

    async def list_all(self) -> list[ModelModel]:
        rows = await self.session.scalars(select(ModelModel).order_by(ModelModel.created_at))
        return list(rows.all())


class ModelCapabilityRepository(BaseRepository[ModelCapabilityModel]):
    model = ModelCapabilityModel

    async def list_by_model(self, model_id: str) -> list[ModelCapabilityModel]:
        rows = await self.session.scalars(
            select(ModelCapabilityModel).where(ModelCapabilityModel.model_id == model_id)
        )
        return list(rows.all())

    async def list_by_models(self, model_ids: list[str]) -> list[ModelCapabilityModel]:
        if not model_ids:
            return []
        rows = await self.session.scalars(
            select(ModelCapabilityModel).where(ModelCapabilityModel.model_id.in_(model_ids))
        )
        return list(rows.all())


class ModelPriceVersionRepository(BaseRepository[ModelPriceVersionModel]):
    model = ModelPriceVersionModel

    async def get_effective(
        self, model_id: str, at: datetime
    ) -> ModelPriceVersionModel | None:
        """取 ``effective_at <= at`` 的最新价格版本。"""

        return await self.session.scalar(
            select(ModelPriceVersionModel)
            .where(
                ModelPriceVersionModel.model_id == model_id,
                ModelPriceVersionModel.effective_at <= at,
            )
            .order_by(ModelPriceVersionModel.effective_at.desc())
            .limit(1)
        )

    async def get_at(
        self, model_id: str, effective_at: datetime
    ) -> ModelPriceVersionModel | None:
        return await self.session.scalar(
            select(ModelPriceVersionModel).where(
                ModelPriceVersionModel.model_id == model_id,
                ModelPriceVersionModel.effective_at == effective_at,
            )
        )

    async def list_by_models(self, model_ids: list[str]) -> list[ModelPriceVersionModel]:
        if not model_ids:
            return []
        rows = await self.session.scalars(
            select(ModelPriceVersionModel)
            .where(ModelPriceVersionModel.model_id.in_(model_ids))
            .order_by(ModelPriceVersionModel.effective_at)
        )
        return list(rows.all())


class ModelRequestRepository(BaseRepository[ModelRequestModel]):
    model = ModelRequestModel

    async def list_by_project(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> Page[ModelRequestModel]:
        return await self.paginate(
            limit=limit,
            offset=offset,
            filters=[ModelRequestModel.project_id == project_id],
        )


class ModelResponseRepository(BaseRepository[ModelResponseModel]):
    model = ModelResponseModel

    async def get_by_request(self, request_id: str) -> ModelResponseModel | None:
        return await self.session.scalar(
            select(ModelResponseModel).where(ModelResponseModel.request_id == request_id)
        )
