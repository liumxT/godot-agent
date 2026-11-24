"""E9-T15 影响分析与回归计划单元测试。"""

from __future__ import annotations

from pathlib import Path

from modules.verification.impact import (
    CHECK_DEFECT_REPRO,
    CHECK_FULL,
    CHECK_SECURITY,
    ChangedFile,
    DefectRef,
    LinkRef,
    TestCaseRef,
    build_regression_plan,
    coerce_changed_file,
    file_kind,
    normalize_path,
    scan_reverse_dependencies,
)
from modules.verification.models import (
    DEFECT_BLOCKER,
    DEFECT_CATEGORY_SCRIPT,
    DEFECT_VERIFYING,
    REGRESSION_DEPENDENCY,
    REGRESSION_FULL,
    REGRESSION_RISK_CRITICAL,
    REGRESSION_RISK_HIGH,
    REGRESSION_RISK_LOW,
    REGRESSION_SECURITY,
    REGRESSION_TARGETED,
    RISK_CRITICAL,
    RISK_HIGH,
)


def test_normalize_path_and_kind() -> None:
    assert normalize_path(".\\scripts\\player.gd") == "scripts/player.gd"
    assert normalize_path("/scenes/main.tscn/") == "scenes/main.tscn"
    assert file_kind("scripts/player.gd") == "script"
    assert file_kind("scenes/main.tscn") == "scene"
    assert file_kind("resources/player.tres") == "resource"
    assert file_kind("assets/icon.png.import") == "import"
    assert file_kind("README.md") == "other"


def test_coerce_changed_file() -> None:
    assert coerce_changed_file("scripts\\a.gd") == ChangedFile(path="scripts/a.gd")
    coerced = coerce_changed_file(
        {"resource_path": "ui/hud.tscn", "risk_level": "high"}
    )
    assert coerced.path == "ui/hud.tscn"
    assert coerced.risk_level == "HIGH"


def test_scan_reverse_dependencies(tmp_path: Path) -> None:
    (tmp_path / "scenes").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "resources").mkdir()
    (tmp_path / "scenes" / "main.tscn").write_text(
        '[ext_resource path="res://scripts/player.gd" type="Script" id="1"]\n',
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "player.gd").write_text(
        'const DATA = preload("res://resources/player.tres")\n',
        encoding="utf-8",
    )
    (tmp_path / ".godot" / "cache").mkdir(parents=True)
    (tmp_path / ".godot" / "cache" / "player.gd").write_text(
        'preload("res://resources/player.tres")\n', encoding="utf-8"
    )

    reverse = scan_reverse_dependencies(tmp_path)

    assert reverse["scripts/player.gd"] == {"scenes/main.tscn"}
    assert reverse["resources/player.tres"] == {"scripts/player.gd"}


def test_plan_targeted_when_no_dependents() -> None:
    plan = build_regression_plan(
        project_id="p1",
        changed_files=[ChangedFile("scripts/orphan.gd")],
        reverse_dependencies={},
        test_cases=[],
        links=[],
        testable_requirement_ids=["req1"],
    )

    assert plan.strategy == REGRESSION_TARGETED
    assert plan.risk_level == REGRESSION_RISK_LOW
    assert plan.affected_test_cases == ()
    assert plan.coverage_gaps == ("req1",)


def test_plan_dependency_strategy_matches_tests_and_requirements() -> None:
    plan = build_regression_plan(
        project_id="p1",
        changed_files=[ChangedFile("scripts/player.gd", risk_level=RISK_HIGH)],
        reverse_dependencies={"scripts/player.gd": {"scenes/main.tscn"}},
        test_cases=[
            TestCaseRef("t1", "test_player_jump", "FUNCTIONAL", "GODOT_TEST"),
            TestCaseRef("t2", "test_hud_layout", "VISUAL", "SCREENSHOT"),
        ],
        links=[LinkRef("req1", "t1"), LinkRef("req2", "t2")],
        testable_requirement_ids=["req1", "req2", "req3"],
    )

    assert plan.strategy == REGRESSION_DEPENDENCY
    assert plan.risk_level == REGRESSION_RISK_HIGH
    assert plan.affected_requirements == ("req1",)
    assert plan.affected_test_cases == ("t1",)
    assert plan.dependents == ("scenes/main.tscn",)
    assert plan.affected_scenes == ("scenes/main.tscn",)
    assert plan.coverage_gaps == ("req3",)


def test_plan_security_and_full_strategies() -> None:
    security = build_regression_plan(
        project_id="p1",
        changed_files=[ChangedFile("src/auth/login.gd")],
        reverse_dependencies={},
        test_cases=[],
        links=[],
        testable_requirement_ids=[],
    )
    assert security.strategy == REGRESSION_SECURITY
    assert security.risk_level == REGRESSION_RISK_HIGH
    assert CHECK_SECURITY in security.required_checks

    full = build_regression_plan(
        project_id="p1",
        changed_files=[ChangedFile("scripts/player.gd")],
        reverse_dependencies={},
        test_cases=[],
        links=[],
        testable_requirement_ids=[],
        force_full=True,
    )
    assert full.strategy == REGRESSION_FULL
    assert CHECK_FULL in full.required_checks


def test_plan_critical_risk_and_historical_defects() -> None:
    plan = build_regression_plan(
        project_id="p1",
        changed_files=[
            ChangedFile("scripts/player.gd", risk_level=RISK_CRITICAL),
        ],
        reverse_dependencies={"scripts/player.gd": {"scenes/main.tscn"}},
        test_cases=[TestCaseRef("t1", "test_player_jump", "FUNCTIONAL")],
        links=[LinkRef("req1", "t1")],
        testable_requirement_ids=["req1"],
        defects=[
            DefectRef(
                "d1",
                "req1",
                DEFECT_BLOCKER,
                DEFECT_CATEGORY_SCRIPT,
                DEFECT_VERIFYING,
            ),
            DefectRef(
                "d2",
                "req9",
                "MINOR",
                DEFECT_CATEGORY_SCRIPT,
                "RESOLVED",
                related_changeset_id="chs_1",
            ),
        ],
        changeset_id="chs_1",
    )

    # 同一变更集的历史缺陷也应进入重点测试。
    assert "d2" in plan.historical_defects
    assert plan.historical_defects == ("d1", "d2")
    assert plan.risk_level == REGRESSION_RISK_CRITICAL
    assert CHECK_DEFECT_REPRO in plan.required_checks
    assert plan.changed_files == ("scripts/player.gd",)
