"""密钥存储实现与访问约定。"""

from __future__ import annotations

import re
from typing import Protocol

from core.errors import ConfigError

KEYRING_SERVICE = "godot-ai-agent"
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class SecretStore(Protocol):
    """密钥存取抽象；测试实现可替换为内存版本。"""

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


def validate_name(name: str) -> str:
    if not _NAME_PATTERN.match(name):
        raise ConfigError(
            "密钥名称非法",
            details={"secret": name, "pattern": _NAME_PATTERN.pattern},
        )
    return name


class KeyringSecretStore:
    """基于操作系统凭证库的实现（通过 keyring）。

    命名建议：``<provider>.<用途>``，例如 ``openai.api_key``。
    """

    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        self._service = service

    def _keyring(self):
        try:
            import keyring
        except ImportError as exc:  # 依赖缺失属于配置问题，必须显式报错
            raise ConfigError(
                "缺少 keyring 依赖，无法访问操作系统凭证库",
                details={"hint": 'pip install "keyring"'},
            ) from exc
        return keyring

    def get(self, name: str) -> str | None:
        validate_name(name)
        keyring = self._keyring()
        try:
            return keyring.get_password(self._service, name)
        except Exception as exc:
            raise ConfigError("读取系统凭证库失败", details={"secret": name}) from exc

    def set(self, name: str, value: str) -> None:
        validate_name(name)
        if not value:
            raise ConfigError("密钥值不能为空", details={"secret": name})
        keyring = self._keyring()
        try:
            keyring.set_password(self._service, name, value)
        except Exception as exc:
            raise ConfigError("写入系统凭证库失败", details={"secret": name}) from exc

    def delete(self, name: str) -> None:
        validate_name(name)
        keyring = self._keyring()
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self._service, name)
        except PasswordDeleteError:
            return
        except Exception as exc:
            raise ConfigError("删除系统凭证失败", details={"secret": name}) from exc


def require_secret(store: SecretStore, name: str) -> str:
    """读取必需密钥；缺失时以 ConfigError 终止启动，不静默降级。"""

    value = store.get(name)
    if value is None:
        raise ConfigError(
            "缺少必要密钥",
            details={
                "secret": name,
                "hint": "请在操作系统凭证库中配置，见 docs/03-development/secrets.md",
            },
        )
    return value


def redact(value: str | None) -> str:
    """日志/错误输出中的密钥占位，禁止输出原值。"""

    return "***" if value else ""
