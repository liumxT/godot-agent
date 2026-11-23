"""资产来源追踪（E8-T12）。

职责：

- 每个 AssetVersion 对应唯一一条 Provenance 记录，重复记录同一内容时幂等返回；
- 支持生成、上传、项目衍生等来源，并保留可审计、可复现的关键字段；
- 处理型版本沿 ``parent_version_id`` 形成追溯链；
- 交付前的完整性检查：未知来源、缺少关键生成字段或缺失父版本来源时拒绝。

来源类型不替代 License 结论；本模块不做授权判断。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import AssetStateInvalid, NotFoundError
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    SOURCE_AI_GENERATED,
    SOURCE_PROJECT_DERIVED,
    SOURCE_TYPES,
    SOURCE_UNKNOWN,
    AssetProvenanceModel,
)
from modules.asset_pipeline.repository import (
    AssetProvenanceRepository,
    AssetRepository,
    AssetVersionRepository,
)

_MAX_TRACE_DEPTH = 64

__all__ = [
    "ProvenanceRequest",
    "ProvenanceService",
    "ProvenanceView",
    "TraceEntry",
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
class ProvenanceRequest:
    project_id: str
    asset_id: str
    asset_version_id: str
    source_type: str
    provider_id: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    generation_id: str | None = None
    request_reference: str | None = None
    prompt_version_id: str | None = None
    seed: str | None = None
    input_hashes: Sequence[str] = ()
    output_hashes: Sequence[str] = ()
    processing_graph: Mapping[str, Any] | None = None
    processor_versions: Sequence[Mapping[str, Any]] = ()
    operator_agent_id: str | None = None
    operator_user_id: str | None = None
    license_reference: str | None = None
    external_source_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise AssetStateInvalid("缺少项目 ID")
        if not self.asset_id.strip():
            raise AssetStateInvalid("缺少资产 ID")
        if not self.asset_version_id.strip():
            raise AssetStateInvalid("缺少资产版本 ID")
        if self.source_type not in SOURCE_TYPES:
            raise AssetStateInvalid(
                "未知资产来源类型", details={"source_type": self.source_type}
            )
        for name, values in (
            ("input_hashes", self.input_hashes),
            ("output_hashes", self.output_hashes),
        ):
            if not all(isinstance(item, str) and item for item in values):
                raise AssetStateInvalid("来源 Hash 必须是非空字符串列表", details={"field": name})


@dataclass(frozen=True, slots=True)
class ProvenanceView:
    provenance_id: str
    asset_id: str
    asset_version_id: str
    source_type: str
    provider_id: str | None
    model_id: str | None
    model_version: str | None
    generation_id: str | None
    request_reference: str | None
    prompt_version_id: str | None
    seed: str | None
    input_hashes: tuple[str, ...]
    output_hashes: tuple[str, ...]
    processing_graph: dict[str, Any] | None
    processor_versions: tuple[dict[str, Any], ...]
    operator_agent_id: str | None
    operator_user_id: str | None
    license_reference: str | None
    external_source_reference: str | None
    created_at: datetime
    created: bool = True


@dataclass(frozen=True, slots=True)
class TraceEntry:
    version_id: str
    version_number: int
    parent_version_id: str | None
    source_type: str
    change_reason: str | None
    provenance: ProvenanceView | None


def _provenance_view(
    entity: AssetProvenanceModel, *, created: bool
) -> ProvenanceView:
    graph = _load(entity.processing_graph_json, None)
    return ProvenanceView(
        provenance_id=entity.provenance_id,
        asset_id=entity.asset_id,
        asset_version_id=entity.asset_version_id,
        source_type=entity.source_type,
        provider_id=entity.provider_id,
        model_id=entity.model_id,
        model_version=entity.model_version,
        generation_id=entity.generation_id,
        request_reference=entity.request_reference,
        prompt_version_id=entity.prompt_version_id,
        seed=entity.seed,
        input_hashes=tuple(_load(entity.input_hashes_json, [])),
        output_hashes=tuple(_load(entity.output_hashes_json, [])),
        processing_graph=graph if isinstance(graph, dict) else None,
        processor_versions=tuple(_load(entity.processor_versions_json, [])),
        operator_agent_id=entity.operator_agent_id,
        operator_user_id=entity.operator_user_id,
        license_reference=entity.license_reference,
        external_source_reference=entity.external_source_reference,
        created_at=entity.created_at,
        created=created,
    )


class ProvenanceService:
    """资产来源记录、追溯与完整性校验。"""

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
        self._logger = get_logger("backend.asset.provenance")

    async def record(self, request: ProvenanceRequest) -> ProvenanceView:
        await self._validate_ownership(
            request.project_id, request.asset_id, request.asset_version_id
        )
        async with self._database.session() as session:
            repository = AssetProvenanceRepository(session)
            existing = await repository.get_for_version(request.asset_version_id)
            if existing is not None:
                session.expunge(existing)
        if existing is not None:
            if not self._matches(existing, request):
                raise AssetStateInvalid(
                    "同一资产版本只能有一条内容一致的来源记录",
                    details={
                        "provenance_id": existing.provenance_id,
                        "asset_version_id": request.asset_version_id,
                    },
                )
            return _provenance_view(existing, created=False)

        now = self._clock()
        entity = AssetProvenanceModel(
            provenance_id="prv_" + uuid4().hex[:12],
            asset_id=request.asset_id,
            asset_version_id=request.asset_version_id,
            source_type=request.source_type,
            provider_id=request.provider_id,
            model_id=request.model_id,
            model_version=request.model_version,
            generation_id=request.generation_id,
            request_reference=request.request_reference,
            prompt_version_id=request.prompt_version_id,
            seed=request.seed,
            input_hashes_json=_dump(list(request.input_hashes)),
            output_hashes_json=_dump(list(request.output_hashes)),
            processing_graph_json=(
                _dump(dict(request.processing_graph))
                if request.processing_graph is not None
                else None
            ),
            processor_versions_json=_dump(
                [dict(item) for item in request.processor_versions]
            ),
            operator_agent_id=request.operator_agent_id,
            operator_user_id=request.operator_user_id,
            license_reference=request.license_reference,
            external_source_reference=request.external_source_reference,
            created_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await AssetProvenanceRepository(session).add(entity)
        await self._publish(
            "asset.provenance.recorded",
            {
                "provenance_id": entity.provenance_id,
                "asset_version_id": request.asset_version_id,
                "source_type": request.source_type,
            },
            project_id=request.project_id,
        )
        return _provenance_view(entity, created=True)

    async def get(
        self, project_id: str, asset_version_id: str
    ) -> ProvenanceView | None:
        async with self._database.session() as session:
            version = await AssetVersionRepository(session).get(asset_version_id)
            if version is None:
                raise NotFoundError(
                    "资产版本不存在", details={"asset_version_id": asset_version_id}
                )
            asset = await AssetRepository(session).get(version.asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产版本不属于该项目",
                    details={
                        "project_id": project_id,
                        "asset_version_id": asset_version_id,
                    },
                )
            entity = await AssetProvenanceRepository(session).get_for_version(
                asset_version_id
            )
            if entity is None:
                return None
            session.expunge(entity)
        return _provenance_view(entity, created=False)

    async def trace(self, project_id: str, asset_version_id: str) -> tuple[TraceEntry, ...]:
        """沿父版本回溯，返回从最早祖先到目标版本的来源链。"""

        entries: list[TraceEntry] = []
        visited: set[str] = set()
        async with self._database.session() as session:
            versions = AssetVersionRepository(session)
            provenance = AssetProvenanceRepository(session)
            current_id: str | None = asset_version_id
            while current_id is not None:
                if current_id in visited or len(visited) >= _MAX_TRACE_DEPTH:
                    raise AssetStateInvalid(
                        "资产版本追溯链存在循环或超长",
                        details={"asset_version_id": asset_version_id},
                    )
                visited.add(current_id)
                version = await versions.get(current_id)
                if version is None:
                    raise NotFoundError(
                        "追溯链中的资产版本不存在",
                        details={"asset_version_id": current_id},
                    )
                asset = await AssetRepository(session).get(version.asset_id)
                if asset is None or asset.project_id != project_id:
                    raise NotFoundError(
                        "追溯链中的资产不属于该项目",
                        details={"project_id": project_id, "asset_id": version.asset_id},
                    )
                entity = await provenance.get_for_version(current_id)
                entries.append(
                    TraceEntry(
                        version_id=version.version_id,
                        version_number=version.version_number,
                        parent_version_id=version.parent_version_id,
                        source_type=version.source_type,
                        change_reason=version.change_reason,
                        provenance=(
                            _provenance_view(entity, created=False)
                            if entity is not None
                            else None
                        ),
                    )
                )
                current_id = version.parent_version_id
        entries.reverse()
        return tuple(entries)

    async def assert_complete(
        self, project_id: str, asset_version_id: str
    ) -> ProvenanceView:
        """交付完整性检查；不满足时抛出 ``AssetStateInvalid``。"""

        entries = await self.trace(project_id, asset_version_id)
        target = entries[-1]
        view = target.provenance
        if view is None:
            raise AssetStateInvalid(
                "资产版本缺少来源记录，不能正式交付",
                details={"asset_version_id": asset_version_id},
            )
        if view.source_type == SOURCE_UNKNOWN:
            raise AssetStateInvalid(
                "资产来源未知，不能正式交付",
                details={"asset_version_id": asset_version_id},
            )
        if view.source_type == SOURCE_AI_GENERATED:
            missing = [
                name
                for name, value in (
                    ("provider_id", view.provider_id),
                    ("model_id", view.model_id),
                    ("generation_id", view.generation_id),
                )
                if not value
            ]
            if not view.output_hashes:
                missing.append("output_hashes")
            if missing:
                raise AssetStateInvalid(
                    "AI 生成资产来源记录不完整",
                    details={"missing": missing, "asset_version_id": asset_version_id},
                )
        if view.source_type == SOURCE_PROJECT_DERIVED:
            if view.processing_graph is None:
                raise AssetStateInvalid(
                    "衍生资产缺少处理图记录",
                    details={"asset_version_id": asset_version_id},
                )
            if len(entries) < 2:
                raise AssetStateInvalid(
                    "衍生资产缺少父版本来源",
                    details={"asset_version_id": asset_version_id},
                )
            parent = entries[-2]
            if parent.provenance is None:
                raise AssetStateInvalid(
                    "衍生资产的父版本缺少来源记录",
                    details={"parent_version_id": parent.version_id},
                )
        return view

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _validate_ownership(
        self, project_id: str, asset_id: str, asset_version_id: str
    ) -> None:
        async with self._database.session() as session:
            version = await AssetVersionRepository(session).get(asset_version_id)
            if version is None or version.asset_id != asset_id:
                raise NotFoundError(
                    "资产版本不属于该资产",
                    details={
                        "asset_id": asset_id,
                        "asset_version_id": asset_version_id,
                    },
                )
            asset = await AssetRepository(session).get_active(asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产不存在或不属于该项目",
                    details={"project_id": project_id, "asset_id": asset_id},
                )

    def _matches(
        self, entity: AssetProvenanceModel, request: ProvenanceRequest
    ) -> bool:
        scalar_fields = (
            "provider_id",
            "model_id",
            "model_version",
            "generation_id",
            "request_reference",
            "prompt_version_id",
            "seed",
            "operator_agent_id",
            "operator_user_id",
            "license_reference",
            "external_source_reference",
        )
        if entity.source_type != request.source_type:
            return False
        for name in scalar_fields:
            value = getattr(request, name)
            if value is None:
                continue
            if getattr(entity, name) != value:
                return False
        if request.input_hashes and list(
            _load(entity.input_hashes_json, [])
        ) != list(request.input_hashes):
            return False
        if request.output_hashes and list(
            _load(entity.output_hashes_json, [])
        ) != list(request.output_hashes):
            return False
        if request.processor_versions and list(
            _load(entity.processor_versions_json, [])
        ) != [dict(item) for item in request.processor_versions]:
            return False
        if request.processing_graph is not None:
            return _load(entity.processing_graph_json, None) == dict(
                request.processing_graph
            )
        return True

    async def _publish(
        self, event_type: str, payload: dict[str, Any], *, project_id: str
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(
                Event.create(event_type, payload, project_id=project_id)
            )
        except Exception:  # noqa: BLE001 - 事件失败不阻断来源记录
            log_event(
                self._logger,
                logging.WARNING,
                "asset.provenance.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )
