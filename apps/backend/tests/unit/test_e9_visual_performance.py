"""E9-T11/T12 视觉与性能验证单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from modules.verification.performance import (
    PerformanceEnvironment,
    PerformanceMetrics,
    PerformanceThresholds,
    PerformanceVerificationExecutor,
    evaluate_performance,
)
from modules.verification.visual import (
    RegionMask,
    ScreenshotMetadata,
    VisualDiffPolicy,
    VisualVerificationExecutor,
    compare_images,
    file_sha256,
    validate_screenshot,
)


def _image(path: Path, color: tuple[int, int, int, int], size=(20, 10)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path)
    return path


def _metadata(path: Path, *, resolution: str = "20x10") -> ScreenshotMetadata:
    return ScreenshotMetadata(
        screenshot_id="shot_1",
        runtime_instance_id="inst_1",
        scene="res://main.tscn",
        project_revision="rev-1",
        resolution=resolution,
        renderer="vulkan",
        captured_at=datetime(2026, 11, 24, tzinfo=UTC),
        content_hash=file_sha256(path),
    )


def test_identical_images_pass(tmp_path: Path) -> None:
    baseline = _image(tmp_path / "base.png", (10, 20, 30, 255))
    actual = _image(tmp_path / "actual.png", (10, 20, 30, 255))

    result = compare_images(actual, baseline)

    assert result.passed is True
    assert result.diff_ratio == 0


def test_visual_difference_fails(tmp_path: Path) -> None:
    baseline = _image(tmp_path / "base.png", (0, 0, 0, 255))
    actual = _image(tmp_path / "actual.png", (255, 255, 255, 255))

    result = compare_images(actual, baseline)

    assert result.passed is False
    assert result.diff_ratio == 1.0


def test_masks_ignore_dynamic_regions(tmp_path: Path) -> None:
    baseline = _image(tmp_path / "base.png", (0, 0, 0, 255))
    actual_path = tmp_path / "actual.png"
    image = Image.new("RGBA", (20, 10), (0, 0, 0, 255))
    for x in range(5):
        for y in range(5):
            image.putpixel((x, y), (255, 255, 255, 255))
    image.save(actual_path)

    masked = compare_images(
        actual_path,
        baseline,
        VisualDiffPolicy(masks=(RegionMask(name="particles", x=0, y=0, width=6, height=6),)),
    )
    assert masked.passed is True
    assert masked.diff_pixels == 0


def test_missing_baseline_requires_manual_review(tmp_path: Path) -> None:
    actual = _image(tmp_path / "actual.png", (1, 2, 3, 255))
    result = compare_images(actual, None)
    assert result.passed is None
    assert result.requires_manual_review is True


def test_size_mismatch_fails(tmp_path: Path) -> None:
    baseline = _image(tmp_path / "base.png", (0, 0, 0, 255), size=(20, 10))
    actual = _image(tmp_path / "actual.png", (0, 0, 0, 255), size=(10, 10))
    result = compare_images(actual, baseline)
    assert result.passed is False
    assert "尺寸" in result.reasons[0]


def test_manual_review_policy_forces_unknown(tmp_path: Path) -> None:
    baseline = _image(tmp_path / "base.png", (0, 0, 0, 255))
    actual = _image(tmp_path / "actual.png", (0, 0, 0, 255))
    result = compare_images(actual, baseline, VisualDiffPolicy(require_manual_review=True))
    assert result.passed is None
    assert result.requires_manual_review is True


def test_validate_screenshot_detects_hash_and_size_problems(tmp_path: Path) -> None:
    actual = _image(tmp_path / "actual.png", (0, 0, 0, 255))
    metadata = _metadata(actual)
    assert validate_screenshot(actual, metadata) == ()

    tampered = ScreenshotMetadata(
        screenshot_id=metadata.screenshot_id,
        runtime_instance_id=metadata.runtime_instance_id,
        scene=metadata.scene,
        project_revision=metadata.project_revision,
        resolution="99x99",
        renderer=metadata.renderer,
        captured_at=metadata.captured_at,
        content_hash="0" * 64,
    )
    problems = validate_screenshot(actual, tampered)
    assert any("Hash" in item for item in problems)
    assert any("尺寸" in item for item in problems)


@pytest.mark.asyncio
async def test_visual_executor_passes_with_evidence(tmp_path: Path) -> None:
    baseline = _image(tmp_path / "base.png", (5, 5, 5, 255))
    actual = _image(tmp_path / "actual.png", (5, 5, 5, 255))
    executor = VisualVerificationExecutor(actual, _metadata(actual), baseline=baseline)

    outcome = await executor(None)  # type: ignore[arg-type]

    assert outcome.result_status == "PASSED"
    assert outcome.evidence[0].evidence_type == "SCREENSHOT"
    assert outcome.evidence[0].metadata["project_revision"] == "rev-1"


@pytest.mark.asyncio
async def test_visual_executor_invalid_hash_is_unknown(tmp_path: Path) -> None:
    actual = _image(tmp_path / "actual.png", (5, 5, 5, 255))
    metadata = ScreenshotMetadata(
        screenshot_id="shot",
        runtime_instance_id="inst",
        scene="res://main.tscn",
        project_revision="rev",
        resolution="20x10",
        renderer="vulkan",
        captured_at=datetime.now(UTC),
        content_hash="f" * 64,
    )
    executor = VisualVerificationExecutor(actual, metadata)

    outcome = await executor(None)  # type: ignore[arg-type]

    assert outcome.result_status == "UNKNOWN"
    assert outcome.evidence == ()


_ENV = PerformanceEnvironment(
    os="Windows",
    cpu="Ryzen 7",
    gpu="RTX 4060",
    ram_mb=32768,
    godot_version="4.3",
    renderer="vulkan",
    resolution="1920x1080",
    project_revision="rev-1",
    scenario="gameplay",
)


def test_performance_passes_thresholds() -> None:
    decision = evaluate_performance(
        [PerformanceMetrics(fps=60, frame_time_ms=16.6, memory_mb=512)],
        PerformanceThresholds(minimum_fps=50, maximum_frame_time_ms=20, maximum_memory_mb=1024),
        _ENV,
    )
    assert decision.passed is True
    assert decision.averages["fps"] == 60


def test_performance_violations_and_no_samples() -> None:
    decision = evaluate_performance(
        [PerformanceMetrics(fps=20, frame_time_ms=60, memory_mb=4096)],
        PerformanceThresholds(minimum_fps=50, maximum_frame_time_ms=20, maximum_memory_mb=1024),
        _ENV,
    )
    assert decision.passed is False
    assert len(decision.violations) == 3

    empty = evaluate_performance([], PerformanceThresholds(minimum_fps=50), _ENV)
    assert empty.passed is None


def test_performance_degradation_requires_same_environment() -> None:
    baseline = [PerformanceMetrics(fps=60, memory_mb=512)]
    current = [PerformanceMetrics(fps=40, memory_mb=512)]

    decision = evaluate_performance(
        current,
        PerformanceThresholds(max_degradation_ratio=0.2),
        _ENV,
        baseline_samples=baseline,
        baseline_environment=_ENV,
    )
    assert decision.passed is False
    assert decision.compared_baseline is True
    assert any("下降" in item for item in decision.violations)

    other = PerformanceEnvironment(
        os="Linux",
        cpu="i7",
        gpu="RTX 3060",
        ram_mb=16384,
        godot_version="4.3",
        renderer="vulkan",
        resolution="1280x720",
    )
    ignored = evaluate_performance(
        current,
        PerformanceThresholds(),
        _ENV,
        baseline_samples=baseline,
        baseline_environment=other,
    )
    assert ignored.compared_baseline is False
    assert any("环境" in item for item in ignored.warnings)


@pytest.mark.asyncio
async def test_performance_executor_emits_evidence() -> None:
    executor = PerformanceVerificationExecutor(
        _ENV,
        [PerformanceMetrics(fps=60, frame_time_ms=16.6)],
        PerformanceThresholds(minimum_fps=50),
    )
    outcome = await executor(None)  # type: ignore[arg-type]

    assert outcome.result_status == "PASSED"
    assert outcome.evidence[0].evidence_type == "PERFORMANCE_SAMPLE"
    assert outcome.evidence[0].metadata["project_revision"] == "rev-1"

    failing = PerformanceVerificationExecutor(
        _ENV,
        [PerformanceMetrics(fps=10)],
        PerformanceThresholds(minimum_fps=50),
    )
    failed = await failing(None)  # type: ignore[arg-type]
    assert failed.result_status == "FAILED"
