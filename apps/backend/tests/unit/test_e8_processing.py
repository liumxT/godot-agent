"""E8-M4 单元测试：处理处理器、处理图与默认注册表。"""

from __future__ import annotations

import io
import struct
import wave

import pytest
from PIL import Image, ImageDraw

from core.errors import AssetProcessingInvalid
from modules.asset_pipeline.processing_types import (
    ProcessingArtifact,
    ProcessingContext,
    ProcessingLimits,
    ProcessingPayload,
    parse_processing_graph,
)
from modules.asset_pipeline.processors import default_processing_registry
from modules.asset_pipeline.processors.audio import (
    AudioChannelConvertProcessor,
    AudioCompressProcessor,
    AudioFadeProcessor,
    AudioLoopPointDetectProcessor,
    AudioLoudnessNormalizeProcessor,
    AudioResampleProcessor,
    AudioSilenceTrimProcessor,
)
from modules.asset_pipeline.processors.image import (
    ImageAlphaValidateProcessor,
    ImageAtlasPackProcessor,
    ImageBackgroundRemoveProcessor,
    ImageCompressProcessor,
    ImageCropProcessor,
    ImageDecodeProcessor,
    ImageFormatConvertProcessor,
    ImageMetadataExtractProcessor,
    ImagePixelArtScaleProcessor,
    ImageResizeProcessor,
    ImageSpriteSheetSliceProcessor,
)
from modules.asset_pipeline.processors.model3d import (
    MaterialInspectionProcessor,
    MeshInspectionProcessor,
)

_TRIANGLE_OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def _context() -> ProcessingContext:
    return ProcessingContext.create("proj_1", "asset_1", ProcessingLimits())


def _payload(data: bytes, image_format: str = "png") -> ProcessingPayload:
    return ProcessingPayload((ProcessingArtifact(data=data, format=image_format),))


def _png(
    width: int = 8,
    height: int = 8,
    *,
    mode: str = "RGBA",
    color=(255, 0, 0, 255),
) -> bytes:
    image = Image.new(mode, (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _wav(
    samples: list[int] | None = None,
    *,
    sample_rate: int = 8000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    values = samples if samples is not None else [1000, -1000] * 20
    frames = b""
    if sample_width == 2:
        if channels == 2:
            interleaved: list[int] = []
            for value in values:
                interleaved.extend([value, value])
            frames = struct.pack(f"<{len(interleaved)}h", *interleaved)
        else:
            frames = struct.pack(f"<{len(values)}h", *values)
    elif sample_width == 4:
        if channels == 2:
            interleaved = []
            for value in values:
                interleaved.extend([value * 65536, value * 65536])
            frames = struct.pack(f"<{len(interleaved)}i", *interleaved)
        else:
            widened = [value * 65536 for value in values]
            frames = struct.pack(f"<{len(widened)}i", *widened)
    else:
        raise AssertionError("测试仅支持 2/4 字节采样")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)
    return buffer.getvalue()


def _wav_metrics(data: bytes) -> dict[str, int | float]:
    with wave.open(io.BytesIO(data), "rb") as handle:
        return {
            "channels": handle.getnchannels(),
            "sample_width": handle.getsampwidth(),
            "sample_rate": handle.getframerate(),
            "frames": handle.getnframes(),
        }


def test_default_registry_registers_supported_processors() -> None:
    registry = default_processing_registry()
    ids = registry.ids()
    assert "image.decode" in ids
    assert "image.sprite_sheet_slice" in ids
    assert "audio.resample" in ids
    assert "model3d.mesh_inspection" in ids
    assert "model3d.format_convert" not in ids
    with pytest.raises(AssetProcessingInvalid):
        registry.get("model3d.format_convert")


def test_processing_graph_requires_single_terminal_and_rejects_cycles() -> None:
    graph = parse_processing_graph(
        {
            "nodes": [
                {"id": "a", "processor": "image.decode"},
                {"id": "b", "processor": "image.resize", "depends_on": ["a"]},
            ]
        }
    )
    assert graph.terminal == "b"
    assert [node.node_id for node in graph.ordered()] == ["a", "b"]
    with pytest.raises(AssetProcessingInvalid):
        parse_processing_graph(
            {
                "nodes": [
                    {"id": "a", "processor": "image.decode"},
                    {"id": "b", "processor": "image.resize"},
                ]
            }
        )
    with pytest.raises(AssetProcessingInvalid):
        parse_processing_graph(
            {
                "nodes": [
                    {"id": "a", "processor": "image.decode", "depends_on": ["b"]},
                    {"id": "b", "processor": "image.resize", "depends_on": ["a"]},
                ]
            }
        )


def test_image_decode_and_resize_report_metadata() -> None:
    decoded = ImageDecodeProcessor().process(_payload(_png(8, 4)), {}, _context())
    assert decoded.artifacts[0].metadata["image"]["width"] == 8

    resized = ImageResizeProcessor().process(
        decoded, {"width": 4, "height": 2, "resample": "nearest"}, _context()
    )
    image = Image.open(io.BytesIO(resized.artifacts[0].data))
    assert image.size == (4, 2)
    assert resized.artifacts[0].metadata["width"] == 4

    with pytest.raises(AssetProcessingInvalid):
        ImageResizeProcessor().process(decoded, {"width": 0, "height": 2}, _context())


def test_image_crop_validates_bounds() -> None:
    cropped = ImageCropProcessor().process(_payload(_png(8, 8)), {"box": [1, 1, 5, 5]}, _context())
    assert Image.open(io.BytesIO(cropped.artifacts[0].data)).size == (4, 4)
    with pytest.raises(AssetProcessingInvalid):
        ImageCropProcessor().process(_payload(_png(8, 8)), {"box": [0, 0, 20, 20]}, _context())


def test_image_background_remove_and_alpha_validate() -> None:
    source = Image.new("RGB", (8, 8), (255, 255, 255))
    draw = ImageDraw.Draw(source)
    draw.rectangle([2, 2, 5, 5], fill=(10, 20, 30))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    removed = ImageBackgroundRemoveProcessor().process(
        _payload(buffer.getvalue()), {"tolerance": 8}, _context()
    )
    image = Image.open(io.BytesIO(removed.artifacts[0].data)).convert("RGBA")
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((3, 3))[3] == 255

    validated = ImageAlphaValidateProcessor().process(removed, {}, _context())
    assert validated.artifacts[0].metadata["alpha"]["has_alpha"] is True

    with pytest.raises(AssetProcessingInvalid):
        ImageAlphaValidateProcessor().process(
            _payload(_png(8, 8, mode="RGB", color=(1, 2, 3))), {}, _context()
        )


def test_image_format_color_and_compress() -> None:
    converted = ImageFormatConvertProcessor().process(
        _payload(_png(8, 8)), {"format": "webp", "quality": 80}, _context()
    )
    assert converted.artifacts[0].format == "webp"
    assert Image.open(io.BytesIO(converted.artifacts[0].data)).format == "WEBP"

    compressed = ImageCompressProcessor().process(
        _payload(_png(8, 8)), {"format": "webp", "quality": 50}, _context()
    )
    assert compressed.artifacts[0].metadata["format"] == "webp"

    scaled = ImagePixelArtScaleProcessor().process(_payload(_png(4, 4)), {"scale": 3}, _context())
    assert Image.open(io.BytesIO(scaled.artifacts[0].data)).size == (12, 12)

    metadata = ImageMetadataExtractProcessor().process(_payload(_png(4, 4)), {}, _context())
    assert metadata.artifacts[0].metadata["image"]["frames"] == 1


def test_image_sprite_sheet_slice_and_atlas_pack() -> None:
    sheet = bytearray()
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for row in range(2):
        for column in range(2):
            for x in range(4):
                for y in range(4):
                    image.putpixel(
                        (column * 4 + x, row * 4 + y),
                        (row * 100, column * 100, 50, 255),
                    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    sheet.extend(buffer.getvalue())

    sliced = ImageSpriteSheetSliceProcessor().process(
        _payload(bytes(sheet)),
        {"frame_width": 4, "frame_height": 4, "columns": 2, "rows": 2},
        _context(),
    )
    assert len(sliced.artifacts) == 4
    assert all(len(item.data) > 0 for item in sliced.artifacts)

    with pytest.raises(AssetProcessingInvalid):
        ImageSpriteSheetSliceProcessor().process(
            _payload(bytes(sheet)),
            {"frame_width": 4, "frame_height": 4, "columns": 3, "rows": 2},
            _context(),
        )

    packed = ImageAtlasPackProcessor().process(
        ProcessingPayload(tuple(sliced.artifacts)),
        {"columns": 2, "padding": 1},
        _context(),
    )
    atlas = Image.open(io.BytesIO(packed.artifacts[0].data))
    assert atlas.width == 4 * 2 + 1 * 3


def test_audio_processors_operate_on_pcm_wav() -> None:
    source = _payload(_wav(), "wav")
    resampled = AudioResampleProcessor().process(source, {"sample_rate": 4000}, _context())
    metrics = _wav_metrics(resampled.artifacts[0].data)
    assert metrics["sample_rate"] == 4000
    assert 0 < metrics["frames"] < 40

    stereo = AudioChannelConvertProcessor().process(
        _payload(_wav(channels=1), "wav"), {"channels": 2}, _context()
    )
    assert _wav_metrics(stereo.artifacts[0].data)["channels"] == 2

    loud = AudioLoudnessNormalizeProcessor().process(
        _payload(_wav([200, -200] * 10), "wav"),
        {"target_peak_db": -1.0},
        _context(),
    )
    assert loud.artifacts[0].metadata["normalization"]["gain_db"] > 0

    trimmed = AudioSilenceTrimProcessor().process(
        _payload(_wav([0, 0, 0, 4000, -4000, 4000, 0, 0]), "wav"),
        {"threshold_db": -60.0},
        _context(),
    )
    assert _wav_metrics(trimmed.artifacts[0].data)["frames"] == 3

    faded = AudioFadeProcessor().process(
        _payload(_wav([4000] * 20), "wav"),
        {"fade_in_ms": 1, "fade_out_ms": 1},
        _context(),
    )
    with wave.open(io.BytesIO(faded.artifacts[0].data), "rb") as handle:
        first = struct.unpack("<h", handle.readframes(1))[0]
    assert first == 0

    looped = AudioLoopPointDetectProcessor().process(
        _payload(_wav([0, 0, 1000, 2000, 0, 0]), "wav"), {}, _context()
    )
    assert looped.artifacts[0].metadata["loop"]["loop_start_frame"] == 2

    compressed = AudioCompressProcessor().process(
        _payload(_wav(sample_width=4), "wav"), {"sample_width": 2}, _context()
    )
    assert _wav_metrics(compressed.artifacts[0].data)["sample_width"] == 2


def test_audio_rejects_unsupported_format_and_bit_depth() -> None:
    with pytest.raises(AssetProcessingInvalid):
        AudioResampleProcessor().process(
            _payload(b"not-audio", "mp3"), {"sample_rate": 8000}, _context()
        )
    with pytest.raises(AssetProcessingInvalid):
        AudioCompressProcessor().process(
            _payload(_wav(sample_width=2), "wav"), {"sample_width": 4}, _context()
        )


def test_model3d_inspection_reports_geometry_and_materials() -> None:
    payload = _payload(_TRIANGLE_OBJ, "obj")
    geometry = MeshInspectionProcessor().process(payload, {}, _context())
    report = geometry.artifacts[0].metadata["geometry"]
    assert report["triangle_count"] == 1
    assert report["empty"] is False

    materials = MaterialInspectionProcessor().process(payload, {}, _context())
    assert materials.artifacts[0].metadata["materials"]["material_count"] == 0

    with pytest.raises(AssetProcessingInvalid):
        MeshInspectionProcessor().process(_payload(b"not a model", "fbx"), {}, _context())
