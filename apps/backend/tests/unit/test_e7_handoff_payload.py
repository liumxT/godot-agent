"""E7-T07 / T08 单元测试：Handoff payload 与 Lead 默认权限。"""

from __future__ import annotations

import pytest

from core.errors import AgentHandoffInvalid, AgentTeamInvalid
from modules.multi_agent.lead import (
    LEAD_PERMISSIONS,
    WRITE_PERMISSIONS,
    LeadAgentService,
)
from modules.multi_agent.service import HandoffPayload


def _payload(**overrides) -> HandoffPayload:
    values = {
        "original_objective": "实现玩家移动与跳跃",
        "current_scope": "Player 场景与输入映射",
        "completed_work": ("移动已完成",),
        "remaining_work": ("跳跃未完成",),
        "next_steps": ("完成跳跃并补测试",),
        "acceptance_criteria": ("玩家可以跳跃",),
    }
    values.update(overrides)
    return HandoffPayload(**values)


def test_payload_accepts_complete_handoff() -> None:
    payload = _payload()
    payload.validate(handoff_type="TASK_HANDOFF")
    reference = payload.reference()
    assert reference.startswith("handoff://")
    assert payload.to_dict()["acceptance_criteria"] == ["玩家可以跳跃"]


def test_payload_requires_objective_scope_steps_and_acceptance() -> None:
    with pytest.raises(AgentHandoffInvalid) as exc_info:
        HandoffPayload(original_objective="", current_scope="").validate(
            handoff_type="TASK_HANDOFF"
        )
    assert exc_info.value.details["reasons"] == ["MISSING_FIELDS"]
    assert set(exc_info.value.details["fields"]) == {
        "original_objective",
        "current_scope",
        "next_steps",
        "acceptance_criteria",
    }


def test_failure_handoff_requires_failure_reason() -> None:
    with pytest.raises(AgentHandoffInvalid) as exc_info:
        _payload().validate(handoff_type="FAILURE_HANDOFF")
    assert exc_info.value.details["reasons"] == ["FAILURE_REASON_REQUIRED"]


def test_payload_from_mapping_rejects_hidden_reasoning() -> None:
    data = _payload().to_dict()
    data["hidden_reasoning"] = "我不能共享的推理"
    with pytest.raises(AgentHandoffInvalid) as exc_info:
        HandoffPayload.from_mapping(data)
    assert exc_info.value.details["reasons"] == ["UNKNOWN_FIELD"]
    assert "hidden_reasoning" in exc_info.value.details["fields"]


def test_lead_permissions_are_read_only_by_default() -> None:
    assert LeadAgentService.default_permissions() == LEAD_PERMISSIONS
    assert not LeadAgentService.can_write(LEAD_PERMISSIONS)
    assert LEAD_PERMISSIONS.isdisjoint(WRITE_PERMISSIONS)


def test_lead_permissions_grant_write_only_explicitly() -> None:
    granted = LeadAgentService.granted_permissions(("PROJECT_WRITE",))
    assert LeadAgentService.can_write(granted)
    with pytest.raises(AgentTeamInvalid):
        LeadAgentService.granted_permissions(("UNKNOWN_PERMISSION",))
