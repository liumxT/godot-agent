"""Provider Configuration（E5-T04）。

- 配置每次修改追加版本，旧版本保留用于审计回溯；
- 数据库只保存密钥名称（``credential_ref``），密钥值由 SecretStore 管理；
- 配置在落库前必须通过适配器校验，缺少凭证时显式失败；
- 日志只记录配置版本与操作者，不输出密钥。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from core.errors import NotFoundError, ValidationFailed
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.secrets.store import SecretStore
from modules.model_gateway.models import ModelProviderModel, ProviderConfigurationModel
from modules.model_gateway.providers.base import (
    DEFAULT_TIMEOUT_SECONDS,
    BaseProviderAdapter,
    ProviderHealth,
)
from modules.model_gateway.providers.registry import (
    AdapterRegistry,
    default_adapter_registry,
)
from modules.model_gateway.repository import (
    ModelProviderRepository,
    ProviderConfigurationRepository,
)

__all__ = ["ProviderConfigurationService", "ProviderConfigurationView"]


@dataclass(frozen=True, slots=True)
class ProviderConfigurationView:
    configuration_id: str
    provider_id: str
    endpoint: str
    api_version: str | None
    credential_ref: str | None
    timeout_seconds: int
    enabled: bool
    configuration_version: int
    updated_by: str | None
    updated_at: datetime


def _view(entity: ProviderConfigurationModel) -> ProviderConfigurationView:
    return ProviderConfigurationView(
        configuration_id=entity.configuration_id,
        provider_id=entity.provider_id,
        endpoint=entity.endpoint,
        api_version=entity.api_version,
        credential_ref=entity.credential_ref,
        timeout_seconds=entity.timeout_seconds,
        enabled=entity.enabled,
        configuration_version=entity.configuration_version,
        updated_by=entity.updated_by,
        updated_at=ensure_utc(entity.updated_at),
    )


class ProviderConfigurationService:
    def __init__(
        self,
        database: DatabaseService,
        secret_store: SecretStore,
        *,
        adapters: AdapterRegistry | None = None,
        default_timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._secret_store = secret_store
        self._adapters = adapters or default_adapter_registry()
        self._default_timeout_seconds = default_timeout_seconds
        self._clock = clock
        self._logger = get_logger("backend.model_gateway.configuration")

    async def save(
        self,
        provider_id: str,
        *,
        endpoint: str,
        api_version: str | None = None,
        credential_ref: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
        enabled: bool = True,
        actor_id: str | None = None,
    ) -> ProviderConfigurationView:
        """新增或更新 Provider 配置；任何修改都会产生新版本。"""

        if api_key is not None and not credential_ref:
            raise ValidationFailed("写入 API Key 时必须提供 credential_ref")
        now = self._clock()
        resolved_timeout = timeout_seconds or self._default_timeout_seconds

        async with self._database.session() as session:
            provider = await ModelProviderRepository(session).get(provider_id)
            if provider is None:
                raise NotFoundError("Provider 不存在", details={"provider_id": provider_id})
            adapter = self._build_adapter(
                provider,
                endpoint=endpoint,
                api_version=api_version,
                credential_ref=credential_ref,
                api_key=api_key,
                timeout_seconds=resolved_timeout,
            )
            adapter.validate_configuration()

            async with transaction(session):
                repository = ProviderConfigurationRepository(session)
                latest = await repository.get_latest(provider_id)
                entity = ProviderConfigurationModel(
                    configuration_id=_new_id("mcf_"),
                    provider_id=provider_id,
                    endpoint=endpoint.strip(),
                    api_version=api_version,
                    credential_ref=credential_ref,
                    timeout_seconds=resolved_timeout,
                    enabled=enabled,
                    configuration_version=(latest.configuration_version + 1) if latest else 1,
                    updated_by=actor_id,
                    created_at=now,
                    updated_at=now,
                )
                await repository.add(entity)
                provider.configuration_ref = entity.configuration_id
                provider.updated_at = now
                await session.flush()
                view = _view(entity)

        if api_key is not None and credential_ref is not None:
            self._secret_store.set(credential_ref, api_key)
        log_event(
            self._logger,
            logging.INFO,
            "provider_configuration_saved",
            f"provider configuration saved: version={view.configuration_version}",
            component="model_gateway",
        )
        return view

    async def set_enabled(
        self,
        provider_id: str,
        *,
        enabled: bool,
        actor_id: str | None = None,
    ) -> ProviderConfigurationView:
        current = await self.get(provider_id)
        if current is None:
            raise ValidationFailed(
                "Provider 尚未配置", details={"provider_id": provider_id}
            )
        return await self.save(
            provider_id,
            endpoint=current.endpoint,
            api_version=current.api_version,
            credential_ref=current.credential_ref,
            timeout_seconds=current.timeout_seconds,
            enabled=enabled,
            actor_id=actor_id,
        )

    async def set_credential(
        self, provider_id: str, *, credential_ref: str, api_key: str
    ) -> None:
        if not credential_ref.strip():
            raise ValidationFailed("credential_ref 不能为空")
        if not api_key:
            raise ValidationFailed("API Key 不能为空", details={"provider_id": provider_id})
        async with self._database.session() as session:
            if await ModelProviderRepository(session).get(provider_id) is None:
                raise NotFoundError("Provider 不存在", details={"provider_id": provider_id})
        self._secret_store.set(credential_ref, api_key)
        log_event(
            self._logger,
            logging.INFO,
            "provider_credential_updated",
            component="model_gateway",
        )

    async def get(self, provider_id: str) -> ProviderConfigurationView | None:
        async with self._database.session() as session:
            entity = await ProviderConfigurationRepository(session).get_latest(provider_id)
        return _view(entity) if entity is not None else None

    async def list_versions(self, provider_id: str) -> list[ProviderConfigurationView]:
        async with self._database.session() as session:
            rows = await ProviderConfigurationRepository(session).list_by_provider(provider_id)
        return [_view(row) for row in rows]

    async def test_connection(self, provider_id: str) -> ProviderHealth:
        """校验当前配置是否可调用；不发起生成请求。"""

        async with self._database.session() as session:
            provider = await ModelProviderRepository(session).get(provider_id)
            if provider is None:
                raise NotFoundError("Provider 不存在", details={"provider_id": provider_id})
            config = await ProviderConfigurationRepository(session).get_latest(provider_id)
        if config is None:
            raise ValidationFailed(
                "Provider 尚未配置", details={"provider_id": provider_id}
            )
        adapter = self._build_adapter(
            provider,
            endpoint=config.endpoint,
            api_version=config.api_version,
            credential_ref=config.credential_ref,
            api_key=None,
            timeout_seconds=config.timeout_seconds,
        )
        return adapter.health_check()

    def _build_adapter(
        self,
        provider: ModelProviderModel,
        *,
        endpoint: str,
        api_version: str | None,
        credential_ref: str | None,
        api_key: str | None,
        timeout_seconds: int,
    ) -> BaseProviderAdapter:
        resolved_key = api_key
        if resolved_key is None and credential_ref:
            resolved_key = self._secret_store.get(credential_ref)
        return self._adapters.create(
            provider.provider_type,
            endpoint=endpoint,
            api_version=api_version,
            api_key=resolved_key,
            timeout_seconds=timeout_seconds,
        )


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]
