"""示例配置与凭证泄漏检查（E0-T07 验收）。"""

from __future__ import annotations

import re
from pathlib import Path

from config.settings import load_settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parents[1]
ENV_EXAMPLE = BACKEND_ROOT / ".env.example"

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _assignments() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        pairs.append((key.strip(), value.strip()))
    return pairs


def test_env_example_is_loadable() -> None:
    settings = load_settings(_env_file=ENV_EXAMPLE)

    assert settings.host == "127.0.0.1"
    assert settings.database_url.startswith("sqlite")


def test_env_example_keys_use_prefix() -> None:
    assert _assignments()
    for key, _ in _assignments():
        assert key.startswith("GODOT_AI_"), key


def test_env_example_contains_no_credentials() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(text), f"示例配置疑似包含真实凭证: {pattern.pattern}"


def test_gitignore_excludes_local_env() -> None:
    lines = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    }

    assert ".env" in lines
    assert "!.env.example" in lines
