"""Model Gateway 调用编排（E5-T08 ~ T14）。

职责：

- 统一请求校验、模型/Provider 解析与 Provider 配置装载；
- 超时、重试与错误分类；已发送但结果未知的请求标记 UNKNOWN，不自动重发；
- 持久化请求、响应、Token、费用与调用审计；
- 流式输出只在完整结束后才产生可执行工具调用。

Provider 的网络细节只存在于适配器中，本模块不引用任何厂商 SDK。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from core.errors import (
    ModelCallFailed,
    ModelRequestUnknown,
    ModelUnavailable,
    NotFoundError,
    ProviderNotConfigured,
)
from core.logging import get_logger
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.secrets.store import SecretStore
from modules.model_gateway.cost import CostBreakdown, calculate_cost
from modules.model_gateway.models import (
    MODEL_ACTIVE,
    PROVIDER_ENABLED,
    REQUEST_CANCELLED,
    REQUEST_FAILED,
    REQUEST_SENDING,
    REQUEST_STREAMING,
    REQUEST_SUCCEEDED,
    REQUEST_TIMEOUT,
    REQUEST_UNKNOWN,
    REQUEST_VALIDATING,
    RESPONSE_CANCELLED,
    RESPONSE_FAILED,
    RESPONSE_SUCCEEDED,
    ModelCallAuditModel,
    ModelCostRecordModel,
    ModelRequestModel,
    ModelResponseModel,
    ModelUsageRecordModel,
)
from modules.model_gateway.providers.base import (
    BaseProviderAdapter,
    ProviderCallFailure,
    ProviderGenerationResult,
    ProviderModelDeclaration,
    ToolCallAccumulator,
)
from modules.model_gateway.providers.errors import ProviderErrorCategory, ProviderErrorInfo
from modules.model_gateway.providers.registry import AdapterRegistry, default_adapter_registry
from modules.model_gateway.registry import ModelRegistryService, ModelView, PriceView
from modules.model_gateway.repository import (
    ModelCallAuditRepository,
    ModelCostRecordRepository,
    ModelRequestRepository,
    ModelResponseRepository,
    ModelUsageRecordRepository,
    ProviderConfigurationRepository,
)
from modules.model_gateway.schemas import (
    FINISH_CANCELLED,
    FINISH_UNKNOWN,
    STREAM_CANCELLED,
    STREAM_COMPLETED,
    STREAM_CONTENT_DELTA,
    STREAM_FAILED,
    STREAM_STARTED,
    STREAM_TOOL_CALL_DELTA,
    STREAM_USAGE_UPDATE,
    USAGE_SOURCE_PARTIAL,
    ModelInvocationRequest,
    ModelResponse,
    ModelUsage,
    StreamEvent,
    ToolCall,
    measure_request_bytes,
    validate_invocation,
)

BUDGET_CHECK_NOT_CONFIGURED = "NOT_CONFIGURED"

_TERMINAL_REQUEST_STATUSES = frozenset(
    {REQUEST_SUCCEEDED, REQUEST_FAILED, REQUEST_TIMEOUT, REQUEST_UNKNOWN, REQUEST_CANCELLED}
)
_UNRESOLVED_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.NETWORK_ERROR,
        ProviderErrorCategory.UNKNOWN_RESULT,
    }
)
_RETRYABLE_HTTP_STATUSES = frozenset(
    {
        ProviderErrorCategory.RATE_LIMIT,
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
    }
)
_SENSITIVE_KEY_HINTS = (
    "key",
    "token",
    "secret",
    "password",
    "authorization",
    "prompt",
    "content",
)


@dataclass(frozen=True, slots=True)
class ModelUsageSummary:
    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class UsageSummary:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    by_model: tuple[ModelUsageSummary, ...]


@dataclass(frozen=True, slots=True)
class CostSummary:
    input_cost: Decimal
    output_cost: Decimal
    total_cost: Decimal
    currencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditView:
    audit_id: str
    request_id: str
    project_id: str
    provider_id: str
    model_id: str
    status: str
    error_category: str | None
    requested_at: datetime
    responded_at: datetime | None
    latency_ms: int | None
    usage_id: str | None
    cost_id: str | None
    attempt_count: int
    request_bytes: int
    response_bytes: int


@dataclass(frozen=True, slots=True)
class _Prepared:
    request: ModelInvocationRequest
    model: ModelView
    adapter: BaseProviderAdapter
    price: PriceView | None
    timeout_seconds: float
    request_bytes: int


@dataclass
class _StreamAccumulator:
    content: list[str] = field(default_factory=list)
    tool_calls: ToolCallAccumulator = field(default_factory=ToolCallAccumulator)
    usage: ModelUsage | None = None
    finish_reason: str = FINISH_UNKNOWN

    def text(self) -> str | None:
        value = "".join(self.content)
        return value or None

    def add_tool_delta(self, delta: Mapping[str, Any]) -> None:
        index = delta.get("index", 0)
        index = index if isinstance(index, int) else 0
        self.tool_calls.add(
            index,
            call_id=_as_str(delta.get("call_id")),
            name=_as_str(delta.get("name")),
            arguments_delta=_as_str(delta.get("arguments_delta")),
        )

    def partial_usage(self) -> ModelUsage | None:
        if self.usage is None:
            return None
        return replace(self.usage, usage_source=USAGE_SOURCE_PARTIAL)


class ModelGatewayService:
    def __init__(
        self,
        database: DatabaseService,
        secret_store: SecretStore,
        registry: ModelRegistryService,
        *,
        adapters: AdapterRegistry | None = None,
        max_request_bytes: int = 2 * 1024 * 1024,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        default_timeout_seconds: int = 60,
        transport=None,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._secret_store = secret_store
        self._registry = registry
        self._adapters = adapters or default_adapter_registry()
        self._max_request_bytes = max_request_bytes
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._default_timeout_seconds = default_timeout_seconds
        self._transport = transport
        self._clock = clock
        self._logger = get_logger("backend.model_gateway.gateway")

    async def generate(self, request: ModelInvocationRequest) -> ModelResponse:
        prepared = await self._prepare(request)
        invocation = replace(prepared.request, request_id=_new_id("mreq_"), stream=False)
        started = self._clock()
        await self._create_request(invocation, prepared)

        attempts = 0
        result: ProviderGenerationResult | None = None
        failure: ProviderCallFailure | None = None
        while attempts <= self._max_retries:
            attempts += 1
            await self._mark(invocation.request_id, REQUEST_SENDING)
            try:
                async with asyncio.timeout(prepared.timeout_seconds):
                    result = await prepared.adapter.generate(invocation)
                break
            except TimeoutError:
                failure = _timeout_failure()
            except ProviderCallFailure as exc:
                failure = exc
            except Exception as exc:
                self._logger.exception("provider_call_unexpected_error")
                failure = ProviderCallFailure(
                    ProviderErrorInfo(
                        category=ProviderErrorCategory.UNKNOWN_RESULT,
                        message=str(exc) or type(exc).__name__,
                        retryable=False,
                    ),
                    sent=True,
                )
            if failure is None or not self._should_retry(failure, attempts):
                break
            failure = None
            await asyncio.sleep(self._retry_backoff_seconds * (2 ** (attempts - 1)))

        if result is None:
            failure = failure or _timeout_failure()
            status = await self._persist_failure(
                prepared, invocation.request_id, failure, started=started, attempts=attempts
            )
            details = {
                "request_id": invocation.request_id,
                "status": status,
                "category": failure.info.category.value,
                "retryable": False,
            }
            if status == REQUEST_UNKNOWN:
                raise ModelRequestUnknown(
                    "模型调用结果未知，不能直接重试", details=details
                )
            raise ModelCallFailed("模型调用失败", details=details)

        return await self._persist_success(
            prepared,
            invocation.request_id,
            content=result.content,
            tool_calls=result.tool_calls,
            finish_reason=result.finish_reason,
            usage=result.usage,
            provider_request_id=result.provider_request_id,
            started=started,
            attempts=attempts,
        )

    async def stream(self, request: ModelInvocationRequest) -> AsyncIterator[StreamEvent]:
        prepared = await self._prepare(request)
        invocation = replace(prepared.request, request_id=_new_id("mreq_"), stream=True)
        request_id = invocation.request_id
        started = self._clock()
        await self._create_request(invocation, prepared)

        accumulator = _StreamAccumulator()
        finalized = False
        streaming_marked = False
        yield StreamEvent(type=STREAM_STARTED, request_id=request_id)
        try:
            await self._mark(request_id, REQUEST_SENDING)
            async with asyncio.timeout(prepared.timeout_seconds):
                async for event in prepared.adapter.generate_stream(invocation):
                    if event.type == STREAM_COMPLETED:
                        accumulator.usage = event.usage or accumulator.usage
                        accumulator.finish_reason = event.finish_reason or FINISH_UNKNOWN
                        continue
                    if event.type == STREAM_CONTENT_DELTA:
                        accumulator.content.append(event.content_delta or "")
                    elif event.type == STREAM_TOOL_CALL_DELTA and event.tool_call_delta:
                        accumulator.add_tool_delta(event.tool_call_delta)
                    elif event.type == STREAM_USAGE_UPDATE:
                        accumulator.usage = event.usage or accumulator.usage
                    if not streaming_marked and event.type in (
                        STREAM_CONTENT_DELTA,
                        STREAM_TOOL_CALL_DELTA,
                    ):
                        await self._mark(request_id, REQUEST_STREAMING)
                        streaming_marked = True
                    yield event

            tool_calls = accumulator.tool_calls.build()
            await self._persist_success(
                prepared,
                request_id,
                content=accumulator.text(),
                tool_calls=tool_calls,
                finish_reason=accumulator.finish_reason,
                usage=accumulator.usage,
                provider_request_id=None,
                started=started,
                attempts=1,
            )
            finalized = True
            yield StreamEvent(
                type=STREAM_COMPLETED,
                request_id=request_id,
                usage=accumulator.usage,
                finish_reason=accumulator.finish_reason,
            )
        except ProviderCallFailure as failure:
            status = await self._persist_failure(
                prepared, request_id, failure, started=started, attempts=1,
                partial=accumulator,
            )
            finalized = True
            yield StreamEvent(
                type=STREAM_FAILED,
                request_id=request_id,
                error=failure.info,
                finish_reason=status,
            )
        except TimeoutError:
            failure = _timeout_failure()
            await self._persist_failure(
                prepared, request_id, failure, started=started, attempts=1,
                partial=accumulator,
            )
            finalized = True
            yield StreamEvent(
                type=STREAM_FAILED,
                request_id=request_id,
                error=failure.info,
                finish_reason=REQUEST_UNKNOWN,
            )
        except asyncio.CancelledError:
            await self._persist_cancel(prepared, request_id, accumulator, started=started)
            finalized = True
            yield StreamEvent(type=STREAM_CANCELLED, request_id=request_id)
            raise
        finally:
            if not finalized:
                await self._persist_cancel(
                    prepared, request_id, accumulator, started=started
                )

    async def list_requests(self, project_id: str, *, limit: int = 50, offset: int = 0):
        async with self._database.session() as session:
            return await ModelRequestRepository(session).list_by_project(
                project_id, limit=limit, offset=offset
            )

    async def get_audit(self, request_id: str) -> AuditView | None:
        async with self._database.session() as session:
            entity = await ModelCallAuditRepository(session).get_by_request(request_id)
        if entity is None:
            return None
        return AuditView(
            audit_id=entity.audit_id,
            request_id=entity.request_id,
            project_id=entity.project_id,
            provider_id=entity.provider_id,
            model_id=entity.model_id,
            status=entity.status,
            error_category=entity.error_category,
            requested_at=entity.requested_at,
            responded_at=entity.responded_at,
            latency_ms=entity.latency_ms,
            usage_id=entity.usage_id,
            cost_id=entity.cost_id,
            attempt_count=entity.attempt_count,
            request_bytes=entity.request_bytes,
            response_bytes=entity.response_bytes,
        )

    async def usage_summary(self, project_id: str) -> UsageSummary:
        async with self._database.session() as session:
            repository = ModelUsageRecordRepository(session)
            input_tokens, output_tokens, total_tokens = await repository.totals(project_id)
            by_model = await repository.totals_by_model(project_id)
        return UsageSummary(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            by_model=tuple(
                ModelUsageSummary(
                    model_id=row[0],
                    input_tokens=row[1],
                    output_tokens=row[2],
                    total_tokens=row[3],
                )
                for row in by_model
            ),
        )

    async def cost_summary(self, project_id: str) -> CostSummary:
        async with self._database.session() as session:
            repository = ModelCostRecordRepository(session)
            input_cost, output_cost = await repository.totals(project_id)
            currencies = await repository.currencies(project_id)
        return CostSummary(
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=input_cost + output_cost,
            currencies=tuple(currencies),
        )

    async def _prepare(self, request: ModelInvocationRequest) -> _Prepared:
        validate_invocation(request, max_bytes=self._max_request_bytes)
        try:
            model = await self._registry.get_model(request.model_id)
        except NotFoundError as exc:
            raise ModelUnavailable(
                "指定的模型未登记", details={"model_id": request.model_id}
            ) from exc
        if model.status != MODEL_ACTIVE:
            raise ModelUnavailable(
                "模型已禁用", details={"model_id": model.model_id}
            )
        provider = await self._registry.get_provider(model.provider_id)
        if provider.status != PROVIDER_ENABLED:
            raise ModelUnavailable(
                "Provider 已禁用", details={"provider_id": provider.provider_id}
            )
        async with self._database.session() as session:
            config = await ProviderConfigurationRepository(session).get_latest(
                provider.provider_id
            )
        if config is None or not config.enabled:
            raise ProviderNotConfigured(
                "Provider 尚未启用配置", details={"provider_id": provider.provider_id}
            )
        api_key = (
            self._secret_store.get(config.credential_ref)
            if config.credential_ref
            else None
        )
        declarations = tuple(
            ProviderModelDeclaration(
                model_key=item.model_key,
                display_name=item.display_name,
                context_window=item.context_window,
                max_output_tokens=item.max_output_tokens,
                capabilities={
                    capability.capability: capability.support_status
                    for capability in item.capabilities
                },
            )
            for item in await self._registry.list_models(provider_id=provider.provider_id)
        )
        adapter = self._adapters.create(
            provider.provider_type,
            endpoint=config.endpoint,
            api_version=config.api_version,
            api_key=api_key,
            timeout_seconds=config.timeout_seconds,
            models=declarations,
            transport=self._transport,
        )
        adapter.validate_configuration()
        timeout_seconds = (
            request.timeout_seconds
            or config.timeout_seconds
            or self._default_timeout_seconds
        )
        return _Prepared(
            request=request,
            model=model,
            adapter=adapter,
            price=model.price,
            timeout_seconds=float(timeout_seconds),
            request_bytes=measure_request_bytes(request),
        )

    async def _create_request(
        self, request: ModelInvocationRequest, prepared: _Prepared
    ) -> None:
        now = self._clock()
        metadata = {
            "model_key": request.model_key,
            "message_count": len(request.messages),
            "roles": [message.role for message in request.messages],
            "tool_count": len(request.tools),
            "has_system_instructions": bool(request.system_instructions),
            "response_format": request.response_format.kind if request.response_format else None,
            "stream": request.stream,
            "request_bytes": prepared.request_bytes,
            "client_metadata": _redact_metadata(request.metadata),
        }
        async with self._database.session() as session, transaction(session):
            await ModelRequestRepository(session).add(
                ModelRequestModel(
                    request_id=request.request_id,
                    project_id=request.project_id,
                    task_id=request.task_id,
                    attempt_id=request.attempt_id,
                    agent_instance_id=request.agent_instance_id,
                    workflow_id=request.workflow_id,
                    provider_id=prepared.model.provider_id,
                    model_id=prepared.model.model_id,
                    status=REQUEST_VALIDATING,
                    request_metadata=json.dumps(metadata, ensure_ascii=False),
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
            )

    async def _mark(self, request_id: str, status: str) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await ModelRequestRepository(session).get(request_id)
            if entity is None:
                raise NotFoundError("模型请求不存在", details={"request_id": request_id})
            if entity.status in _TERMINAL_REQUEST_STATUSES:
                return
            entity.status = status
            entity.updated_at = self._clock()

    async def _persist_success(
        self,
        prepared: _Prepared,
        request_id: str,
        *,
        content: str | None,
        tool_calls: tuple[ToolCall, ...],
        finish_reason: str,
        usage: ModelUsage | None,
        provider_request_id: str | None,
        started: datetime,
        attempts: int,
    ) -> ModelResponse:
        now = self._clock()
        latency_ms = _latency_ms(started, now)
        response_metadata = {
            "tool_calls": [
                {
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": dict(call.arguments),
                }
                for call in tool_calls
            ],
            "budget_check": BUDGET_CHECK_NOT_CONFIGURED,
        }
        response_bytes = _response_bytes(content, response_metadata)
        async with self._database.session() as session, transaction(session):
            request_entity = await ModelRequestRepository(session).get(request_id)
            if request_entity is None:
                raise NotFoundError("模型请求不存在", details={"request_id": request_id})
            request_entity.status = REQUEST_SUCCEEDED
            request_entity.updated_at = now
            request_entity.completed_at = now
            await ModelResponseRepository(session).add(
                ModelResponseModel(
                    response_id=_new_id("mrs_"),
                    request_id=request_id,
                    status=RESPONSE_SUCCEEDED,
                    response_metadata=json.dumps(response_metadata, ensure_ascii=False),
                    usage=json.dumps(usage.to_dict(), ensure_ascii=False) if usage else None,
                    finish_reason=finish_reason,
                    provider_request_id=provider_request_id,
                    latency_ms=latency_ms,
                    created_at=now,
                )
            )
            usage_id = await self._record_usage(
                session, prepared, request_id, usage, now
            )
            cost_id = await self._record_cost(
                session,
                prepared,
                request_id,
                calculate_cost(usage, prepared.price),
                now,
            )
            await self._record_audit(
                session,
                prepared,
                request_id,
                status=REQUEST_SUCCEEDED,
                error_category=None,
                started=started,
                responded_at=now,
                latency_ms=latency_ms,
                usage_id=usage_id,
                cost_id=cost_id,
                attempts=attempts,
                request_bytes=prepared.request_bytes,
                response_bytes=response_bytes,
                now=now,
            )
        self._logger.info(
            "model_call_succeeded request_id=%s model_id=%s latency_ms=%s",
            request_id,
            prepared.model.model_id,
            latency_ms,
        )
        return ModelResponse(
            request_id=request_id,
            provider_id=prepared.model.provider_id,
            model_id=prepared.model.model_id,
            status=REQUEST_SUCCEEDED,
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            provider_request_id=provider_request_id,
            latency_ms=latency_ms,
        )

    async def _persist_failure(
        self,
        prepared: _Prepared,
        request_id: str,
        failure: ProviderCallFailure,
        *,
        started: datetime,
        attempts: int,
        partial: _StreamAccumulator | None = None,
    ) -> str:
        now = self._clock()
        latency_ms = _latency_ms(started, now)
        status = _request_status_for_failure(failure)
        usage = partial.partial_usage() if partial is not None else None
        content = partial.text() if partial is not None else None
        error_payload = {
            "category": failure.info.category.value,
            "message": failure.info.message,
            "retryable": failure.info.retryable,
            "provider_code": failure.info.provider_code,
            "http_status": failure.info.http_status,
        }
        response_metadata = {"error": error_payload}
        response_bytes = _response_bytes(content, response_metadata)
        async with self._database.session() as session, transaction(session):
            request_entity = await ModelRequestRepository(session).get(request_id)
            if request_entity is None:
                raise NotFoundError("模型请求不存在", details={"request_id": request_id})
            request_entity.status = status
            request_entity.updated_at = now
            request_entity.completed_at = now
            await ModelResponseRepository(session).add(
                ModelResponseModel(
                    response_id=_new_id("mrs_"),
                    request_id=request_id,
                    status=RESPONSE_FAILED,
                    response_metadata=json.dumps(response_metadata, ensure_ascii=False),
                    usage=json.dumps(usage.to_dict(), ensure_ascii=False) if usage else None,
                    finish_reason=None,
                    provider_request_id=None,
                    latency_ms=latency_ms,
                    created_at=now,
                )
            )
            usage_id = await self._record_usage(session, prepared, request_id, usage, now)
            cost_id = await self._record_cost(
                session, prepared, request_id, calculate_cost(usage, prepared.price), now
            )
            await self._record_audit(
                session,
                prepared,
                request_id,
                status=status,
                error_category=failure.info.category.value,
                started=started,
                responded_at=now,
                latency_ms=latency_ms,
                usage_id=usage_id,
                cost_id=cost_id,
                attempts=attempts,
                request_bytes=prepared.request_bytes,
                response_bytes=response_bytes,
                now=now,
            )
        self._logger.warning(
            "model_call_failed request_id=%s status=%s category=%s",
            request_id,
            status,
            failure.info.category.value,
        )
        return status

    async def _persist_cancel(
        self,
        prepared: _Prepared,
        request_id: str,
        accumulator: _StreamAccumulator,
        *,
        started: datetime,
    ) -> None:
        now = self._clock()
        latency_ms = _latency_ms(started, now)
        usage = accumulator.partial_usage()
        content = accumulator.text()
        async with self._database.session() as session, transaction(session):
            request_entity = await ModelRequestRepository(session).get(request_id)
            if request_entity is None or request_entity.status in _TERMINAL_REQUEST_STATUSES:
                return
            request_entity.status = REQUEST_CANCELLED
            request_entity.updated_at = now
            request_entity.completed_at = now
            await ModelResponseRepository(session).add(
                ModelResponseModel(
                    response_id=_new_id("mrs_"),
                    request_id=request_id,
                    status=RESPONSE_CANCELLED,
                    response_metadata=json.dumps(
                        {
                            "cancelled": True,
                            "tool_calls": [
                                {
                                    "call_id": call.call_id,
                                    "name": call.name,
                                    "arguments": dict(call.arguments),
                                }
                                for call in _safe_tool_calls(accumulator)
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    usage=json.dumps(usage.to_dict(), ensure_ascii=False) if usage else None,
                    finish_reason=FINISH_CANCELLED,
                    provider_request_id=None,
                    latency_ms=latency_ms,
                    created_at=now,
                )
            )
            usage_id = await self._record_usage(session, prepared, request_id, usage, now)
            cost_id = await self._record_cost(
                session, prepared, request_id, calculate_cost(usage, prepared.price), now
            )
            await self._record_audit(
                session,
                prepared,
                request_id,
                status=REQUEST_CANCELLED,
                error_category="CANCELLED",
                started=started,
                responded_at=now,
                latency_ms=latency_ms,
                usage_id=usage_id,
                cost_id=cost_id,
                attempts=1,
                request_bytes=prepared.request_bytes,
                response_bytes=_response_bytes(content, {"cancelled": True}),
                now=now,
            )

    async def _record_usage(
        self,
        session,
        prepared: _Prepared,
        request_id: str,
        usage: ModelUsage | None,
        now: datetime,
    ) -> str | None:
        if usage is None:
            return None
        entity = ModelUsageRecordModel(
            usage_id=_new_id("mus_"),
            request_id=request_id,
            project_id=prepared.request.project_id,
            task_id=prepared.request.task_id,
            attempt_id=prepared.request.attempt_id,
            agent_instance_id=prepared.request.agent_instance_id,
            provider_id=prepared.model.provider_id,
            model_id=prepared.model.model_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            total_tokens=usage.total_tokens,
            usage_source=usage.usage_source,
            recorded_at=now,
        )
        await ModelUsageRecordRepository(session).add(entity)
        return entity.usage_id

    async def _record_cost(
        self,
        session,
        prepared: _Prepared,
        request_id: str,
        cost: CostBreakdown,
        now: datetime,
    ) -> str:
        entity = ModelCostRecordModel(
            cost_id=_new_id("mcs_"),
            request_id=request_id,
            project_id=prepared.request.project_id,
            task_id=prepared.request.task_id,
            attempt_id=prepared.request.attempt_id,
            agent_instance_id=prepared.request.agent_instance_id,
            provider_id=prepared.model.provider_id,
            model_id=prepared.model.model_id,
            input_cost=cost.input_cost,
            output_cost=cost.output_cost,
            cached_input_cost=cost.cached_input_cost,
            additional_cost=cost.additional_cost,
            provider_reported_cost=cost.provider_reported_cost,
            currency=cost.currency,
            pricing_version_id=cost.pricing_version_id,
            calculation_status=cost.calculation_status,
            calculated_at=now,
        )
        await ModelCostRecordRepository(session).add(entity)
        return entity.cost_id

    async def _record_audit(
        self,
        session,
        prepared: _Prepared,
        request_id: str,
        *,
        status: str,
        error_category: str | None,
        started: datetime,
        responded_at: datetime | None,
        latency_ms: int | None,
        usage_id: str | None,
        cost_id: str | None,
        attempts: int,
        request_bytes: int,
        response_bytes: int,
        now: datetime,
    ) -> None:
        await ModelCallAuditRepository(session).add(
            ModelCallAuditModel(
                audit_id=_new_id("mau_"),
                request_id=request_id,
                project_id=prepared.request.project_id,
                task_id=prepared.request.task_id,
                attempt_id=prepared.request.attempt_id,
                agent_instance_id=prepared.request.agent_instance_id,
                provider_id=prepared.model.provider_id,
                model_id=prepared.model.model_id,
                status=status,
                error_category=error_category,
                requested_at=started,
                responded_at=responded_at,
                latency_ms=latency_ms,
                usage_id=usage_id,
                cost_id=cost_id,
                attempt_count=attempts,
                request_bytes=request_bytes,
                response_bytes=response_bytes,
                metadata_json=json.dumps(
                    {"budget_check": BUDGET_CHECK_NOT_CONFIGURED}, ensure_ascii=False
                ),
                created_at=now,
            )
        )

    def _should_retry(self, failure: ProviderCallFailure, attempts: int) -> bool:
        if attempts > self._max_retries:
            return False
        if not failure.info.retryable:
            return False
        if failure.info.http_status is not None:
            # Provider 明确以 HTTP 状态拒绝时，服务端未开始计费，允许按策略重试。
            return failure.info.category in _RETRYABLE_HTTP_STATUSES
        return not failure.sent


def _request_status_for_failure(failure: ProviderCallFailure) -> str:
    if failure.sent and failure.info.category in _UNRESOLVED_CATEGORIES:
        return REQUEST_UNKNOWN
    if failure.info.category is ProviderErrorCategory.TIMEOUT:
        return REQUEST_TIMEOUT
    return REQUEST_FAILED


def _timeout_failure() -> ProviderCallFailure:
    return ProviderCallFailure(
        ProviderErrorInfo(
            category=ProviderErrorCategory.TIMEOUT,
            message="模型调用超时",
            retryable=True,
        ),
        sent=True,
    )


def _latency_ms(started: datetime, finished: datetime) -> int:
    return max(0, int((finished - started).total_seconds() * 1000))


def _response_bytes(content: str | None, metadata: Mapping[str, Any]) -> int:
    return len((content or "").encode()) + len(
        json.dumps(metadata, ensure_ascii=False, default=str).encode()
    )


def _safe_tool_calls(accumulator: _StreamAccumulator) -> tuple[ToolCall, ...]:
    try:
        return accumulator.tool_calls.build()
    except ProviderCallFailure:
        return ()


def _redact_metadata(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "[truncated]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 50:
                result["..."] = "truncated"
                break
            name = str(key)
            if any(hint in name.lower() for hint in _SENSITIVE_KEY_HINTS):
                result[name] = "[redacted]"
            else:
                result[name] = _redact_metadata(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact_metadata(item, depth + 1) for item in value[:20]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "..."
    return value


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]
