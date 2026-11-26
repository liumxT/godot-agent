"""不可变构建制品登记（E10-T08）。

规则：

- Artifact 内容不可变；内容变化必须生成新版本与新 Hash；
- 同一构建下按 ``artifact_version`` 递增，不覆盖旧记录；
- 验证状态可在状态机允许范围内迁移，但不改变内容哈希；
- 完整性校验通过重新计算清单哈希实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import (
    ArtifactHashMismatch,
    ArtifactImmutable,
    ArtifactVerificationInvalid,
    BuildStateInvalid,
    NotFoundError,
    ValidationFailed,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.models import (
    ARTIFACT_REGISTERED,
    ARTIFACT_STATUSES,
    ARTIFACT_TRANSITIONS,
    ARTIFACT_VERIFIED,
    ARTIFACT_VERIFYING,
    ArtifactManifestModel,
    ArtifactModel,
)
from modules.build_release.repository import (
    ArtifactManifestRepository,
    ArtifactRepository,
)
from modules.build_release.service import _dump, _hash_payload, _load, _new_id


@dataclass(frozen=True, slots=True)
class ArtifactView:
    artifact_id: str
    project_id: str
    build_id: str | None
    attempt_id: str | None
    artifact_version: int
    name: str
    platform: str
    architecture: str
    format: str
    file_size: int
    content_hash: str
    storage_reference: str
    verification_status: str
    manifest_hash: str
    files: tuple[dict[str, Any], ...]
    created_at: datetime


def _artifact_view(entity: ArtifactModel, manifest: ArtifactManifestModel | None) -> ArtifactView:
    return ArtifactView(
        artifact_id=entity.artifact_id,
        project_id=entity.project_id,
        build_id=entity.build_id,
        attempt_id=entity.attempt_id,
        artifact_version=entity.artifact_version,
        name=entity.name,
        platform=entity.platform,
        architecture=entity.architecture,
        format=entity.format,
        file_size=entity.file_size,
        content_hash=entity.content_hash,
        storage_reference=entity.storage_reference,
        verification_status=entity.verification_status,
        manifest_hash=manifest.manifest_hash if manifest is not None else "",
        files=tuple(_load(manifest.manifest_json, [])) if manifest is not None else (),
        created_at=entity.created_at,
    )


def normalize_files(
    files: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """规范化并校验制品文件清单。"""

    normalized: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValidationFailed("制品清单条目必须是对象")
        path = str(entry.get("path", "")).strip()
        if not path:
            raise ValidationFailed("制品清单条目缺少 path")
        try:
            size = int(entry.get("size", 0))
        except TypeError, ValueError:
            raise ValidationFailed("制品清单 size 非法", details={"path": path}) from None
        if size < 0:
            raise ValidationFailed("制品清单 size 不能为负", details={"path": path})
        digest = str(entry.get("hash", ""))
        normalized.append({"path": path, "size": size, "hash": digest})
    if not normalized:
        raise ValidationFailed("制品清单不能为空")
    normalized.sort(key=lambda item: item["path"])
    return normalized


def compute_content_hash(files: list[dict[str, Any]]) -> str:
    return _hash_payload({"files": files})


class ArtifactRegistryService:
    """不可变制品的唯一登记入口。"""

    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def register_artifact(
        self,
        *,
        project_id: str,
        platform: str,
        architecture: str,
        storage_reference: str,
        files: list[dict[str, Any]],
        build_id: str | None = None,
        attempt_id: str | None = None,
        name: str = "",
        format: str = "",
    ) -> ArtifactView:
        if not project_id:
            raise ValidationFailed("project_id 不能为空")
        if not platform or not architecture:
            raise ValidationFailed("platform / architecture 不能为空")
        if not storage_reference:
            raise ValidationFailed("storage_reference 不能为空")
        normalized = normalize_files(files)
        content_hash = compute_content_hash(normalized)
        manifest_hash = _hash_payload({"files": normalized})
        file_size = sum(item["size"] for item in normalized)
        now = utcnow()

        async with self._database.session() as session, transaction(session):
            repo = ArtifactRepository(session)
            existing_rows = (
                await repo.list_for_build(build_id)
                if build_id
                else await repo.list_for_project(project_id)
            )
            for existing in existing_rows:
                if existing.content_hash == content_hash:
                    manifest = await ArtifactManifestRepository(session).get_for_artifact(
                        existing.artifact_id
                    )
                    return _artifact_view(existing, manifest)
            version = await repo.next_version(project_id, build_id)
            entity = ArtifactModel(
                artifact_id=_new_id("art"),
                project_id=project_id,
                build_id=build_id,
                attempt_id=attempt_id,
                artifact_version=version,
                name=name,
                platform=platform,
                architecture=architecture,
                format=format,
                file_size=file_size,
                content_hash=content_hash,
                storage_reference=storage_reference,
                verification_status=ARTIFACT_REGISTERED,
                created_at=now,
            )
            await repo.add(entity)
            await ArtifactManifestRepository(session).add(
                ArtifactManifestModel(
                    manifest_id=_new_id("aman"),
                    artifact_id=entity.artifact_id,
                    manifest_json=_dump(normalized),
                    manifest_hash=manifest_hash,
                    created_at=now,
                )
            )
        return _artifact_view(
            entity,
            ArtifactManifestModel(
                manifest_id="",
                artifact_id=entity.artifact_id,
                manifest_json=_dump(normalized),
                manifest_hash=manifest_hash,
                created_at=now,
            ),
        )

    async def get_artifact(self, artifact_id: str) -> ArtifactView:
        async with self._database.session() as session:
            entity = await ArtifactRepository(session).get(artifact_id)
            if entity is None:
                raise NotFoundError("制品不存在", details={"artifact_id": artifact_id})
            manifest = await ArtifactManifestRepository(session).get_for_artifact(artifact_id)
        return _artifact_view(entity, manifest)

    async def list_artifacts(
        self,
        project_id: str,
        *,
        platform: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in ARTIFACT_STATUSES:
            raise ValidationFailed("未知制品状态", details={"status": status})
        async with self._database.session() as session:
            page = await ArtifactRepository(session).list_page(
                project_id=project_id,
                platform=platform,
                status=status,
                limit=limit,
                offset=offset,
            )
            manifests = {
                item.artifact_id: await ArtifactManifestRepository(session).get_for_artifact(
                    item.artifact_id
                )
                for item in page.items
            }
        return {
            "items": [_artifact_view(item, manifests.get(item.artifact_id)) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def list_build_artifacts(self, build_id: str) -> list[ArtifactView]:
        async with self._database.session() as session:
            rows = await ArtifactRepository(session).list_for_build(build_id)
            manifests = {
                item.artifact_id: await ArtifactManifestRepository(session).get_for_artifact(
                    item.artifact_id
                )
                for item in rows
            }
        return [_artifact_view(item, manifests.get(item.artifact_id)) for item in rows]

    async def transition_verification(
        self, artifact_id: str, target: str, *, reason: str = ""
    ) -> ArtifactView:
        if target not in ARTIFACT_STATUSES:
            raise ArtifactVerificationInvalid("未知制品验证状态", details={"status": target})
        async with self._database.session() as session, transaction(session):
            repo = ArtifactRepository(session)
            entity = await repo.get(artifact_id)
            if entity is None:
                raise NotFoundError("制品不存在", details={"artifact_id": artifact_id})
            if target not in ARTIFACT_TRANSITIONS.get(entity.verification_status, frozenset()):
                raise BuildStateInvalid(
                    "制品验证状态迁移非法",
                    details={"from": entity.verification_status, "to": target, "reason": reason},
                )
            entity.verification_status = target
            await session.flush()
        return await self.get_artifact(artifact_id)

    async def mark_verified(self, artifact_id: str) -> ArtifactView:
        current = await self.get_artifact(artifact_id)
        if current.verification_status == ARTIFACT_VERIFIED:
            return current
        if current.verification_status == ARTIFACT_REGISTERED:
            await self.transition_verification(artifact_id, ARTIFACT_VERIFYING)
        return await self.transition_verification(artifact_id, ARTIFACT_VERIFIED)

    async def assert_content_unchanged(self, artifact_id: str, files: list[dict[str, Any]]) -> None:
        current = await self.get_artifact(artifact_id)
        normalized = normalize_files(files)
        if compute_content_hash(normalized) != current.content_hash:
            raise ArtifactHashMismatch(
                "制品内容与登记哈希不一致，必须生成新版本",
                details={"artifact_id": artifact_id},
            )
        raise ArtifactImmutable(
            "已注册制品不可原地修改",
            details={"artifact_id": artifact_id, "content_hash": current.content_hash},
        )

    async def verify_integrity(self, artifact_id: str, files: list[dict[str, Any]]) -> bool:
        current = await self.get_artifact(artifact_id)
        normalized = normalize_files(files)
        if compute_content_hash(normalized) != current.content_hash:
            raise ArtifactHashMismatch(
                "制品完整性校验失败",
                details={"artifact_id": artifact_id, "expected": current.content_hash},
            )
        return True

    async def require_verified(self, artifact_id: str) -> ArtifactView:
        artifact = await self.get_artifact(artifact_id)
        if artifact.verification_status != ARTIFACT_VERIFIED:
            raise ArtifactVerificationInvalid(
                "制品未通过验证，禁止进入打包或发布",
                details={
                    "artifact_id": artifact_id,
                    "status": artifact.verification_status,
                },
            )
        return artifact
