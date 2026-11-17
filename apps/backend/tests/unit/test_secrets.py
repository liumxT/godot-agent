"""密钥访问与脱敏测试（E0-T07）。"""

from __future__ import annotations

import pytest

from core.errors import ConfigError
from infrastructure.secrets import KeyringSecretStore, redact, require_secret


class MemorySecretStore:
    """测试用内存实现，避免污染本机凭证库。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._data.get(name)

    def set(self, name: str, value: str) -> None:
        self._data[name] = value

    def delete(self, name: str) -> None:
        self._data.pop(name, None)


def test_require_secret_returns_value() -> None:
    store = MemorySecretStore()
    store.set("openai.api_key", "placeholder-value")

    assert require_secret(store, "openai.api_key") == "placeholder-value"


def test_require_secret_missing_raises_config_error() -> None:
    store = MemorySecretStore()

    with pytest.raises(ConfigError) as exc_info:
        require_secret(store, "openai.api_key")

    assert exc_info.value.details["secret"] == "openai.api_key"
    assert "placeholder-value" not in str(exc_info.value.details)


def test_redact_hides_value() -> None:
    assert redact("secret-value") == "***"
    assert redact(None) == ""
    assert redact("") == ""


def test_invalid_secret_name_rejected() -> None:
    store = KeyringSecretStore()

    with pytest.raises(ConfigError):
        store.get("bad name!")


def test_keyring_dependency_available() -> None:
    keyring = pytest.importorskip("keyring")

    assert KeyringSecretStore()._keyring() is keyring
