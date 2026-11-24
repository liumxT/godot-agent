"""E5 统一请求 / 响应 / 费用 / 工具调用聚合单元测试（T08 / T09 / T11 / T12 / T14）。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from core.errors import ProviderConfigurationInvalid, RequestTooLarge, ValidationFailed
from modules.model_gateway.cost import (
    CALCULATION_ESTIMATED,
    CALCULATION_UNAVAILABLE,
    calculate_cost,
)
from modules.model_gateway.models import CAPABILITY_TEXT_INPUT
from modules.model_gateway.providers.base import (
    ProviderCallFailure,
    ProviderModelDeclaration,
    ToolCallAccumulator,
)
from modules.model_gateway.providers.errors import ProviderErrorCategory
from modules.model_gateway.providers.openai import OpenAIAdapter
from modules.model_gateway.registry import PriceView
from modules.model_gateway.schemas import (
    ModelInvocationRequest,
    ModelMessage,
    ModelUsage,
    TextPart,
    ToolCall,
    ToolDefinition,
    validate_invocation,
)


def _text(value: str) -> TextPart:
    return TextPart(text=value)


def _request(*, tools: tuple[ToolDefinition, ...] = ()) -> ModelInvocationRequest:
    return ModelInvocationRequest(
        project_id="prj_demo",
        model_id="mdl_demo",
        model_key="demo-model",
        messages=(ModelMessage(role="USER", content=(_text("hello"),)),),
        tools=tools,
    )


def _price() -> PriceView:
    return PriceView(
        price_version_id="mpv_test",
        input_price=Decimal("1.5"),
        output_price=Decimal(6),
        currency="USD",
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_message_rules_require_tool_call_id_and_content() -> None:
    with pytest.raises(ValidationFailed):
        ModelMessage(role="TOOL", content=(_text("result"),))
    with pytest.raises(ValidationFailed):
        ModelMessage(role="USER", content=())
    with pytest.raises(ValidationFailed):
        ModelMessage(role="ASSISTANT", content=())

    assistant = ModelMessage(
        role="ASSISTANT",
        tool_calls=(ToolCall(call_id="call_1", name="read_file", arguments={}),),
    )
    assert assistant.tool_calls[0].name == "read_file"
    tool = ModelMessage(role="TOOL", content=(_text("ok"),), tool_call_id="call_1")
    assert tool.tool_call_id == "call_1"


def test_invocation_rejects_duplicate_tools_and_oversized_requests() -> None:
    tool = ToolDefinition(
        name="read_file",
        description="read",
        parameters={"type": "object", "properties": {}},
    )
    with pytest.raises(ValidationFailed):
        validate_invocation(_request(tools=(tool, tool)), max_bytes=1024 * 1024)
    with pytest.raises(RequestTooLarge):
        validate_invocation(_request(), max_bytes=8)
    validate_invocation(_request(tools=(tool,)), max_bytes=1024 * 1024)


def test_usage_rejects_negative_tokens() -> None:
    with pytest.raises(ValidationFailed):
        ModelUsage(input_tokens=-1)
    usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    assert usage.to_dict()["input_tokens"] == 10


def test_cost_is_estimated_from_price_version() -> None:
    usage = ModelUsage(input_tokens=1_000_000, output_tokens=500_000, total_tokens=1_500_000)
    cost = calculate_cost(usage, _price())

    assert cost.calculation_status == CALCULATION_ESTIMATED
    assert cost.input_cost == Decimal("1.500000")
    assert cost.output_cost == Decimal("3.000000")
    assert cost.pricing_version_id == "mpv_test"
    assert cost.currency == "USD"


def test_cost_is_unavailable_without_usage_or_price() -> None:
    assert calculate_cost(None, _price()).calculation_status == CALCULATION_UNAVAILABLE
    missing_price = calculate_cost(ModelUsage(input_tokens=10), None)
    assert missing_price.calculation_status == CALCULATION_UNAVAILABLE
    assert missing_price.input_cost is None


def test_tool_call_accumulator_requires_complete_json() -> None:
    accumulator = ToolCallAccumulator()
    accumulator.add(0, call_id="call_1", name="read_file", arguments_delta='{"path": ')
    with pytest.raises(ProviderCallFailure):
        accumulator.build()

    accumulator.add(0, arguments_delta='"main.gd"}')
    calls = accumulator.build()
    assert len(calls) == 1
    assert calls[0].arguments == {"path": "main.gd"}

    complete = ToolCallAccumulator()
    complete.add_complete("call_2", "write_file", '{"path": "x"}')
    assert complete.build()[0].name == "write_file"


def test_adapter_classifies_http_and_transport_failures() -> None:
    adapter = OpenAIAdapter(endpoint="https://api.example.com/v1", api_key="sk-test")

    rate_limited = adapter._failure_from_response(
        httpx.Response(429, json={"error": {"code": "rate_limit", "message": "slow"}})
    )
    assert rate_limited.info.category is ProviderErrorCategory.RATE_LIMIT
    assert rate_limited.sent is True

    server_error = adapter._failure_from_response(httpx.Response(503, text="down"))
    assert server_error.info.category is ProviderErrorCategory.PROVIDER_UNAVAILABLE

    unauthorized = adapter._failure_from_response(httpx.Response(401, text="no"))
    assert unauthorized.info.category is ProviderErrorCategory.AUTH_ERROR

    connect = adapter._failure_from_exception(httpx.ConnectError("refused"))
    assert connect.info.category is ProviderErrorCategory.NETWORK_ERROR
    assert connect.sent is False

    timeout = adapter._failure_from_exception(httpx.ReadTimeout("slow"))
    assert timeout.info.category is ProviderErrorCategory.TIMEOUT
    assert timeout.sent is True


def test_provider_declaration_rejects_unknown_capability() -> None:
    with pytest.raises(ProviderConfigurationInvalid):
        ProviderModelDeclaration(
            model_key="m",
            display_name="M",
            context_window=1000,
            capabilities={"NOT_A_CAPABILITY": "SUPPORTED"},
        )
    declaration = ProviderModelDeclaration(
        model_key="m",
        display_name="M",
        context_window=1000,
        capabilities={CAPABILITY_TEXT_INPUT: "SUPPORTED"},
    )
    assert declaration.capabilities[CAPABILITY_TEXT_INPUT] == "SUPPORTED"
