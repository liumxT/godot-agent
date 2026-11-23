"""E7-T10 / T11 / T17 单元测试：资源请求与冲突解决策略。"""

from __future__ import annotations

import pytest

from core.errors import AgentResourceLockInvalid
from modules.multi_agent.models import RESOLUTION_STRATEGIES
from modules.multi_agent.resources import ResourceRequest, resource_signature


def test_resource_request_requires_known_type_and_mode() -> None:
    with pytest.raises(AgentResourceLockInvalid) as exc_info:
        ResourceRequest(resource_type="UNKNOWN", resource_key="res://player.tscn").validate()
    assert exc_info.value.details["reasons"] == ["UNKNOWN_RESOURCE_TYPE"]

    with pytest.raises(AgentResourceLockInvalid) as exc_info:
        ResourceRequest(
            resource_type="SCENE", resource_key="res://player.tscn", mode="APPEND"
        ).validate()
    assert exc_info.value.details["reasons"] == ["UNKNOWN_MODE"]


def test_resource_request_rejects_empty_key() -> None:
    with pytest.raises(AgentResourceLockInvalid) as exc_info:
        ResourceRequest(resource_type="SCENE", resource_key=" ").validate()
    assert exc_info.value.details["reasons"] == ["RESOURCE_KEY_REQUIRED"]


def test_last_write_wins_is_not_a_resolution_strategy() -> None:
    assert "LAST_WRITE_WINS" not in RESOLUTION_STRATEGIES
    assert "USER_DECISION" in RESOLUTION_STRATEGIES


def test_resource_signature_is_order_independent() -> None:
    first = resource_signature(["res://b.tscn", "res://a.gd"])
    second = resource_signature(["res://a.gd", "res://b.tscn"])
    assert first == second
