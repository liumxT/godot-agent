"""E11 Godot 项目结构校验（T04 / T20 交付校验）。

不启动引擎，只做静态一致性检查：
- project.godot 的主场景、自动加载、输入映射与渲染配置；
- 场景/资源文件中的 `res://` 引用必须真实存在；
- 脚本中的 preload/load 资源必须真实存在；
- 资产与设计文档必须齐备；
- 主场景必须保留 headless 冒烟入口（CI 与验收复用）。
"""

from __future__ import annotations

import re
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[4] / "demo" / "platformer"
PROJECT_ROOT = DEMO_ROOT / "godot_project"

REQUIRED_ACTIONS = {"move_left", "move_right", "jump", "attack", "pause"}
REQUIRED_AUTOLOADS = [
    "EventBus",
    "AudioManager",
    "ScoreManager",
    "SaveManager",
    "GameFlowManager",
]
RESOURCE_REF = re.compile(r'path="(res://[^"]+)"')
SCRIPT_RESOURCE = re.compile(r'(?:preload|load)\("(res://[^"]+)"\)')


def _sections(text: str) -> dict[str, list[str]]:
    """按 `[section]` 切分 project.godot，保留每节的原始行。"""
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return sections


def _keys(section: list[str]) -> dict[str, str]:
    """提取节内顶格 `key=value`（忽略缩进与事件列表内容）。"""
    entries: dict[str, str] = {}
    for line in section:
        if not line or line[0].isspace():
            continue
        key, sep, value = line.partition("=")
        if sep:
            entries[key.strip()] = value.strip()
    return entries


def _settings() -> dict[str, list[str]]:
    return _sections((PROJECT_ROOT / "project.godot").read_text(encoding="utf-8"))


def _res_to_path(res_path: str) -> Path:
    return PROJECT_ROOT / res_path.removeprefix("res://")


def test_project_settings_declare_main_scene_and_autoloads() -> None:
    sections = _settings()
    application = _keys(sections["application"])

    main_scene = application["run/main_scene"].strip('"')
    assert main_scene == "res://scenes/main/main.tscn"
    assert _res_to_path(main_scene).is_file()
    assert application["config/icon"].strip('"') == "res://icon.svg"
    assert _res_to_path("res://icon.svg").is_file()

    autoloads = _keys(sections["autoload"])
    assert list(autoloads) == REQUIRED_AUTOLOADS
    for name, value in autoloads.items():
        assert value.startswith('"*res://'), f"{name} 必须以 * 前缀挂载为单例"
        script = value.strip('"').removeprefix("*")
        assert _res_to_path(script).is_file(), f"{name} 脚本不存在: {script}"


def test_input_map_covers_gameplay_actions() -> None:
    sections = _settings()
    input_section = sections["input"]

    actions: dict[str, list[str]] = {}
    current: str | None = None
    for line in input_section:
        if line and not line[0].isspace() and "=" in line and not line.startswith('"'):
            current = line.split("=", 1)[0].strip()
            actions[current] = [line]
        elif current is not None:
            actions[current].append(line)

    assert REQUIRED_ACTIONS.issubset(actions)
    for action in sorted(REQUIRED_ACTIONS):
        body = "\n".join(actions[action])
        assert "Object(InputEvent" in body, f"{action} 缺少输入事件"
        assert re.search(r'"physical_keycode":\d+', body), f"{action} 缺少物理键码"


def test_display_and_rendering_are_locked() -> None:
    sections = _settings()
    display = _keys(sections["display"])
    rendering = _keys(sections["rendering"])

    assert display["window/size/viewport_width"] == "960"
    assert display["window/size/viewport_height"] == "540"
    assert rendering["renderer/rendering_method"].strip('"') == "gl_compatibility"


def test_scene_and_resource_references_resolve() -> None:
    resource_files = sorted(PROJECT_ROOT.rglob("*.tscn")) + sorted(PROJECT_ROOT.rglob("*.tres"))
    assert resource_files, "未找到任何场景或资源文件"

    missing: list[str] = []
    for file in resource_files:
        text = file.read_text(encoding="utf-8")
        for res_path in RESOURCE_REF.findall(text):
            if res_path.startswith("res://") and not _res_to_path(res_path).is_file():
                missing.append(f"{file.name} -> {res_path}")
    assert missing == [], f"存在失效资源引用: {missing}"


def test_script_resource_references_resolve() -> None:
    scripts = sorted(PROJECT_ROOT.rglob("*.gd"))
    assert scripts, "未找到任何 GDScript"

    missing: list[str] = []
    for file in scripts:
        text = file.read_text(encoding="utf-8")
        for res_path in SCRIPT_RESOURCE.findall(text):
            if not _res_to_path(res_path).is_file():
                missing.append(f"{file.relative_to(PROJECT_ROOT)} -> {res_path}")
    assert missing == [], f"存在失效脚本引用: {missing}"


def test_required_assets_present() -> None:
    for name in ("jump.wav", "hurt.wav", "collect.wav", "bgm.wav"):
        audio = PROJECT_ROOT / "assets" / "audio" / name
        assert audio.is_file() and audio.stat().st_size > 1000, f"音频缺失或为空: {name}"

    for res_path in (
        "res://assets/tilesets/tiles.svg",
        "res://assets/characters/player.svg",
        "res://assets/characters/enemy.svg",
        "res://assets/ui/coin.svg",
        "res://assets/ui/gem.svg",
        "res://assets/environments/spikes.svg",
        "res://resources/tilesets/terrain.tres",
        "res://resources/game_config/player_config.tres",
    ):
        assert _res_to_path(res_path).is_file(), f"资产缺失: {res_path}"


def test_main_scene_keeps_smoke_entry() -> None:
    main_script = (PROJECT_ROOT / "scripts" / "core" / "main.gd").read_text(encoding="utf-8")
    assert '"--smoke" in OS.get_cmdline_user_args()' in main_script
    assert "[SMOKE] RESULT=" in main_script
    assert "get_tree().quit(" in main_script


def test_runtime_verifier_present() -> None:
    scene = PROJECT_ROOT / "scenes" / "tests" / "runtime_verifier.tscn"
    script = PROJECT_ROOT / "scripts" / "tests" / "runtime_verifier.gd"
    assert scene.is_file()
    assert script.is_file()
    assert 'path="res://scripts/tests/runtime_verifier.gd"' in scene.read_text(encoding="utf-8")

    body = script.read_text(encoding="utf-8")
    assert "[VERIFY] RESULT=" in body
    assert "[VERIFY] SUMMARY" in body
    for case_id in (
        "MOVE_RIGHT",
        "JUMP",
        "ATTACK_DAMAGES_ENEMY",
        "ENEMY_PATROL",
        "HAZARD_DAMAGE",
        "COLLECT_ADDS_SCORE",
        "FLOW_GAME_OVER",
        "FLOW_VICTORY",
        "PAUSE",
    ):
        assert case_id in body, f"运行时验证缺少用例: {case_id}"


def test_design_documents_present() -> None:
    documents = [
        "specification/game-requirement-document.md",
        "specification/requirement-registry.md",
        "specification/acceptance-criteria.md",
        "specification/traceability-matrix.md",
        "specification/scope-baseline.md",
        "design/game-design-document.md",
        "design/gameplay-specification.md",
        "design/level-design-document.md",
        "design/game-balance-sheet.md",
        "design/game-flow.md",
        "design/asset-registry.md",
        "design/technical-architecture.md",
    ]
    missing = [name for name in documents if not (DEMO_ROOT / name).is_file()]
    assert missing == [], f"设计文档缺失: {missing}"
