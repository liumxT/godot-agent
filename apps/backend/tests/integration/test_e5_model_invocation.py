"""E5 模型调用集成测试（T08 ~ T14）。

用 ``httpx.MockTransport`` 注入 Provider 网络层，验证真实 Gateway 逻辑：
请求持久化、Token / 费用 / 审计、重试、结果未知与流式取消。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ModelRequestUnknown
from infrastructure.database.service import DatabaseService
from modules.model_gateway.configuration import ProviderConfigurationService
from modules.model_gateway.gateway import ModelGatewayService
from modules.model_gateway.models import (
    CAPABILITY_SUPPORTED,
    CAPABILITY_TEXT_INPUT,
    CAPABILITY_TOOL_CALLING,
    PROVIDER_TYPE_LOCAL,
    REQUEST_CANCELLED,
    REQUEST_SUCCEEDED,
    REQUEST_UNKNOWN,
)
from modules.model_gateway.registry import CapabilitySetting, ModelRegistryService
from modules.model_gateway.repository import ModelRequestRepository
from modules.model_gateway.schemas import (
    FINISH_TOOL_CALL,
    STREAM_COMPLETED,
    STREAM_CONTENT_DELTA,
    STREAM_STARTED,
    ModelInvocationRequest,
    ModelMessage,
    TextPart,
)
from modules.project_registry.service import ProjectRegistryService


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


def _database(app) -> DatabaseService:
    return app.state.services.get("database", DatabaseService)


def _registry(app) -> ModelRegistryService:
    return app.state.services.get("model_registry_service", ModelRegistryService)


def _gateway(app, handler) -> ModelGatewayService:
    return ModelGatewayService(
        _database(app),
        app.state.services.get("secret_store"),
        _registry(app),
        transport=httpx.MockTransport(handler),
        max_retries=2,
        retry_backoff_seconds=0,
        default_timeout_seconds=5,
    )


async def _seed(app, tmp_path: Path):
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    projects = app.state.services.get("project_registry_service", ProjectRegistryService)
    project = await projects.register(project_root=str(root), name="E5 Demo")
    registry = _registry(app)
    provider = await registry.register_provider(
        name="local-llm", provider_type=PROVIDER_TYPE_LOCAL
    )
    configuration = app.state.services.get(
        "provider_configuration_service", ProviderConfigurationService
    )
    await configuration.save(
        provider.provider_id, endpoint="http://127.0.0.1:11434/v1", timeout_seconds=5
    )
    supported = CapabilitySetting(
        support_status=CAPABILITY_SUPPORTED, evidence_source="test"
    )
    model = await registry.register_model(
        provider_id=provider.provider_id,
        model_key="demo-model",
        display_name="Demo",
        context_window=32000,
        max_output_tokens=2048,
        capabilities={
            CAPABILITY_TEXT_INPUT: supported,
            CAPABILITY_TOOL_CALLING: supported,
        },
        input_price="1.5",
        output_price="6",
        source="manual",
    )
    return project, model


def _invocation(project_id: str, model, *, stream: bool = False) -> ModelInvocationRequest:
    return ModelInvocationRequest(
        project_id=project_id,
        model_id=model.model_id,
        model_key=model.model_key,
        messages=(ModelMessage(role="USER", content=(TextPart(text="hi"),)),),
        stream=stream,
    )


def _completion_payload() -> dict:
    return {
        "id": "chatcmpl-1",
        "choices": [
            {
                "message": {
                    "content": "hello back",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "main.gd"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


async def test_generate_persists_response_usage_cost_and_audit(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion_payload())

    async with _running(tmp_path) as app:
        project, model = await _seed(app, tmp_path)
        gateway = _gateway(app, handler)

        response = await gateway.generate(_invocation(project.project_id, model))

        assert len(requests) == 1
        assert str(requests[0].url).endswith("/chat/completions")
        assert response.status == REQUEST_SUCCEEDED
        assert response.content == "hello back"
        assert response.finish_reason == FINISH_TOOL_CALL
        assert response.tool_calls[0].arguments == {"path": "main.gd"}
        assert response.usage is not None and response.usage.total_tokens == 15

        audit = await gateway.get_audit(response.request_id)
        assert audit is not None
        assert audit.status == REQUEST_SUCCEEDED
        assert audit.error_category is None
        assert audit.attempt_count == 1
        assert audit.request_bytes > 0
        assert audit.usage_id is not None and audit.cost_id is not None

        usage = await gateway.usage_summary(project.project_id)
        assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (10, 5, 15)
        assert usage.by_model[0].model_id == model.model_id

        cost = await gateway.cost_summary(project.project_id)
        assert cost.input_cost == Decimal("0.000015")
        assert cost.output_cost == Decimal("0.000030")
        assert cost.total_cost == Decimal("0.000045")
        assert cost.currencies == ("USD",)


async def test_generate_retries_on_rate_limit(tmp_path: Path) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(
                429, json={"error": {"code": "rate_limit", "message": "slow down"}}
            )
        return httpx.Response(200, json=_completion_payload())

    async with _running(tmp_path) as app:
        project, model = await _seed(app, tmp_path)
        gateway = _gateway(app, handler)

        response = await gateway.generate(_invocation(project.project_id, model))

        assert len(attempts) == 2
        audit = await gateway.get_audit(response.request_id)
        assert audit is not None and audit.attempt_count == 2
        assert audit.status == REQUEST_SUCCEEDED


async def test_sent_timeout_is_unknown_and_never_retried(tmp_path: Path) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ReadTimeout("read timed out", request=request)

    async with _running(tmp_path) as app:
        project, model = await _seed(app, tmp_path)
        gateway = _gateway(app, handler)

        with pytest.raises(ModelRequestUnknown) as exc_info:
            await gateway.generate(_invocation(project.project_id, model))

        assert len(attempts) == 1
        request_id = exc_info.value.details["request_id"]
        assert exc_info.value.details["status"] == REQUEST_UNKNOWN
        audit = await gateway.get_audit(request_id)
        assert audit is not None
        assert audit.status == REQUEST_UNKNOWN
        assert audit.error_category == "TIMEOUT"


async def test_connect_error_is_retried_before_request_reaches_provider(
    tmp_path: Path,
) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=_completion_payload())

    async with _running(tmp_path) as app:
        project, model = await _seed(app, tmp_path)
        gateway = _gateway(app, handler)

        response = await gateway.generate(_invocation(project.project_id, model))

        assert len(attempts) == 2
        assert response.status == REQUEST_SUCCEEDED
        audit = await gateway.get_audit(response.request_id)
        assert audit is not None and audit.attempt_count == 2


def _stream_body() -> bytes:
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}',
        "data: [DONE]",
        "",
    ]
    return ("\n".join(lines)).encode()


async def test_stream_emits_deltas_and_persists_completion(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_stream_body(), headers={"content-type": "text/event-stream"}
        )

    async with _running(tmp_path) as app:
        project, model = await _seed(app, tmp_path)
        gateway = _gateway(app, handler)

        events = [
            event
            async for event in gateway.stream(_invocation(project.project_id, model, stream=True))
        ]

        assert events[0].type == STREAM_STARTED
        assert events[-1].type == STREAM_COMPLETED
        text = "".join(
            event.content_delta or "" for event in events if event.type == STREAM_CONTENT_DELTA
        )
        assert text == "Hello"

        audit = await gateway.get_audit(events[0].request_id)
        assert audit is not None and audit.status == REQUEST_SUCCEEDED
        usage = await gateway.usage_summary(project.project_id)
        assert usage.total_tokens == 5


async def test_stream_cancel_marks_request_cancelled(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_stream_body(), headers={"content-type": "text/event-stream"}
        )

    async with _running(tmp_path) as app:
        project, model = await _seed(app, tmp_path)
        gateway = _gateway(app, handler)

        stream = gateway.stream(_invocation(project.project_id, model, stream=True))
        started = await stream.__anext__()
        await stream.__anext__()
        await stream.aclose()

        async with _database(app).session() as session:
            entity = await ModelRequestRepository(session).get(started.request_id)
        assert entity is not None
        assert entity.status == REQUEST_CANCELLED
