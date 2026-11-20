"""OpenAI 兼容 Provider 适配器（E5-T03 / T08 / T09 / T10）。

官方 OpenAI、兼容网关与本地 OpenAI 兼容服务共用 chat/completions 协议，
差异只在 ``provider_type`` 与 endpoint 约束。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from modules.model_gateway.models import (
    PROVIDER_TYPE_OPENAI,
    PROVIDER_TYPE_OPENAI_COMPATIBLE,
)
from modules.model_gateway.providers.base import (
    BaseProviderAdapter,
    ProviderCallFailure,
    ProviderGenerationResult,
    ToolCallAccumulator,
)
from modules.model_gateway.providers.errors import ProviderErrorCategory, ProviderErrorInfo
from modules.model_gateway.schemas import (
    FINISH_CONTENT_FILTER,
    FINISH_MAX_TOKENS,
    FINISH_STOP,
    FINISH_TOOL_CALL,
    FINISH_UNKNOWN,
    RESPONSE_FORMAT_JSON_OBJECT,
    RESPONSE_FORMAT_JSON_SCHEMA,
    STREAM_COMPLETED,
    STREAM_CONTENT_DELTA,
    STREAM_TOOL_CALL_DELTA,
    STREAM_USAGE_UPDATE,
    USAGE_SOURCE_PROVIDER,
    ImagePart,
    ModelInvocationRequest,
    ModelMessage,
    ModelUsage,
    StreamEvent,
    TextPart,
    ToolDefinition,
)


class OpenAICompatibleAdapter(BaseProviderAdapter):
    provider_type = PROVIDER_TYPE_OPENAI_COMPATIBLE
    requires_api_key = True
    allowed_schemes = frozenset({"https"})

    async def generate(self, request: ModelInvocationRequest) -> ProviderGenerationResult:
        payload = self._payload(request, stream=False)
        async with self._client() as client:
            try:
                response = await client.post(
                    self._completions_url(), json=payload, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise self._failure_from_exception(exc) from exc
        if response.status_code >= 400:
            raise self._failure_from_response(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise _invalid_response("Provider 响应不是合法 JSON") from exc
        if not isinstance(data, Mapping):
            raise _invalid_response("Provider 响应结构非法")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise _invalid_response("Provider 响应缺少 choices")
        choice = choices[0] if isinstance(choices[0], Mapping) else {}
        message = choice.get("message")
        message = message if isinstance(message, Mapping) else {}

        accumulator = ToolCallAccumulator()
        raw_calls = message.get("tool_calls")
        for index, item in enumerate(raw_calls if isinstance(raw_calls, list) else []):
            if not isinstance(item, Mapping):
                continue
            function = item.get("function")
            function = function if isinstance(function, Mapping) else {}
            accumulator.add_complete(
                str(item.get("id") or f"call_{index}"),
                str(function.get("name") or ""),
                str(function.get("arguments") or "{}"),
            )
        return ProviderGenerationResult(
            content=_content_text(message.get("content")),
            tool_calls=accumulator.build(),
            finish_reason=_finish_reason(choice.get("finish_reason")),
            usage=_usage_from(data.get("usage")),
            provider_request_id=_provider_request_id(data, response),
        )

    async def generate_stream(
        self, request: ModelInvocationRequest
    ) -> AsyncIterator[StreamEvent]:
        payload = self._payload(request, stream=True)
        accumulator = ToolCallAccumulator()
        usage: ModelUsage | None = None
        finish_reason = FINISH_UNKNOWN
        request_id = request.request_id
        async with self._client() as client:
            try:
                async with client.stream(
                    "POST", self._completions_url(), json=payload, headers=self._headers()
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise self._failure_from_response(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        if not raw:
                            continue
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(chunk, Mapping):
                            continue
                        chunk_usage = _usage_from(chunk.get("usage"))
                        if chunk_usage is not None:
                            usage = chunk_usage
                            yield StreamEvent(
                                type=STREAM_USAGE_UPDATE,
                                request_id=request_id,
                                usage=chunk_usage,
                            )
                        choices = chunk.get("choices")
                        for choice in choices if isinstance(choices, list) else []:
                            if not isinstance(choice, Mapping):
                                continue
                            delta = choice.get("delta")
                            delta = delta if isinstance(delta, Mapping) else {}
                            text = delta.get("content")
                            if isinstance(text, str) and text:
                                yield StreamEvent(
                                    type=STREAM_CONTENT_DELTA,
                                    request_id=request_id,
                                    content_delta=text,
                                )
                            raw_calls = delta.get("tool_calls")
                            for item in raw_calls if isinstance(raw_calls, list) else []:
                                if not isinstance(item, Mapping):
                                    continue
                                function = item.get("function")
                                function = function if isinstance(function, Mapping) else {}
                                index = item.get("index", 0)
                                index = index if isinstance(index, int) else 0
                                bit = {
                                    "index": index,
                                    "call_id": item.get("id"),
                                    "name": function.get("name"),
                                    "arguments_delta": function.get("arguments"),
                                }
                                accumulator.add(
                                    index,
                                    call_id=_as_str(item.get("id")),
                                    name=_as_str(function.get("name")),
                                    arguments_delta=_as_str(function.get("arguments")),
                                )
                                yield StreamEvent(
                                    type=STREAM_TOOL_CALL_DELTA,
                                    request_id=request_id,
                                    tool_call_delta=bit,
                                )
                            if choice.get("finish_reason"):
                                finish_reason = _finish_reason(choice.get("finish_reason"))
            except ProviderCallFailure:
                raise
            except httpx.HTTPError as exc:
                raise self._failure_from_exception(exc) from exc
        accumulator.build()
        yield StreamEvent(
            type=STREAM_COMPLETED,
            request_id=request_id,
            usage=usage,
            finish_reason=finish_reason,
        )

    def _completions_url(self) -> str:
        return self._endpoint.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers

    def _payload(self, request: ModelInvocationRequest, *, stream: bool) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if request.system_instructions:
            messages.append({"role": "system", "content": request.system_instructions})
        messages.extend(_message_payload(message) for message in request.messages)
        payload: dict[str, Any] = {
            "model": request.model_key,
            "messages": messages,
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = [_tool_payload(tool) for tool in request.tools]
        if request.response_format is not None:
            payload["response_format"] = _response_format_payload(
                request.response_format.kind, request.response_format.schema
            )
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload


class OpenAIAdapter(OpenAICompatibleAdapter):
    provider_type = PROVIDER_TYPE_OPENAI


def _message_payload(message: ModelMessage) -> dict[str, Any]:
    role = message.role.lower()
    if message.role == "TOOL":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.text(),
        }
    if not message.content:
        content: Any = None
    elif all(isinstance(part, TextPart) for part in message.content):
        content = message.text()
    else:
        content = [_content_payload(part) for part in message.content]
    payload: dict[str, Any] = {"role": role, "content": content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _content_payload(part: TextPart | ImagePart) -> dict[str, Any]:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    url = part.url or f"data:{part.media_type};base64,{part.data_base64}"
    return {"type": "image_url", "image_url": {"url": url}}


def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _response_format_payload(kind: str, schema: Mapping[str, Any] | None) -> dict[str, Any]:
    if kind == RESPONSE_FORMAT_JSON_OBJECT:
        return {"type": "json_object"}
    if kind == RESPONSE_FORMAT_JSON_SCHEMA:
        return {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": dict(schema or {}), "strict": True},
        }
    return {"type": "text"}


def _content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, Mapping)
            and item.get("type") in ("text", "output_text")
            and isinstance(item.get("text"), str)
        ]
        return "".join(texts) if texts else None
    return None


def _finish_reason(value: Any) -> str:
    mapping = {
        "stop": FINISH_STOP,
        "length": FINISH_MAX_TOKENS,
        "tool_calls": FINISH_TOOL_CALL,
        "function_call": FINISH_TOOL_CALL,
        "content_filter": FINISH_CONTENT_FILTER,
    }
    return mapping.get(str(value), FINISH_UNKNOWN)


def _usage_from(raw: Any) -> ModelUsage | None:
    if not isinstance(raw, Mapping):
        return None
    prompt_details = raw.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, Mapping) else {}
    completion_details = raw.get("completion_tokens_details")
    completion_details = completion_details if isinstance(completion_details, Mapping) else {}
    usage = ModelUsage(
        input_tokens=_optional_int(raw.get("prompt_tokens")),
        output_tokens=_optional_int(raw.get("completion_tokens")),
        cached_input_tokens=_optional_int(prompt_details.get("cached_tokens")),
        reasoning_tokens=_optional_int(completion_details.get("reasoning_tokens")),
        total_tokens=_optional_int(raw.get("total_tokens")),
        usage_source=USAGE_SOURCE_PROVIDER,
    )
    if all(
        value is None
        for value in (
            usage.input_tokens,
            usage.output_tokens,
            usage.cached_input_tokens,
            usage.reasoning_tokens,
            usage.total_tokens,
        )
    ):
        return None
    return usage


def _provider_request_id(data: Mapping[str, Any], response: httpx.Response) -> str | None:
    value = data.get("id")
    if isinstance(value, str) and value:
        return value
    return response.headers.get("x-request-id")


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _invalid_response(message: str) -> ProviderCallFailure:
    return ProviderCallFailure(
        ProviderErrorInfo(
            category=ProviderErrorCategory.INVALID_REQUEST,
            message=message,
            retryable=False,
        ),
        sent=True,
    )
