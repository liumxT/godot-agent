"""E8 资产契约校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.asset_pipeline import models
from shared.contracts import contracts_root, load_json, load_schema, validate_instance

SCHEMA_DIR = "asset_pipeline/schemas"
EXAMPLE_DIR = "asset_pipeline/examples"

VALID_CASES = [
    ("asset.schema.json", "asset.valid.json"),
    ("asset_generation.schema.json", "asset_generation.valid.json"),
    ("asset_license.schema.json", "asset_license.valid.json"),
    ("asset_delivery.schema.json", "asset_delivery.valid.json"),
]


def _schema_paths() -> list[Path]:
    directory = contracts_root() / SCHEMA_DIR
    return sorted(directory.glob("*.schema.json"))


def test_asset_schemas_are_valid_and_complete() -> None:
    paths = _schema_paths()
    assert len(paths) >= 10
    names = {path.name for path in paths}
    assert names == {
        "asset.schema.json",
        "asset_version.schema.json",
        "asset_brief.schema.json",
        "asset_generation.schema.json",
        "asset_processing_job.schema.json",
        "asset_import_job.schema.json",
        "asset_provenance.schema.json",
        "asset_license.schema.json",
        "asset_quality_review.schema.json",
        "asset_delivery.schema.json",
    }
    for path in paths:
        schema = load_schema(f"{SCHEMA_DIR}/{path.name}")
        assert schema["title"]
        assert schema["additionalProperties"] is False
        assert isinstance(schema["required"], list) and schema["required"]


@pytest.mark.parametrize(("schema_name", "example_name"), VALID_CASES)
def test_asset_valid_examples(schema_name: str, example_name: str) -> None:
    instance = load_json(f"{EXAMPLE_DIR}/{example_name}")
    assert validate_instance(instance, f"{SCHEMA_DIR}/{schema_name}") == []


def test_asset_invalid_example_rejected() -> None:
    instance = load_json(f"{EXAMPLE_DIR}/asset.invalid.json")
    errors = validate_instance(instance, f"{SCHEMA_DIR}/asset.schema.json")
    assert errors


def _enum_values(schema_name: str, *path: str):
    node = load_schema(f"{SCHEMA_DIR}/{schema_name}")
    for key in path:
        node = node[key]
    return set(node["enum"])


def test_schema_enums_match_domain_models() -> None:
    assert _enum_values("asset.schema.json", "properties", "category") == set(
        models.ASSET_CATEGORIES
    )
    assert _enum_values("asset.schema.json", "properties", "lifecycle_status") == set(
        models.ASSET_STATUSES
    )
    assert _enum_values("asset_version.schema.json", "properties", "source_type") == set(
        models.SOURCE_TYPES
    )
    assert _enum_values(
        "asset_generation.schema.json", "properties", "generation_status"
    ) == set(models.GENERATION_STATUSES)
    assert _enum_values(
        "asset_processing_job.schema.json", "properties", "processing_status"
    ) == set(models.PROCESSING_STATUSES)
    assert _enum_values("asset_import_job.schema.json", "properties", "import_status") == set(
        models.IMPORT_STATUSES
    )
    assert _enum_values("asset_license.schema.json", "properties", "verification_status") == set(
        models.LICENSE_STATUSES
    )
    assert _enum_values(
        "asset_quality_review.schema.json", "properties", "review_status"
    ) == set(models.QUALITY_STATUSES)
    assert _enum_values("asset_delivery.schema.json", "properties", "delivery_status") == set(
        models.DELIVERY_STATUSES
    )
    assert _enum_values("asset_brief.schema.json", "properties", "status") == set(
        models.BRIEF_STATUSES
    )
