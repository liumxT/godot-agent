"""资产依赖与引用关系图（E8-T14）。

职责：

- 记录资产版本与 Scene / Script / Texture 等资源之间的引用关系；
- 查询资产被哪些资源引用、孤儿资产、失效引用、循环依赖；
- 版本替换与删除前的影响分析，但不直接修改项目文件。

替换资产版本时必须走“引用分析 → ChangeSet → 审批 → Resource Lock → Tool System”
链路，本模块只提供分析结果。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import AssetDependencyInvalid, NotFoundError
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    DEPENDENCY_TYPES,
    AssetDependencyModel,
)
from modules.asset_pipeline.repository import (
    AssetDependencyRepository,
    AssetRepository,
    AssetStorageObjectRepository,
    AssetVersionRepository,
)

__all__ = [
    "AssetDependencyService",
    "DependencyEntry",
    "DependencyView",
    "ReplacementImpact",
]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@dataclass(frozen=True, slots=True)
class DependencyEntry:
    source_type: str
    source_reference: str
    target_type: str
    target_reference: str
    dependency_type: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_type", "source_reference", "target_type", "target_reference"):
            if not str(getattr(self, name)).strip():
                raise AssetDependencyInvalid("依赖记录缺少字段", details={"field": name})
        if self.dependency_type not in DEPENDENCY_TYPES:
            raise AssetDependencyInvalid(
                "未知依赖类型", details={"dependency_type": self.dependency_type}
            )
        if not isinstance(self.metadata, Mapping):
            raise AssetDependencyInvalid("依赖元数据必须是对象")


@dataclass(frozen=True, slots=True)
class DependencyView:
    dependency_id: str
    project_id: str
    asset_version_id: str | None
    source_type: str
    source_reference: str
    target_type: str
    target_reference: str
    dependency_type: str
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReplacementImpact:
    asset_version_id: str
    references: tuple[DependencyView, ...]
    requires_changeset: bool = True

    @property
    def referenced(self) -> bool:
        return bool(self.references)


def _view(entity: AssetDependencyModel) -> DependencyView:
    return DependencyView(
        dependency_id=entity.dependency_id,
        project_id=entity.project_id,
        asset_version_id=entity.asset_version_id,
        source_type=entity.source_type,
        source_reference=entity.source_reference,
        target_type=entity.target_type,
        target_reference=entity.target_reference,
        dependency_type=entity.dependency_type,
        metadata=_load(entity.metadata_json, {}),
        created_at=entity.created_at,
    )


class AssetDependencyService:
    """资产依赖记录与引用影响分析。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        events: EventBus | None = None,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._events = events
        self._clock = clock
        self._logger = get_logger("backend.asset.dependency")

    async def record(
        self,
        project_id: str,
        asset_version_id: str,
        entries: Sequence[DependencyEntry],
    ) -> list[DependencyView]:
        if not entries:
            raise AssetDependencyInvalid("至少需要一条依赖记录")
        await self._validate_version(project_id, asset_version_id)
        now = self._clock()
        created: list[AssetDependencyModel] = []
        async with self._database.session() as session, transaction(session):
            repository = AssetDependencyRepository(session)
            existing = await repository.list_for_version(asset_version_id)
            seen = {
                (
                    item.source_type,
                    item.source_reference,
                    item.target_type,
                    item.target_reference,
                    item.dependency_type,
                )
                for item in existing
            }
            for entry in entries:
                key = (
                    entry.source_type,
                    entry.source_reference,
                    entry.target_type,
                    entry.target_reference,
                    entry.dependency_type,
                )
                if key in seen:
                    continue
                seen.add(key)
                entity = AssetDependencyModel(
                    dependency_id="adp_" + uuid4().hex[:12],
                    project_id=project_id,
                    asset_version_id=asset_version_id,
                    source_type=entry.source_type,
                    source_reference=entry.source_reference,
                    target_type=entry.target_type,
                    target_reference=entry.target_reference,
                    dependency_type=entry.dependency_type,
                    metadata_json=_dump(dict(entry.metadata)),
                    created_at=now,
                )
                await repository.add(entity)
                created.append(entity)
        if created:
            await self._publish(
                "asset.dependency.recorded",
                {
                    "asset_version_id": asset_version_id,
                    "count": len(created),
                },
                project_id=project_id,
            )
        return [_view(item) for item in created]

    async def list_for_version(
        self, project_id: str, asset_version_id: str
    ) -> list[DependencyView]:
        await self._validate_version(project_id, asset_version_id)
        async with self._database.session() as session:
            entities = await AssetDependencyRepository(session).list_for_version(asset_version_id)
        return [_view(item) for item in entities]

    async def list_referencing(
        self, project_id: str, target_reference: str
    ) -> list[DependencyView]:
        if not target_reference.strip():
            raise AssetDependencyInvalid("缺少目标引用")
        async with self._database.session() as session:
            entities = await AssetDependencyRepository(session).list_referencing(
                project_id, target_reference
            )
        return [_view(item) for item in entities]

    async def orphan_asset_ids(self, project_id: str) -> list[str]:
        async with self._database.session() as session:
            return await AssetRepository(session).orphan_asset_ids(project_id)

    async def missing_references(
        self, project_id: str, known_references: Sequence[str]
    ) -> list[DependencyView]:
        """返回目标不在已知资源集合中的依赖（失效引用）。"""

        known = {item for item in known_references if item}
        async with self._database.session() as session:
            entities = await AssetDependencyRepository(session).list_for_project(project_id)
        return [_view(item) for item in entities if item.target_reference not in known]

    async def detect_cycles(self, project_id: str) -> list[list[str]]:
        """检测引用图中的循环依赖，返回去重后的环列表。"""

        async with self._database.session() as session:
            entities = await AssetDependencyRepository(session).list_for_project(project_id)
        graph: dict[str, list[str]] = {}
        for item in entities:
            graph.setdefault(item.source_reference, []).append(item.target_reference)
        cycles: list[list[str]] = []
        seen_cycles: set[tuple[str, ...]] = set()

        def _canonical(cycle: list[str]) -> tuple[str, ...]:
            if not cycle:
                return ()
            rotations = [tuple(cycle[index:] + cycle[:index]) for index in range(len(cycle))]
            return min(rotations)

        def _walk(node: str, stack: list[str], visited: set[str]) -> None:
            if node in stack:
                index = stack.index(node)
                cycle = stack[index:]
                key = _canonical(cycle)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(list(key))
                return
            if node in visited:
                return
            visited.add(node)
            stack.append(node)
            for neighbour in graph.get(node, []):
                _walk(neighbour, stack, visited)
            stack.pop()

        for root in graph:
            _walk(root, [], set())
        return cycles

    async def replacement_impact(self, project_id: str, asset_version_id: str) -> ReplacementImpact:
        """分析替换版本会影响的引用；实际更新必须走 ChangeSet。"""

        references = await self._references_for_version(project_id, asset_version_id)
        return ReplacementImpact(
            asset_version_id=asset_version_id,
            references=tuple(references),
            requires_changeset=True,
        )

    async def deletion_risk(self, project_id: str, asset_version_id: str) -> ReplacementImpact:
        await self._validate_version(project_id, asset_version_id)
        references = await self._references_for_version(project_id, asset_version_id)
        return ReplacementImpact(
            asset_version_id=asset_version_id,
            references=tuple(references),
            requires_changeset=True,
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _references_for_version(
        self, project_id: str, asset_version_id: str
    ) -> list[DependencyView]:
        await self._validate_version(project_id, asset_version_id)
        async with self._database.session() as session:
            objects = await AssetStorageObjectRepository(session).list_for_version(asset_version_id)
            candidates = {item.relative_path for item in objects}
            candidates.add(f"asset://{asset_version_id}")
            references: list[DependencyView] = []
            repository = AssetDependencyRepository(session)
            for reference in sorted(candidates):
                rows = await repository.list_referencing(project_id, reference)
                references.extend(_view(item) for item in rows)
        unique: dict[str, DependencyView] = {item.dependency_id: item for item in references}
        return list(unique.values())

    async def _validate_version(self, project_id: str, asset_version_id: str) -> None:
        async with self._database.session() as session:
            version = await AssetVersionRepository(session).get(asset_version_id)
            if version is None:
                raise NotFoundError(
                    "资产版本不存在", details={"asset_version_id": asset_version_id}
                )
            asset = await AssetRepository(session).get_active(version.asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产版本不属于该项目",
                    details={
                        "project_id": project_id,
                        "asset_version_id": asset_version_id,
                    },
                )

    async def _publish(self, event_type: str, payload: dict[str, Any], *, project_id: str) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(Event.create(event_type, payload, project_id=project_id))
        except Exception:  # noqa: BLE001 - 事件失败不阻断依赖记录
            log_event(
                self._logger,
                logging.WARNING,
                "asset.dependency.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )
