"""安全模型与凭证工具（E2）。

``tokens`` 只包含纯函数：生成、哈希与常量时间比较，不访问数据库与 keyring。
"""

from core.security.tokens import (
    ACCESS_TOKEN_PREFIX,
    CHALLENGE_ID_PREFIX,
    CLIENT_ID_PREFIX,
    TOKEN_ID_PREFIX,
    compute_proof,
    constant_time_equals,
    ensure_utc,
    generate_access_token,
    generate_challenge,
    generate_challenge_id,
    generate_client_id,
    generate_credential_id,
    generate_secret,
    generate_token_id,
    hash_token,
    isoformat,
    secret_name,
    utcnow,
)

__all__ = [
    "ACCESS_TOKEN_PREFIX",
    "CHALLENGE_ID_PREFIX",
    "CLIENT_ID_PREFIX",
    "TOKEN_ID_PREFIX",
    "compute_proof",
    "constant_time_equals",
    "ensure_utc",
    "generate_access_token",
    "generate_challenge",
    "generate_challenge_id",
    "generate_client_id",
    "generate_credential_id",
    "generate_secret",
    "generate_token_id",
    "hash_token",
    "isoformat",
    "secret_name",
    "utcnow",
]
