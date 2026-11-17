"""配置加载测试（E0-UT-002 / E0-UT-003）。"""

from __future__ import annotations

import pytest

from config.settings import Environment, Settings, load_settings
from core.errors import ConfigError

DB_URL = "sqlite+aiosqlite:///:memory:"


def test_load_settings_success() -> None:
    settings = load_settings(_env_file=None, database_url=DB_URL)
    assert settings.host == "127.0.0.1"
    assert settings.environment is Environment.development


def test_missing_required_field_raises_config_error() -> None:
    with pytest.raises(ConfigError) as exc:
        load_settings(_env_file=None)
    assert "database_url" in exc.value.message


def test_invalid_port_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, database_url=DB_URL, port=70000)


def test_non_loopback_host_rejected() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, database_url=DB_URL, host="0.0.0.0")


def test_invalid_log_level_rejected() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, database_url=DB_URL, log_level="TRACE")


def test_non_sqlite_database_rejected() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, database_url="postgresql://localhost/backend")


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GODOT_AI_PORT", "9000")

    settings = load_settings(_env_file=None, database_url=DB_URL)

    assert settings.port == 9000


def test_settings_is_immutable_by_convention() -> None:
    settings: Settings = load_settings(_env_file=None, database_url=DB_URL)
    assert settings.model_dump()["database_url"] == DB_URL
