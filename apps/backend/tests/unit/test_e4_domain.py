"""E4 领域纯函数测试：清单规范化、哈希、Workflow 定义与检查点。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from core.errors import InvalidStateTransition, ValidationFailed
from modules.changeset.service import compute_manifest_hash, normalize_manifest
from modules.task.models import (
    ATTEMPT_STATUSES,
    ATTEMPT_TRANSITIONS,
    TASK_STATUSES,
    TASK_TRANSITIONS,
)
from modules.task.service import AttemptService, TaskService, checkpoint_checksum
from modules.workflow.models import (
    INSTANCE_BLOCKED,
    INSTANCE_CANCELLED,
    INSTANCE_COMPLETED,
    INSTANCE_CREATED,
    INSTANCE_FAILED,
    INSTANCE_PAUSED,
    INSTANCE_PAUSING,
    INSTANCE_READY,
    INSTANCE_RESUMING,
    INSTANCE_RUNNING,
    INSTANCE_TRANSITIONS,
    INSTANCE_WAITING_APPROVAL,
    INSTANCE_WAITING_USER,
)
from modules.workflow.service import WorkflowInstanceService, parse_definition

_INSTANCE_STATUSES = frozenset(
    {
        INSTANCE_CREATED,
        INSTANCE_READY,
        INSTANCE_RUNNING,
        INSTANCE_PAUSING,
        INSTANCE_PAUSED,
        INSTANCE_RESUMING,
        INSTANCE_WAITING_APPROVAL,
        INSTANCE_WAITING_USER,
        INSTANCE_BLOCKED,
        INSTANCE_FAILED,
        INSTANCE_CANCELLED,
        INSTANCE_COMPLETED,
    }
)

_ITEM = {
    "resource_path": "scenes/main.tscn",
    "operation_type": "CREATE",
    "new_content_hash": "b" * 64,
    "risk_level": "LOW",
}


def test_normalize_manifest_sorts_and_rejects_traversal() -> None:
    manifest = normalize_manifest([_ITEM, {**_ITEM, "resource_path": "a.gd"}])
    assert [item["resource_path"] for item in manifest] == ["a.gd", "scenes/main.tscn"]

    with pytest.raises(ValidationFailed):
        normalize_manifest([{**_ITEM, "resource_path": "../outside.tscn"}])


def test_normalize_manifest_rejects_duplicates() -> None:
    with pytest.raises(ValidationFailed):
        normalize_manifest([_ITEM, dict(_ITEM)])


def test_manifest_hash_is_order_independent() -> None:
    first = normalize_manifest([_ITEM, {**_ITEM, "resource_path": "a.gd"}])
    second = normalize_manifest([{**_ITEM, "resource_path": "a.gd"}, _ITEM])
    assert compute_manifest_hash(first) == compute_manifest_hash(second)

    changed = normalize_manifest([{**_ITEM, "new_content_hash": "c" * 64}])
    assert compute_manifest_hash(changed) != compute_manifest_hash([_ITEM])


def test_parse_definition_validates_references() -> None:
    document = {
        "nodes": [
            {"node_key": "analyze", "node_type": "AI_EXECUTION", "phase_key": "p1"},
            {
                "node_key": "implement",
                "node_type": "TOOL_OPERATION",
                "dependency_keys": ["analyze"],
                "phase_key": "p1",
            },
        ],
        "phases": [{"phase_key": "p1", "name": "Phase 1"}],
    }
    parsed = parse_definition(document)
    assert [node["node_key"] for node in parsed["nodes"]] == ["analyze", "implement"]

    with pytest.raises(ValidationFailed):
        parse_definition(
            {"nodes": [{"node_key": "a", "phase_key": "missing"}], "phases": [{"phase_key": "p"}]}
        )
    with pytest.raises(ValidationFailed):
        parse_definition({"nodes": [{"node_key": "a", "dependency_keys": ["b"]}]})


def test_checkpoint_checksum_is_stable_and_sensitive() -> None:
    base = checkpoint_checksum(
        attempt_id="att_1", workflow_state_ref=None, context_ref="ctx", changeset_ref=None
    )
    assert base == checkpoint_checksum(
        attempt_id="att_1", workflow_state_ref=None, context_ref="ctx", changeset_ref=None
    )
    assert base != checkpoint_checksum(
        attempt_id="att_1", workflow_state_ref=None, context_ref="other", changeset_ref=None
    )


@pytest.mark.parametrize("source", sorted(TASK_STATUSES))
def test_task_transition_matrix_enforces_every_illegal_pair(source: str) -> None:
    service = TaskService.__new__(TaskService)
    allowed = TASK_TRANSITIONS.get(source, frozenset())

    for target in TASK_STATUSES - allowed - {source}:
        entity = SimpleNamespace(status=source, version=0, updated_at=None, task_id="tsk_x")
        with pytest.raises(InvalidStateTransition):
            service._apply_transition(entity, target, datetime.now())
        assert entity.status == source

    for target in allowed:
        entity = SimpleNamespace(status=source, version=0, updated_at=None, task_id="tsk_x")
        service._apply_transition(entity, target, datetime.now())
        assert entity.status == target


@pytest.mark.parametrize("source", sorted(ATTEMPT_STATUSES))
def test_attempt_transition_matrix_enforces_every_illegal_pair(source: str) -> None:
    service = AttemptService.__new__(AttemptService)
    allowed = ATTEMPT_TRANSITIONS.get(source, frozenset())

    for target in ATTEMPT_STATUSES - allowed - {source}:
        entity = SimpleNamespace(status=source, attempt_id="att_x")
        with pytest.raises(InvalidStateTransition):
            service._apply_transition(entity, target, datetime.now())
        assert entity.status == source

    for target in allowed:
        entity = SimpleNamespace(status=source, attempt_id="att_x")
        service._apply_transition(entity, target, datetime.now())
        assert entity.status == target


@pytest.mark.parametrize("source", sorted(_INSTANCE_STATUSES))
def test_workflow_transition_matrix_enforces_every_illegal_pair(source: str) -> None:
    service = WorkflowInstanceService.__new__(WorkflowInstanceService)
    allowed = INSTANCE_TRANSITIONS.get(source, frozenset())

    for target in _INSTANCE_STATUSES - allowed - {source}:
        entity = SimpleNamespace(status=source, instance_id="wfi_x")
        with pytest.raises(InvalidStateTransition):
            service._apply_transition(entity, target, datetime.now())
        assert entity.status == source

    for target in allowed:
        entity = SimpleNamespace(status=source, instance_id="wfi_x")
        service._apply_transition(entity, target, datetime.now())
        assert entity.status == target
