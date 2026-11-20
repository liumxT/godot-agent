"""审计服务单元测试（E2-T11-UT）。"""

from __future__ import annotations

import pytest

from core.errors import AuditFailed
from core.logging import clear_registered_secrets, register_secret
from modules.audit.service import (
    MAX_DETAIL_VALUE_LENGTH,
    AuditService,
    sanitize_details,
)


class _FailingDatabase:
    """故障注入：所有会话获取都失败。"""

    def session(self):
        raise RuntimeError("database unavailable")


def test_sanitize_details_allows_only_whitelist() -> None:
    cleaned = sanitize_details(
        {
            "project_id": "proj_alpha",
            "role": "viewer",
            "access_level": 2,
            "client_secret": "must-not-persist",
            "token": "must-not-persist",
            "proof": "must-not-persist",
            "nested": {"payload": "must-not-persist"},
            "empty": None,
        }
    )

    assert cleaned == {"project_id": "proj_alpha", "role": "viewer", "access_level": 2}


def test_sanitize_details_redacts_registered_secret() -> None:
    register_secret("super-secret-value")
    try:
        cleaned = sanitize_details({"project_id": "proj-super-secret-value"})
    finally:
        clear_registered_secrets()

    assert cleaned == {"project_id": "proj-***"}


def test_sanitize_details_truncates_long_values() -> None:
    cleaned = sanitize_details({"endpoint": "/api/v1/" + "x" * 500})

    assert len(cleaned["endpoint"]) == MAX_DETAIL_VALUE_LENGTH


async def test_sensitive_audit_failure_is_fail_closed() -> None:
    service = AuditService(_FailingDatabase(), fail_closed=True)

    with pytest.raises(AuditFailed) as exc_info:
        await service.record("auth.succeeded", client_id="cli_1", sensitive=True)

    assert exc_info.value.code == "AUDIT_FAILED"


async def test_non_sensitive_audit_failure_is_fail_open() -> None:
    service = AuditService(_FailingDatabase(), fail_closed=True)

    assert await service.record("session.created", client_id="cli_1") is None


async def test_fail_closed_can_be_disabled() -> None:
    service = AuditService(_FailingDatabase(), fail_closed=False)

    assert await service.record("access.granted", sensitive=True) is None
