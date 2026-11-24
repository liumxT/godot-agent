"""E9-T06 Godot 静态分析单元测试。"""

from __future__ import annotations

from pathlib import Path

from modules.verification.godot.static_analyzer import analyze_gdscript, analyze_project


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_clean_project_passes(tmp_path: Path) -> None:
    _write(tmp_path / "project.godot", "config_version=5\n[application]\n")
    _write(
        tmp_path / "scripts" / "player.gd",
        'extends CharacterBody2D\n\nclass_name Player\n\nfunc _ready() -> void:\n\tprint("ok")\n',
    )
    report = analyze_project(tmp_path)
    assert report.passed is True
    assert report.errors == ()
    assert report.files_scanned == 2


def test_missing_project_file_is_error(tmp_path: Path) -> None:
    report = analyze_project(tmp_path)
    assert report.passed is False
    assert {item.code for item in report.errors} == {"project_file_missing"}


def test_unbalanced_delimiters_are_errors(tmp_path: Path) -> None:
    _write(tmp_path / "project.godot", "config_version=5\n")
    path = _write(tmp_path / "broken.gd", "func broken( -> void:\n\tpass\n")
    findings = analyze_gdscript(path, tmp_path)
    assert [item.code for item in findings] == ["gd_unbalanced_delimiters"]


def test_strings_and_comments_do_not_break_balance(tmp_path: Path) -> None:
    _write(tmp_path / "project.godot", "config_version=5\n")
    path = _write(
        tmp_path / "strings.gd",
        'extends Node\n# 说明 ( [ {\nvar text = "括号 ) ] } 不应计数"\n',
    )
    assert analyze_gdscript(path, tmp_path) == []


def test_duplicate_class_name_is_error(tmp_path: Path) -> None:
    _write(tmp_path / "project.godot", "config_version=5\n")
    _write(tmp_path / "a.gd", "extends Node\nclass_name Player\n")
    _write(tmp_path / "b.gd", "extends Node\nclass_name Player\n")
    report = analyze_project(tmp_path)
    assert any(item.code == "gd_class_name_conflict" for item in report.errors)


def test_mixed_indentation_is_warning_not_failure(tmp_path: Path) -> None:
    _write(tmp_path / "project.godot", "config_version=5\n")
    _write(
        tmp_path / "mixed.gd",
        "extends Node\n\nfunc _ready() -> void:\n\tpass\n\nfunc _process(_delta: float) -> void:\n    pass\n",
    )
    report = analyze_project(tmp_path)
    assert report.passed is True
    assert any(item.code == "gd_mixed_indentation" for item in report.warnings)


def test_empty_script_is_warning(tmp_path: Path) -> None:
    _write(tmp_path / "project.godot", "config_version=5\n")
    _write(tmp_path / "empty.gd", "\n\n")
    report = analyze_project(tmp_path)
    assert report.passed is True
    assert any(item.code == "gd_empty_script" for item in report.warnings)
