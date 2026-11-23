"""E7-T13 / T14 单元测试：专用 Agent 目录与游戏工作流模板。"""

from __future__ import annotations

import pytest

from core.errors import NotFoundError
from modules.multi_agent.models import RISK_PROFILES
from modules.multi_agent.specialized import (
    EXECUTION_READY_AGENTS,
    PRIORITY_P0,
    PRIORITY_P1,
    PRIORITY_P2,
    SPECIALIZED_AGENTS,
    SpecializedAgentCatalog,
    validate_catalog,
)
from modules.multi_agent.workflows import (
    GAME_WORKFLOWS,
    GameWorkflowService,
    build_document,
    validate_workflow_specs,
)
from modules.workflow.models import (
    NODE_TYPE_AI_EXECUTION,
    NODE_TYPE_USER_CONFIRMATION,
    NODE_TYPE_VERIFICATION,
)


def test_catalog_covers_all_priorities() -> None:
    assert len(SPECIALIZED_AGENTS) == 38
    assert sum(1 for spec in SPECIALIZED_AGENTS if spec.priority == PRIORITY_P0) == 15
    assert sum(1 for spec in SPECIALIZED_AGENTS if spec.priority == PRIORITY_P1) == 18
    assert sum(1 for spec in SPECIALIZED_AGENTS if spec.priority == PRIORITY_P2) == 5


def test_catalog_specs_have_complete_contract() -> None:
    for spec in SPECIALIZED_AGENTS:
        assert spec.capabilities, spec.key
        assert spec.input_contract and spec.output_contract, spec.key
        assert spec.acceptance_criteria, spec.key
        assert spec.permission_ceiling in RISK_PROFILES, spec.key
        assert spec.version


def test_execution_ready_agents_are_reachable_p0() -> None:
    assert len(EXECUTION_READY_AGENTS) >= 5
    ready = {spec.key for spec in SPECIALIZED_AGENTS if spec.execution_ready}
    assert ready == set(EXECUTION_READY_AGENTS)
    catalog = _catalog_stub()
    for key in EXECUTION_READY_AGENTS:
        assert catalog.get(key).priority == PRIORITY_P0


def test_validate_catalog_passes() -> None:
    validate_catalog()


def test_catalog_lookup_by_key_and_name() -> None:
    catalog = _catalog_stub()
    by_key = catalog.get("game_designer")
    by_name = catalog.get("Game Designer")
    assert by_key is by_name
    with pytest.raises(NotFoundError):
        catalog.get("unknown_agent")


def test_all_workflow_templates_have_reviewed_phases() -> None:
    assert len(GAME_WORKFLOWS) == 5
    validate_workflow_specs()
    for spec in GAME_WORKFLOWS:
        document = build_document(spec)
        assert len(document["nodes"]) == len(spec.steps)
        assert len(document["phases"]) == len(spec.steps)
        for phase in document["phases"]:
            assert phase["review_required"] is True
        ai_nodes = [node for node in document["nodes"] if node["node_type"] == NODE_TYPE_AI_EXECUTION]
        assert all(node["config"].get("agent_key") for node in ai_nodes)
        final_type = document["nodes"][-1]["node_type"]
        assert final_type in {NODE_TYPE_USER_CONFIRMATION, NODE_TYPE_VERIFICATION}


def test_workflow_service_rejects_unknown_key() -> None:
    service = GameWorkflowService(definitions=None, instances=None)
    with pytest.raises(NotFoundError):
        service.get("unknown_workflow")


def _catalog_stub() -> SpecializedAgentCatalog:
    return SpecializedAgentCatalog(definitions=None, prompts=None)
