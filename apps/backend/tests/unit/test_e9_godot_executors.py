"""E9-T06/T07 静态执行器单元测试。

验证执行器只产出证据草案：失败报告同样带证据，且哈希可追溯。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.verification.godot.executors import (
    ResourceValidationExecutor,
    SceneStructureExecutor,
    StaticAnalysisExecutor,
    report_outcome,
)
from modules.verification.godot.findings import AnalysisReport, error
from modules.verification.godot.scene_validator import NodeRequirement
from modules.verification.models import (
    TEST_TYPE_RESOURCE,
    TEST_TYPE_STATIC,
    TEST_TYPE_STRUCTURAL,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_passing_report_produces_passed_outcome_with_evidence() -> None:
    report = AnalysisReport(kind="STATIC_ANALYSIS", files_scanned=3)
    outcome = report_outcome(report, test_type=TEST_TYPE_STATIC)

    assert outcome.execution_status == "COMPLETED"
    assert outcome.result_status == "PASSED"
    assert outcome.failure_reason is None
    assert len(outcome.evidence) == 1
    draft = outcome.evidence[0]
    assert draft.content_hash == report.content_hash()
    assert draft.source_reference.startswith("verification://")
    assert draft.metadata["report"]["passed"] is True


def test_failing_report_produces_failed_outcome_with_reason_and_evidence() -> None:
    report = AnalysisReport(
        kind="STATIC_ANALYSIS",
        files_scanned=1,
        findings=(error("gd_unbalanced_delimiters", "存在未闭合的 (", "scripts/player.gd", 3),),
    )
    outcome = report_outcome(report, test_type=TEST_TYPE_STATIC)

    assert outcome.result_status == "FAILED"
    assert outcome.failure_reason is not None
    assert "gd_unbalanced_delimiters" in outcome.failure_reason
    # 失败报告本身就是证据，保证 FAILED 可追溯
    assert len(outcome.evidence) == 1


@pytest.mark.asyncio
async def test_static_executor_scans_project(tmp_path: Path) -> None:
    _write(tmp_path / "project.godot", "config_version=5\n")
    _write(tmp_path / "scripts" / "player.gd", "extends Node\n")

    outcome = await StaticAnalysisExecutor(tmp_path)(None)  # type: ignore[arg-type]

    assert outcome.result_status == "PASSED"
    assert outcome.evidence[0].metadata["report"]["kind"] == "STATIC_ANALYSIS"


@pytest.mark.asyncio
async def test_scene_executor_reports_structure_failure(tmp_path: Path) -> None:
    _write(tmp_path / "project.godot", "config_version=5\n")
    _write(
        tmp_path / "player.tscn",
        '[gd_scene format=3]\n\n[node name="Player" type="Node2D"]\n',
    )

    outcome = await SceneStructureExecutor(
        tmp_path,
        required=(NodeRequirement(scene="player.tscn", path=".", type="CharacterBody2D"),),
    )(None)  # type: ignore[arg-type]

    assert outcome.result_status == "FAILED"
    assert "scene_required_node_type" in (outcome.failure_reason or "")


@pytest.mark.asyncio
async def test_resource_executor_detects_missing_import(tmp_path: Path) -> None:
    _write(tmp_path / "art" / "icon.png", "png")

    outcome = await ResourceValidationExecutor(tmp_path)(None)  # type: ignore[arg-type]

    assert outcome.result_status == "PASSED"
    report = outcome.evidence[0].metadata["report"]
    assert report["kind"] == "RESOURCE_VALIDATION"
    assert report["warning_count"] == 1
    assert report["findings"][0]["code"] == "resource_missing_import"


def test_executor_labels_are_stable() -> None:
    for test_type in (TEST_TYPE_STATIC, TEST_TYPE_STRUCTURAL, TEST_TYPE_RESOURCE):
        outcome = report_outcome(AnalysisReport(kind="X", files_scanned=0), test_type=test_type)
        assert outcome.evidence[0].evidence_type
        assert outcome.evidence[0].source_type
