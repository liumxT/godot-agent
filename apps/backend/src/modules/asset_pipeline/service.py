"""Asset Registry 服务（E8-T02）。

职责边界：

- Asset 是逻辑资产，元数据唯一入口；
- AssetVersion 创建后不可变（版本写入在 E8-T03 批次补齐）；
- 项目隔离：所有查询都必须带 ``project_id``；
- 软删除只更新生命周期与 ``deleted_at``，不物理删除历史版本；
- 领域事件采用 best-effort 发布，事件失败不影响已提交的元数据。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    AssetStateInvalid,
    NotFoundError,
    VersionConflict,
)
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    ASSET_ACTIVE,
    ASSET_ARCHIVED,
    ASSET_CATEGORIES,
    ASSET_DRAFT,
    ASSET_STATUSES,
    ASSET_TRANSITIONS,
    AssetModel,
)
from modules.asset_pipeline.repository import (
    AssetDependencyRepository,
    AssetRepository,
    AssetVersionRepository,
)

_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_MAX_TAGS = 32
_MAX_TAG_LENGTH = 64


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@dataclass(frozen=True, slots=True)
class AssetView:
    asset_id: str
    project_id: str
    name: str
    category: str
    asset_type: str
    description: str | None
    tags: tuple[str, ...]
    current_version_id: str | None
    lifecycle_status: str
    created_by: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


def _asset_view(entity: AssetModel) -> AssetView:
    tags = _load(entity.tags_json, [])
    return AssetView(
        asset_id=entity.asset_id,
        project_id=entity.project_id,
        name=entity.name,
        category=entity.category,
        asset_type=entity.asset_type,
        description=entity.description,
        tags=tuple(str(tag) for tag in tags),
        current_version_id=entity.current_version_id,
        lifecycle_status=entity.lifecycle_status,
        created_by=entity.created_by,
        version=entity.version,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        deleted_at=entity.deleted_at,
    )


def _validate_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    if len(tags) > _MAX_TAGS:
        raise AssetStateInvalid("标签数量超过限制", details={"limit": _MAX_TAGS})
    cleaned = tuple(sorted({tag.strip() for tag in tags if tag and tag.strip()}))
    for tag in cleaned:
        if len(tag) > _MAX_TAG_LENGTH:
            raise AssetStateInvalid(
                "标签长度超过限制", details={"tag": tag, "limit": _MAX_TAG_LENGTH}
            )
    return cleaned


def _validate_taxonomy(category: str, asset_type: str) -> None:
    if category not in ASSET_CATEGORIES:
        raise AssetStateInvalid(
            "资产分类未知",
            details={"category": category, "allowed": sorted(ASSET_CATEGORIES)},
        )
    if not _TYPE_PATTERN.match(asset_type or ""):
        raise AssetStateInvalid("资产类型格式非法", details={"asset_type": asset_type})


class AssetService:
    """资产注册中心。"""

    def __init__(self, database: DatabaseService, *, events: EventBus | None = None) -> None:
        self._database = database
        self._events = events
        self._logger = get_logger("backend.asset")

    async def create(
        self,
        *,
        project_id: str,
        name: str,
        category: str,
        asset_type: str,
        description: str | None = None,
        tags: tuple[str, ...] = (),
        created_by: str | None = None,
        lifecycle_status: str = ASSET_DRAFT,
    ) -> AssetView:
        _validate_taxonomy(category, asset_type)
        clean_name = name.strip()
        if not clean_name:
            raise AssetStateInvalid("资产名称不能为空")
        clean_tags = _validate_tags(tags)
        if lifecycle_status not in ASSET_STATUSES:
            raise AssetStateInvalid("资产生命周期状态非法", details={"status": lifecycle_status})
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repository = AssetRepository(session)
            if await repository.get_by_name(project_id, clean_name) is not None:
                raise AssetStateInvalid("同项目下资产名称已存在", details={"name": clean_name})
            entity = await repository.add(
                AssetModel(
                    asset_id=_new_id("ast_"),
                    project_id=project_id,
                    name=clean_name,
                    category=category,
                    asset_type=asset_type,
                    description=description,
                    tags_json=_dump(list(clean_tags)),
                    current_version_id=None,
                    lifecycle_status=lifecycle_status,
                    created_by=created_by,
                    version=1,
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
            )
            view = _asset_view(entity)
        await self._publish(
            "asset.created",
            {"asset_id": view.asset_id, "category": category, "asset_type": asset_type},
            project_id=project_id,
        )
        return view

    async def get(self, asset_id: str, *, include_deleted: bool = False) -> AssetView:
        async with self._database.session() as session:
            entity = await AssetRepository(session).get(asset_id)
        if entity is None or (entity.deleted_at is not None and not include_deleted):
            raise NotFoundError("资产不存在", details={"asset_id": asset_id})
        return _asset_view(entity)

    async def list(
        self,
        *,
        project_id: str,
        category: str | None = None,
        asset_type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        source_type: str | None = None,
        license_status: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await AssetRepository(session).list_page(
                project_id=project_id,
                category=category,
                asset_type=asset_type,
                status=status,
                tag=tag,
                source_type=source_type,
                license_status=license_status,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_asset_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def update_metadata(
        self,
        asset_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tags: tuple[str, ...] | None = None,
        expected_version: int | None = None,
    ) -> AssetView:
        async with self._database.session() as session:
            repository = AssetRepository(session)
            entity = await repository.get(asset_id)
            if entity is None or entity.deleted_at is not None:
                raise NotFoundError("资产不存在", details={"asset_id": asset_id})
            version = expected_version if expected_version is not None else entity.version
            if expected_version is not None and entity.version != expected_version:
                raise VersionConflict(
                    "资产版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            values: dict[str, object] = {"updated_at": utcnow()}
            if name is not None:
                clean_name = name.strip()
                if not clean_name:
                    raise AssetStateInvalid("资产名称不能为空")
                existing = await repository.get_by_name(entity.project_id, clean_name)
                if existing is not None and existing.asset_id != asset_id:
                    raise AssetStateInvalid("同项目下资产名称已存在", details={"name": clean_name})
                values["name"] = clean_name
            if description is not None:
                values["description"] = description
            if tags is not None:
                values["tags_json"] = _dump(list(_validate_tags(tags)))
            async with transaction(session):
                updated = await repository.update_metadata(
                    asset_id, expected_version=version, values=values
                )
            if not updated:
                raise VersionConflict("资产已被其他操作修改，请重新读取")
            entity = await repository.get(asset_id)
            assert entity is not None
            view = _asset_view(entity)
        await self._publish("asset.updated", {"asset_id": asset_id}, project_id=view.project_id)
        return view

    async def transition(
        self,
        asset_id: str,
        to_status: str,
        *,
        expected_version: int | None = None,
        archive: bool = False,
    ) -> AssetView:
        if to_status not in ASSET_STATUSES:
            raise AssetStateInvalid("资产生命周期状态非法", details={"status": to_status})
        async with self._database.session() as session:
            repository = AssetRepository(session)
            entity = await repository.get(asset_id)
            if entity is None:
                raise NotFoundError("资产不存在", details={"asset_id": asset_id})
            if entity.deleted_at is not None and not archive:
                raise NotFoundError("资产已删除", details={"asset_id": asset_id})
            version = expected_version if expected_version is not None else entity.version
            if expected_version is not None and entity.version != expected_version:
                raise VersionConflict(
                    "资产版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            allowed = ASSET_TRANSITIONS.get(entity.lifecycle_status, frozenset())
            if to_status not in allowed:
                raise AssetStateInvalid(
                    "资产状态迁移不合法",
                    details={"from": entity.lifecycle_status, "to": to_status},
                )
            now = utcnow()
            async with transaction(session):
                changed = await repository.transition_status(
                    asset_id,
                    from_statuses=frozenset({entity.lifecycle_status}),
                    to_status=to_status,
                    expected_version=version,
                    now=now,
                    deleted_at=now if archive or to_status == ASSET_ARCHIVED else None,
                )
            if not changed:
                raise VersionConflict("资产已被其他操作修改，请重新读取")
            entity = await repository.get(asset_id)
            assert entity is not None
            view = _asset_view(entity)
        await self._publish(
            "asset.updated",
            {"asset_id": asset_id, "lifecycle_status": to_status},
            project_id=view.project_id,
        )
        return view

    async def activate(self, asset_id: str, *, expected_version: int | None = None) -> AssetView:
        return await self.transition(asset_id, ASSET_ACTIVE, expected_version=expected_version)

    async def deprecate(self, asset_id: str, *, expected_version: int | None = None) -> AssetView:
        return await self.transition(asset_id, "DEPRECATED", expected_version=expected_version)

    async def archive(self, asset_id: str, *, expected_version: int | None = None) -> AssetView:
        return await self.transition(
            asset_id, ASSET_ARCHIVED, expected_version=expected_version, archive=True
        )

    async def set_current_version(self, asset_id: str, version_id: str) -> AssetView:
        async with self._database.session() as session:
            repository = AssetRepository(session)
            entity = await repository.get(asset_id)
            if entity is None or entity.deleted_at is not None:
                raise NotFoundError("资产不存在", details={"asset_id": asset_id})
            version_entity = await AssetVersionRepository(session).get(version_id)
            if version_entity is None or version_entity.asset_id != asset_id:
                raise AssetStateInvalid("目标版本不属于该资产", details={"version_id": version_id})
            now = utcnow()
            async with transaction(session):
                changed = await repository.set_current_version(asset_id, version_id, now)
            if not changed:
                raise VersionConflict("资产已被其他操作修改，请重新读取")
            entity = await repository.get(asset_id)
            assert entity is not None
            view = _asset_view(entity)
        await self._publish(
            "asset.version.created",
            {"asset_id": asset_id, "asset_version_id": version_id},
            project_id=view.project_id,
        )
        return view

    async def list_versions(self, asset_id: str) -> list[dict[str, Any]]:
        await self.get(asset_id)
        async with self._database.session() as session:
            rows = await AssetVersionRepository(session).list_for_asset(asset_id)
        return [
            {
                "version_id": row.version_id,
                "asset_id": row.asset_id,
                "version_number": row.version_number,
                "parent_version_id": row.parent_version_id,
                "content_hash": row.content_hash,
                "source_type": row.source_type,
                "change_reason": row.change_reason,
                "created_by": row.created_by,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def duplicates(self, project_id: str) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            return await AssetRepository(session).duplicate_hashes(project_id)

    async def orphans(self, project_id: str) -> list[str]:
        async with self._database.session() as session:
            return await AssetRepository(session).orphan_asset_ids(project_id)

    async def references(self, asset_id: str) -> list[dict[str, Any]]:
        asset = await self.get(asset_id)
        if asset.current_version_id is None:
            return []
        async with self._database.session() as session:
            rows = await AssetDependencyRepository(session).list_for_version(
                asset.current_version_id
            )
        return [
            {
                "dependency_id": row.dependency_id,
                "source_type": row.source_type,
                "source_reference": row.source_reference,
                "target_type": row.target_type,
                "target_reference": row.target_reference,
                "dependency_type": row.dependency_type,
            }
            for row in rows
        ]

    async def _publish(self, event_type: str, payload: dict[str, Any], *, project_id: str) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(Event.create(event_type, payload, project_id=project_id))
        except Exception:  # noqa: BLE001 - 事件失败不回滚已提交元数据
            log_event(
                self._logger,
                logging.WARNING,
                "asset_event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )
