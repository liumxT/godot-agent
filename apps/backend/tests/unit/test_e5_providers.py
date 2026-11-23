"""E5 Provider 适配器单元测试（T02 / T03）。"""

from __future__ import annotations

import pytest

from core.errors import (
    AppError,
    ProviderConfigurationInvalid,
    ProviderNotConfigured,
    StartupError,
)
from modules.model_gateway.models import (
    CAPABILITY_STREAMING,
    CAPABILITY_SUPPORTED,
    CAPABILITY_TEXT_INPUT,
    CAPABILITY_UNKNOWN,
    PROVIDER_TYPE_LOCAL,
    PROVIDER_TYPE_OPENAI,
)
from modules.model_gateway.providers.base import ProviderModelDeclaration
from modules.model_gateway.providers.errors import ProviderErrorCategory
from modules.model_gateway.providers.local import LocalAdapter
from modules.model_gateway.providers.openai import OpenAIAdapter
from modules.model_gateway.providers.registry import AdapterRegistry, default_adapter_registry


def _declaration() -> ProviderModelDeclaration:
    return ProviderModelDeclaration(
        model_key="demo-model",
        display_name="Demo",
        context_window=128000,
        max_output_tokens=4096,
        capabilities={
            CAPABILITY_TEXT_INPUT: CAPABILITY_SUPPORTED,
            CAPABILITY_STREAMING: CAPABILITY_SUPPORTED,
        },
    )


def test_default_registry_covers_planned_provider_types() -> None:
    assert default_adapter_registry().types() == (
        "ANTHROPIC",
        "LOCAL",
        "OPENAI",
        "OPENAI_COMPATIBLE",
    )


def test_unknown_provider_type_is_rejected() -> None:
    with pytest.raises(ProviderConfigurationInvalid):
        AdapterRegistry().create("UNKNOWN", endpoint="https://example.com")


def test_capabilities_default_to_unknown() -> None:
    adapter = OpenAIAdapter(
        endpoint="https://api.openai.com/v1",
        api_key="sk-test",
        models=(_declaration(),),
    )

    capabilities = adapter.get_model_capabilities("demo-model")

    assert capabilities[CAPABILITY_TEXT_INPUT] == CAPABILITY_SUPPORTED
    assert capabilities[CAPABILITY_STREAMING] == CAPABILITY_SUPPORTED
    assert capabilities["TOOL_CALLING"] == CAPABILITY_UNKNOWN
    assert set(capabilities) == {
        "TEXT_INPUT",
        "TEXT_OUTPUT",
        "IMAGE_INPUT",
        "AUDIO_INPUT",
        "AUDIO_OUTPUT",
        "IMAGE_OUTPUT",
        "MODEL_3D_OUTPUT",
        "VIDEO_INPUT",
        "TOOL_CALLING",
        "STRUCTURED_OUTPUT",
        "JSON_SCHEMA",
        "STREAMING",
        "LONG_CONTEXT",
        "REASONING_MODE",
    }


def test_unknown_model_declaration_is_rejected() -> None:
    adapter = OpenAIAdapter(endpoint="https://api.openai.com/v1", api_key="sk-test")

    with pytest.raises(ProviderConfigurationInvalid):
        adapter.get_model_capabilities("missing-model")


def test_cloud_provider_requires_https_and_api_key() -> None:
    insecure = OpenAIAdapter(endpoint="http://api.openai.com/v1", api_key="sk-test")
    with pytest.raises(ProviderConfigurationInvalid):
        insecure.validate_configuration()

    missing_key = OpenAIAdapter(endpoint="https://api.openai.com/v1")
    with pytest.raises(ProviderNotConfigured):
        missing_key.validate_configuration()


def test_local_provider_allows_http_and_no_key() -> None:
    adapter = LocalAdapter(endpoint="http://127.0.0.1:11434")

    adapter.validate_configuration()
    assert adapter.health_check().status == "CONFIGURED"


def test_health_check_reports_unconfigured_detail() -> None:
    health = LocalAdapter(endpoint="not-a-url").health_check()

    assert health.status == "UNCONFIGURED"
    assert health.detail


def test_normalize_error_maps_provider_categories() -> None:
    adapter = LocalAdapter(endpoint="http://127.0.0.1:11434")

    timeout = adapter.normalize_error(TimeoutError("slow"))
    assert timeout.category is ProviderErrorCategory.TIMEOUT
    assert timeout.retryable is True

    unavailable = adapter.normalize_error(AppError("down", status_code=503))
    assert unavailable.category is ProviderErrorCategory.PROVIDER_UNAVAILABLE
    assert unavailable.retryable is True

    unauthorized = adapter.normalize_error(AppError("bad key", status_code=401))
    assert unauthorized.category is ProviderErrorCategory.AUTH_ERROR
    assert unauthorized.retryable is False

    unknown = adapter.normalize_error(RuntimeError("?"))
    assert unknown.category is ProviderErrorCategory.UNKNOWN_RESULT
    assert unknown.retryable is False


def test_normalize_usage_does_not_invent_fields() -> None:
    adapter = LocalAdapter(endpoint="http://127.0.0.1:11434")

    usage = adapter.normalize_usage(
        {
            "input_tokens": 10,
            "output_tokens": True,
            "total_tokens": "20",
            "cached_input_tokens": 3,
            "extra": 99,
        }
    )

    assert usage == {"input_tokens": 10, "cached_input_tokens": 3}


def test_invalid_capability_declaration_is_rejected() -> None:
    with pytest.raises(ProviderConfigurationInvalid):
        ProviderModelDeclaration(
            model_key="demo",
            display_name="Demo",
            context_window=100,
            capabilities={"NOT_A_CAPABILITY": CAPABILITY_SUPPORTED},
        )


def test_registry_duplicate_registration_is_rejected() -> None:
    registry = default_adapter_registry()

    with pytest.raises(StartupError) as exc_info:
        registry.register(PROVIDER_TYPE_OPENAI, OpenAIAdapter)

    assert "重复注册" in str(exc_info.value)
    assert registry.supports(PROVIDER_TYPE_LOCAL) is True
