"""图像生成适配器（E8-T06）。

当前提供 OpenAI Images 协议实现，其他兼容服务可通过
``OPENAI_COMPATIBLE`` provider_type 复用。适配器只负责协议转换与结果归一化，
不包含资产生命周期、版本或 License 逻辑。
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from typing import Any

from modules.model_gateway.asset_generation import (
    ASSET_JOB_SUCCEEDED,
    ASSET_KIND_IMAGE,
    AssetGenerationOutput,
    AssetGenerationRequest,
    AssetGenerationResult,
    BaseAssetGenerationAdapter,
)
from modules.model_gateway.models import PROVIDER_TYPE_OPENAI, PROVIDER_TYPE_OPENAI_COMPATIBLE
from modules.model_gateway.providers.base import ProviderCallFailure

_IMAGE_SIZES: frozenset[tuple[int, int]] = frozenset(
    {
        (256, 256),
        (512, 512),
        (768, 768),
        (1024, 1024),
        (1024, 1536),
        (1536, 1024),
        (1024, 1792),
        (1792, 1024),
    }
)


class OpenAIImageAdapter(BaseAssetGenerationAdapter):
    """OpenAI ``/images/generations`` 协议。"""

    kind = ASSET_KIND_IMAGE
    provider_types = frozenset({PROVIDER_TYPE_OPENAI, PROVIDER_TYPE_OPENAI_COMPATIBLE})
    formats = frozenset({"png", "webp", "jpeg", "jpg"})
    max_output_count = 4
    supports_async = False
    supports_cancel = False
    default_format = "png"

    def validate_request(self, request: AssetGenerationRequest) -> None:
        super().validate_request(request)
        width = _positive_int(request.parameter("width", 512), "width")
        height = _positive_int(request.parameter("height", 512), "height")
        if (width, height) not in _IMAGE_SIZES:
            raise _invalid_size(width, height)
        transparent = request.parameter("transparent_background", False)
        if not isinstance(transparent, bool):
            raise _invalid_parameter("transparent_background", "必须是布尔值")
        if transparent and request.format(self.default_format) not in {"png", "webp"}:
            raise _invalid_parameter("transparent_background", "透明背景仅支持 PNG / WebP")

    async def submit_generation(
        self, request: AssetGenerationRequest
    ) -> AssetGenerationResult:
        self.validate_configuration()
        width = _positive_int(request.parameter("width", 512), "width")
        height = _positive_int(request.parameter("height", 512), "height")
        output_format = request.format(self.default_format)
        payload: dict[str, Any] = {
            "model": request.model_key,
            "prompt": request.prompt,
            "n": request.output_count,
            "size": f"{width}x{height}",
            "response_format": "b64_json",
        }
        if output_format != "png":
            payload["output_format"] = "jpeg" if output_format == "jpg" else output_format
        if request.parameter("transparent_background", False):
            payload["background"] = "transparent"
        try:
            async with self._client() as client:
                response = await client.post(
                    self.endpoint.rstrip("/") + "/images/generations",
                    headers=self._headers(),
                    json=payload,
                )
                if response.status_code >= 400:
                    raise self._failure_from_response(response)
                data = response.json()
                outputs = await self._normalize_payload(
                    client, data, output_format, len_hint=request.output_count
                )
                job_id = _job_id(data, response)
        except ProviderCallFailure:
            raise
        except Exception as error:
            raise self._failure_from_exception(error) from error
        return AssetGenerationResult(
            status=ASSET_JOB_SUCCEEDED,
            provider_job_id=job_id,
            outputs=outputs,
        )

    async def retrieve_result(self, reference: str) -> bytes:
        """按 Provider 返回的 URL 取回原始字节。"""

        self.validate_configuration()
        if not reference.startswith(("https://", "http://")):
            raise _invalid_parameter("url", "必须是 HTTP(S) 地址")
        try:
            async with self._client() as client:
                response = await client.get(reference)
                if response.status_code >= 400:
                    raise self._failure_from_response(response)
                return response.content
        except ProviderCallFailure:
            raise
        except Exception as error:
            raise self._failure_from_exception(error) from error

    async def _normalize_payload(
        self,
        client,
        payload: Mapping[str, Any],
        output_format: str,
        *,
        len_hint: int,
    ) -> tuple[AssetGenerationOutput, ...]:
        items = payload.get("data")
        if not isinstance(items, list) or not items:
            raise ProviderCallFailure(
                _invalid_error("图像 Provider 未返回生成结果"), sent=True
            )
        if len(items) < len_hint:
            raise ProviderCallFailure(
                _invalid_error("图像 Provider 返回结果数量不足"), sent=True
            )
        outputs: list[AssetGenerationOutput] = []
        for item in items[:len_hint]:
            if not isinstance(item, Mapping):
                raise ProviderCallFailure(_invalid_error("图像结果格式非法"), sent=True)
            raw: bytes | None = None
            encoded = item.get("b64_json")
            if isinstance(encoded, str) and encoded:
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as error:
                    raise ProviderCallFailure(
                        _invalid_error("图像 Base64 解码失败"), sent=True
                    ) from error
            else:
                url = item.get("url")
                if isinstance(url, str) and url:
                    try:
                        response = await client.get(url)
                    except Exception as error:
                        raise self._failure_from_exception(error) from error
                    if response.status_code >= 400:
                        raise self._failure_from_response(response)
                    raw = response.content
            if not raw:
                raise ProviderCallFailure(
                    _invalid_error("图像结果缺少数据"), sent=True
                )
            outputs.append(
                AssetGenerationOutput(
                    data=raw,
                    format=output_format,
                    width=_optional_positive_int(item.get("width"), "width"),
                    height=_optional_positive_int(item.get("height"), "height"),
                    metadata={"revised_prompt": item.get("revised_prompt")},
                )
            )
        return tuple(outputs)


def _job_id(payload: Mapping[str, Any], response) -> str:
    value = payload.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    header = response.headers.get("x-request-id")
    if header:
        return header
    return "image_sync"


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise _invalid_parameter(name, "必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise _invalid_parameter(name, "必须是正整数") from error
    if parsed <= 0:
        raise _invalid_parameter(name, "必须是正整数")
    return parsed


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)


def _invalid_parameter(name: str, reason: str):
    from core.errors import AssetGenerationInvalid

    return AssetGenerationInvalid(
        "图像生成参数非法", details={"parameter": name, "reason": reason}
    )


def _invalid_size(width: int, height: int):
    from core.errors import AssetGenerationInvalid

    return AssetGenerationInvalid(
        "图像尺寸不受支持",
        details={"width": width, "height": height, "supported": sorted(_IMAGE_SIZES)},
    )


def _invalid_error(message: str):
    from modules.model_gateway.providers.errors import (
        ProviderErrorCategory,
        ProviderErrorInfo,
    )

    return ProviderErrorInfo(
        category=ProviderErrorCategory.INVALID_REQUEST,
        message=message,
        retryable=False,
    )
