"""Secrets 访问层（E0-T07）。

凭证只存操作系统凭证库：Windows Credential Manager / macOS Keychain /
Linux Secret Service。配置、日志、数据库中都不得出现明文凭证。
"""

from infrastructure.secrets.store import (
    KEYRING_SERVICE,
    KeyringSecretStore,
    MemorySecretStore,
    SecretStore,
    redact,
    require_secret,
)

__all__ = [
    "KEYRING_SERVICE",
    "KeyringSecretStore",
    "MemorySecretStore",
    "SecretStore",
    "redact",
    "require_secret",
]
