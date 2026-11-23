"""E6-T16 可观测性脱敏单元测试。"""

from __future__ import annotations

from modules.agent_runtime.observability import log_context, sanitize


def test_sanitize_redacts_sensitive_keys_recursively() -> None:
    payload = {
        "model": "fake",
        "api_key": "sk-secret",
        "nested": {"authorization": "Bearer x", "reasoning": "hidden", "keep": 1},
        "items": [{"token": "abc"}, {"value": 2}],
    }
    cleaned = sanitize(payload)
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["authorization"] == "[REDACTED]"
    assert cleaned["nested"]["reasoning"] == "[REDACTED]"
    assert cleaned["nested"]["keep"] == 1
    assert cleaned["items"][0]["token"] == "[REDACTED]"
    assert cleaned["items"][1]["value"] == 2


def test_sanitize_truncates_long_strings() -> None:
    cleaned = sanitize({"content": "a" * 5000})
    assert cleaned["content"].endswith("...[truncated]")


def test_log_context_omits_empty_dimensions() -> None:
    context = log_context(instance_id="agi_1", execution_id="agex_1", project_id="prj_1")
    assert context == {
        "agent_instance_id": "agi_1",
        "agent_execution_id": "agex_1",
        "project_id": "prj_1",
    }
