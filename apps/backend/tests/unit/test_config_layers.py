"""配置分层加载测试（E1-T02-UT-001…004）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.layers import load_layered_settings
from config.settings import load_settings
from core.errors import ConfigError

DB_URL = "sqlite+aiosqlite:///:memory:"


def _write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_are_used_without_file_or_env(tmp_path: Path) -> None:
    settings = load_layered_settings(
        overrides={"database_url": DB_URL},
        config_file=tmp_path / "missing.toml",
        environ={},
        env_file=None,
    )

    assert settings.port == 8765
    assert settings.host == "127.0.0.1"
    assert settings.log_level.value == "INFO"


def test_file_configuration_is_loaded(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "backend.toml",
        f'database_url = "{DB_URL}"\nport = 9001\nlog_level = "DEBUG"\n',
    )

    settings = load_layered_settings(config_file=config, environ={}, env_file=None)

    assert settings.port == 9001
    assert settings.log_level.value == "DEBUG"


def test_environment_overrides_file(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "backend.toml",
        f'database_url = "{DB_URL}"\nport = 9001\n',
    )

    settings = load_layered_settings(
        config_file=config,
        environ={"GODOT_AI_PORT": "9002", "GODOT_AI_CONFIG_FILE": "ignored.toml"},
        env_file=None,
    )

    assert settings.port == 9002


def test_runtime_overrides_take_highest_priority(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "backend.toml",
        f'database_url = "{DB_URL}"\nport = 9001\n',
    )

    settings = load_layered_settings(
        overrides={"port": 9003},
        config_file=config,
        environ={"GODOT_AI_PORT": "9002"},
        env_file=None,
    )

    assert settings.port == 9003


def test_unknown_file_field_is_rejected(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "backend.toml",
        f'database_url = "{DB_URL}"\nunknown_field = 1\n',
    )

    with pytest.raises(ConfigError) as exc_info:
        load_layered_settings(config_file=config, environ={}, env_file=None)

    assert "unknown_field" in exc_info.value.details["fields"]


def test_invalid_file_value_is_rejected(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "backend.toml",
        f'database_url = "{DB_URL}"\nport = 0\n',
    )

    with pytest.raises(ConfigError):
        load_layered_settings(config_file=config, environ={}, env_file=None)


def test_malformed_file_is_rejected(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "backend.toml", "port = \n")

    with pytest.raises(ConfigError):
        load_layered_settings(config_file=config, environ={}, env_file=None)


def test_plain_loader_remains_supported() -> None:
    settings = load_settings(_env_file=None, database_url=DB_URL)
    assert settings.port == 8765
