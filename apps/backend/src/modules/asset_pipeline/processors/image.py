"""图像处理处理器（E8-T09）。

所有处理器只操作内存中的 ``ProcessingArtifact``：

- 不读取任意文件路径，不接受外部 URL；
- 解码前后都检查像素数、文件大小与产物数量；
- 输出统一重新编码，并记录尺寸、模式、格式与帧数；
- 参数非法一律抛出 ``AssetProcessingInvalid``。
"""

from __future__ import annotations

import io
import math
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from core.errors import AssetProcessingInvalid
from modules.asset_pipeline.processing_types import (
    ProcessingArtifact,
    ProcessingContext,
    ProcessingPayload,
)

PROCESSOR_VERSION = "1.0"

_PIL_FORMATS = {
    "png": "PNG",
    "webp": "WEBP",
    "jpeg": "JPEG",
    "bmp": "BMP",
    "gif": "GIF",
    "tiff": "TIFF",
}
_FORMAT_BY_PIL = {value: key for key, value in _PIL_FORMATS.items()}
_RESAMPLING = {
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
}
_COLOR_MODES = frozenset({"RGB", "RGBA", "L", "LA", "P"})


def _invalid(message: str, **details: Any) -> AssetProcessingInvalid:
    return AssetProcessingInvalid(message, details=details or None)


def _single(payload: ProcessingPayload) -> ProcessingArtifact:
    if len(payload.artifacts) != 1:
        raise _invalid("该处理器要求单一图像输入", artifacts=len(payload.artifacts))
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


def _bool_param(
    parameters: Mapping[str, Any], name: str, *, default: bool = False
) -> bool:
    value = parameters.get(name, default)
    if not isinstance(value, bool):
        raise _invalid(f"参数 {name} 必须是布尔值", parameter=name)
    return value


def _format_param(parameters: Mapping[str, Any], name: str, *, default: str) -> str:
    value = str(parameters.get(name, default)).strip().lower()
    if value not in _PIL_FORMATS:
        raise _invalid(
            "不支持的图像格式", parameter=name, value=value, allowed=sorted(_PIL_FORMATS)
        )
    return value


def _resample_param(parameters: Mapping[str, Any], *, default: str = "lanczos"):
    value = str(parameters.get("resample", default)).strip().lower()
    if value not in _RESAMPLING:
        raise _invalid(
            "不支持的重采样算法", parameter="resample", value=value, allowed=sorted(_RESAMPLING)
        )
    return _RESAMPLING[value]


def _color_param(value: Any, *, channels: int) -> tuple[int, ...]:
    if value is None:
        return tuple([0] * (channels - 1) + [0]) if channels == 4 else tuple([0] * channels)
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) not in (6, 8):
            raise _invalid("颜色必须是 #RRGGBB 或 #RRGGBBAA", color=value)
        try:
            raw = bytes.fromhex(text)
        except ValueError as error:
            raise _invalid("颜色格式非法", color=value) from error
        rgba = tuple(raw) if len(raw) == 4 else tuple(raw) + (255,)
        return rgba if channels == 4 else rgba[:channels]
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        parts = tuple(int(item) for item in value)
        if any(item < 0 or item > 255 for item in parts):
            raise _invalid("颜色通道必须在 0-255 之间", color=value)
        return parts if channels == 4 else parts[:channels]
    raise _invalid("颜色参数非法", color=value)


def _open(artifact: ProcessingArtifact, context: ProcessingContext) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(artifact.data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise _invalid("图像无法解码", format=artifact.format) from error
    context.check_pixels(*image.size)
    return image


def _image_metadata(image: Image.Image, image_format: str) -> dict[str, Any]:
    return {
        "format": image_format,
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "frames": int(getattr(image, "n_frames", 1) or 1),
        "has_alpha": image.mode in ("RGBA", "LA"),
    }


def _encode(
    image: Image.Image,
    image_format: str,
    *,
    quality: int | None = None,
    optimize: bool = False,
    compress_level: int | None = None,
) -> ProcessingArtifact:
    pil_format = _PIL_FORMATS[image_format]
    target = image
    if pil_format == "JPEG" and target.mode not in ("RGB", "L"):
        target = target.convert("RGB")
    save_kwargs: dict[str, Any] = {}
    if pil_format in ("JPEG", "WEBP") and quality is not None:
        save_kwargs["quality"] = quality
    if pil_format == "PNG" and compress_level is not None:
        save_kwargs["compress_level"] = compress_level
    if optimize:
        save_kwargs["optimize"] = True
    buffer = io.BytesIO()
    try:
        target.save(buffer, format=pil_format, **save_kwargs)
    except (OSError, ValueError) as error:
        raise _invalid("图像编码失败", format=image_format, reason=str(error)) from error
    return ProcessingArtifact(
        data=buffer.getvalue(),
        format=image_format,
        filename_hint=None,
        metadata=_image_metadata(target, image_format),
    )


def _replace(
    artifact: ProcessingArtifact,
    *,
    metadata: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> ProcessingArtifact:
    merged = dict(artifact.metadata)
    if extra:
        merged.update(extra)
    if metadata is not None:
        merged["image"] = dict(metadata)
    return ProcessingArtifact(
        data=artifact.data,
        format=artifact.format,
        filename_hint=artifact.filename_hint,
        metadata=merged,
    )


class ImageDecodeProcessor:
    """校验图像可解码，并输出标准化元数据。"""

    processor_id = "image.decode"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        if not isinstance(parameters, Mapping):
            raise _invalid("处理参数必须是对象")

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        return ProcessingPayload(
            (_replace(artifact, metadata=_image_metadata(image, artifact.format)),)
        )


class ImageResizeProcessor:
    processor_id = "image.resize"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _int_param(parameters, "width", minimum=1, maximum=16384)
        _int_param(parameters, "height", minimum=1, maximum=16384)
        _resample_param(parameters)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        width = _int_param(parameters, "width", minimum=1, maximum=16384)
        height = _int_param(parameters, "height", minimum=1, maximum=16384)
        context.check_pixels(width, height)
        resized = image.resize((width, height), _resample_param(parameters))
        return ProcessingPayload((_encode(resized, artifact.format),))


class ImageCropProcessor:
    processor_id = "image.crop"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        box = parameters.get("box")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise _invalid("crop 需要 box=[left, top, right, bottom]")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in box):
            raise _invalid("box 必须是整数数组")
        left, top, right, bottom = box
        if right <= left or bottom <= top:
            raise _invalid("box 的右下角必须大于左上角", box=list(box))

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        left, top, right, bottom = (int(item) for item in parameters["box"])
        if left < 0 or top < 0 or right > image.width or bottom > image.height:
            raise _invalid(
                "crop 区域超出图像范围",
                box=[left, top, right, bottom],
                width=image.width,
                height=image.height,
            )
        return ProcessingPayload((_encode(image.crop((left, top, right, bottom)), artifact.format),))


class ImagePadProcessor:
    processor_id = "image.pad"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        for name in ("left", "top", "right", "bottom"):
            _int_param(parameters, name, default=0, minimum=0, maximum=16384)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        limits = tuple(
            _int_param(parameters, name, default=0, minimum=0, maximum=16384)
            for name in ("left", "top", "right", "bottom")
        )
        context.check_pixels(
            image.width + limits[0] + limits[2], image.height + limits[1] + limits[3]
        )
        channels = 4 if image.mode in ("RGBA", "LA") else 3
        fill = _color_param(parameters.get("color"), channels=channels)
        padded = ImageOps.expand(image, border=limits, fill=fill)
        return ProcessingPayload((_encode(padded, artifact.format),))


class ImageBackgroundRemoveProcessor:
    processor_id = "image.background_remove"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _int_param(parameters, "tolerance", default=16, minimum=0, maximum=255)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context).convert("RGBA")
        tolerance = _int_param(parameters, "tolerance", default=16, minimum=0, maximum=255)
        raw_color = parameters.get("color")
        if raw_color is None:
            color = image.getpixel((0, 0))[:3]
        else:
            color = _color_param(raw_color, channels=3)
        background = Image.new("RGB", image.size, color)
        difference = ImageChops.difference(image.convert("RGB"), background).convert("L")
        mask = difference.point(lambda value: 255 if value > tolerance else 0)
        alpha = ImageChops.multiply(image.getchannel("A"), mask)
        image.putalpha(alpha)
        return ProcessingPayload((_encode(image, artifact.format),))


class ImageAlphaValidateProcessor:
    processor_id = "image.alpha_validate"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _bool_param(parameters, "require_alpha", default=True)
        _number_param(
            parameters, "min_opaque_ratio", default=0.0, minimum=0.0, maximum=1.0
        )
        _number_param(
            parameters, "max_transparent_ratio", default=1.0, minimum=0.0, maximum=1.0
        )

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        require_alpha = _bool_param(parameters, "require_alpha", default=True)
        min_opaque = _number_param(
            parameters, "min_opaque_ratio", default=0.0, minimum=0.0, maximum=1.0
        )
        max_transparent = _number_param(
            parameters, "max_transparent_ratio", default=1.0, minimum=0.0, maximum=1.0
        )
        has_alpha = image.mode in ("RGBA", "LA", "PA")
        if require_alpha and not has_alpha:
            raise _invalid("图像缺少 Alpha 通道", mode=image.mode)
        stats: dict[str, Any] = {
            "mode": image.mode,
            "has_alpha": has_alpha,
            "width": image.width,
            "height": image.height,
        }
        if has_alpha:
            alpha = image.convert("RGBA").getchannel("A")
            histogram = alpha.histogram()
            total = max(sum(histogram), 1)
            opaque = histogram[255] / total
            transparent = histogram[0] / total
            partial = 1.0 - opaque - transparent
            stats.update(
                {
                    "opaque_ratio": round(opaque, 6),
                    "transparent_ratio": round(transparent, 6),
                    "partial_ratio": round(partial, 6),
                }
            )
            if opaque < min_opaque:
                raise _invalid(
                    "图像不透明像素比例过低",
                    opaque_ratio=round(opaque, 6),
                    min_opaque_ratio=min_opaque,
                )
            if transparent > max_transparent:
                raise _invalid(
                    "图像透明像素比例过高",
                    transparent_ratio=round(transparent, 6),
                    max_transparent_ratio=max_transparent,
                )
        elif min_opaque > 0.0:
            raise _invalid("图像缺少 Alpha 通道，无法满足不透明比例要求")
        return ProcessingPayload((_replace(artifact, extra={"alpha": stats}),))


class ImageFormatConvertProcessor:
    processor_id = "image.format_convert"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _format_param(parameters, "format", default="png")
        if "quality" in parameters:
            _int_param(parameters, "quality", minimum=1, maximum=100)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        target = _format_param(parameters, "format", default="png")
        quality = (
            _int_param(parameters, "quality", minimum=1, maximum=100)
            if "quality" in parameters
            else None
        )
        return ProcessingPayload((_encode(image, target, quality=quality),))


class ImageColorConvertProcessor:
    processor_id = "image.color_convert"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        mode = str(parameters.get("mode", "")).strip().upper()
        if mode not in _COLOR_MODES:
            raise _invalid(
                "不支持的颜色模式",
                parameter="mode",
                value=mode,
                allowed=sorted(_COLOR_MODES),
            )

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        return ProcessingPayload((_encode(image.convert(parameters["mode"].upper()), artifact.format),))


class ImageSpriteSheetSliceProcessor:
    processor_id = "image.sprite_sheet_slice"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _int_param(parameters, "frame_width", minimum=1, maximum=8192)
        _int_param(parameters, "frame_height", minimum=1, maximum=8192)
        _int_param(parameters, "columns", minimum=1, maximum=1024)
        _int_param(parameters, "rows", minimum=1, maximum=1024)
        _int_param(parameters, "margin", default=0, minimum=0, maximum=4096)
        _int_param(parameters, "spacing", default=0, minimum=0, maximum=4096)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        frame_width = _int_param(parameters, "frame_width", minimum=1, maximum=8192)
        frame_height = _int_param(parameters, "frame_height", minimum=1, maximum=8192)
        columns = _int_param(parameters, "columns", minimum=1, maximum=1024)
        rows = _int_param(parameters, "rows", minimum=1, maximum=1024)
        margin = _int_param(parameters, "margin", default=0, minimum=0, maximum=4096)
        spacing = _int_param(parameters, "spacing", default=0, minimum=0, maximum=4096)
        expected_width = margin * 2 + columns * frame_width + (columns - 1) * spacing
        expected_height = margin * 2 + rows * frame_height + (rows - 1) * spacing
        if image.width != expected_width or image.height != expected_height:
            raise _invalid(
                "Sprite Sheet 网格与图像尺寸不匹配",
                expected=[expected_width, expected_height],
                actual=[image.width, image.height],
            )
        artifacts: list[ProcessingArtifact] = []
        for row in range(rows):
            for column in range(columns):
                left = margin + column * (frame_width + spacing)
                top = margin + row * (frame_height + spacing)
                frame = image.crop((left, top, left + frame_width, top + frame_height))
                encoded = _encode(frame, artifact.format)
                artifacts.append(
                    ProcessingArtifact(
                        data=encoded.data,
                        format=encoded.format,
                        filename_hint=f"frame_{row:02d}_{column:02d}.{encoded.format}",
                        metadata=encoded.metadata,
                    )
                )
        context.check_artifacts(len(artifacts))
        return ProcessingPayload(tuple(artifacts))


class ImageAtlasPackProcessor:
    processor_id = "image.atlas_pack"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _int_param(parameters, "columns", default=4, minimum=1, maximum=1024)
        _int_param(parameters, "padding", default=0, minimum=0, maximum=4096)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        columns = _int_param(parameters, "columns", default=4, minimum=1, maximum=1024)
        padding = _int_param(parameters, "padding", default=0, minimum=0, maximum=4096)
        images = [_open(artifact, context).convert("RGBA") for artifact in payload.artifacts]
        cell_width = max(item.width for item in images)
        cell_height = max(item.height for item in images)
        rows = math.ceil(len(images) / columns)
        sheet_width = columns * cell_width + padding * (columns + 1)
        sheet_height = rows * cell_height + padding * (rows + 1)
        context.check_pixels(sheet_width, sheet_height)
        sheet = Image.new("RGBA", (sheet_width, sheet_height), (0, 0, 0, 0))
        for index, item in enumerate(images):
            row, column = divmod(index, columns)
            sheet.paste(
                item,
                (
                    padding + column * (cell_width + padding),
                    padding + row * (cell_height + padding),
                ),
            )
        output_format = _format_param(parameters, "format", default="png")
        return ProcessingPayload((_encode(sheet, output_format),))


class ImagePixelArtScaleProcessor:
    processor_id = "image.pixel_art_scale"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _int_param(parameters, "scale", default=2, minimum=1, maximum=16)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        scale = _int_param(parameters, "scale", default=2, minimum=1, maximum=16)
        width = image.width * scale
        height = image.height * scale
        context.check_pixels(width, height)
        if scale == 1:
            return ProcessingPayload((_replace(artifact, metadata=_image_metadata(image, artifact.format)),))
        scaled = image.resize((width, height), Image.Resampling.NEAREST)
        return ProcessingPayload((_encode(scaled, artifact.format),))


class ImageCompressProcessor:
    processor_id = "image.compress"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        _format_param(parameters, "format", default="webp")
        if "quality" in parameters:
            _int_param(parameters, "quality", default=80, minimum=1, maximum=100)
        if "compress_level" in parameters:
            _int_param(parameters, "compress_level", default=6, minimum=0, maximum=9)
        _bool_param(parameters, "optimize", default=False)

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        target = _format_param(parameters, "format", default="webp")
        quality = (
            _int_param(parameters, "quality", default=80, minimum=1, maximum=100)
            if "quality" in parameters
            else 80
        )
        compress_level = (
            _int_param(parameters, "compress_level", default=6, minimum=0, maximum=9)
            if "compress_level" in parameters
            else None
        )
        optimize = _bool_param(parameters, "optimize", default=False)
        return ProcessingPayload(
            (
                _encode(
                    image,
                    target,
                    quality=quality,
                    optimize=optimize,
                    compress_level=compress_level,
                ),
            )
        )


class ImageMetadataExtractProcessor:
    processor_id = "image.metadata_extract"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        if not isinstance(parameters, Mapping):
            raise _invalid("处理参数必须是对象")

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        image = _open(artifact, context)
        metadata = _image_metadata(image, artifact.format)
        info = {
            key: value
            for key, value in image.info.items()
            if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 256
        }
        metadata["info"] = info
        return ProcessingPayload((_replace(artifact, extra={"image": metadata}),))


def image_processors() -> tuple[Any, ...]:
    """默认图像处理器集合。"""

    return (
        ImageDecodeProcessor(),
        ImageResizeProcessor(),
        ImageCropProcessor(),
        ImagePadProcessor(),
        ImageBackgroundRemoveProcessor(),
        ImageAlphaValidateProcessor(),
        ImageFormatConvertProcessor(),
        ImageColorConvertProcessor(),
        ImageSpriteSheetSliceProcessor(),
        ImageAtlasPackProcessor(),
        ImagePixelArtScaleProcessor(),
        ImageCompressProcessor(),
        ImageMetadataExtractProcessor(),
    )
