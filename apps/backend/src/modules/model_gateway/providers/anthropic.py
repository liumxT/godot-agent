"""Anthropic Provider 适配器（E5-T03 / T08 / T09 / T10）。

Anthropic Messages API 与 OpenAI 结构差异较大：系统提示、工具调用和工具结果
都需要转换为 Anthropic 的内容块；这些差异只存在于本适配器内部。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from modules.model_gateway.models import PROVIDER_TYPE_ANTHROPIC
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
    ToolCall,
    ToolDefinition,
)

DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_OUTPUT_TOKENS = 4096


class AnthropicAdapter(BaseProviderAdapter):
    provider_type = PROVIDER_TYPE_ANTHROPIC
    requires_api_key = True
    allowed_schemes = frozenset({"https"})

    async def generate(self, request: ModelInvocationRequest) -> ProviderGenerationResult:
        payload = self._payload(request)
        async with self._client() as client:
            try:
                response = await client.post(
                    self._messages_url(), json=payload, headers=self._headers()
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
        content = data.get("content")
        if not isinstance(content, list):
            raise _invalid_response("Provider 响应缺少 content")

        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
            if block.get("type") == "tool_use":
                arguments = block.get("input")
                calls.append(
                    ToolCall(
                        call_id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=arguments if isinstance(arguments, Mapping) else {},
                    )
                )
        return ProviderGenerationResult(
            content="".join(texts) if texts else None,
            tool_calls=tuple(calls),
            finish_reason=_finish_reason(data.get("stop_reason")),
            usage=_usage_from(data.get("usage")),
            provider_request_id=_provider_request_id(data, response),
        )

    async def generate_stream(self, request: ModelInvocationRequest) -> AsyncIterator[StreamEvent]:
        payload = self._payload(request)
        payload["stream"] = True
        accumulator = ToolCallAccumulator()
        raw_usage: dict[str, int] = {}
        finish_reason = FINISH_UNKNOWN
        request_id = request.request_id
        async with self._client() as client:
            try:
                async with client.stream(
                    "POST", self._messages_url(), json=payload, headers=self._headers()
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise self._failure_from_response(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, Mapping):
                            continue
                        event_type = event.get("type")
                        if event_type == "error":
                            raise _stream_error(event)
                        if event_type == "message_start":
                            message = event.get("message")
                            message = message if isinstance(message, Mapping) else {}
                            _merge_usage(raw_usage, message.get("usage"))
                            if raw_usage:
                                yield StreamEvent(
                                    type=STREAM_USAGE_UPDATE,
                                    request_id=request_id,
                                    usage=_usage_from(raw_usage),
                                )
                        elif event_type == "content_block_start":
                            block = event.get("content_block")
                            block = block if isinstance(block, Mapping) else {}
                            index = _index(event)
                            if block.get("type") == "tool_use":
                                call_id = str(block.get("id") or "")
                                name = str(block.get("name") or "")
                                accumulator.add(index, call_id=call_id, name=name)
                                yield StreamEvent(
                                    type=STREAM_TOOL_CALL_DELTA,
                                    request_id=request_id,
                                    tool_call_delta={
                                        "index": index,
                                        "call_id": call_id,
                                        "name": name,
                                        "arguments_delta": None,
                                    },
                                )
                        elif event_type == "content_block_delta":
                            delta = event.get("delta")
                            delta = delta if isinstance(delta, Mapping) else {}
                            index = _index(event)
                            if delta.get("type") == "text_delta" and isinstance(
                                delta.get("text"), str
                            ):
                                yield StreamEvent(
                                    type=STREAM_CONTENT_DELTA,
                                    request_id=request_id,
                                    content_delta=delta["text"],
                                )
                            if delta.get("type") == "input_json_delta" and isinstance(
                                delta.get("partial_json"), str
                            ):
                                accumulator.add(index, arguments_delta=delta["partial_json"])
                                yield StreamEvent(
                                    type=STREAM_TOOL_CALL_DELTA,
                                    request_id=request_id,
                                    tool_call_delta={
                                        "index": index,
                                        "arguments_delta": delta["partial_json"],
                                    },
                                )
                        elif event_type == "message_delta":
                            delta = event.get("delta")
                            delta = delta if isinstance(delta, Mapping) else {}
                            if delta.get("stop_reason"):
                                finish_reason = _finish_reason(delta.get("stop_reason"))
                            _merge_usage(raw_usage, event.get("usage"))
                            if raw_usage:
                                yield StreamEvent(
                                    type=STREAM_USAGE_UPDATE,
                                    request_id=request_id,
                                    usage=_usage_from(raw_usage),
                                )
                        elif event_type == "message_stop":
                            break
            except ProviderCallFailure:
                raise
            except httpx.HTTPError as exc:
                raise self._failure_from_exception(exc) from exc
        accumulator.build()
        yield StreamEvent(
            type=STREAM_COMPLETED,
            request_id=request_id,
            usage=_usage_from(raw_usage),
            finish_reason=finish_reason,
        )

    def _messages_url(self) -> str:
        base = self._endpoint.rstrip("/")
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "x-api-key": self._api_key or "",
            "anthropic-version": self._api_version or DEFAULT_ANTHROPIC_VERSION,
        }

    def _payload(self, request: ModelInvocationRequest) -> dict[str, Any]:
        system_parts: list[str] = []
        if request.system_instructions:
            system_parts.append(request.system_instructions)
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            if message.role == "SYSTEM":
                system_parts.append(message.text())
                continue
            messages.append(_message_payload(message))
        payload: dict[str, Any] = {
            "model": request.model_key,
            "max_tokens": request.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
            "messages": messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.tools:
            payload["tools"] = [_tool_payload(tool) for tool in request.tools]
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload


def _message_payload(message: ModelMessage) -> dict[str, Any]:
    if message.role == "TOOL":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.text(),
                }
            ],
        }
    if message.role == "ASSISTANT":
        blocks: list[dict[str, Any]] = []
        text = message.text()
        if text:
            blocks.append({"type": "text", "text": text})
        for call in message.tool_calls:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call.call_id,
                    "name": call.name,
                    "input": dict(call.arguments),
                }
            )
        return {"role": "assistant", "content": blocks}
    blocks = [_content_payload(part) for part in message.content]
    return {"role": "user", "content": blocks}


def _content_payload(part: TextPart | ImagePart) -> dict[str, Any]:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    if part.url:
        source: dict[str, Any] = {"type": "url", "url": part.url}
    else:
        source = {
            "type": "base64",
            "media_type": part.media_type,
            "data": part.data_base64,
        }
    return {"type": "image", "source": source}


def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": dict(tool.parameters),
    }


def _finish_reason(value: Any) -> str:
    mapping = {
        "end_turn": FINISH_STOP,
        "stop_sequence": FINISH_STOP,
        "max_tokens": FINISH_MAX_TOKENS,
        "tool_use": FINISH_TOOL_CALL,
        "refusal": FINISH_CONTENT_FILTER,
    }
    return mapping.get(str(value), FINISH_UNKNOWN)


def _usage_from(raw: Any) -> ModelUsage | None:
    if not isinstance(raw, Mapping):
        return None
    usage = ModelUsage(
        input_tokens=_optional_int(raw.get("input_tokens")),
        output_tokens=_optional_int(raw.get("output_tokens")),
        cached_input_tokens=_optional_int(raw.get("cache_read_input_tokens")),
        usage_source=USAGE_SOURCE_PROVIDER,
    )
    if usage.input_tokens is None and usage.output_tokens is None:
        return None
    return usage


def _merge_usage(target: dict[str, int], raw: Any) -> None:
    if not isinstance(raw, Mapping):
        return
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
        value = _optional_int(raw.get(key))
        if value is not None:
            target[key] = value


def _provider_request_id(data: Mapping[str, Any], response: httpx.Response) -> str | None:
    value = data.get("id")
    if isinstance(value, str) and value:
        return value
    return response.headers.get("request-id")


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _index(event: Mapping[str, Any]) -> int:
    value = event.get("index")
    return value if isinstance(value, int) else 0


def _stream_error(event: Mapping[str, Any]) -> ProviderCallFailure:
    error = event.get("error")
    error = error if isinstance(error, Mapping) else {}
    return ProviderCallFailure(
        ProviderErrorInfo(
            category=ProviderErrorCategory.CONTENT_REJECTED,
            message=str(error.get("message") or "Provider 流式响应返回错误"),
            retryable=False,
            provider_code=str(error.get("type")) if error.get("type") else None,
        ),
        sent=True,
    )


def _invalid_response(message: str) -> ProviderCallFailure:
    return ProviderCallFailure(
        ProviderErrorInfo(
            category=ProviderErrorCategory.INVALID_REQUEST,
            message=message,
            retryable=False,
        ),
        sent=True,
    )
