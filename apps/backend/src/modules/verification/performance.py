"""性能验证（E9-T12）。

采集 FPS、帧时间、CPU/GPU 时间、内存、资源与场景加载时间，按阈值判定，
并与同环境基线比较识别性能退化。环境不一致时禁止直接对比。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from modules.verification.godot.executors import EvidenceDraft, LayerOutcome
from modules.verification.orchestrator import VerificationContext


@dataclass(frozen=True, slots=True)
class PerformanceEnvironment:
    os: str
    cpu: str
    gpu: str
    ram_mb: int
    godot_version: str
    renderer: str
    resolution: str
    project_revision: str = ""
    scenario: str = ""

    def fingerprint(self) -> str:
        payload = "|".join(
            (
                self.os,
                self.cpu,
                self.gpu,
                str(self.ram_mb),
                self.godot_version,
                self.renderer,
                self.resolution,
                self.scenario,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os,
            "cpu": self.cpu,
            "gpu": self.gpu,
            "ram_mb": self.ram_mb,
            "godot_version": self.godot_version,
            "renderer": self.renderer,
            "resolution": self.resolution,
            "project_revision": self.project_revision,
            "scenario": self.scenario,
            "fingerprint": self.fingerprint(),
        }


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    fps: float | None = None
    frame_time_ms: float | None = None
    physics_frame_time_ms: float | None = None
    cpu_time_ms: float | None = None
    gpu_time_ms: float | None = None
    memory_mb: float | None = None
    object_count: int | None = None
    node_count: int | None = None
    texture_memory_mb: float | None = None
    audio_memory_mb: float | None = None
    resource_load_ms: float | None = None
    scene_load_ms: float | None = None

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            if value is not None and value < 0:
                raise ValueError(f"性能指标 {name} 不能为负")

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "fps": self.fps,
            "frame_time_ms": self.frame_time_ms,
            "physics_frame_time_ms": self.physics_frame_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "gpu_time_ms": self.gpu_time_ms,
            "memory_mb": self.memory_mb,
            "object_count": self.object_count,
            "node_count": self.node_count,
            "texture_memory_mb": self.texture_memory_mb,
            "audio_memory_mb": self.audio_memory_mb,
            "resource_load_ms": self.resource_load_ms,
            "scene_load_ms": self.scene_load_ms,
        }


@dataclass(frozen=True, slots=True)
class PerformanceThresholds:
    target_fps: float | None = None
    minimum_fps: float | None = None
    maximum_frame_time_ms: float | None = None
    maximum_memory_mb: float | None = None
    maximum_scene_load_ms: float | None = None
    max_degradation_ratio: float = 0.2

    def __post_init__(self) -> None:
        if not 0 <= self.max_degradation_ratio <= 1:
            raise ValueError("性能退化阈值必须位于 0..1")


@dataclass(frozen=True, slots=True)
class PerformanceDecision:
    passed: bool | None
    violations: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    averages: dict[str, float] = field(default_factory=dict)
    environment_fingerprint: str = ""
    compared_baseline: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": list(self.violations),
            "warnings": list(self.warnings),
            "averages": self.averages,
            "environment_fingerprint": self.environment_fingerprint,
            "compared_baseline": self.compared_baseline,
        }


def _average(samples: list[PerformanceMetrics], field_name: str) -> float | None:
    values = [value for sample in samples if (value := getattr(sample, field_name)) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def evaluate_performance(
    samples: list[PerformanceMetrics],
    thresholds: PerformanceThresholds,
    environment: PerformanceEnvironment,
    *,
    baseline_samples: list[PerformanceMetrics] | None = None,
    baseline_environment: PerformanceEnvironment | None = None,
) -> PerformanceDecision:
    if not samples:
        return PerformanceDecision(
            passed=None,
            violations=("没有性能样本，无法判定",),
            environment_fingerprint=environment.fingerprint(),
        )

    averages = {
        name: value
        for name in PerformanceMetrics().to_dict()
        if (value := _average(samples, name)) is not None
    }
    violations: list[str] = []
    warnings: list[str] = []

    fps = averages.get("fps")
    if thresholds.minimum_fps is not None and fps is not None:
        if fps < thresholds.minimum_fps:
            violations.append(f"平均 FPS {fps:.2f} 低于最低要求 {thresholds.minimum_fps:.2f}")
        elif thresholds.target_fps is not None and fps < thresholds.target_fps:
            warnings.append(f"平均 FPS {fps:.2f} 未达到目标 {thresholds.target_fps:.2f}")
    frame_time = averages.get("frame_time_ms")
    if (
        thresholds.maximum_frame_time_ms is not None
        and frame_time is not None
        and frame_time > thresholds.maximum_frame_time_ms
    ):
        violations.append(
            f"平均帧时间 {frame_time:.2f}ms 超过上限 {thresholds.maximum_frame_time_ms:.2f}ms"
        )
    memory = averages.get("memory_mb")
    if (
        thresholds.maximum_memory_mb is not None
        and memory is not None
        and memory > thresholds.maximum_memory_mb
    ):
        violations.append(f"内存 {memory:.2f}MB 超过上限 {thresholds.maximum_memory_mb:.2f}MB")
    scene_load = averages.get("scene_load_ms")
    if (
        thresholds.maximum_scene_load_ms is not None
        and scene_load is not None
        and scene_load > thresholds.maximum_scene_load_ms
    ):
        violations.append(
            f"场景加载 {scene_load:.2f}ms 超过上限 {thresholds.maximum_scene_load_ms:.2f}ms"
        )

    compared = False
    if baseline_samples and baseline_environment is not None:
        if baseline_environment.fingerprint() != environment.fingerprint():
            warnings.append("基线环境与当前环境不一致，禁止直接对比性能数字")
        else:
            compared = True
            ratio = thresholds.max_degradation_ratio
            for name, label in (
                ("fps", "FPS"),
                ("memory_mb", "内存"),
                ("scene_load_ms", "场景加载时间"),
            ):
                current = averages.get(name)
                baseline = _average(baseline_samples, name)
                if current is None or baseline in (None, 0):
                    continue
                if name == "fps":
                    drop = (baseline - current) / baseline
                    if drop > ratio:
                        violations.append(f"FPS 相比基线下降 {drop:.1%}，超过 {ratio:.0%}")
                else:
                    growth = (current - baseline) / baseline
                    if growth > ratio:
                        violations.append(f"{label} 相比基线增长 {growth:.1%}，超过 {ratio:.0%}")

    return PerformanceDecision(
        passed=not violations,
        violations=tuple(violations),
        warnings=tuple(warnings),
        averages={key: round(value, 4) for key, value in averages.items()},
        environment_fingerprint=environment.fingerprint(),
        compared_baseline=compared,
    )


class PerformanceVerificationExecutor:
    def __init__(
        self,
        environment: PerformanceEnvironment,
        samples: list[PerformanceMetrics],
        thresholds: PerformanceThresholds,
        *,
        baseline_samples: list[PerformanceMetrics] | None = None,
        baseline_environment: PerformanceEnvironment | None = None,
    ) -> None:
        self._environment = environment
        self._samples = samples
        self._thresholds = thresholds
        self._baseline_samples = baseline_samples
        self._baseline_environment = baseline_environment

    async def __call__(self, context: VerificationContext) -> LayerOutcome:
        decision = evaluate_performance(
            self._samples,
            self._thresholds,
            self._environment,
            baseline_samples=self._baseline_samples,
            baseline_environment=self._baseline_environment,
        )
        report = {
            "environment": self._environment.to_dict(),
            "samples": [sample.to_dict() for sample in self._samples],
            "thresholds": {
                "target_fps": self._thresholds.target_fps,
                "minimum_fps": self._thresholds.minimum_fps,
                "maximum_frame_time_ms": self._thresholds.maximum_frame_time_ms,
                "maximum_memory_mb": self._thresholds.maximum_memory_mb,
                "maximum_scene_load_ms": self._thresholds.maximum_scene_load_ms,
                "max_degradation_ratio": self._thresholds.max_degradation_ratio,
            },
            "decision": decision.to_dict(),
        }
        payload = json.dumps(report, ensure_ascii=False, sort_keys=True)
        evidence = EvidenceDraft(
            evidence_type="PERFORMANCE_SAMPLE",
            source_type="GODOT_RUNTIME",
            source_reference=f"performance://{self._environment.scenario or 'default'}",
            content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            metadata={
                "project_revision": self._environment.project_revision,
                "environment": self._environment.to_dict(),
                "report": report,
            },
        )
        if decision.passed is None:
            return LayerOutcome(
                execution_status="UNKNOWN",
                result_status="UNKNOWN",
                evidence=(evidence,),
                failure_reason="; ".join(decision.violations) or "性能无法判定",
                details=report,
            )
        if decision.passed:
            return LayerOutcome(
                execution_status="COMPLETED",
                result_status="PASSED",
                evidence=(evidence,),
                details=report,
            )
        return LayerOutcome(
            execution_status="COMPLETED",
            result_status="FAILED",
            evidence=(evidence,),
            failure_reason="; ".join(decision.violations),
            details=report,
        )
