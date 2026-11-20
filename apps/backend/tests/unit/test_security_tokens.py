"""安全令牌纯函数测试（E2-T03-UT / T04）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from datetime import UTC, datetime

from core.security.tokens import (
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
)

CLIENT_ID_PATTERN = re.compile(r"^cli_[a-z0-9]{12}$")
CHALLENGE_ID_PATTERN = re.compile(r"^chl_[a-z0-9]{12}$")
TOKEN_ID_PATTERN = re.compile(r"^tok_[a-z0-9]{12}$")
CREDENTIAL_ID_PATTERN = re.compile(r"^cred_[a-z0-9]{12}$")
SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
ACCESS_TOKEN_PATTERN = re.compile(r"^gda_[A-Za-z0-9_-]{43}$")


def test_client_id_format_and_uniqueness() -> None:
    values = {generate_client_id() for _ in range(100)}

    assert len(values) == 100
    assert all(CLIENT_ID_PATTERN.match(value) for value in values)


def test_identifier_prefixes() -> None:
    assert CHALLENGE_ID_PATTERN.match(generate_challenge_id())
    assert TOKEN_ID_PATTERN.match(generate_token_id())
    assert CREDENTIAL_ID_PATTERN.match(generate_credential_id())
    assert secret_name("cli_ab2cd3ef4g5h") == "client.cli_ab2cd3ef4g5h"


def test_secret_challenge_and_token_entropy_shape() -> None:
    assert SECRET_PATTERN.match(generate_secret())
    assert SECRET_PATTERN.match(generate_challenge())
    assert ACCESS_TOKEN_PATTERN.match(generate_access_token())


def test_hash_token_is_sha256_hex_and_stable() -> None:
    token = generate_access_token()

    digest = hash_token(token)

    assert digest == hashlib.sha256(token.encode()).hexdigest()
    assert len(digest) == 64
    assert hash_token(token) == digest


def test_constant_time_equals() -> None:
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")


def test_compute_proof_matches_manual_hmac() -> None:
    secret = generate_secret()
    challenge_id = generate_challenge_id()
    challenge = generate_challenge()

    expected = (
        base64.urlsafe_b64encode(
            hmac.new(
                secret.encode(),
                f"{challenge_id}.{challenge}".encode(),
                hashlib.sha256,
            ).digest()
        )
        .decode()
        .rstrip("=")
    )

    assert compute_proof(secret, challenge_id, challenge) == expected


def test_ensure_utc_and_isoformat() -> None:
    naive = datetime(2026, 11, 18, 10, 0, 0)

    assert ensure_utc(naive).tzinfo is UTC
    assert isoformat(datetime(2026, 11, 18, 10, 0, 0, tzinfo=UTC)) == "2026-11-18T10:00:00Z"
