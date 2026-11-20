"""配置服务测试（E1-T02-UT-005…006）。"""

from __future__ import annotations

import pytest

from config.service import ConfigService, redact_mapping
from config.settings import LogLevel, load_settings
from core.errors import ConfigError
from core.logging import capture_logs

DB_URL = "sqlite+aiosqlite:///:memory:"


def _service() -> ConfigService:
    settings = load_settings(_env_file=None, database_url=DB_URL, environment="test")
    return ConfigService(settings)


def test_sensitive_values_are_redacted() -> None:
    redacted = redact_mapping({"api_key": "sk-live-123", "auth_token": "abc", "port": 8765})

    assert redacted == {"api_key": "***", "auth_token": "***", "port": 8765}


def test_snapshot_is_read_only() -> None:
    snapshot = _service().snapshot()

    assert snapshot["port"] == 8765
    with pytest.raises(TypeError):
        snapshot["port"] = 9000  # type: ignore[index]


def test_hot_reload_field_is_applied() -> None:
    service = _service()

    with capture_logs() as records:
        updated = service.update(log_level="DEBUG")

    assert updated.log_level is LogLevel.DEBUG
    assert service.current.log_level is LogLevel.DEBUG
    assert any(item["event"] == "config_loaded" for item in records)


def test_immutable_field_change_is_rejected() -> None:
    service = _service()

    with capture_logs() as records, pytest.raises(ConfigError) as exc_info:
        service.update(database_url="sqlite+aiosqlite:///other.db")

    assert exc_info.value.details["policy"] == "IMMUTABLE"
    assert service.current.database_url == DB_URL
    assert any(item["event"] == "config_rejected" for item in records)


def test_restart_required_field_change_is_rejected() -> None:
    service = _service()

    with pytest.raises(ConfigError) as exc_info:
        service.update(port=9000)

    assert exc_info.value.details["policy"] == "RESTART_REQUIRED"


def test_unknown_field_is_rejected() -> None:
    service = _service()

    with pytest.raises(ConfigError):
        service.update(not_a_setting=1)


def test_invalid_hot_reload_value_is_rejected() -> None:
    service = _service()

    with pytest.raises(ConfigError):
        service.update(log_level="TRACE")


def test_hot_reload_callback_receives_new_settings() -> None:
    received: list[str] = []
    settings = load_settings(_env_file=None, database_url=DB_URL, environment="test")
    service = ConfigService(
        settings, on_hot_reload=lambda item: received.append(item.log_level.value)
    )

    service.update(log_level="WARNING")

    assert received == ["WARNING"]
