"""资产版本管理（E8-T03）。

规则：

- AssetVersion 创建后内容不可变；任何内容变化都创建新版本；
- 每个版本必须保存 ``content_hash`` 与来源类型；
- 版本通过 ``parent_version_id`` 形成关系链；
- 回滚只切换 ``Asset.current_version_id``，不改写历史版本；
- 重复提交相同内容与来源时返回已有版本（幂等），不产生重复版本。
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
    SOURCE_TYPES,
    AssetVariantModel,
    AssetVersionModel,
)
from modules.asset_pipeline.repository import (
    AssetRepository,
    AssetVariantRepository,
    AssetVersionRepository,
)

_HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_VARIANT_TYPES = frozenset({"ANIMATION", "RESOLUTION", "FORMAT", "IMPORT_CONFIG", "PLATFORM"})


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@dataclass(frozen=True, slots=True)
class AssetVersionView:
    version_id: str
    asset_id: str
    version_number: int
    parent_version_id: str | None
    content_hash: str
    metadata: dict[str, Any]
    source_type: str
    change_reason: str | None
    provenance_id: str | None
    created_by: str | None
    created_at: datetime
    created: bool = True


def _version_view(entity: AssetVersionModel, *, created: bool = True) -> AssetVersionView:
    return AssetVersionView(
        version_id=entity.version_id,
        asset_id=entity.asset_id,
        version_number=entity.version_number,
        parent_version_id=entity.parent_version_id,
        content_hash=entity.content_hash,
        metadata=_load(entity.metadata_json, {}),
        source_type=entity.source_type,
        change_reason=entity.change_reason,
        provenance_id=entity.provenance_id,
        created_by=entity.created_by,
        created_at=entity.created_at,
        created=created,
    )


@dataclass(frozen=True, slots=True)
class AssetVariantView:
    variant_id: str
    asset_id: str
    asset_version_id: str | None
    name: str
    variant_type: str
    variant_key: str
    metadata: dict[str, Any]
    created_at: datetime


def _variant_view(entity: AssetVariantModel) -> AssetVariantView:
    return AssetVariantView(
        variant_id=entity.variant_id,
        asset_id=entity.asset_id,
        asset_version_id=entity.asset_version_id,
        name=entity.name,
        variant_type=entity.variant_type,
        variant_key=entity.variant_key,
        metadata=_load(entity.metadata_json, {}),
        created_at=entity.created_at,
    )


def _validate_hash(content_hash: str) -> str:
    normalized = (content_hash or "").strip().lower()
    if not _HASH_PATTERN.match(normalized):
        raise AssetStateInvalid(
            "内容 Hash 必须是 64 位十六进制", details={"content_hash": content_hash}
        )
    return normalized


class AssetVersionService:
    """不可变版本与变体管理。"""

    def __init__(self, database: DatabaseService, *, events: EventBus | None = None) -> None:
        self._database = database
        self._events = events
        self._logger = get_logger("backend.asset")

    async def create_version(
        self,
        asset_id: str,
        *,
        content_hash: str,
        source_type: str,
        metadata: dict[str, Any] | None = None,
        change_reason: str | None = None,
        parent_version_id: str | None = None,
        provenance_id: str | None = None,
        created_by: str | None = None,
        make_current: bool = True,
    ) -> AssetVersionView:
        digest = _validate_hash(content_hash)
        if source_type not in SOURCE_TYPES:
            raise AssetStateInvalid("来源类型非法", details={"source_type": source_type})
        metadata = metadata or {}
        if not isinstance(metadata, dict):
            raise AssetStateInvalid("版本元数据必须是对象")

        async with self._database.session() as session, transaction(session):
            assets = AssetRepository(session)
            asset = await assets.get(asset_id)
            if asset is None or asset.deleted_at is not None:
                raise NotFoundError("资产不存在", details={"asset_id": asset_id})
            versions = AssetVersionRepository(session)
            latest = await versions.latest(asset_id)
            if parent_version_id is not None:
                parent = await versions.get(parent_version_id)
                if parent is None or parent.asset_id != asset_id:
                    raise AssetStateInvalid(
                        "父版本不属于该资产", details={"parent_version_id": parent_version_id}
                    )
            if latest is not None:
                same_content = (
                    latest.content_hash == digest
                    and latest.source_type == source_type
                    and latest.change_reason == change_reason
                    and latest.parent_version_id == (parent_version_id or latest.parent_version_id)
                    and _load(latest.metadata_json, {}) == metadata
                )
                if same_content:
                    return _version_view(latest, created=False)
            version = await versions.add(
                AssetVersionModel(
                    version_id="asv_" + uuid4().hex[:12],
                    asset_id=asset_id,
                    version_number=(latest.version_number if latest else 0) + 1,
                    parent_version_id=parent_version_id
                    if parent_version_id is not None
                    else (latest.version_id if latest else None),
                    content_hash=digest,
                    metadata_json=_dump(metadata),
                    source_type=source_type,
                    change_reason=change_reason,
                    provenance_id=provenance_id,
                    created_by=created_by,
                    created_at=utcnow(),
                )
            )
            view = _version_view(version)
            if make_current:
                await assets.set_current_version(asset_id, view.version_id, utcnow())
            project_id = asset.project_id
        await self._publish(
            "asset.version.created",
            {
                "asset_id": asset_id,
                "asset_version_id": view.version_id,
                "version_number": view.version_number,
                "source_type": source_type,
            },
            project_id=project_id,
        )
        return view

    async def get_version(self, asset_id: str, version_id: str) -> AssetVersionView:
        async with self._database.session() as session:
            versions = AssetVersionRepository(session)
            entity = await versions.get(version_id)
            if entity is None or entity.asset_id != asset_id:
                raise NotFoundError(
                    "资产版本不存在", details={"asset_id": asset_id, "version_id": version_id}
                )
        return _version_view(entity, created=False)

    async def compare_versions(
        self, asset_id: str, left_version_id: str, right_version_id: str
    ) -> dict[str, Any]:
        left = await self.get_version(asset_id, left_version_id)
        right = await self.get_version(asset_id, right_version_id)
        left_keys = set(left.metadata)
        right_keys = set(right.metadata)
        return {
            "asset_id": asset_id,
            "left": {"version_id": left.version_id, "version_number": left.version_number},
            "right": {"version_id": right.version_id, "version_number": right.version_number},
            "content_hash_equal": left.content_hash == right.content_hash,
            "source_type_equal": left.source_type == right.source_type,
            "metadata_added": sorted(right_keys - left_keys),
            "metadata_removed": sorted(left_keys - right_keys),
            "metadata_changed": sorted(
                key for key in left_keys & right_keys if left.metadata[key] != right.metadata[key]
            ),
        }

    async def rollback(
        self,
        asset_id: str,
        target_version_id: str,
        *,
        expected_version: int | None = None,
        reason: str | None = None,
        operator_id: str | None = None,
    ) -> AssetVersionView:
        """回滚 = 切换当前版本引用；不修改任何历史版本。"""

        async with self._database.session() as session, transaction(session):
            assets = AssetRepository(session)
            asset = await assets.get(asset_id)
            if asset is None or asset.deleted_at is not None:
                raise NotFoundError("资产不存在", details={"asset_id": asset_id})
            if expected_version is not None and asset.version != expected_version:
                raise VersionConflict(
                    "资产版本已变化",
                    details={"expected": expected_version, "actual": asset.version},
                )
            versions = AssetVersionRepository(session)
            target = await versions.get(target_version_id)
            if target is None or target.asset_id != asset_id:
                raise NotFoundError(
                    "目标版本不属于该资产",
                    details={"asset_id": asset_id, "version_id": target_version_id},
                )
            if asset.current_version_id == target_version_id:
                raise AssetStateInvalid(
                    "目标版本已是当前版本", details={"version_id": target_version_id}
                )
            previous = asset.current_version_id
            await assets.set_current_version(asset_id, target_version_id, utcnow())
            view = _version_view(target, created=False)
            project_id = asset.project_id
        await self._publish(
            "asset.version.rolled_back",
            {
                "asset_id": asset_id,
                "asset_version_id": target_version_id,
                "previous_version_id": previous,
                "reason": reason,
                "operator_id": operator_id,
            },
            project_id=project_id,
        )
        return view

    async def create_variant(
        self,
        asset_id: str,
        *,
        name: str,
        variant_type: str,
        variant_key: str,
        asset_version_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssetVariantView:
        if variant_type not in _VARIANT_TYPES:
            raise AssetStateInvalid(
                "变体类型非法",
                details={"variant_type": variant_type, "allowed": sorted(_VARIANT_TYPES)},
            )
        clean_key = variant_key.strip()
        if not clean_key:
            raise AssetStateInvalid("变体标识不能为空")
        async with self._database.session() as session, transaction(session):
            asset = await AssetRepository(session).get(asset_id)
            if asset is None or asset.deleted_at is not None:
                raise NotFoundError("资产不存在", details={"asset_id": asset_id})
            if asset_version_id is not None:
                version = await AssetVersionRepository(session).get(asset_version_id)
                if version is None or version.asset_id != asset_id:
                    raise AssetStateInvalid(
                        "变体版本不属于该资产", details={"asset_version_id": asset_version_id}
                    )
            variants = AssetVariantRepository(session)
            if await variants.get_by_key(asset_id, variant_type, clean_key) is not None:
                raise AssetStateInvalid(
                    "变体已存在",
                    details={
                        "asset_id": asset_id,
                        "variant_type": variant_type,
                        "variant_key": clean_key,
                    },
                )
            entity = await variants.add(
                AssetVariantModel(
                    variant_id="avr_" + uuid4().hex[:12],
                    asset_id=asset_id,
                    asset_version_id=asset_version_id,
                    name=name.strip() or clean_key,
                    variant_type=variant_type,
                    variant_key=clean_key,
                    metadata_json=_dump(metadata or {}),
                    created_at=utcnow(),
                )
            )
            view = _variant_view(entity)
            project_id = asset.project_id
        await self._publish(
            "asset.updated",
            {"asset_id": asset_id, "variant_id": view.variant_id},
            project_id=project_id,
        )
        return view

    async def set_variant_version(
        self, asset_id: str, variant_id: str, asset_version_id: str
    ) -> AssetVariantView:
        async with self._database.session() as session, transaction(session):
            versions = AssetVersionRepository(session)
            version = await versions.get(asset_version_id)
            if version is None or version.asset_id != asset_id:
                raise AssetStateInvalid(
                    "变体版本不属于该资产", details={"asset_version_id": asset_version_id}
                )
            variants = AssetVariantRepository(session)
            entity = await variants.get(variant_id)
            if entity is None or entity.asset_id != asset_id:
                raise NotFoundError("变体不存在", details={"variant_id": variant_id})
            entity.asset_version_id = asset_version_id
            await session.flush()
            view = _variant_view(entity)
        return view

    async def list_variants(self, asset_id: str) -> list[AssetVariantView]:
        async with self._database.session() as session:
            rows = await AssetVariantRepository(session).list_for_asset(asset_id)
        return [_variant_view(row) for row in rows]

    async def _publish(self, event_type: str, payload: dict[str, Any], *, project_id: str) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(Event.create(event_type, payload, project_id=project_id))
        except Exception:  # noqa: BLE001 - 事件失败不回滚已提交版本
            log_event(
                self._logger,
                logging.WARNING,
                "asset_event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )
