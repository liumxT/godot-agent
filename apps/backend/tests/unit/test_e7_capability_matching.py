"""E7-T02 Capability 目录与匹配单元测试。"""

from __future__ import annotations

import pytest

from modules.multi_agent.capabilities import (
    BUILTIN_CAPABILITIES,
    BUILTIN_CAPABILITY_NAMES,
    MODEL_SUPPORTED,
    MODEL_UNSUPPORTED,
    CandidateProfile,
    CapabilityRequirement,
    match_candidates,
)
from modules.multi_agent.models import (
    CAPABILITY_CATEGORIES,
    CAPABILITY_CATEGORY_PROGRAMMING,
    RISK_PROFILES,
)

_MODEL_CAPS = {
    "TEXT_INPUT": MODEL_SUPPORTED,
    "TEXT_OUTPUT": MODEL_SUPPORTED,
    "STRUCTURED_OUTPUT": MODEL_SUPPORTED,
}


def _candidate(**overrides) -> CandidateProfile:
    defaults = {
        "definition_id": "def_1",
        "name": "agent",
        "enabled": True,
        "capabilities": ("gameplay_programming",),
        "permission_ceiling": "R2",
        "available_tools": frozenset({"file.read", "file.write"}),
        "model_capabilities": _MODEL_CAPS,
        "current_load": 0,
        "max_concurrency": 4,
        "success_rate": 0.8,
        "estimated_cost": 1.0,
    }
    defaults.update(overrides)
    return CandidateProfile(**defaults)


def _requirement(**overrides) -> CapabilityRequirement:
    defaults = {
        "capabilities": ("gameplay_programming",),
        "required_tools": ("file.read",),
        "required_model_capabilities": ("TEXT_INPUT",),
        "required_risk_level": "R1",
    }
    defaults.update(overrides)
    return CapabilityRequirement(**defaults)


def test_builtin_catalog_is_unique_and_valid() -> None:
    assert len(BUILTIN_CAPABILITIES) >= 30
    names = [spec.name for spec in BUILTIN_CAPABILITIES]
    assert len(names) == len(set(names))
    assert BUILTIN_CAPABILITY_NAMES == frozenset(names)
    for spec in BUILTIN_CAPABILITIES:
        assert spec.category in CAPABILITY_CATEGORIES
        assert spec.risk_profile in RISK_PROFILES
    assert "gameplay_programming" in BUILTIN_CAPABILITY_NAMES
    gameplay = next(spec for spec in BUILTIN_CAPABILITIES if spec.name == "gameplay_programming")
    assert gameplay.category == CAPABILITY_CATEGORY_PROGRAMMING


def test_disabled_agent_is_excluded() -> None:
    outcome = match_candidates(_requirement(), [_candidate(enabled=False)])
    assert outcome.ranked == ()
    assert outcome.excluded[0].reasons == ("AGENT_DISABLED",)


def test_missing_capability_is_excluded() -> None:
    outcome = match_candidates(
        _requirement(capabilities=("level_design",)),
        [_candidate(capabilities=("gameplay_programming",))],
    )
    assert outcome.ranked == ()
    assert "CAPABILITY_MISSING" in outcome.excluded[0].reasons


def test_permission_ceiling_is_hard_limit() -> None:
    outcome = match_candidates(
        _requirement(required_risk_level="R3"),
        [_candidate(permission_ceiling="R2")],
    )
    assert outcome.ranked == ()
    assert outcome.excluded[0].reasons == ("PERMISSION_INSUFFICIENT",)


def test_tool_unavailable_is_excluded() -> None:
    outcome = match_candidates(
        _requirement(required_tools=("file.write", "godot.node.create")),
        [_candidate()],
    )
    assert outcome.ranked == ()
    assert "TOOL_UNAVAILABLE" in outcome.excluded[0].reasons


def test_model_capability_unknown_is_excluded() -> None:
    outcome = match_candidates(
        _requirement(required_model_capabilities=("IMAGE_INPUT",)),
        [_candidate()],
    )
    assert outcome.ranked == ()
    assert outcome.excluded[0].reasons == ("MODEL_CAPABILITY_UNKNOWN",)
    unsupported = match_candidates(
        _requirement(required_model_capabilities=("IMAGE_INPUT",)),
        [
            _candidate(
                model_capabilities={
                    "TEXT_INPUT": MODEL_SUPPORTED,
                    "TEXT_OUTPUT": MODEL_SUPPORTED,
                    "IMAGE_INPUT": MODEL_UNSUPPORTED,
                }
            )
        ],
    )
    assert unsupported.excluded[0].reasons == ("MODEL_CAPABILITY_UNSUPPORTED",)


def test_project_scope_and_budget_are_hard_limits() -> None:
    outcome = match_candidates(
        _requirement(project_id="prj_1"),
        [_candidate(project_id="prj_2"), _candidate(definition_id="def_2", project_id=None)],
    )
    assert outcome.ranked == ()
    assert all("PROJECT_INACCESSIBLE" in item.reasons for item in outcome.excluded)
    budget = match_candidates(_requirement(), [_candidate(budget_available=False)])
    assert budget.excluded[0].reasons == ("BUDGET_INSUFFICIENT",)


def test_ranking_prefers_success_and_low_load() -> None:
    outcome = match_candidates(
        _requirement(),
        [
            _candidate(definition_id="slow", success_rate=0.2, current_load=4),
            _candidate(definition_id="fast", success_rate=0.9, current_load=0),
            _candidate(definition_id="fast_expensive", success_rate=0.9, estimated_cost=9.0),
        ],
    )
    ids = [item.definition_id for item in outcome.ranked]
    assert ids[0] == "fast"
    assert ids[-1] == "slow"


def test_high_load_candidate_is_demoted_not_excluded() -> None:
    outcome = match_candidates(
        _requirement(),
        [
            _candidate(definition_id="busy", current_load=8, max_concurrency=4),
            _candidate(definition_id="idle", current_load=0, max_concurrency=4),
        ],
    )
    assert {item.definition_id for item in outcome.ranked} == {"busy", "idle"}
    assert outcome.best is not None
    assert outcome.best.definition_id == "idle"


def test_requirement_validation() -> None:
    with pytest.raises(ValueError):
        CapabilityRequirement(capabilities=())
    with pytest.raises(ValueError):
        CapabilityRequirement(capabilities=("x",), required_risk_level="R9")
