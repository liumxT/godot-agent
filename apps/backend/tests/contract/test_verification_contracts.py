"""E9 共享契约测试。"""

from __future__ import annotations

import json

import pytest

from modules.verification import models
from shared.contracts import contracts_root, load_json, load_schema, validate_instance

SCHEMA_DIR = contracts_root() / "verification" / "schemas"
EXAMPLE_DIR = contracts_root() / "verification" / "examples"

EXPECTED_SCHEMAS = {
    "acceptance_criterion.schema.json",
    "verification_campaign.schema.json",
    "verification_evidence.schema.json",
    "verification_result.schema.json",
    "verification_run.schema.json",
}


def _schema_path(name: str) -> str:
    return f"verification/schemas/{name}"


def test_schema_files_are_complete() -> None:
    assert {path.name for path in SCHEMA_DIR.glob("*.schema.json")} == EXPECTED_SCHEMAS
    for name in EXPECTED_SCHEMAS:
        schema = load_schema(_schema_path(name))
        assert schema["title"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["required"]


@pytest.mark.parametrize(
    "example,schema",
    [
        ("verification_campaign.valid.json", "verification_campaign.schema.json"),
        ("verification_result.valid.json", "verification_result.schema.json"),
        ("verification_evidence.valid.json", "verification_evidence.schema.json"),
        ("acceptance_criterion.valid.json", "acceptance_criterion.schema.json"),
        ("verification_evidence.invalid.hash.json", "verification_evidence.schema.json"),
    ],
)
def test_examples_match_expectation(example: str, schema: str) -> None:
    instance = json.loads((EXAMPLE_DIR / example).read_text(encoding="utf-8"))
    errors = validate_instance(instance, _schema_path(schema))
    if ".invalid." in example:
        assert errors
    else:
        assert errors == []


def _enum(schema_name: str, field: str) -> set[str]:
    schema = load_schema(_schema_path(schema_name))
    return set(schema["properties"][field]["enum"])


def test_contract_enums_match_domain_constants() -> None:
    assert _enum("verification_campaign.schema.json", "status") == models.CAMPAIGN_STATUSES
    assert _enum("verification_campaign.schema.json", "campaign_type") == models.CAMPAIGN_TYPES
    assert _enum("verification_run.schema.json", "execution_status") == models.RUN_STATUSES
    assert _enum("verification_result.schema.json", "result_status") == models.RESULT_STATUSES
    assert (
        _enum("verification_evidence.schema.json", "validity_status")
        == models.EVIDENCE_VALIDITY_STATUSES
    )
    assert _enum("verification_evidence.schema.json", "evidence_type") == models.EVIDENCE_TYPES
    assert _enum("verification_evidence.schema.json", "source_type") == models.EVIDENCE_SOURCE_TYPES
    assert _enum("acceptance_criterion.schema.json", "criterion_type") == models.CRITERION_TYPES


def test_error_codes_are_registered() -> None:
    payload = load_json("errors/error-codes.json")
    codes = {entry["code"] for entry in payload["codes"]}
    assert {
        "VERIFICATION_STATE_INVALID",
        "VERIFICATION_PLAN_INVALID",
        "VERIFICATION_RESULT_INVALID",
        "VERIFICATION_EVIDENCE_INVALID",
        "VERIFICATION_EVIDENCE_STALE",
        "VERIFICATION_REQUIREMENT_UNTRACEABLE",
        "VERIFICATION_CAMPAIGN_NOT_COMPLETE",
        "QUALITY_GATE_BLOCKED",
        "QUALITY_GATE_INVALID",
        "DEFECT_STATE_INVALID",
        "DEFECT_INVALID",
        "PHASE_REVIEW_INVALID",
    } <= codes
