"""E9-T07 场景结构校验单元测试。"""

from __future__ import annotations

from pathlib import Path

from modules.verification.godot.scene_validator import NodeRequirement, validate_scenes

GOOD_SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/player.gd" id="1_abc"]

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_abc")

[node name="Collision" type="CollisionShape2D" parent="."]

[connection signal="body_entered" from="Collision" to="." method="_on_body_entered"]
"""


def _scene(tmp_path: Path, content: str = GOOD_SCENE) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "player.gd").write_text("extends CharacterBody2D\n", encoding="utf-8")
    path = tmp_path / "player.tscn"
    path.write_text(content, encoding="utf-8")
    return path


def test_good_scene_and_requirements_pass(tmp_path: Path) -> None:
    _scene(tmp_path)
    report = validate_scenes(
        tmp_path,
        required=(
            NodeRequirement(scene="player.tscn", path=".", type="CharacterBody2D"),
            NodeRequirement(scene="player.tscn", path="Collision", type="CollisionShape2D"),
        ),
    )
    assert report.passed is True
    assert report.details["scenes"]["player.tscn"]["root_type"] == "CharacterBody2D"


def test_missing_ext_resource_is_error(tmp_path: Path) -> None:
    _scene(tmp_path)
    (tmp_path / "scripts" / "player.gd").unlink()
    report = validate_scenes(tmp_path)
    assert "scene_missing_ext_resource" in {item.code for item in report.errors}


def test_unknown_ext_resource_reference_is_error(tmp_path: Path) -> None:
    _scene(
        tmp_path,
        GOOD_SCENE.replace('ExtResource("1_abc")', 'ExtResource("9_missing")'),
    )
    report = validate_scenes(tmp_path)
    assert "scene_unknown_ext_resource" in {item.code for item in report.errors}


def test_duplicate_sibling_nodes_are_errors(tmp_path: Path) -> None:
    duplicated = GOOD_SCENE + '\n[node name="Collision" type="Area2D" parent="."]\n'
    _scene(tmp_path, duplicated)
    report = validate_scenes(tmp_path)
    assert "scene_duplicate_node" in {item.code for item in report.errors}


def test_connection_to_missing_node_is_error(tmp_path: Path) -> None:
    _scene(tmp_path, GOOD_SCENE.replace('from="Collision"', 'from="Ghost"'))
    report = validate_scenes(tmp_path)
    assert "scene_connection_missing_node" in {item.code for item in report.errors}


def test_required_node_type_mismatch_is_error(tmp_path: Path) -> None:
    _scene(tmp_path)
    report = validate_scenes(
        tmp_path,
        required=(NodeRequirement(scene="player.tscn", path=".", type="Node2D"),),
    )
    assert "scene_required_node_type" in {item.code for item in report.errors}


def test_scene_without_root_is_error(tmp_path: Path) -> None:
    _scene(
        tmp_path,
        '[gd_scene format=3]\n\n[node name="Child" type="Node2D" parent="."]\n',
    )
    report = validate_scenes(tmp_path)
    assert "scene_root_missing" in {item.code for item in report.errors}


def test_missing_required_scene_is_error(tmp_path: Path) -> None:
    _scene(tmp_path)
    report = validate_scenes(
        tmp_path, required=(NodeRequirement(scene="missing.tscn", path=".", type="Node2D"),)
    )
    assert "scene_required_missing" in {item.code for item in report.errors}
