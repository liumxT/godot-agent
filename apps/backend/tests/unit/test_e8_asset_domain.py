"""E8-T01 / T02 领域与存储单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.errors import AssetPathInvalid, AssetStorageError
from core.security.policy import evaluate
from core.security.principal import (
    ACTION_E8_ASSET_APPROVE,
    ACTION_E8_ASSET_CREATE,
    ACTION_E8_ASSET_GENERATE,
    ACTION_E8_ASSET_IMPORT,
    ACTION_E8_ASSET_READ,
    ROLE_EDITOR,
    ROLE_OWNER,
    ROLE_VIEWER,
    Principal,
    Resource,
)
from modules.asset_pipeline import models
from modules.asset_pipeline.storage import (
    AssetStorage,
    normalize_relative_path,
)


def _principal(role: str) -> Principal:
    return Principal(
        client_id="client-1",
        client_type="godot",
        session_id="session-1",
        role=role,
        project_id="prj_1",
    )


def test_asset_lifecycle_is_terminal_after_archived() -> None:
    assert models.ASSET_TRANSITIONS[models.ASSET_ARCHIVED] == frozenset()
    assert models.ASSET_ACTIVE in models.ASSET_TRANSITIONS[models.ASSET_DRAFT]
    assert models.ASSET_DEPRECATED in models.ASSET_TRANSITIONS[models.ASSET_ACTIVE]


def test_every_status_has_transition_entry() -> None:
    for statuses, transitions in (
        (models.ASSET_STATUSES, models.ASSET_TRANSITIONS),
        (models.GENERATION_STATUSES, models.GENERATION_TRANSITIONS),
        (models.PROCESSING_STATUSES, models.PROCESSING_TRANSITIONS),
        (models.IMPORT_STATUSES, models.IMPORT_TRANSITIONS),
        (models.QUALITY_STATUSES, models.QUALITY_TRANSITIONS),
        (models.LICENSE_STATUSES, models.LICENSE_TRANSITIONS),
        (models.DELIVERY_STATUSES, models.DELIVERY_TRANSITIONS),
        (models.BRIEF_STATUSES, models.BRIEF_TRANSITIONS),
    ):
        assert set(transitions) == set(statuses)
        for target in transitions.values():
            assert target <= statuses


def test_transitions_for_unknown_kind_rejected() -> None:
    with pytest.raises(ValueError):
        models.transitions_for("unknown")


@pytest.mark.parametrize(
    "path",
    [
        "",
        "   ",
        "/abs/path.png",
        "C:/windows.png",
        "../escape.png",
        "a/../b.png",
        "a//b.png",
        "a/./b.png",
        "CON.png",
        "a\\..\\b.png",
    ],
)
def test_invalid_relative_paths_rejected(path: str) -> None:
    with pytest.raises(AssetPathInvalid):
        normalize_relative_path(path)


def test_relative_path_normalized() -> None:
    assert normalize_relative_path("hero/idle_01.png") == "hero/idle_01.png"
    assert normalize_relative_path(r"hero\idle_01.png") == "hero/idle_01.png"


def test_storage_write_read_and_hash(tmp_path: Path) -> None:
    storage = AssetStorage(tmp_path / "assets")
    data = b"fake-png-bytes"
    result = storage.write_bytes("prj_1", "generated", "hero/idle.png", data)
    assert result["size_bytes"] == len(data)
    assert result["content_hash"] == storage.hash_file(
        tmp_path / "assets" / "projects" / "prj_1" / "generated" / "hero" / "idle.png"
    )
    assert storage.read_bytes("prj_1", "generated", "hero/idle.png") == data


def test_storage_rejects_overwrite_and_traversal(tmp_path: Path) -> None:
    storage = AssetStorage(tmp_path / "assets")
    storage.write_bytes("prj_1", "source", "a.png", b"a")
    with pytest.raises(AssetPathInvalid):
        storage.write_bytes("prj_1", "source", "a.png", b"b")
    with pytest.raises(AssetPathInvalid):
        storage.resolve("prj_1", "source", "../escape.png")
    with pytest.raises(AssetPathInvalid):
        storage.area_dir("prj_1", "unknown")


def test_storage_file_size_limit(tmp_path: Path) -> None:
    storage = AssetStorage(tmp_path / "assets", max_file_bytes=4)
    with pytest.raises(AssetStorageError):
        storage.write_bytes("prj_1", "source", "big.bin", b"12345")


def test_storage_allocate_avoids_conflicts(tmp_path: Path) -> None:
    storage = AssetStorage(tmp_path / "assets")
    storage.write_bytes("prj_1", "processed", "hero.png", b"1")
    relative, _ = storage.allocate("prj_1", "processed", "hero.png")
    assert relative == "hero_001.png"


def test_storage_read_missing_file(tmp_path: Path) -> None:
    storage = AssetStorage(tmp_path / "assets")
    with pytest.raises(AssetStorageError):
        storage.read_bytes("prj_1", "source", "missing.png")


@pytest.mark.parametrize("project_id", ["", "../x", "a b", "x" * 65])
def test_invalid_project_id_rejected(tmp_path: Path, project_id: str) -> None:
    storage = AssetStorage(tmp_path / "assets")
    with pytest.raises(AssetPathInvalid):
        storage.project_dir(project_id)


def test_policy_e8_asset_roles() -> None:
    resource = Resource(kind="asset", project_id="prj_1")
    assert evaluate(_principal(ROLE_VIEWER), ACTION_E8_ASSET_READ, resource).decision == "ALLOW"
    assert evaluate(_principal(ROLE_VIEWER), ACTION_E8_ASSET_CREATE, resource).decision == "DENY"
    assert evaluate(_principal(ROLE_EDITOR), ACTION_E8_ASSET_GENERATE, resource).decision == "ALLOW"
    assert evaluate(_principal(ROLE_EDITOR), ACTION_E8_ASSET_IMPORT, resource).decision == "ALLOW"
    assert evaluate(_principal(ROLE_EDITOR), ACTION_E8_ASSET_APPROVE, resource).decision == "DENY"
    assert evaluate(_principal(ROLE_OWNER), ACTION_E8_ASSET_APPROVE, resource).decision == "ALLOW"
