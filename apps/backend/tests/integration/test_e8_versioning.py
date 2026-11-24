"""E8-T03 资产版本与变体集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AssetStateInvalid, NotFoundError, VersionConflict
from modules.asset_pipeline.service import AssetService
from modules.asset_pipeline.versioning import AssetVersionService
from modules.project_registry.service import ProjectRegistryService

HASH_A = "a" * 64
HASH_B = "b" * 64


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8version.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _project(app, tmp_path: Path, name: str):
    registry = _service(app, "project_registry_service", ProjectRegistryService)
    root = tmp_path / name.lower().replace(" ", "_")
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    return await registry.register(project_root=str(root), name=name)


@pytest.mark.asyncio
async def test_version_creation_is_immutable_and_idempotent(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        assets = _service(app, "asset_service", AssetService)
        versions = _service(app, "asset_version_service", AssetVersionService)
        project = await _project(app, tmp_path, "Versioning")
        asset = await assets.create(
            project_id=project.project_id, name="hero", category="IMAGE", asset_type="CHARACTER"
        )

        first = await versions.create_version(
            asset.asset_id,
            content_hash=HASH_A,
            source_type="AI_GENERATED",
            metadata={"format": "png", "width": 64},
            change_reason="initial",
            created_by="agent:artist",
        )
        assert first.created is True
        assert first.version_number == 1
        assert first.parent_version_id is None
        current = await assets.get(asset.asset_id)
        assert current.current_version_id == first.version_id
        assert current.version == asset.version + 1

        duplicate = await versions.create_version(
            asset.asset_id,
            content_hash=HASH_A,
            source_type="AI_GENERATED",
            metadata={"format": "png", "width": 64},
            change_reason="initial",
        )
        assert duplicate.created is False
        assert duplicate.version_id == first.version_id
        assert len(await assets.list_versions(asset.asset_id)) == 1

        second = await versions.create_version(
            asset.asset_id,
            content_hash=HASH_B,
            source_type="AI_GENERATED",
            metadata={"format": "png", "width": 128, "height": 128},
            change_reason="higher resolution",
        )
        assert second.version_number == 2
        assert second.parent_version_id == first.version_id

        comparison = await versions.compare_versions(
            asset.asset_id, first.version_id, second.version_id
        )
        assert comparison["content_hash_equal"] is False
        assert comparison["metadata_added"] == ["height"]
        assert comparison["metadata_changed"] == ["width"]

        rolled_back = await versions.rollback(
            asset.asset_id,
            first.version_id,
            expected_version=(await assets.get(asset.asset_id)).version,
            reason="rollback to v1",
            operator_id="user:lead",
        )
        assert rolled_back.version_id == first.version_id
        restored = await assets.get(asset.asset_id)
        assert restored.current_version_id == first.version_id
        with pytest.raises(AssetStateInvalid):
            await versions.rollback(asset.asset_id, first.version_id)
        with pytest.raises(VersionConflict):
            await versions.rollback(
                asset.asset_id, second.version_id, expected_version=current.version
            )


@pytest.mark.asyncio
async def test_version_validation_and_cross_asset_isolation(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        assets = _service(app, "asset_service", AssetService)
        versions = _service(app, "asset_version_service", AssetVersionService)
        project = await _project(app, tmp_path, "Isolation")
        first = await assets.create(
            project_id=project.project_id, name="a", category="IMAGE", asset_type="CHARACTER"
        )
        second = await assets.create(
            project_id=project.project_id, name="b", category="IMAGE", asset_type="CHARACTER"
        )

        with pytest.raises(AssetStateInvalid):
            await versions.create_version(
                first.asset_id, content_hash="not-a-hash", source_type="AI_GENERATED"
            )
        with pytest.raises(AssetStateInvalid):
            await versions.create_version(first.asset_id, content_hash=HASH_A, source_type="MAGIC")

        first_version = await versions.create_version(
            first.asset_id, content_hash=HASH_A, source_type="AI_GENERATED"
        )
        second_version = await versions.create_version(
            second.asset_id, content_hash=HASH_B, source_type="USER_CREATED"
        )
        with pytest.raises(NotFoundError):
            await versions.get_version(first.asset_id, second_version.version_id)
        with pytest.raises(NotFoundError):
            await versions.rollback(first.asset_id, second_version.version_id)
        with pytest.raises(AssetStateInvalid):
            await versions.create_version(
                first.asset_id,
                content_hash=HASH_B,
                source_type="AI_GENERATED",
                parent_version_id=second_version.version_id,
            )

        await assets.archive(first.asset_id)
        with pytest.raises(NotFoundError):
            await versions.create_version(
                first.asset_id, content_hash=HASH_B, source_type="AI_GENERATED"
            )
        assert first_version.version_id


@pytest.mark.asyncio
async def test_variants_link_versions(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        assets = _service(app, "asset_service", AssetService)
        versions = _service(app, "asset_version_service", AssetVersionService)
        project = await _project(app, tmp_path, "Variants")
        asset = await assets.create(
            project_id=project.project_id, name="hero", category="IMAGE", asset_type="CHARACTER"
        )
        version = await versions.create_version(
            asset.asset_id, content_hash=HASH_A, source_type="AI_GENERATED"
        )

        idle = await versions.create_variant(
            asset.asset_id, name="idle", variant_type="ANIMATION", variant_key="idle"
        )
        contaminated = await versions.create_variant(
            asset.asset_id, name="run", variant_type="ANIMATION", variant_key="run"
        )
        with pytest.raises(AssetStateInvalid):
            await versions.create_variant(
                asset.asset_id, name="idle2", variant_type="ANIMATION", variant_key="idle"
            )
        with pytest.raises(AssetStateInvalid):
            await versions.create_variant(
                asset.asset_id, name="bad", variant_type="UNKNOWN", variant_key="bad"
            )

        updated = await versions.set_variant_version(
            asset.asset_id, contaminated.variant_id, version.version_id
        )
        assert updated.asset_version_id == version.version_id
        listed = await versions.list_variants(asset.asset_id)
        assert [item.variant_key for item in listed] == ["idle", "run"]
        assert idle.asset_version_id is None
