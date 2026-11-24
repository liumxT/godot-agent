"""E8-M7 集成测试：资产 API、仪表盘与 Agent 工具契约。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image

from bootstrap.application import create_app
from config.settings import load_settings
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.asset_pipeline.models import (
    SOURCE_AI_GENERATED,
    STORAGE_GENERATED,
    AssetStorageObjectModel,
)
from modules.asset_pipeline.storage import AssetStorage
from modules.asset_pipeline.versioning import AssetVersionService
from modules.multi_agent.specialized import SPECIALIZED_AGENTS


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8m7.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _session(app, client) -> str:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": "admin", "client_name": "E8 M7"},
        headers={"X-Bootstrap-Token": bootstrap},
    )
    body = registered.json()
    challenge = (
        await client.post("/api/v1/auth/challenge", json={"client_id": body["client_id"]})
    ).json()
    verified = await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "client_id": body["client_id"],
            "proof": _proof(
                body["client_secret"],
                challenge["challenge_id"],
                challenge["challenge"],
            ),
        },
    )
    issued = await client.post("/api/v1/sessions", headers=_bearer(verified.json()["access_token"]))
    return issued.json()["session_token"]


async def _project(client, headers, tmp_path: Path) -> str:
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    created = await client.post(
        "/api/v1/projects",
        json={"project_root": str(root), "name": "E8 M7"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["project_id"]


def _png() -> bytes:
    image = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _seed_version(app, project_id: str, asset_id: str):
    storage = app.state.services.get("asset_storage", AssetStorage)
    versions = app.state.services.get("asset_version_service", AssetVersionService)
    database = app.state.services.get("database", DatabaseService)
    relative_path = f"{asset_id}/hero.png"
    written = storage.write_bytes(project_id, STORAGE_GENERATED, relative_path, _png())
    version = await versions.create_version(
        asset_id,
        content_hash=str(written["content_hash"]),
        source_type=SOURCE_AI_GENERATED,
        metadata={"filename": "hero.png"},
        change_reason="initial_asset",
        created_by="tester",
    )
    async with database.session() as session, transaction(session):
        session.add(
            AssetStorageObjectModel(
                object_id="asob_" + uuid4().hex[:12],
                project_id=project_id,
                asset_version_id=version.version_id,
                storage_area=STORAGE_GENERATED,
                relative_path=relative_path,
                content_hash=str(written["content_hash"]),
                size_bytes=int(written["size_bytes"]),
                mime_type="image/png",
                created_at=version.created_at,
            )
        )
    return version


@asynccontextmanager
async def _asset_fixture(tmp_path: Path):
    async with _running(tmp_path) as (app, client):
        token = await _session(app, client)
        headers = _bearer(token)
        project_id = await _project(client, headers, tmp_path)
        created = await client.post(
            f"/api/v1/projects/{project_id}/assets",
            json={
                "name": "hero",
                "category": "IMAGE",
                "asset_type": "CHARACTER",
                "tags": ["platformer", "pixel"],
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        asset = created.json()
        version = await _seed_version(app, project_id, asset["asset_id"])
        yield app, client, headers, project_id, asset, version


async def test_asset_api_browser_and_dashboard(tmp_path: Path) -> None:
    async with _asset_fixture(tmp_path) as (
        _app,
        client,
        headers,
        project_id,
        asset,
        _version,
    ):
        listed = await client.get(f"/api/v1/projects/{project_id}/assets", headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1

        fetched = await client.get(f"/api/v1/assets/{asset['asset_id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "hero"

        patched = await client.patch(
            f"/api/v1/assets/{asset['asset_id']}/metadata",
            json={"description": "pixel hero", "tags": ["pixel"]},
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["tags"] == ["pixel"]

        versions = await client.get(f"/api/v1/assets/{asset['asset_id']}/versions", headers=headers)
        assert versions.status_code == 200
        assert versions.json()["total"] == 1

        dependencies = await client.get(
            f"/api/v1/assets/{asset['asset_id']}/dependencies", headers=headers
        )
        assert dependencies.status_code == 200
        assert dependencies.json()["total"] == 0

        dashboard = await client.get(
            f"/api/v1/projects/{project_id}/assets/dashboard", headers=headers
        )
        assert dashboard.status_code == 200, dashboard.text
        body = dashboard.json()
        assert body["total"] == 1
        row = body["items"][0]
        assert row["asset_id"] == asset["asset_id"]
        assert row["version_count"] == 1
        assert row["current_version_id"] == _version.version_id
        assert row["quality_status"] is None
        assert body["unknown"]["total"] == 0


async def test_delivery_api_blocks_ungated_asset(tmp_path: Path) -> None:
    async with _asset_fixture(tmp_path) as (
        _app,
        client,
        headers,
        _project_id,
        asset,
        version,
    ):
        response = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/delivery-plans",
            json={
                "version_id": version.version_id,
                "target_path": "res://assets/hero.png",
            },
            headers=headers,
        )
        assert response.status_code in {400, 403, 409}, response.text
        assert "审核" in response.text or "来源" in response.text or "License" in response.text


async def test_management_page_renders_asset_section(tmp_path: Path) -> None:
    async with _running(tmp_path) as (_app, client):
        response = await client.get("/api/v1/manage")
        assert response.status_code == 200
        assert "资产" in response.text
        assert "assets/dashboard" in response.text


def test_art_agents_use_asset_contract_without_direct_write() -> None:
    specs = {spec.key: spec for spec in SPECIALIZED_AGENTS}
    for key in ("2d_artist", "animation_specialist"):
        spec = specs[key]
        assert any(tool.startswith("asset.") for tool in spec.required_tools)
        assert "file.write" not in spec.required_tools

    pipeline = specs["asset_pipeline_specialist"]
    assert "asset.import.request" in pipeline.required_tools
    assert "file.write" not in pipeline.required_tools
    assert any("Tool System" in rule for rule in pipeline.collaboration_rules)

    for key in ("art_director", "audio_designer", "vfx_artist", "3d_artist"):
        assert any(tool.startswith("asset.") for tool in specs[key].required_tools)
