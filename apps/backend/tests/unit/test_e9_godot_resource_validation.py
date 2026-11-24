"""E9-T07 资源引用校验单元测试。"""

from __future__ import annotations

from pathlib import Path

from modules.verification.godot.resource_validator import validate_resources

GOOD_RESOURCE = """[gd_resource type="Resource" load_steps=2 format=3]

[ext_resource type="Texture2D" path="res://art/icon.png" id="1_icon"]

[resource]
icon = ExtResource("1_icon")
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _project(tmp_path: Path) -> None:
    _write(tmp_path / "art" / "icon.png", "png")
    _write(tmp_path / "art" / "icon.png.import", "[remap]\n")
    _write(tmp_path / "items" / "potion.tres", GOOD_RESOURCE)


def test_valid_resource_passes(tmp_path: Path) -> None:
    _project(tmp_path)
    report = validate_resources(tmp_path)
    assert report.passed is True
    assert report.findings == ()
    assert report.details == {"text_resources": 1, "importable_assets": 1}


def test_missing_ext_resource_file_is_error(tmp_path: Path) -> None:
    _write(tmp_path / "items" / "potion.tres", GOOD_RESOURCE)
    report = validate_resources(tmp_path)
    assert "resource_missing_ext_resource" in {item.code for item in report.errors}


def test_undeclared_ext_resource_reference_is_error(tmp_path: Path) -> None:
    _write(tmp_path / "art" / "icon.png", "png")
    _write(tmp_path / "art" / "icon.png.import", "[remap]\n")
    _write(
        tmp_path / "items" / "potion.tres",
        GOOD_RESOURCE.replace('ExtResource("1_icon")', 'ExtResource("9_missing")'),
    )
    report = validate_resources(tmp_path)
    assert "resource_unknown_ext_resource" in {item.code for item in report.errors}


def test_missing_import_metadata_is_warning_only(tmp_path: Path) -> None:
    _write(tmp_path / "art" / "icon.png", "png")
    report = validate_resources(tmp_path)
    assert report.passed is True
    assert [item.code for item in report.warnings] == ["resource_missing_import"]


def test_bad_header_is_error(tmp_path: Path) -> None:
    _write(tmp_path / "items" / "broken.tres", "not a godot resource\n")
    report = validate_resources(tmp_path)
    assert "resource_header_missing" in {item.code for item in report.errors}
