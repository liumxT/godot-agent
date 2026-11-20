"""令牌、挑战与客户端标识生成（E2-T03 / T04）。

纯函数模块：不访问数据库、不访问 keyring、不依赖 FastAPI。
所有随机值使用 ``secrets``；比较一律使用 ``hmac.compare_digest``。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime

CLIENT_ID_PREFIX = "cli_"
CHALLENGE_ID_PREFIX = "chl_"
TOKEN_ID_PREFIX = "tok_"
CREDENTIAL_ID_PREFIX = "cred_"
SESSION_ID_PREFIX = "ses_"
LEASE_ID_PREFIX = "lea_"
EDITOR_INSTANCE_PREFIX = "edi_"
ACCESS_ID_PREFIX = "acc_"
AUDIT_ID_PREFIX = "aud_"
ACCESS_TOKEN_PREFIX = "gda_"
SESSION_TOKEN_PREFIX = "gds_"
CLIENT_SECRET_NAME_PREFIX = "client."

_RANDOM_BYTES = 32


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """SQLite 返回的 ``datetime`` 不带时区；统一按 UTC 解释。"""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _identifier(prefix: str, length: int = 12) -> str:
    raw = base64.b32encode(secrets.token_bytes(8)).decode("ascii").rstrip("=").lower()
    return prefix + raw[:length]


def generate_client_id() -> str:
    return _identifier(CLIENT_ID_PREFIX)


def generate_challenge_id() -> str:
    return _identifier(CHALLENGE_ID_PREFIX)


def generate_token_id() -> str:
    return _identifier(TOKEN_ID_PREFIX)


def generate_credential_id() -> str:
    return _identifier(CREDENTIAL_ID_PREFIX)


def generate_session_id() -> str:
    return _identifier(SESSION_ID_PREFIX)


def generate_lease_id() -> str:
    return _identifier(LEASE_ID_PREFIX)


def generate_editor_instance_id() -> str:
    return _identifier(EDITOR_INSTANCE_PREFIX)


def generate_access_id() -> str:
    return _identifier(ACCESS_ID_PREFIX)


def generate_audit_id() -> str:
    return _identifier(AUDIT_ID_PREFIX)


def generate_secret() -> str:
    """客户端 Secret：32 字节随机数的 base64url（43 字符，无填充）。"""

    return _base64url(secrets.token_bytes(_RANDOM_BYTES))


def generate_challenge() -> str:
    return _base64url(secrets.token_bytes(_RANDOM_BYTES))


def generate_access_token() -> str:
    return ACCESS_TOKEN_PREFIX + _base64url(secrets.token_bytes(_RANDOM_BYTES))


def generate_session_token() -> str:
    return SESSION_TOKEN_PREFIX + _base64url(secrets.token_bytes(_RANDOM_BYTES))


def hash_token(token: str) -> str:
    """数据库只存不可逆的 SHA-256 摘要。"""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def secret_name(client_id: str) -> str:
    """keyring 中的命名：``client.<client_id>``。"""

    return CLIENT_SECRET_NAME_PREFIX + client_id


def compute_proof(secret: str, challenge_id: str, challenge: str) -> str:
    """``base64url(HMAC-SHA256(secret, challenge_id + "." + challenge))``。"""

    message = f"{challenge_id}.{challenge}".encode()
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return _base64url(digest)
