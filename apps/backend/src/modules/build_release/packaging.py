"""交付包封装与完整性校验（E10-T09）。

规则：

- Package 必须绑定 Artifact 与清单哈希；
- 包哈希覆盖工件内容哈希、清单哈希与包版本；
- 校验失败标记 REJECTED 并拒绝交付；
- 同一 Artifact 可生成多个包版本，但不能覆盖历史。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import ArtifactHashMismatch, NotFoundError, PackageInvalid
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.models import (
    PACKAGE_CREATED,
    PACKAGE_REJECTED,
    PACKAGE_TRANSITIONS,
    PACKAGE_VERIFIED,
    PackageManifestModel,
    PackageModel,
)
from modules.build_release.repository import (
    PackageManifestRepository,
    PackageRepository,
)
from modules.build_release.service import _dump, _hash_payload, _load, _new_id


@dataclass(frozen=True, slots=True)
class PackageView:
    package_id: str
    project_id: str
    package_version: int
    artifact_id: str
    format: str
    manifest_hash: str
    package_hash: str
    storage_reference: str
    status: str
    manifest: dict[str, Any]
    created_at: datetime


def _package_view(entity: PackageModel, manifest: PackageManifestModel | None) -> PackageView:
    return PackageView(
        package_id=entity.package_id,
        project_id=entity.project_id,
        package_version=entity.package_version,
        artifact_id=entity.artifact_id,
        format=entity.format,
        manifest_hash=entity.manifest_hash,
        package_hash=entity.package_hash,
        storage_reference=entity.storage_reference,
        status=entity.status,
        manifest=_load(manifest.manifest_json, {}) if manifest is not None else {},
        created_at=entity.created_at,
    )


class PackagingService:
    """交付包封装与校验。"""

    def __init__(self, database: DatabaseService, *, artifacts: ArtifactRegistryService) -> None:
        self._database = database
        self._artifacts = artifacts

    async def create_package(
        self,
        *,
        project_id: str,
        artifact_id: str,
        format: str = "zip",
        storage_reference: str = "",
    ) -> PackageView:
        artifact = await self._artifacts.get_artifact(artifact_id)
        if artifact.project_id != project_id:
            raise PackageInvalid("制品不属于该项目", details={"artifact_id": artifact_id})
        if not artifact.files:
            raise PackageInvalid("制品缺少文件清单", details={"artifact_id": artifact_id})
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repo = PackageRepository(session)
            version = await repo.next_version(artifact_id)
            manifest = {
                "artifact_id": artifact.artifact_id,
                "artifact_version": artifact.artifact_version,
                "artifact_content_hash": artifact.content_hash,
                "format": format,
                "package_version": version,
                "files": list(artifact.files),
            }
            manifest_hash = _hash_payload(manifest)
            package_hash = _hash_payload(
                {
                    "manifest_hash": manifest_hash,
                    "artifact_content_hash": artifact.content_hash,
                    "format": format,
                    "package_version": version,
                }
            )
            entity = PackageModel(
                package_id=_new_id("pkg"),
                project_id=project_id,
                package_version=version,
                artifact_id=artifact_id,
                format=format,
                manifest_hash=manifest_hash,
                package_hash=package_hash,
                storage_reference=storage_reference,
                status=PACKAGE_CREATED,
                created_at=now,
            )
            await repo.add(entity)
            await PackageManifestRepository(session).add(
                PackageManifestModel(
                    manifest_id=_new_id("pman"),
                    package_id=entity.package_id,
                    manifest_json=_dump(manifest),
                    manifest_hash=manifest_hash,
                    created_at=now,
                )
            )
        return _package_view(
            entity,
            PackageManifestModel(
                manifest_id="",
                package_id=entity.package_id,
                manifest_json=_dump(manifest),
                manifest_hash=manifest_hash,
                created_at=now,
            ),
        )

    async def get_package(self, package_id: str) -> PackageView:
        async with self._database.session() as session:
            entity = await PackageRepository(session).get(package_id)
            if entity is None:
                raise NotFoundError("交付包不存在", details={"package_id": package_id})
            manifest = await PackageManifestRepository(session).get_for_package(package_id)
        return _package_view(entity, manifest)

    async def list_packages(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await PackageRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
            manifests = {
                item.package_id: await PackageManifestRepository(session).get_for_package(
                    item.package_id
                )
                for item in page.items
            }
        return {
            "items": [_package_view(item, manifests.get(item.package_id)) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def verify_package(self, package_id: str) -> PackageView:
        view = await self.get_package(package_id)
        artifact = await self._artifacts.get_artifact(view.artifact_id)
        manifest_hash = _hash_payload(view.manifest)
        if manifest_hash != view.manifest_hash:
            await self._mark_rejected(package_id)
            raise PackageInvalid("交付包清单哈希不一致", details={"package_id": package_id})
        if view.manifest.get("artifact_content_hash") != artifact.content_hash:
            await self._mark_rejected(package_id)
            raise ArtifactHashMismatch(
                "交付包绑定的制品内容已变化", details={"package_id": package_id}
            )
        expected_package_hash = _hash_payload(
            {
                "manifest_hash": view.manifest_hash,
                "artifact_content_hash": artifact.content_hash,
                "format": view.format,
                "package_version": view.package_version,
            }
        )
        if expected_package_hash != view.package_hash:
            await self._mark_rejected(package_id)
            raise PackageInvalid("交付包包哈希不一致", details={"package_id": package_id})
        async with self._database.session() as session, transaction(session):
            entity = await PackageRepository(session).get(package_id)
            assert entity is not None
            if PACKAGE_VERIFIED not in PACKAGE_TRANSITIONS.get(entity.status, frozenset()):
                raise PackageInvalid(
                    "交付包当前状态不可验证",
                    details={"package_id": package_id, "status": entity.status},
                )
            entity.status = PACKAGE_VERIFIED
            await session.flush()
        return await self.get_package(package_id)

    async def require_verified(self, package_id: str) -> PackageView:
        view = await self.get_package(package_id)
        if view.status != PACKAGE_VERIFIED:
            raise PackageInvalid(
                "交付包未通过校验，禁止发布",
                details={"package_id": package_id, "status": view.status},
            )
        return view

    async def _mark_rejected(self, package_id: str) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await PackageRepository(session).get(package_id)
            if entity is None:
                return
            if PACKAGE_REJECTED in PACKAGE_TRANSITIONS.get(entity.status, frozenset()):
                entity.status = PACKAGE_REJECTED
                await session.flush()
