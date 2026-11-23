"""E8-T04 Asset Brief 集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import AssetBriefInvalid, NotFoundError, VersionConflict
from modules.asset_pipeline.briefs import AssetBriefService
from modules.project_registry.service import ProjectRegistryService

IMAGE_SPEC = {
    "width": 64,
    "height": 64,
    "transparent_background": True,
    "format": "png",
    "pixel_art": True,
}


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8brief.db').as_posix()}",
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
async def test_brief_create_update_and_status(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        briefs = _service(app, "asset_brief_service", AssetBriefService)
        project = await _project(app, tmp_path, "Briefs")

        created = await briefs.create(
            project_id=project.project_id,
            title="主角待机动画",
            asset_category="IMAGE",
            visual_direction="16-bit 像素风，明亮配色",
            style_reference="res://docs/art_bible.md",
            technical_constraints=IMAGE_SPEC,
            animation_requirements={"states": ["idle", "run"], "fps": 8},
            delivery_requirements={"format": "sprite_sheet"},
            license_requirements={"commercial_use": True},
            acceptance_criteria=("主体居中", "透明背景"),
            created_by="agent:designer",
        )
        assert created.status == "DRAFT"
        assert created.version == 1
        assert created.technical_constraints["width"] == 64
        assert created.acceptance_criteria == ("主体居中", "透明背景")

        proposed = await briefs.propose(created.brief_id)
        assert proposed.status == "PROPOSED"

        updated = await briefs.update(
            created.brief_id,
            expected_version=proposed.version,
            technical_constraints={**IMAGE_SPEC, "width": 128, "height": 128},
            acceptance_criteria=("主体居中", "透明背景", "2x 缩放"),
        )
        assert updated.version == proposed.version + 1
        assert updated.technical_constraints["width"] == 128

        with pytest.raises(VersionConflict):
            await briefs.update(
                created.brief_id,
                expected_version=proposed.version,
                title="过期写入",
            )

        approved = await briefs.approve(created.brief_id)
        assert approved.status == "APPROVED"
        with pytest.raises(AssetBriefInvalid):
            await briefs.update(created.brief_id, title="批准后修改")

        spec = await briefs.generation_spec(created.brief_id)
        assert spec["technical_constraints"]["height"] == 128
        assert spec["license_requirements"] == {"commercial_use": True}

    (tmp_path / "isolated").mkdir(parents=True, exist_ok=True)
    async with _running(tmp_path / "isolated") as app:
        briefs = _service(app, "asset_brief_service", AssetBriefService)
        project = await _project(app, tmp_path / "isolated", "Other")
        await briefs.create(
            project_id=project.project_id,
            title="音效",
            asset_category="AUDIO",
            technical_constraints={
                "format": "ogg",
                "sample_rate": 44100,
                "channels": 2,
                "duration_seconds": 2,
                "usage": "sfx",
            },
        )
        listed = await briefs.list(project.project_id)
        assert listed["total"] == 1


@pytest.mark.asyncio
async def test_brief_rejects_invalid_specs_and_missing_briefs(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        briefs = _service(app, "asset_brief_service", AssetBriefService)
        project = await _project(app, tmp_path, "Validation")

        with pytest.raises(AssetBriefInvalid):
            await briefs.create(
                project_id=project.project_id,
                title="错误规格",
                asset_category="IMAGE",
                technical_constraints={"width": 64},
            )
        with pytest.raises(AssetBriefInvalid):
            await briefs.create(
                project_id=project.project_id,
                title="错误分类",
                asset_category="VIDEO",
                technical_constraints={},
            )
        with pytest.raises(NotFoundError):
            await briefs.get("brf_missing")

        created = await briefs.create(
            project_id=project.project_id,
            title="有效",
            asset_category="IMAGE",
            technical_constraints=IMAGE_SPEC,
        )
        with pytest.raises(AssetBriefInvalid):
            await briefs.transition(created.brief_id, "APPROVED")
        await briefs.propose(created.brief_id)
        rejected = await briefs.reject(created.brief_id)
        assert rejected.status == "REJECTED"
        superseded = await briefs.supersede(created.brief_id)
        assert superseded.status == "SUPERSEDED"
