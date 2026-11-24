"""视觉验证（E9-T11）。

截图必须来自真实 Runtime/Editor，并记录完整上下文。像素完全一致不是唯一
标准：支持容差、区域屏蔽与人工审核；无法判定时保持 UNKNOWN，不冒充通过。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from modules.verification.godot.executors import EvidenceDraft, LayerOutcome
from modules.verification.orchestrator import VerificationContext


@dataclass(frozen=True, slots=True)
class ScreenshotMetadata:
    screenshot_id: str
    runtime_instance_id: str
    scene: str
    project_revision: str
    resolution: str
    renderer: str
    captured_at: datetime
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "screenshot_id": self.screenshot_id,
            "runtime_instance_id": self.runtime_instance_id,
            "scene": self.scene,
            "project_revision": self.project_revision,
            "resolution": self.resolution,
            "renderer": self.renderer,
            "captured_at": self.captured_at.isoformat(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class RegionMask:
    """需要屏蔽的矩形区域（用于动画、粒子、随机效果等）。"""

    name: str
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if min(self.x, self.y, self.width, self.height) < 0:
            raise ValueError("屏蔽区域坐标不能为负")
        if self.width == 0 or self.height == 0:
            raise ValueError("屏蔽区域尺寸必须大于 0")


@dataclass(frozen=True, slots=True)
class VisualDiffPolicy:
    max_diff_ratio: float = 0.02
    tolerance: int = 0
    masks: tuple[RegionMask, ...] = ()
    require_manual_review: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.max_diff_ratio <= 1:
            raise ValueError("差异阈值必须位于 0..1")
        if not 0 <= self.tolerance <= 255:
            raise ValueError("像素容差必须位于 0..255")


@dataclass(frozen=True, slots=True)
class VisualDiffResult:
    passed: bool | None
    diff_ratio: float
    diff_pixels: int
    total_pixels: int
    requires_manual_review: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    baseline_available: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "diff_ratio": self.diff_ratio,
            "diff_pixels": self.diff_pixels,
            "total_pixels": self.total_pixels,
            "requires_manual_review": self.requires_manual_review,
            "reasons": list(self.reasons),
            "baseline_available": self.baseline_available,
        }


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_resolution(value: str) -> tuple[int, int] | None:
    try:
        width, height = value.lower().split("x", 1)
        return int(width), int(height)
    except (ValueError, AttributeError):
        return None


def validate_screenshot(
    path: str | Path, metadata: ScreenshotMetadata
) -> tuple[str, ...]:
    """返回截图上下文问题；空元组表示通过校验。"""

    problems: list[str] = []
    file_path = Path(path)
    if not file_path.is_file():
        return ("截图文件不存在",)
    actual_hash = file_sha256(file_path)
    if actual_hash != metadata.content_hash:
        problems.append("截图 Content Hash 与元数据不一致")
    expected = parse_resolution(metadata.resolution)
    if expected is not None:
        try:
            with Image.open(file_path) as image:
                if image.size != expected:
                    problems.append(
                        f"截图尺寸 {image.size[0]}x{image.size[1]} 与声明 {metadata.resolution} 不一致"
                    )
        except OSError:
            problems.append("截图无法解码")
    return tuple(problems)


def compare_images(
    actual: str | Path,
    baseline: str | Path | None,
    policy: VisualDiffPolicy | None = None,
) -> VisualDiffResult:
    policy = policy or VisualDiffPolicy()
    if baseline is None or not Path(baseline).is_file():
        return VisualDiffResult(
            passed=None,
            diff_ratio=0.0,
            diff_pixels=0,
            total_pixels=0,
            requires_manual_review=True,
            reasons=("缺少基线截图，需要人工审核",),
            baseline_available=False,
        )

    with Image.open(actual) as actual_image, Image.open(baseline) as baseline_image:
        left = actual_image.convert("RGBA")
        right = baseline_image.convert("RGBA")
    if left.size != right.size:
        return VisualDiffResult(
            passed=False,
            diff_ratio=1.0,
            diff_pixels=left.size[0] * left.size[1],
            total_pixels=left.size[0] * left.size[1],
            requires_manual_review=policy.require_manual_review,
            reasons=(
                f"截图尺寸不一致: {left.size[0]}x{left.size[1]} vs {right.size[0]}x{right.size[1]}",
            ),
        )

    diff = ImageChops.difference(left, right).convert("L")
    if policy.tolerance > 0:
        diff = diff.point(lambda value: 255 if value > policy.tolerance else 0)
    if policy.masks:
        drawing = ImageDraw.Draw(diff)
        for mask in policy.masks:
            drawing.rectangle(
                (mask.x, mask.y, mask.x + mask.width - 1, mask.y + mask.height - 1),
                fill=0,
            )

    total = diff.size[0] * diff.size[1]
    histogram = diff.histogram()
    diff_pixels = total - histogram[0]
    ratio = diff_pixels / total if total else 0.0
    reasons: list[str] = []
    if ratio > policy.max_diff_ratio:
        reasons.append(
            f"差异像素占比 {ratio:.4f} 超过阈值 {policy.max_diff_ratio:.4f}"
        )
        passed: bool | None = False
    else:
        passed = True
    if policy.require_manual_review:
        reasons.append("策略要求人工审核视觉结果")
    return VisualDiffResult(
        passed=None if policy.require_manual_review else passed,
        diff_ratio=ratio,
        diff_pixels=diff_pixels,
        total_pixels=total,
        requires_manual_review=policy.require_manual_review,
        reasons=tuple(reasons),
    )


class VisualVerificationExecutor:
    """把截图对比结果转为验证结论；无法判定时保持 UNKNOWN。"""

    def __init__(
        self,
        screenshot: str | Path,
        metadata: ScreenshotMetadata,
        *,
        baseline: str | Path | None = None,
        policy: VisualDiffPolicy | None = None,
    ) -> None:
        self._screenshot = Path(screenshot)
        self._metadata = metadata
        self._baseline = baseline
        self._policy = policy or VisualDiffPolicy()

    async def __call__(self, context: VerificationContext) -> LayerOutcome:
        problems = validate_screenshot(self._screenshot, self._metadata)
        if problems:
            return LayerOutcome(
                execution_status="UNKNOWN",
                result_status="UNKNOWN",
                failure_reason="; ".join(problems),
                details={"screenshot_problems": list(problems)},
            )

        diff = compare_images(self._screenshot, self._baseline, self._policy)
        report = {
            "screenshot": self._metadata.to_dict(),
            "diff": diff.to_dict(),
        }
        evidence = EvidenceDraft(
            evidence_type="SCREENSHOT",
            source_type="GODOT_RUNTIME",
            source_reference=f"file:///{self._screenshot.as_posix()}",
            content_hash=self._metadata.content_hash,
            metadata={**self._metadata.to_dict(), "report": report},
        )
        if diff.passed is True:
            return LayerOutcome(
                execution_status="COMPLETED",
                result_status="PASSED",
                evidence=(evidence,),
                details=report,
            )
        if diff.passed is False:
            return LayerOutcome(
                execution_status="COMPLETED",
                result_status="FAILED",
                evidence=(evidence,),
                failure_reason="; ".join(diff.reasons) or "视觉差异超出阈值",
                details=report,
            )
        return LayerOutcome(
            execution_status="UNKNOWN",
            result_status="UNKNOWN",
            evidence=(evidence,),
            failure_reason="; ".join(diff.reasons) or "视觉结果需要人工审核",
            details=report,
        )


def visual_report(payload: dict[str, object]) -> str:
    """稳定序列化，便于计算证据 Hash。"""

    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
