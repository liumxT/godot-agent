"""音频生成适配器（E8-T07）。

提供 OpenAI Speech 协议实现，并在归一化阶段进行基础技术检查：

- 容器魔数与可解码性；
- 采样率、声道与时长；
- 峰值电平、削波与静音比例；
- 首尾不连续（用于识别明显爆音）。

更完整的音频质量规则属于 E8-T10 Quality Control。
"""

from __future__ import annotations

import io
import math
import struct
import wave
from typing import Any

from core.errors import AssetGenerationInvalid
from modules.model_gateway.asset_generation import (
    ASSET_JOB_SUCCEEDED,
    ASSET_KIND_AUDIO,
    AssetGenerationOutput,
    AssetGenerationRequest,
    AssetGenerationResult,
    BaseAssetGenerationAdapter,
)
from modules.model_gateway.models import PROVIDER_TYPE_OPENAI, PROVIDER_TYPE_OPENAI_COMPATIBLE
from modules.model_gateway.providers.base import ProviderCallFailure

_AUDIO_FORMATS = frozenset({"wav", "mp3", "ogg"})
_RESPONSE_FORMATS = {"wav": "wav", "mp3": "mp3", "ogg": "opus"}
_OPUS_SAMPLE_RATE = 48000


class OpenAIAudioAdapter(BaseAssetGenerationAdapter):
    """OpenAI ``/audio/speech`` 协议。"""

    kind = ASSET_KIND_AUDIO
    provider_types = frozenset({PROVIDER_TYPE_OPENAI, PROVIDER_TYPE_OPENAI_COMPATIBLE})
    formats = _AUDIO_FORMATS
    max_output_count = 1
    supports_async = False
    supports_cancel = False
    default_format = "wav"

    def validate_request(self, request: AssetGenerationRequest) -> None:
        super().validate_request(request)
        voice = request.parameter("voice", "alloy")
        if not isinstance(voice, str) or not voice.strip():
            raise _invalid("voice", "必须是非空字符串")
        speed = request.parameter("speed", 1.0)
        try:
            parsed_speed = float(speed)
        except (TypeError, ValueError) as error:
            raise _invalid("speed", "必须是数字") from error
        if not 0.25 <= parsed_speed <= 4.0:
            raise _invalid("speed", "必须在 0.25 到 4.0 之间")

    async def submit_generation(
        self, request: AssetGenerationRequest
    ) -> AssetGenerationResult:
        self.validate_configuration()
        output_format = request.format(self.default_format)
        payload = {
            "model": request.model_key,
            "input": request.prompt,
            "voice": str(request.parameter("voice", "alloy")),
            "response_format": _RESPONSE_FORMATS[output_format],
            "speed": float(request.parameter("speed", 1.0)),
        }
        try:
            async with self._client() as client:
                response = await client.post(
                    self.endpoint.rstrip("/") + "/audio/speech",
                    headers=self._headers(),
                    json=payload,
                )
                if response.status_code >= 400:
                    raise self._failure_from_response(response)
                data = response.content
                job_id = response.headers.get("x-request-id") or "audio_sync"
        except ProviderCallFailure:
            raise
        except Exception as error:
            raise self._failure_from_exception(error) from error
        try:
            metadata = inspect_audio(data, output_format)
        except AssetGenerationInvalidAudio as error:
            raise _audio_error(error) from error
        except AssetGenerationInvalid as error:
            raise ProviderCallFailure(
                _provider_error(error.message), sent=True
            ) from error
        output = AssetGenerationOutput(
            data=data,
            format=output_format,
            duration_seconds=metadata.get("duration_seconds"),
            sample_rate=metadata.get("sample_rate"),
            channels=metadata.get("channels"),
            metadata=metadata,
        )
        return AssetGenerationResult(
            status=ASSET_JOB_SUCCEEDED,
            provider_job_id=job_id,
            outputs=(output,),
        )


def inspect_audio(data: bytes, output_format: str) -> dict[str, Any]:
    """基础音频技术检查；不支持解码时返回容器级结果。"""

    if not data:
        raise AssetGenerationInvalidAudio("音频产物为空")
    fmt = output_format.strip().lower()
    if fmt == "wav":
        return _inspect_wav(data)
    if fmt == "ogg":
        return _inspect_ogg(data)
    if fmt == "mp3":
        return _inspect_mp3(data)
    raise AssetGenerationInvalidAudio(f"不支持的音频格式：{fmt}")


def _inspect_wav(data: bytes) -> dict[str, Any]:
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            frames = handle.readframes(frame_count)
    except (wave.Error, EOFError) as error:
        raise AssetGenerationInvalidAudio("WAV 容器无法解析") from error
    duration = frame_count / sample_rate if sample_rate else 0.0
    metrics: dict[str, Any] = {
        "container": "wav",
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width": sample_width,
        "frame_count": frame_count,
        "duration_seconds": round(duration, 6),
        "decodable": True,
    }
    if sample_width == 2 and frames:
        samples = struct.unpack(f"<{len(frames) // 2}h", frames[: (len(frames) // 2) * 2])
        metrics.update(_pcm_metrics(samples))
    return metrics


def _pcm_metrics(samples: tuple[int, ...]) -> dict[str, Any]:
    peak = max(abs(value) for value in samples)
    peak_ratio = peak / 32768.0
    silent = sum(1 for value in samples if abs(value) < 33) / len(samples)
    head_tail = abs(samples[-1] - samples[0]) / 32768.0
    return {
        "peak": peak,
        "peak_db": round(20.0 * _log10(max(peak_ratio, 1e-9)), 2),
        "clipping": peak >= 32767,
        "silence_ratio": round(silent, 4),
        "head_tail_discontinuity": round(head_tail, 4),
    }


def _inspect_ogg(data: bytes) -> dict[str, Any]:
    if not data.startswith(b"OggS"):
        raise AssetGenerationInvalidAudio("OGG 容器魔数非法")
    marker = data.find(b"OpusHead")
    if marker < 0:
        return {"container": "ogg", "codec": "unknown", "decodable": True}
    head = data[marker + 8 : marker + 19]
    if len(head) < 11:
        raise AssetGenerationInvalidAudio("OGG OpusHead 不完整")
    channels = head[1]
    input_rate = int.from_bytes(head[4:8], "little")
    pre_skip = int.from_bytes(head[2:4], "little")
    duration = _ogg_duration(data, pre_skip)
    return {
        "container": "ogg",
        "codec": "opus",
        "sample_rate": input_rate or _OPUS_SAMPLE_RATE,
        "channels": channels,
        "duration_seconds": duration,
        "decodable": True,
    }


def _ogg_duration(data: bytes, pre_skip: int) -> float | None:
    marker = data.rfind(b"OggS")
    if marker < 0 or marker + 14 > len(data):
        return None
    granule = int.from_bytes(data[marker + 6 : marker + 14], "little", signed=False)
    if granule <= 0:
        return None
    samples = max(granule - pre_skip, 0)
    return round(samples / _OPUS_SAMPLE_RATE, 6)


def _inspect_mp3(data: bytes) -> dict[str, Any]:
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return {"container": "mp3", "decodable": True}
    raise AssetGenerationInvalidAudio("MP3 容器无法识别")


def _log10(value: float) -> float:
    return math.log10(value)


class AssetGenerationInvalidAudio(Exception):
    """音频基础检查失败，适配器层转换为统一生成错误。"""


def _invalid(name: str, reason: str):
    from core.errors import AssetGenerationInvalid

    return AssetGenerationInvalid(
        "音频生成参数非法", details={"parameter": name, "reason": reason}
    )


def _provider_error(message: str):
    from modules.model_gateway.providers.errors import (
        ProviderErrorCategory,
        ProviderErrorInfo,
    )

    return ProviderErrorInfo(
        category=ProviderErrorCategory.CONTENT_REJECTED,
        message=message,
        retryable=False,
    )


def _audio_error(error: AssetGenerationInvalidAudio) -> ProviderCallFailure:
    return ProviderCallFailure(_provider_error(str(error)), sent=True)


__all__ = [
    "AssetGenerationInvalidAudio",
    "OpenAIAudioAdapter",
    "inspect_audio",
]
