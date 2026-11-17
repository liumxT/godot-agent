"""Shared Contracts 样例校验（E0-T05 验收）。

Backend 必须与 Plugin 对同一份 manifest 得出相同的有效性结论。
"""

from __future__ import annotations

import pytest

from shared.contracts import (
    ContractError,
    iter_manifest,
    load_json,
    load_schema,
    protocol_version,
    validate_instance,
)

CASES = list(iter_manifest())


def _sample_path(case: dict) -> dict:
    return load_json("schemas/" + case["file"])


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_manifest_case(case: dict) -> None:
    errors = validate_instance(_sample_path(case), case["schema"])
    assert bool(errors) is not case["valid"], f"{case['id']} 校验结论与预期不符: {errors}"


def test_protocol_version_is_frozen() -> None:
    assert protocol_version() == "1.0"


def test_unknown_field_is_rejected() -> None:
    sample = _sample_path({"file": "examples/request.valid.json"})
    sample["unexpected"] = True
    assert validate_instance(sample, "api/request.schema.json")


def test_error_schema_matches_response_embedded_definition() -> None:
    standalone = dict(load_schema("errors/error.schema.json"))
    for key in ("$schema", "$id", "title"):
        standalone.pop(key, None)
    embedded = load_schema("api/response.schema.json")["$defs"]["error"]
    assert standalone == embedded, "response 内嵌 error 定义与 errors/error.schema.json 不一致"


def test_missing_contract_file_raises() -> None:
    with pytest.raises(ContractError):
        load_json("schemas/examples/not-exists.json")
