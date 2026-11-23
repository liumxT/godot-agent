"""E8-T01 / T02 资产注册中心集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AssetStateInvalid, NotFoundError, VersionConflict
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.asset_pipeline.models import (
    ASSET_ACTIVE,
    ASSET_ARCHIVED,
    ASSET_DRAFT,
    LICENSE_UNKNOWN,
    LICENSE_VERIFIED,
    AssetDependencyModel,
    AssetLicenseModel,
    AssetVersionModel,
)
from modules.asset_pipeline.repository import (
    AssetDependencyRepository,
    AssetLicenseRepository,
    AssetVersionRepository,
)
from modules.asset_pipeline.service import AssetService
from modules.project_registry.service import ProjectRegistryService

HASH_A = "a" * 64
HASH_B = "b" * 64


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8registry.db').as_posix()}",
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


async def _add_version(app, asset_id: str, number: int, content_hash: str) -> dict[str, str]:
    database = _service(app, "database", DatabaseService)
    version_id = f"asv_{asset_id[-6:]}{number:04d}"
    async with database.session() as session:
        await AssetVersionRepository(session).add(
            AssetVersionModel(
                version_id=version_id,
                asset_id=asset_id,
                version_number=number,
                parent_version_id=None,
                content_hash=content_hash,
                metadata_json="{}",
                source_type="AI_GENERATED",
                change_reason="test",
                provenance_id=None,
                created_by="agent:artist",
                created_at=utcnow(),
            )
        )
        await session.commit()
    return {"version_id": version_id, "asset_id": asset_id}


@pytest.mark.asyncio
async def test_asset_registry_create_list_and_lifecycle(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        assets = _service(app, "asset_service", AssetService)
        project = await _project(app, tmp_path, "Registry")
        created = await assets.create(
            project_id=project.project_id,
            name="hero_idle",
            category="IMAGE",
            asset_type="CHARACTER",
            description="待机动画",
            tags=("hero", "idle", "hero"),
            created_by="agent:artist",
        )
        assert created.asset_id.startswith("ast_")
        assert created.lifecycle_status == ASSET_DRAFT
        assert created.tags == ("hero", "idle")

        activated = await assets.activate(created.asset_id)
        assert activated.lifecycle_status == ASSET_ACTIVE
        assert activated.version == created.version + 1

        updated = await assets.update_metadata(
            created.asset_id, description="主角待机", expected_version=activated.version
        )
        assert updated.description == "主角待机"
        assert updated.version == activated.version + 1

        with pytest.raises(VersionConflict):
            await assets.update_metadata(
                created.asset_id, description="过期写入", expected_version=activated.version
            )

        page = await assets.list(project_id=project.project_id, category="IMAGE")
        assert page["total"] == 1
        assert page["items"][0].asset_id == created.asset_id

        deprecated = await assets.deprecate(created.asset_id)
        assert deprecated.lifecycle_status == "DEPRECATED"
        archived = await assets.archive(created.asset_id)
        assert archived.lifecycle_status == ASSET_ARCHIVED
        with pytest.raises(NotFoundError):
            await assets.activate(created.asset_id)
        with pytest.raises(NotFoundError):
            await assets.get(created.asset_id)


@pytest.mark.asyncio
async def test_asset_registry_validation_and_project_isolation(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        assets = _service(app, "asset_service", AssetService)
        first = await _project(app, tmp_path, "First")
        second = await _project(app, tmp_path, "Second")

        with pytest.raises(AssetStateInvalid):
            await assets.create(
                project_id=first.project_id,
                name="bad",
                category="VIDEO",
                asset_type="CHARACTER",
            )
        with pytest.raises(AssetStateInvalid):
            await assets.create(
                project_id=first.project_id,
                name="bad",
                category="IMAGE",
                asset_type="lower case",
            )

        await assets.create(
            project_id=first.project_id, name="hero", category="IMAGE", asset_type="CHARACTER"
        )
        with pytest.raises(AssetStateInvalid):
            await assets.create(
                project_id=first.project_id,
                name="hero",
                category="IMAGE",
                asset_type="CHARACTER",
            )
        await assets.create(
            project_id=second.project_id, name="hero", category="IMAGE", asset_type="ENEMY"
        )

        first_page = await assets.list(project_id=first.project_id)
        second_page = await assets.list(project_id=second.project_id)
        assert first_page["total"] == 1
        assert second_page["total"] == 1
        assert first_page["items"][0].project_id == first.project_id


@pytest.mark.asyncio
async def test_asset_registry_filters_duplicates_and_orphans(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        assets = _service(app, "asset_service", AssetService)
        database = _service(app, "database", DatabaseService)
        project = await _project(app, tmp_path, "Filters")

        first = await assets.create(
            project_id=project.project_id,
            name="hero",
            category="IMAGE",
            asset_type="CHARACTER",
            tags=("hero",),
        )
        second = await assets.create(
            project_id=project.project_id,
            name="hero_run",
            category="IMAGE",
            asset_type="CHARACTER",
            tags=("hero", "run"),
        )
        first_version = await _add_version(app, first.asset_id, 1, HASH_A)
        await _add_version(app, second.asset_id, 1, HASH_A)
        third_version = await _add_version(app, second.asset_id, 2, HASH_B)
        await assets.set_current_version(first.asset_id, first_version["version_id"])
        await assets.set_current_version(second.asset_id, third_version["version_id"])

        async with database.session() as session:
            await AssetLicenseRepository(session).add(
                AssetLicenseModel(
                    license_id="lic_001",
                    asset_id=first.asset_id,
                    asset_version_id=first_version["version_id"],
                    license_name="AI-Generated",
                    license_family="provider_terms",
                    source_type="AI_GENERATED",
                    source_reference=None,
                    commercial_use=True,
                    modification_allowed=True,
                    redistribution_allowed=True,
                    attribution_required=False,
                    attribution_text=None,
                    expiration_policy=None,
                    expiration_at=None,
                    territory=None,
                    evidence_reference="evidence://1",
                    verification_method="MANUAL",
                    verification_status=LICENSE_VERIFIED,
                    reviewer_id="user:lead",
                    reviewed_at=utcnow(),
                    created_at=utcnow(),
                )
            )
            await AssetDependencyRepository(session).add(
                AssetDependencyModel(
                    dependency_id="dep_001",
                    project_id=project.project_id,
                    asset_version_id=third_version["version_id"],
                    source_type="SCENE",
                    source_reference="res://scenes/main.tscn",
                    target_type="ASSET",
                    target_reference="res://assets/characters/hero.png",
                    dependency_type="DIRECT_REFERENCE",
                    metadata_json="{}",
                    created_at=utcnow(),
                )
            )
            await session.commit()

        by_tag = await assets.list(project_id=project.project_id, tag="run")
        assert [item.name for item in by_tag["items"]] == ["hero_run"]

        by_source = await assets.list(project_id=project.project_id, source_type="AI_GENERATED")
        assert by_source["total"] == 2

        by_license = await assets.list(
            project_id=project.project_id, license_status=LICENSE_VERIFIED
        )
        assert [item.asset_id for item in by_license["items"]] == [first.asset_id]
        by_unknown_license = await assets.list(
            project_id=project.project_id, license_status=LICENSE_UNKNOWN
        )
        assert by_unknown_license["total"] == 0

        duplicates = await assets.duplicates(project.project_id)
        assert duplicates == [{"content_hash": HASH_A, "asset_count": 2}]

        orphans = await assets.orphans(project.project_id)
        assert first.asset_id in orphans
        assert second.asset_id not in orphans

        references = await assets.references(second.asset_id)
        assert references[0]["source_reference"] == "res://scenes/main.tscn"

        versions = await assets.list_versions(second.asset_id)
        assert [item["version_number"] for item in versions] == [1, 2]


@pytest.mark.asyncio
async def test_asset_versions_of_other_asset_rejected(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        assets = _service(app, "asset_service", AssetService)
        project = await _project(app, tmp_path, "Versions")
        first = await assets.create(
            project_id=project.project_id, name="a", category="IMAGE", asset_type="CHARACTER"
        )
        second = await assets.create(
            project_id=project.project_id, name="b", category="IMAGE", asset_type="CHARACTER"
        )
        version = await _add_version(app, second.asset_id, 1, HASH_A)
        with pytest.raises(AssetStateInvalid):
            await assets.set_current_version(first.asset_id, version["version_id"])
