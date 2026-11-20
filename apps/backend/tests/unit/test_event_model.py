"""事件模型测试（E1-T09-UT-001 / UT-004 及契约校验）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.errors import ValidationFailed
from core.events.model import Event
from shared.contracts import validate_instance


def test_create_fills_required_fields() -> None:
    event = Event.create("task.created", {"task_id": "t1"}, correlation_id="corr-1")

    assert event.event_version == 1
    assert event.producer == "backend"
    assert event.occurred_at.tzinfo is not None
    assert event.correlation_id == "corr-1"
    assert validate_instance(event.to_contract(), "events/event.schema.json") == []


def test_contract_mapping() -> None:
    occurred = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    event = Event.create(
        "task.created",
        {"task_id": "t1"},
        event_version=2,
        occurred_at=occurred,
        session_id="session-1",
    )

    contract = event.to_contract()

    assert contract["timestamp"] == "2026-11-18T10:00:00Z"
    assert contract["source"] == "backend"
    assert contract["session_id"] == "session-1"
    assert "event_version" not in contract
    assert validate_instance(contract, "events/event.schema.json") == []


def test_event_version_is_preserved() -> None:
    event = Event.create("task.created", {}, event_version=3)

    assert event.event_version == 3


def test_invalid_event_type_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        Event.create("TaskCreated", {})


def test_invalid_event_version_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        Event.create("task.created", {}, event_version=0)


def test_naive_occurred_at_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        Event.create("task.created", {}, occurred_at=datetime(2026, 1, 1))


def test_storage_round_trip() -> None:
    event = Event.create("task.created", {"task_id": "t1"}, correlation_id="corr")

    restored = Event.from_storage(
        event_id=event.event_id,
        event_type=event.event_type,
        event_version=event.event_version,
        payload=event.payload_json,
        correlation_id=event.correlation_id,
        occurred_at="2026-11-18 10:00:00",
    )

    assert restored.event_id == event.event_id
    assert restored.payload == {"task_id": "t1"}
    assert restored.occurred_at.tzinfo is not None


def test_invalid_payload_json_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        Event.from_storage(
            event_id="e1",
            event_type="task.created",
            event_version=1,
            payload="not-json",
            correlation_id=None,
            occurred_at=datetime.now(UTC),
        )
