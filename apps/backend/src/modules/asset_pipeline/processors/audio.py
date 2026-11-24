"""音频处理处理器（E8-T09）。

本阶段只处理 PCM WAV，所有操作在内存中完成：

- 不调用外部编解码器或命令行工具；
- 采样帧数、文件大小与执行时间受 ``ProcessingLimits`` 限制；
- 每个处理器都校验参数，失败时抛出 ``AssetProcessingInvalid``；
- 采样位宽 1/2/3/4 字节均按 WAV 规范解释（8 位为无符号）。
"""

from __future__ import annotations

import io
import math
import struct
import wave
from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.errors import AssetProcessingInvalid
from modules.asset_pipeline.processing_types import (
    ProcessingArtifact,
    ProcessingContext,
    ProcessingPayload,
)

PROCESSOR_VERSION = "1.0"
_MAX_FRAMES = 10_000_000
_SUPPORTED_WIDTHS = (1, 2, 3, 4)
_SCALE = {1: 128.0, 2: 32768.0, 3: 8388608.0, 4: 2147483648.0}


def _invalid(message: str, **details: Any) -> AssetProcessingInvalid:
    return AssetProcessingInvalid(message, details=details or None)


def _single(payload: ProcessingPayload) -> ProcessingArtifact:
    if len(payload.artifacts) != 1:
        raise _invalid("该处理器要求单一音频输入", artifacts=len(payload.artifacts))
    return payload.artifacts[0]


def _int_param(
    parameters: Mapping[str, Any],
    name: str,
    *,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = parameters.get(name, default)
    if value is None:
        raise _invalid(f"缺少参数 {name}", parameter=name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"参数 {name} 必须是整数", parameter=name)
    if minimum is not None and value < minimum:
        raise _invalid(f"参数 {name} 不能小于 {minimum}", parameter=name, value=value)
    if maximum is not None and value > maximum:
        raise _invalid(f"参数 {name} 不能大于 {maximum}", parameter=name, value=value)
    return value


def _number_param(
    parameters: Mapping[str, Any],
    name: str,
    *,
    default: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = parameters.get(name, default)
    if value is None:
        raise _invalid(f"缺少参数 {name}", parameter=name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"参数 {name} 必须是数字", parameter=name)
    number = float(value)
    if minimum is not None and number < minimum:
        raise _invalid(f"参数 {name} 不能小于 {minimum}", parameter=name, value=number)
    if maximum is not None and number > maximum:
        raise _invalid(f"参数 {name} 不能大于 {maximum}", parameter=name, value=number)
    return number


def _db_to_ratio(db: float) -> float:
    return math.pow(10.0, db / 20.0)


def _ratio_to_db(ratio: float) -> float:
    return 20.0 * math.log10(max(ratio, 1e-12))


@dataclass(slots=True)
class _WavData:
    channels: list[array]
    sample_rate: int
    sample_width: int

    @property
    def frame_count(self) -> int:
        return len(self.channels[0]) if self.channels else 0

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.sample_rate if self.sample_rate else 0.0

    def peak(self) -> float:
        peak = 0.0
        for channel in self.channels:
            for value in channel:
                peak = max(peak, abs(value))
        return peak


def _decode_samples(raw: bytes, sample_width: int) -> list[float]:
    if sample_width == 1:
        return [(value - 128) / _SCALE[1] for value in raw]
    if sample_width == 2:
        count = len(raw) // 2
        values = struct.unpack(f"<{count}h", raw[: count * 2])
        return [value / _SCALE[2] for value in values]
    if sample_width == 3:
        samples: list[float] = []
        for offset in range(0, len(raw) - 2, 3):
            value = int.from_bytes(raw[offset : offset + 3], "little", signed=True)
            samples.append(value / _SCALE[3])
        return samples
    count = len(raw) // 4
    values = struct.unpack(f"<{count}i", raw[: count * 4])
    return [value / _SCALE[4] for value in values]


def _encode_samples(channels: list[array], sample_width: int) -> bytes:
    buffer = bytearray()
    frames = len(channels[0]) if channels else 0
    if sample_width == 1:
        for index in range(frames):
            for channel in channels:
                value = round(channel[index] * 127.0 + 128.0)
                buffer.append(max(0, min(255, value)))
        return bytes(buffer)
    if sample_width == 2:
        for index in range(frames):
            for channel in channels:
                value = round(channel[index] * 32767.0)
                buffer.extend(struct.pack("<h", max(-32768, min(32767, value))))
        return bytes(buffer)
    if sample_width == 3:
        for index in range(frames):
            for channel in channels:
                value = round(channel[index] * 8388607.0)
                value = max(-8388608, min(8388607, value))
                buffer.extend(value.to_bytes(3, "little", signed=True))
        return bytes(buffer)
    for index in range(frames):
        for channel in channels:
            value = round(channel[index] * 2147483647.0)
            value = max(-2147483648, min(2147483647, value))
            buffer.extend(struct.pack("<i", value))
    return bytes(buffer)


def _read(artifact: ProcessingArtifact, context: ProcessingContext) -> _WavData:
    if artifact.format.strip().lower() != "wav":
        raise _invalid("音频处理器仅支持 WAV", format=artifact.format)
    try:
        with wave.open(io.BytesIO(artifact.data), "rb") as handle:
            channel_count = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            raw = handle.readframes(frame_count)
    except (wave.Error, EOFError, struct.error) as error:
        raise _invalid("WAV 无法解析", format=artifact.format) from error
    if channel_count not in (1, 2):
        raise _invalid("仅支持单声道或立体声", channels=channel_count)
    if sample_width not in _SUPPORTED_WIDTHS:
        raise _invalid("不支持的采样位宽", sample_width=sample_width)
    if sample_rate <= 0:
        raise _invalid("采样率非法", sample_rate=sample_rate)
    frames = len(raw) // (channel_count * sample_width)
    if frames > _MAX_FRAMES:
        raise _invalid("音频帧数超过处理限制", frames=frames, max_frames=_MAX_FRAMES)
    samples = _decode_samples(raw[: frames * channel_count * sample_width], sample_width)
    channels = [array("d") for _ in range(channel_count)]
    for index, value in enumerate(samples):
        channels[index % channel_count].append(value)
    context.check_deadline()
    return _WavData(channels=channels, sample_rate=sample_rate, sample_width=sample_width)


def _metadata(wav: _WavData) -> dict[str, Any]:
    return {
        "audio": {
            "channels": len(wav.channels),
            "sample_rate": wav.sample_rate,
            "sample_width": wav.sample_width,
            "frames": wav.frame_count,
            "duration_seconds": round(wav.duration_seconds, 6),
            "peak_db": round(_ratio_to_db(wav.peak()), 2),
        }
    }


def _write(
    wav: _WavData,
    *,
    sample_width: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> ProcessingArtifact:
    width = sample_width or wav.sample_width
    if width not in _SUPPORTED_WIDTHS:
        raise _invalid("不支持的采样位宽", sample_width=width)
    buffer = io.BytesIO()
    try:
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(len(wav.channels))
            handle.setsampwidth(width)
            handle.setframerate(wav.sample_rate)
            handle.writeframes(_encode_samples(wav.channels, width))
    except (wave.Error, struct.error) as error:
        raise _invalid("WAV 编码失败", reason=str(error)) from error
    output = _WavData(
        channels=wav.channels,
        sample_rate=wav.sample_rate,
        sample_width=width,
    )
    metadata = _metadata(output)
    if extra:
        metadata.update(extra)
    return ProcessingArtifact(
        data=buffer.getvalue(),
        format="wav",
        filename_hint=None,
        metadata=metadata,
    )


def _convert_channels(wav: _WavData, target: int) -> _WavData:
    if len(wav.channels) == target:
        return wav
    frames = wav.frame_count
    if target == 1:
        mono = array("d")
        for index in range(frames):
            mono.append(sum(channel[index] for channel in wav.channels) / len(wav.channels))
        return _WavData(channels=[mono], sample_rate=wav.sample_rate, sample_width=wav.sample_width)
    left = wav.channels[0]
    right = array("d", left)
    return _WavData(
        channels=[array("d", left), right],
        sample_rate=wav.sample_rate,
        sample_width=wav.sample_width,
    )


def _resample(wav: _WavData, target_rate: int) -> _WavData:
    if target_rate == wav.sample_rate:
        return wav
    ratio = target_rate / wav.sample_rate
    target_frames = max(1, round(wav.frame_count * ratio))
    channels: list[array] = []
    for channel in wav.channels:
        source_frames = len(channel)
        output = array("d")
        for index in range(target_frames):
            position = index / ratio
            left_index = min(int(position), source_frames - 1)
            right_index = min(left_index + 1, source_frames - 1)
            fraction = position - left_index
            output.append(channel[left_index] * (1.0 - fraction) + channel[right_index] * fraction)
        channels.append(output)
    return _WavData(channels=channels, sample_rate=target_rate, sample_width=wav.sample_width)


class AudioResampleProcessor:
    processor_id = "audio.resample"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _int_param(parameters, "sample_rate", minimum=1, maximum=384_000)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        wav = _read(_single(payload), context)
        target = _int_param(parameters, "sample_rate", minimum=1, maximum=384_000)
        return ProcessingPayload((_write(_resample(wav, target)),))


class AudioChannelConvertProcessor:
    processor_id = "audio.channel_convert"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        channels = _int_param(parameters, "channels", minimum=1, maximum=2)
        if channels not in (1, 2):
            raise _invalid("声道数只支持 1 或 2", channels=channels)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        wav = _read(_single(payload), context)
        target = _int_param(parameters, "channels", minimum=1, maximum=2)
        return ProcessingPayload((_write(_convert_channels(wav, target)),))


class AudioFormatConvertProcessor:
    processor_id = "audio.format_convert"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        target = str(parameters.get("format", "wav")).strip().lower()
        if target != "wav":
            raise _invalid("本阶段只支持输出 WAV", format=target)
        if "sample_width" in parameters:
            _int_param(parameters, "sample_width", minimum=1, maximum=4)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        wav = _read(_single(payload), context)
        width = (
            _int_param(parameters, "sample_width", minimum=1, maximum=4)
            if "sample_width" in parameters
            else None
        )
        return ProcessingPayload((_write(wav, sample_width=width),))


class AudioLoudnessNormalizeProcessor:
    processor_id = "audio.loudness_normalize"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _number_param(parameters, "target_peak_db", default=-1.0, minimum=-60.0, maximum=0.0)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        wav = _read(_single(payload), context)
        target = _number_param(
            parameters, "target_peak_db", default=-1.0, minimum=-60.0, maximum=0.0
        )
        peak = wav.peak()
        if peak <= 0.0:
            raise _invalid("音频为静音，无法归一化")
        gain = _db_to_ratio(target) / peak
        for channel in wav.channels:
            for index in range(len(channel)):
                channel[index] = max(-1.0, min(1.0, channel[index] * gain))
        return ProcessingPayload(
            (_write(wav, extra={"normalization": {"gain_db": round(_ratio_to_db(gain), 2)}}),)
        )


class AudioPeakLimitProcessor:
    processor_id = "audio.peak_limit"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _number_param(parameters, "max_peak_db", default=-0.1, minimum=-60.0, maximum=0.0)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        wav = _read(_single(payload), context)
        limit = _db_to_ratio(
            _number_param(parameters, "max_peak_db", default=-0.1, minimum=-60.0, maximum=0.0)
        )
        peak = wav.peak()
        applied = 1.0
        if peak > limit:
            applied = limit / peak
            for channel in wav.channels:
                for index in range(len(channel)):
                    channel[index] = channel[index] * applied
        return ProcessingPayload(
            (_write(wav, extra={"peak_limit": {"applied_gain": round(applied, 6)}}),)
        )


class AudioSilenceTrimProcessor:
    processor_id = "audio.silence_trim"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _number_param(parameters, "threshold_db", default=-50.0, minimum=-120.0, maximum=0.0)
        _int_param(parameters, "padding_ms", default=0, minimum=0, maximum=60_000)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        wav = _read(_single(payload), context)
        threshold = _db_to_ratio(
            _number_param(parameters, "threshold_db", default=-50.0, minimum=-120.0, maximum=0.0)
        )
        first = None
        last = None
        for index in range(wav.frame_count):
            if any(abs(channel[index]) > threshold for channel in wav.channels):
                if first is None:
                    first = index
                last = index
        if first is None or last is None:
            raise _invalid("音频全部为静音，无法裁剪")
        padding = int(
            _int_param(parameters, "padding_ms", default=0, minimum=0, maximum=60_000)
            * wav.sample_rate
            / 1000
        )
        start = max(0, first - padding)
        end = min(wav.frame_count, last + 1 + padding)
        trimmed = _WavData(
            channels=[array("d", channel[start:end]) for channel in wav.channels],
            sample_rate=wav.sample_rate,
            sample_width=wav.sample_width,
        )
        return ProcessingPayload(
            (
                _write(
                    trimmed,
                    extra={"silence_trim": {"start_frame": start, "end_frame": end}},
                ),
            )
        )


class AudioFadeProcessor:
    processor_id = "audio.fade_in_out"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _int_param(parameters, "fade_in_ms", default=0, minimum=0, maximum=60_000)
        _int_param(parameters, "fade_out_ms", default=0, minimum=0, maximum=60_000)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        wav = _read(_single(payload), context)
        fade_in = int(
            _int_param(parameters, "fade_in_ms", default=0, minimum=0, maximum=60_000)
            * wav.sample_rate
            / 1000
        )
        fade_out = int(
            _int_param(parameters, "fade_out_ms", default=0, minimum=0, maximum=60_000)
            * wav.sample_rate
            / 1000
        )
        frames = wav.frame_count
        if fade_in + fade_out > frames:
            raise _invalid(
                "淡入淡出总长度超过音频时长",
                frames=frames,
                fade_in=fade_in,
                fade_out=fade_out,
            )
        for index in range(fade_in):
            gain = index / fade_in
            for channel in wav.channels:
                channel[index] *= gain
        for offset in range(fade_out):
            gain = offset / fade_out
            for channel in wav.channels:
                channel[frames - 1 - offset] *= gain
        return ProcessingPayload(
            (_write(wav, extra={"fade": {"fade_in_frames": fade_in, "fade_out_frames": fade_out}}),)
        )


class AudioLoopPointDetectProcessor:
    processor_id = "audio.loop_point_detect"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _number_param(parameters, "threshold_db", default=-50.0, minimum=-120.0, maximum=0.0)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        wav = _read(artifact, context)
        threshold = _db_to_ratio(
            _number_param(parameters, "threshold_db", default=-50.0, minimum=-120.0, maximum=0.0)
        )
        first = 0
        last = wav.frame_count - 1
        for index in range(wav.frame_count):
            if any(abs(channel[index]) > threshold for channel in wav.channels):
                first = index
                break
        for index in range(wav.frame_count - 1, -1, -1):
            if any(abs(channel[index]) > threshold for channel in wav.channels):
                last = index
                break
        seam = 0.0
        if wav.frame_count > 1:
            seam = max(abs(channel[last] - channel[first]) for channel in wav.channels)
        metadata = dict(artifact.metadata)
        metadata["loop"] = {
            "loop_start_frame": first,
            "loop_end_frame": last + 1,
            "seam_delta": round(seam, 6),
        }
        return ProcessingPayload(
            (
                ProcessingArtifact(
                    data=artifact.data,
                    format=artifact.format,
                    filename_hint=artifact.filename_hint,
                    metadata=metadata,
                ),
            )
        )


class AudioCompressProcessor:
    processor_id = "audio.compress"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _int_param(parameters, "sample_width", default=2, minimum=1, maximum=4)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        wav = _read(_single(payload), context)
        target = _int_param(parameters, "sample_width", default=2, minimum=1, maximum=4)
        if target >= wav.sample_width:
            raise _invalid(
                "目标位宽必须小于当前位宽",
                sample_width=wav.sample_width,
                target=target,
            )
        return ProcessingPayload((_write(wav, sample_width=target),))


def audio_processors() -> tuple[Any, ...]:
    """默认音频处理器集合。"""

    return (
        AudioResampleProcessor(),
        AudioChannelConvertProcessor(),
        AudioFormatConvertProcessor(),
        AudioLoudnessNormalizeProcessor(),
        AudioPeakLimitProcessor(),
        AudioSilenceTrimProcessor(),
        AudioFadeProcessor(),
        AudioLoopPointDetectProcessor(),
        AudioCompressProcessor(),
    )
