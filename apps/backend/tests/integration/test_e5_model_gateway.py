"""E5 Model Gateway 集成测试（T01 / T04 / T05 / T06 / T07）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    ModelAlreadyRegistered,
    ModelUnavailable,
    ProviderConfigurationInvalid,
    ValidationFailed,
)
from core.security.tokens import utcnow
from modules.model_gateway.configuration import ProviderConfigurationService
from modules.model_gateway.models import (
    CAPABILITY_STREAMING,
    CAPABILITY_SUPPORTED,
    CAPABILITY_TEXT_INPUT,
    CAPABILITY_TEXT_OUTPUT,
    CAPABILITY_TOOL_CALLING,
    CAPABILITY_UNKNOWN,
    CAPABILITY_UNSUPPORTED,
    PROVIDER_DISABLED,
    PROVIDER_TYPE_LOCAL,
    PROVIDER_TYPE_OPENAI,
)
from modules.model_gateway.registry import CapabilitySetting, ModelRegistryService
from modules.model_gateway.routing import (
    ModelRoutingRequest,
    ModelRoutingService,
)


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e5.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _registry(app) -> ModelRegistryService:
    return app.state.services.get("model_registry_service", ModelRegistryService)


def _routing(app) -> ModelRoutingService:
    return app.state.services.get("model_routing_service", ModelRoutingService)


def _configuration(app) -> ProviderConfigurationService:
    return app.state.services.get("provider_configuration_service", ProviderConfigurationService)


def _supported(evidence: str = "official-docs") -> CapabilitySetting:
    return CapabilitySetting(
        support_status=CAPABILITY_SUPPORTED,
        evidence_source=evidence,
        verified_at=utcnow(),
    )


async def test_registry_registers_models_with_versioned_prices(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        registry = _registry(app)
        provider = await registry.register_provider(
            name="openai-main", provider_type=PROVIDER_TYPE_OPENAI
        )
        model = await registry.register_model(
            provider_id=provider.provider_id,
            model_key="gpt-demo",
            display_name="GPT Demo",
            context_window=128000,
            max_output_tokens=8192,
            capabilities={
                CAPABILITY_TEXT_INPUT: _supported(),
                CAPABILITY_STREAMING: _supported("provider-probe"),
                CAPABILITY_TOOL_CALLING: CapabilitySetting(support_status=CAPABILITY_UNKNOWN),
            },
            input_price="1.5",
            output_price="6",
            source="manual",
        )

        assert model.price is not None
        assert model.price.input_price == Decimal("1.5")
        assert model.price.currency == "USD"
        assert model.capability_status(CAPABILITY_TEXT_INPUT) == CAPABILITY_SUPPORTED
        assert model.capability_status(CAPABILITY_TOOL_CALLING) == CAPABILITY_UNKNOWN
        assert model.capability_status(CAPABILITY_TEXT_OUTPUT) is None

        with pytest.raises(ModelAlreadyRegistered):
            await registry.register_model(
                provider_id=provider.provider_id,
                model_key="gpt-demo",
                display_name="Duplicate",
                context_window=1000,
            )
        with pytest.raises(ValidationFailed):
            await registry.register_model(
                provider_id=provider.provider_id,
                model_key="no-evidence",
                display_name="No evidence",
                context_window=1000,
                capabilities={CAPABILITY_TEXT_INPUT: CapabilitySetting(CAPABILITY_SUPPORTED)},
            )

        future = utcnow() + timedelta(days=1)
        await registry.add_price_version(
            model.model_id,
            input_price="1",
            output_price="4",
            effective_at=future,
        )
        current = await registry.get_model(model.model_id)
        assert current.price is not None
        assert current.price.input_price == Decimal("1.5")

        await registry.set_model_status(model.model_id, "DISABLED")
        assert (await registry.get_model(model.model_id)).status == "DISABLED"


async def test_provider_configuration_versions_and_secret_handling(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        registry = _registry(app)
        configuration = _configuration(app)
        secret_store = app.state.services.get("secret_store")
        provider = await registry.register_provider(
            name="cloud", provider_type=PROVIDER_TYPE_OPENAI
        )

        first = await configuration.save(
            provider.provider_id,
            endpoint="https://api.example.com/v1",
            credential_ref="e5.openai_api_key",
            api_key="sk-secret-value",
            actor_id="tester",
        )
        assert first.configuration_version == 1
        assert first.enabled is True
        assert secret_store.get("e5.openai_api_key") == "sk-secret-value"
        assert "sk-secret-value" not in repr(first)

        second = await configuration.set_enabled(
            provider.provider_id, enabled=False, actor_id="tester"
        )
        assert second.configuration_version == 2
        assert second.enabled is False
        assert len(await configuration.list_versions(provider.provider_id)) == 2

        health = await configuration.test_connection(provider.provider_id)
        assert health.status == "CONFIGURED"

        with pytest.raises(ProviderConfigurationInvalid):
            await configuration.save(
                provider.provider_id,
                endpoint="http://api.example.com/v1",
                credential_ref="e5.openai_api_key",
            )
        assert len(await configuration.list_versions(provider.provider_id)) == 2

        local = await registry.register_provider(name="ollama", provider_type=PROVIDER_TYPE_LOCAL)
        local_config = await configuration.save(
            local.provider_id, endpoint="http://127.0.0.1:11434"
        )
        assert local_config.credential_ref is None
        assert (await configuration.test_connection(local.provider_id)).status == "CONFIGURED"


async def test_routing_respects_capabilities_and_never_silently_downgrades(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        registry = _registry(app)
        routing = _routing(app)
        provider = await registry.register_provider(
            name="cloud", provider_type=PROVIDER_TYPE_OPENAI
        )
        cheap = await registry.register_model(
            provider_id=provider.provider_id,
            model_key="cheap-model",
            display_name="Cheap",
            context_window=32000,
            max_output_tokens=4096,
            capabilities={
                CAPABILITY_TEXT_INPUT: _supported(),
                CAPABILITY_TEXT_OUTPUT: _supported(),
            },
            input_price="1",
            output_price="1",
        )
        strong = await registry.register_model(
            provider_id=provider.provider_id,
            model_key="strong-model",
            display_name="Strong",
            context_window=200000,
            max_output_tokens=32000,
            capabilities={
                CAPABILITY_TEXT_INPUT: _supported(),
                CAPABILITY_TEXT_OUTPUT: _supported(),
                CAPABILITY_TOOL_CALLING: _supported("tool-probe"),
            },
            input_price="5",
            output_price="15",
        )
        unverified = await registry.register_model(
            provider_id=provider.provider_id,
            model_key="unverified-model",
            display_name="Unverified",
            context_window=1000000,
            max_output_tokens=64000,
            capabilities={
                CAPABILITY_TEXT_INPUT: _supported(),
                CAPABILITY_TOOL_CALLING: CapabilitySetting(CAPABILITY_UNSUPPORTED),
            },
            input_price="2",
            output_price="2",
        )

        selected = await routing.select(
            ModelRoutingRequest(
                required_capabilities=(CAPABILITY_TOOL_CALLING,),
                cost_preference="cheapest",
            )
        )
        assert selected.selected_model_id == strong.model_id
        assert selected.capability_check[CAPABILITY_TOOL_CALLING] == CAPABILITY_SUPPORTED

        with pytest.raises(ModelUnavailable) as exc_info:
            await routing.select(
                ModelRoutingRequest(
                    requested_model="cheap-model",
                    required_capabilities=(CAPABILITY_TOOL_CALLING,),
                )
            )
        details = exc_info.value.details
        assert "CAPABILITY_NOT_VERIFIED:TOOL_CALLING" in details["reasons"]
        assert any(item["model_id"] == strong.model_id for item in details["fallback_options"])
        assert all(item["model_id"] != cheap.model_id for item in details["fallback_options"])
        assert all(item["model_id"] != unverified.model_id for item in details["fallback_options"])

        with pytest.raises(ModelUnavailable):
            await routing.select(ModelRoutingRequest(requested_model="unknown-model"))

        explicit = await routing.select(ModelRoutingRequest(requested_model=strong.model_id))
        assert explicit.routing_reason == "requested_model_available"
        assert explicit.budget_check == "NOT_EVALUATED"


async def test_routing_excludes_disabled_provider_and_oversized_context(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        registry = _registry(app)
        routing = _routing(app)
        provider = await registry.register_provider(name="local", provider_type=PROVIDER_TYPE_LOCAL)
        model = await registry.register_model(
            provider_id=provider.provider_id,
            model_key="local-small",
            display_name="Local Small",
            context_window=8000,
            max_output_tokens=None,
            capabilities={CAPABILITY_TEXT_INPUT: _supported()},
        )

        with pytest.raises(ModelUnavailable) as exc_info:
            await routing.select(ModelRoutingRequest(context_size=20000))
        assert exc_info.value.details["context_size"] == 20000

        with pytest.raises(ModelUnavailable) as exc_info:
            await routing.select(
                ModelRoutingRequest(requested_model=model.model_id, output_limit=1024)
            )
        assert "OUTPUT_LIMIT_UNKNOWN" in exc_info.value.details["reasons"]

        await registry.set_provider_status(provider.provider_id, PROVIDER_DISABLED)
        with pytest.raises(ModelUnavailable) as exc_info:
            await routing.select(ModelRoutingRequest(requested_model=model.model_id))
        assert "PROVIDER_DISABLED" in exc_info.value.details["reasons"]

        await registry.set_provider_status(provider.provider_id, "ENABLED")
        selected = await routing.select(ModelRoutingRequest(requested_model=model.model_id))
        assert selected.selected_model_id == model.model_id
