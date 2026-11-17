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


def test_settings_is_immutable_by_convention() -> None:
    settings: Settings = load_settings(_env_file=None, database_url=DB_URL)
    assert settings.model_dump()["database_url"] == DB_URL
