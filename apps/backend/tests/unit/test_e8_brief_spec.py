"""E8-T03 / T04 版本与 Brief 规格单元测试。"""

from __future__ import annotations

import pytest

from core.errors import AssetBriefInvalid
from modules.asset_pipeline import models
from modules.asset_pipeline.briefs import (
    validate_audio_spec,
    validate_image_spec,
    validate_technical_spec,
)

IMAGE_SPEC = {
    "width": 64,
    "height": 64,
    "transparent_background": True,
    "format": "png",
    "pixel_art": True,
    "texture_filtering": "nearest",
    "frame_count": 4,
    "frame_size": [64, 64],
    "animation_fps": 8,
    "loop_mode": "loop",
    "godot_resource": {"resource_type": "AnimatedSprite2D", "properties": {}},
}


def test_valid_image_spec_normalized() -> None:
    assert validate_image_spec(dict(IMAGE_SPEC))["width"] == 64


@pytest.mark.parametrize(
    "patch",
    [
        {"width": 0},
        {"width": "64"},
        {"height": 9000},
        {"format": "bmp"},
        {"bit_depth": 12},
        {"frame_size": [64]},
        {"sprite_sheet": {"columns": 0, "rows": 2}},
        {"godot_resource": {"resource_type": "Node3D"}},
        {"unknown_field": True},
    ],
)
def test_invalid_image_spec_rejected(patch: dict) -> None:
    spec = {**IMAGE_SPEC, **patch}
    with pytest.raises(AssetBriefInvalid):
        validate_image_spec(spec)


def test_missing_image_dimensions_rejected() -> None:
    with pytest.raises(AssetBriefInvalid):
        validate_image_spec({"format": "png"})


def test_valid_audio_spec() -> None:
    spec = {
        "format": "ogg",
        "sample_rate": 44100,
        "channels": 2,
        "duration_seconds": 12.5,
        "peak_db": -3,
        "volume_range": [-12, 0],
        "loop_start_seconds": 1,
        "loop_end_seconds": 10,
        "seamless_loop": True,
        "fade_in_out": True,
        "usage": "music",
    }
    assert validate_audio_spec(spec)["sample_rate"] == 44100


@pytest.mark.parametrize(
    "patch",
    [
        {"sample_rate": 96000},
        {"channels": 6},
        {"duration_seconds": 0},
        {"peak_db": 3},
        {"volume_range": [0, -12]},
        {"loop_end_seconds": 0.5},
        {"usage": "podcast"},
    ],
)
def test_invalid_audio_spec_rejected(patch: dict) -> None:
    spec = {
        "format": "ogg",
        "sample_rate": 44100,
        "channels": 2,
        "duration_seconds": 12.5,
        "peak_db": -3,
        "volume_range": [-12, 0],
        "loop_start_seconds": 1,
        "loop_end_seconds": 10,
        "usage": "music",
        **patch,
    }
    with pytest.raises(AssetBriefInvalid):
        validate_audio_spec(spec)


def test_model_and_resource_specs() -> None:
    assert validate_technical_spec("MODEL_3D", {"format": "glb", "scale": 1.5})["scale"] == 1.5
    assert validate_technical_spec("RESOURCE", {"format": "tres", "preload": True})
    with pytest.raises(AssetBriefInvalid):
        validate_technical_spec("MODEL_3D", {"format": "stl"})
    with pytest.raises(AssetBriefInvalid):
        validate_technical_spec("IMAGE", None)  # 空规格仍缺少必需尺寸


def test_unknown_category_rejected() -> None:
    with pytest.raises(AssetBriefInvalid):
        validate_technical_spec("VIDEO", {})


def test_brief_transitions_are_declared() -> None:
    assert models.BRIEF_APPROVED in models.BRIEF_TRANSITIONS[models.BRIEF_PROPOSED]
    assert models.BRIEF_SUPERSEDED in models.BRIEF_TRANSITIONS[models.BRIEF_APPROVED]
    assert models.BRIEF_TRANSITIONS[models.BRIEF_SUPERSEDED] == frozenset()
