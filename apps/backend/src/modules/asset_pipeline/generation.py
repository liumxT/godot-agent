"""资产生成编排器（E8-T05）。

职责：

- 校验 Asset Brief、资产类别与显式 Provider / 模型选择；
- 幂等键与请求 Hash：同一请求不重复调用 Provider，同键不同请求直接拒绝；
- 通过 Model Gateway 提交图像 / 音频 / 3D 生成，禁止绕过 Gateway；
- 持久化 Generation、Provider Job、输出与预算预留；
- 成功后写入内部暂存区、创建不可变版本并记录 Provenance；
- 已发送但结果未知的任务标记 ``UNKNOWN``，禁止静默重提交。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from core.errors import (
    AssetBriefInvalid,
    AssetGenerationInvalid,
    AssetGenerationUnknown,
    AssetStateInvalid,
    ModelCallFailed,
    NotFoundError,
)
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.briefs import AssetBriefService
from modules.asset_pipeline.models import (
    ASSET_ARCHIVED,
    BRIEF_APPROVED,
    GENERATION_CANCELLED,
    GENERATION_CREATED,
    GENERATION_FAILED,
    GENERATION_RUNNING,
    GENERATION_SUBMITTED,
    GENERATION_SUCCEEDED,
    GENERATION_TRANSITIONS,
    GENERATION_UNKNOWN,
    SOURCE_AI_GENERATED,
    STORAGE_GENERATED,
    AssetGenerationModel,
    AssetGenerationOutputModel,
    AssetModel,
    AssetProvenanceModel,
    AssetProviderJobModel,
    AssetStorageObjectModel,
)
from modules.asset_pipeline.repository import (
    AssetBriefRepository,
    AssetGenerationOutputRepository,
    AssetGenerationRepository,
    AssetProvenanceRepository,
    AssetProviderJobRepository,
    AssetRepository,
    AssetStorageObjectRepository,
)
from modules.asset_pipeline.storage import AssetStorage
from modules.asset_pipeline.versioning import AssetVersionService
from modules.model_gateway.asset_generation import (
    ASSET_JOB_FAILED,
    ASSET_JOB_RUNNING,
    ASSET_JOB_SUCCEEDED,
    ASSET_JOB_UNKNOWN,
    ASSET_KIND_AUDIO,
    ASSET_KIND_IMAGE,
    ASSET_KIND_MODEL_3D,
    AssetGenerationOutput,
    AssetGenerationRequest,
    AssetGenerationResult,
    ResolvedAssetProvider,
    validate_asset_kind,
)
from modules.model_gateway.gateway import ModelGatewayService

_TERMINAL_GENERATION_STATUSES = frozenset(
    {GENERATION_SUCCEEDED, GENERATION_FAILED, GENERATION_CANCELLED}
)
_EXTENSION_PATTERN = re.compile(r"^[a-z0-9]{1,8}$")
_MIME_TYPES = {
    "png": "image/png",
    "webp": "image/webp",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "glb": "model/gltf-binary",
    "gltf": "model/gltf+json",
    "obj": "model/obj",
}
_KIND_BY_CATEGORY = {
    ASSET_KIND_IMAGE: ASSET_KIND_IMAGE,
    ASSET_KIND_AUDIO: ASSET_KIND_AUDIO,
    ASSET_KIND_MODEL_3D: ASSET_KIND_MODEL_3D,
}


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
class GenerationRequest:
    project_id: str
    asset_id: str
    kind: str
    prompt: str
    provider_id: str | None = None
    model_id: str | None = None
    brief_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    output_count: int = 1
    budget: dict[str, Any] | None = None
    timeout_seconds: float | None = None
    idempotency_key: str | None = None
    created_by: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise AssetGenerationInvalid("缺少项目 ID")
        if not self.asset_id.strip():
            raise AssetGenerationInvalid("缺少资产 ID")
        validate_asset_kind(self.kind)
        if not self.prompt.strip():
            raise AssetGenerationInvalid("生成提示词不能为空")
        if not isinstance(self.output_count, int) or isinstance(self.output_count, bool):
            raise AssetGenerationInvalid("输出数量必须是整数")
        if self.output_count < 1:
            raise AssetGenerationInvalid("输出数量必须大于 0")
        if not isinstance(self.parameters, dict):
            raise AssetGenerationInvalid("生成参数必须是对象")
        if self.budget is not None and not isinstance(self.budget, dict):
            raise AssetGenerationInvalid("生成预算必须是对象")
        if self.idempotency_key is not None and len(self.idempotency_key) > 128:
            raise AssetGenerationInvalid("幂等键不能超过 128 个字符")

    def canonical_hash(self) -> str:
        payload = {
            "project_id": self.project_id,
            "asset_id": self.asset_id,
            "kind": self.kind,
            "prompt": self.prompt,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "brief_id": self.brief_id,
            "parameters": self.parameters,
            "output_count": self.output_count,
            "budget": self.budget,
        }
        return hashlib.sha256(_dump(payload).encode("utf-8")).hexdigest()

    def resolved_idempotency_key(self, request_hash: str) -> str:
        return self.idempotency_key or f"gen:{request_hash[:48]}"


@dataclass(frozen=True, slots=True)
class GenerationOutputView:
    output_id: str
    reference: str
    content_hash: str
    format: str
    width: int | None
    height: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GenerationView:
    generation_id: str
    project_id: str
    asset_id: str
    brief_id: str | None
    status: str
    kind: str
    provider_id: str | None
    model_id: str | None
    provider_job_id: str | None
    result_version_id: str | None
    error_code: str | None
    request_hash: str
    idempotency_key: str
    budget: dict[str, Any]
    outputs: tuple[GenerationOutputView, ...]
    created_at: datetime
    submitted_at: datetime | None
    last_checked_at: datetime | None
    completed_at: datetime | None
    created: bool = True


def _output_view(entity: AssetGenerationOutputModel) -> GenerationOutputView:
    return GenerationOutputView(
        output_id=entity.output_id,
        reference=entity.temporary_reference,
        content_hash=entity.content_hash,
        format=entity.format,
        width=entity.width,
        height=entity.height,
        metadata=_load(entity.metadata_json, {}),
    )


def _generation_view(
    entity: AssetGenerationModel,
    *,
    project_id: str,
    outputs: list[AssetGenerationOutputModel],
    created: bool = True,
) -> GenerationView:
    spec = _load(entity.requested_spec_json, {})
    return GenerationView(
        generation_id=entity.generation_id,
        project_id=project_id,
        asset_id=entity.asset_id,
        brief_id=entity.brief_id,
        status=entity.generation_status,
        kind=spec.get("kind", ""),
        provider_id=entity.provider_id,
        model_id=entity.model_id,
        provider_job_id=entity.provider_job_id,
        result_version_id=entity.result_version_id,
        error_code=entity.error_code,
        request_hash=entity.request_hash,
        idempotency_key=entity.idempotency_key,
        budget=_load(entity.budget_reservation_json, {}),
        outputs=tuple(_output_view(item) for item in outputs),
        created_at=entity.created_at,
        submitted_at=entity.submitted_at,
        last_checked_at=entity.last_checked_at,
        completed_at=entity.completed_at,
        created=created,
    )


class GenerationOrchestrator:
    """资产生成编排服务。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        gateway: ModelGatewayService,
        storage: AssetStorage,
        versions: AssetVersionService,
        briefs: AssetBriefService | None = None,
        events: EventBus | None = None,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._gateway = gateway
        self._storage = storage
        self._versions = versions
        self._briefs = briefs or AssetBriefService(database)
        self._events = events
        self._clock = clock
        self._logger = get_logger("backend.asset.generation")

    async def submit(self, request: GenerationRequest) -> GenerationView:
        request_hash = request.canonical_hash()
        idempotency_key = request.resolved_idempotency_key(request_hash)
        existing = await self._find_by_idempotency(idempotency_key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AssetGenerationInvalid(
                    "幂等键已被不同请求占用",
                    details={
                        "generation_id": existing.generation_id,
                        "idempotency_key": idempotency_key,
                    },
                )
            if existing.generation_status != GENERATION_CREATED:
                return await self._view_for(existing, created=False)
            return await self._resume_created(existing, request)

        asset = await self._load_asset(request.project_id, request.asset_id)
        self._validate_asset(asset, request.kind)
        await self._validate_brief(request)
        resolved = await self._gateway.resolve_asset_provider(
            kind=request.kind,
            provider_id=request.provider_id,
            model_id=request.model_id,
        )
        adapter_request = self._adapter_request(
            request,
            resolved,
            idempotency_key=idempotency_key,
        )
        budget = self._reserve_budget(request, resolved, adapter_request)
        now = self._clock()
        entity = AssetGenerationModel(
            generation_id="agen_" + uuid4().hex[:12],
            asset_id=asset.asset_id,
            brief_id=request.brief_id,
            requested_spec_json=_dump(
                {
                    "kind": request.kind,
                    "prompt": request.prompt,
                    "parameters": request.parameters,
                    "output_count": request.output_count,
                    "timeout_seconds": request.timeout_seconds,
                }
            ),
            provider_id=resolved.provider_id,
            model_id=resolved.model_id,
            provider_job_id=None,
            generation_status=GENERATION_CREATED,
            result_version_id=None,
            error_code=None,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            budget_reservation_json=_dump(budget),
            created_by=request.created_by,
            created_at=now,
            submitted_at=None,
            last_checked_at=None,
            completed_at=None,
        )
        async with self._database.session() as session, transaction(session):
            await AssetGenerationRepository(session).add(entity)
        await self._publish(
            "asset.generation.created",
            {"generation_id": entity.generation_id, "asset_id": asset.asset_id},
            project_id=request.project_id,
        )
        return await self._submit_existing(entity, request, resolved, adapter_request)

    async def get(self, generation_id: str) -> GenerationView:
        async with self._database.session() as session:
            entity = await AssetGenerationRepository(session).get(generation_id)
            if entity is None:
                raise NotFoundError("资产生成任务不存在", details={"generation_id": generation_id})
            asset = await AssetRepository(session).get(entity.asset_id)
            if asset is None:
                raise NotFoundError(
                    "资产生成任务关联资产不存在", details={"asset_id": entity.asset_id}
                )
            outputs = await AssetGenerationOutputRepository(session).list_for_generation(
                generation_id
            )
            return _generation_view(
                entity, project_id=asset.project_id, outputs=outputs, created=False
            )

    async def list_for_asset(self, project_id: str, asset_id: str) -> list[GenerationView]:
        asset = await self._load_asset(project_id, asset_id)
        async with self._database.session() as session:
            entities = await AssetGenerationRepository(session).list_for_asset(asset_id)
            output_repository = AssetGenerationOutputRepository(session)
            views: list[GenerationView] = []
            for entity in entities:
                outputs = await output_repository.list_for_generation(entity.generation_id)
                views.append(
                    _generation_view(
                        entity, project_id=asset.project_id, outputs=outputs, created=False
                    )
                )
            return views

    async def refresh(self, generation_id: str) -> GenerationView:
        """查询 Provider 状态；用于异步任务与 UNKNOWN 结果恢复。"""

        async with self._database.session() as session:
            entity = await AssetGenerationRepository(session).get(generation_id)
            if entity is None:
                raise NotFoundError("资产生成任务不存在", details={"generation_id": generation_id})
            asset = await AssetRepository(session).get(entity.asset_id)
            if asset is None:
                raise NotFoundError(
                    "资产生成任务关联资产不存在", details={"asset_id": entity.asset_id}
                )
            session.expunge(entity)
            session.expunge(asset)
            spec = _load(entity.requested_spec_json, {})
        if entity.generation_status in _TERMINAL_GENERATION_STATUSES:
            return await self._view_for(entity, created=False)
        if not entity.provider_job_id:
            raise AssetGenerationInvalid(
                "生成任务没有 Provider Job ID，无法查询",
                details={"generation_id": generation_id},
            )
        resolved = await self._gateway.resolve_asset_provider(
            kind=spec.get("kind", ""),
            provider_id=entity.provider_id,
            model_id=entity.model_id,
        )
        adapter_request = self._adapter_request_from_spec(
            entity, spec, resolved, project_id=asset.project_id
        )
        try:
            result = await self._gateway.query_asset_generation(
                resolved, adapter_request, entity.provider_job_id
            )
        except AssetGenerationUnknown:
            await self._mark_status(
                generation_id,
                GENERATION_UNKNOWN,
                last_checked_at=self._clock(),
                error_code="ASSET_GENERATION_UNKNOWN",
            )
            raise
        return await self._handle_result(
            entity, asset, resolved, adapter_request, result, from_refresh=True
        )

    async def cancel(self, generation_id: str) -> GenerationView:
        async with self._database.session() as session:
            entity = await AssetGenerationRepository(session).get(generation_id)
            if entity is None:
                raise NotFoundError("资产生成任务不存在", details={"generation_id": generation_id})
            asset = await AssetRepository(session).get(entity.asset_id)
            if asset is None:
                raise NotFoundError(
                    "资产生成任务关联资产不存在", details={"asset_id": entity.asset_id}
                )
            session.expunge(entity)
            session.expunge(asset)
            spec = _load(entity.requested_spec_json, {})
        if entity.generation_status in _TERMINAL_GENERATION_STATUSES:
            raise AssetStateInvalid(
                "生成任务已结束，不能取消",
                details={
                    "generation_id": generation_id,
                    "status": entity.generation_status,
                },
            )
        if not entity.provider_job_id:
            await self._mark_status(generation_id, GENERATION_CANCELLED)
            await self._publish(
                "asset.generation.cancelled",
                {"generation_id": generation_id, "asset_id": entity.asset_id},
                project_id=asset.project_id,
            )
            return await self.get(generation_id)
        resolved = await self._gateway.resolve_asset_provider(
            kind=spec.get("kind", ""),
            provider_id=entity.provider_id,
            model_id=entity.model_id,
        )
        adapter_request = self._adapter_request_from_spec(
            entity, spec, resolved, project_id=asset.project_id
        )
        try:
            await self._gateway.cancel_asset_generation(
                resolved, adapter_request, entity.provider_job_id
            )
        except AssetGenerationUnknown:
            await self._mark_status(
                generation_id,
                GENERATION_UNKNOWN,
                last_checked_at=self._clock(),
                error_code="ASSET_GENERATION_UNKNOWN",
            )
            raise
        await self._mark_status(
            generation_id,
            GENERATION_CANCELLED,
            completed_at=self._clock(),
            last_checked_at=self._clock(),
        )
        await self._publish(
            "asset.generation.cancelled",
            {"generation_id": generation_id, "asset_id": entity.asset_id},
            project_id=asset.project_id,
        )
        return await self.get(generation_id)

    # ------------------------------------------------------------------
    # 内部流程
    # ------------------------------------------------------------------

    async def _resume_created(
        self, entity: AssetGenerationModel, request: GenerationRequest
    ) -> GenerationView:
        """只对 ``CREATED`` 状态恢复提交；提交前必先落 SUBMITTED，不会重复计费。"""

        asset = await self._load_asset(request.project_id, entity.asset_id)
        self._validate_asset(asset, request.kind)
        resolved = await self._gateway.resolve_asset_provider(
            kind=request.kind,
            provider_id=entity.provider_id,
            model_id=entity.model_id,
        )
        return await self._submit_existing_from_existing(entity, request, resolved)

    async def _submit_existing_from_existing(
        self,
        entity: AssetGenerationModel,
        request: GenerationRequest,
        resolved: ResolvedAssetProvider,
    ) -> GenerationView:
        adapter_request = self._adapter_request(
            request, resolved, idempotency_key=entity.idempotency_key
        )
        return await self._submit_existing(entity, request, resolved, adapter_request)

    async def _submit_existing(
        self,
        entity: AssetGenerationModel,
        request: GenerationRequest,
        resolved: ResolvedAssetProvider,
        adapter_request: AssetGenerationRequest,
    ) -> GenerationView:
        await self._mark_status(
            entity.generation_id,
            GENERATION_SUBMITTED,
            submitted_at=self._clock(),
        )
        await self._publish(
            "asset.generation.submitted",
            {
                "generation_id": entity.generation_id,
                "asset_id": entity.asset_id,
                "provider_id": resolved.provider_id,
                "model_id": resolved.model_id,
            },
            project_id=request.project_id,
        )
        try:
            result = await self._gateway.submit_asset_generation(resolved, adapter_request)
        except AssetGenerationUnknown as error:
            await self._mark_status(
                entity.generation_id,
                GENERATION_UNKNOWN,
                last_checked_at=self._clock(),
                error_code=error.code,
            )
            await self._publish(
                "asset.generation.unknown",
                {
                    "generation_id": entity.generation_id,
                    "asset_id": entity.asset_id,
                    "error_code": error.code,
                },
                project_id=request.project_id,
            )
            raise
        except ModelCallFailed as error:
            await self._mark_status(
                entity.generation_id,
                GENERATION_FAILED,
                completed_at=self._clock(),
                last_checked_at=self._clock(),
                error_code=error.code,
            )
            await self._publish(
                "asset.generation.failed",
                {
                    "generation_id": entity.generation_id,
                    "asset_id": entity.asset_id,
                    "error_code": error.code,
                },
                project_id=request.project_id,
            )
            raise
        asset = await self._load_asset(request.project_id, entity.asset_id)
        return await self._handle_result(
            entity, asset, resolved, adapter_request, result, from_refresh=False
        )

    async def _handle_result(
        self,
        entity: AssetGenerationModel,
        asset: AssetModel,
        resolved: ResolvedAssetProvider,
        adapter_request: AssetGenerationRequest,
        result: AssetGenerationResult,
        *,
        from_refresh: bool,
    ) -> GenerationView:
        generation_id = entity.generation_id
        now = self._clock()
        if result.status == ASSET_JOB_SUCCEEDED:
            await self._record_provider_job(entity, resolved, result, now)
            return await self._finalize(entity, asset, resolved, result, adapter_request)
        if result.status == ASSET_JOB_RUNNING:
            current = await self._current_status(generation_id)
            target = (
                GENERATION_RUNNING
                if current in (GENERATION_SUBMITTED, GENERATION_RUNNING)
                else current
            )
            await self._record_provider_job(entity, resolved, result, now)
            await self._mark_status(
                generation_id,
                target,
                provider_job_id=result.provider_job_id or entity.provider_job_id,
                last_checked_at=now,
            )
            return await self.get(generation_id)
        if result.status == ASSET_JOB_FAILED:
            await self._record_provider_job(entity, resolved, result, now)
            code = result.error_code or "ASSET_GENERATION_FAILED"
            await self._mark_status(
                generation_id,
                GENERATION_FAILED,
                provider_job_id=result.provider_job_id or entity.provider_job_id,
                completed_at=now,
                last_checked_at=now,
                error_code=code,
            )
            await self._publish(
                "asset.generation.failed",
                {
                    "generation_id": generation_id,
                    "asset_id": entity.asset_id,
                    "error_code": code,
                },
                project_id=asset.project_id,
            )
            raise ModelCallFailed(
                "资产生成失败",
                details={"generation_id": generation_id, "error_code": code},
            )
        # UNKNOWN
        await self._record_provider_job(entity, resolved, result, now)
        await self._mark_status(
            generation_id,
            GENERATION_UNKNOWN,
            provider_job_id=result.provider_job_id or entity.provider_job_id,
            last_checked_at=now,
            error_code=result.error_code or "ASSET_GENERATION_UNKNOWN",
        )
        await self._publish(
            "asset.generation.unknown",
            {
                "generation_id": generation_id,
                "asset_id": entity.asset_id,
                "error_code": result.error_code or "ASSET_GENERATION_UNKNOWN",
            },
            project_id=asset.project_id,
        )
        raise AssetGenerationUnknown(
            "资产生成结果未知，禁止直接重试",
            details={"generation_id": generation_id, "from_refresh": from_refresh},
        )

    async def _finalize(
        self,
        entity: AssetGenerationModel,
        asset: AssetModel,
        resolved: ResolvedAssetProvider,
        result: AssetGenerationResult,
        adapter_request: AssetGenerationRequest,
    ) -> GenerationView:
        outputs = result.outputs
        if not outputs:
            raise AssetGenerationInvalid(
                "生成成功但缺少产物", details={"generation_id": entity.generation_id}
            )
        self._storage.ensure_layout(asset.project_id)
        stored: list[dict[str, Any]] = []
        hashes: list[str] = []
        for index, output in enumerate(outputs):
            extension = _extension(output.format)
            filename = f"{entity.generation_id}_{index:02d}.{extension}"
            relative_path = f"{asset.asset_id}/{filename}"
            digest = output.content_hash
            self._storage.write_bytes(
                asset.project_id,
                STORAGE_GENERATED,
                relative_path,
                output.data,
            )
            hashes.append(digest)
            stored.append(
                {
                    "relative_path": relative_path,
                    "content_hash": digest,
                    "size_bytes": len(output.data),
                    "mime_type": _MIME_TYPES.get(extension, "application/octet-stream"),
                    "output": output,
                }
            )
        composite_hash = hashlib.sha256("".join(hashes).encode("ascii")).hexdigest()
        provenance_id = "prv_" + uuid4().hex[:12]
        metadata = {
            "generation_id": entity.generation_id,
            "provider_id": resolved.provider_id,
            "model_id": resolved.model_id,
            "model_key": resolved.model_key,
            "kind": adapter_request.kind,
            "outputs": [
                {
                    "content_hash": item["content_hash"],
                    "format": item["output"].format,
                    "size_bytes": item["size_bytes"],
                }
                for item in stored
            ],
        }
        version = await self._versions.create_version(
            asset.asset_id,
            content_hash=composite_hash,
            source_type=SOURCE_AI_GENERATED,
            metadata=metadata,
            change_reason="ai_generation",
            provenance_id=provenance_id,
            created_by=entity.created_by,
            make_current=True,
        )
        now = self._clock()
        if version.created:
            async with self._database.session() as session, transaction(session):
                provenance = AssetProvenanceRepository(session)
                await provenance.add(
                    AssetProvenanceModel(
                        provenance_id=provenance_id,
                        asset_id=asset.asset_id,
                        asset_version_id=version.version_id,
                        source_type=SOURCE_AI_GENERATED,
                        provider_id=resolved.provider_id,
                        model_id=resolved.model_id,
                        model_version=str(adapter_request.parameter("model_version", "")) or None,
                        generation_id=entity.generation_id,
                        request_reference=entity.generation_id,
                        prompt_version_id=None,
                        seed=_optional_text(adapter_request.parameter("seed")),
                        input_hashes_json=_dump([]),
                        output_hashes_json=_dump(hashes),
                        processing_graph_json=None,
                        processor_versions_json=_dump([]),
                        operator_agent_id=None,
                        operator_user_id=entity.created_by,
                        license_reference=None,
                        external_source_reference=None,
                        created_at=now,
                    )
                )
                output_repository = AssetGenerationOutputRepository(session)
                storage_repository = AssetStorageObjectRepository(session)
                for item in stored:
                    output: AssetGenerationOutput = item["output"]
                    await output_repository.add(
                        AssetGenerationOutputModel(
                            output_id="aout_" + uuid4().hex[:12],
                            generation_id=entity.generation_id,
                            temporary_reference=item["relative_path"],
                            content_hash=item["content_hash"],
                            width=output.width,
                            height=output.height,
                            format=output.format,
                            metadata_json=_dump(output.metadata),
                            created_at=now,
                        )
                    )
                    await storage_repository.add(
                        AssetStorageObjectModel(
                            object_id="asob_" + uuid4().hex[:12],
                            project_id=asset.project_id,
                            asset_version_id=version.version_id,
                            storage_area=STORAGE_GENERATED,
                            relative_path=item["relative_path"],
                            content_hash=item["content_hash"],
                            size_bytes=item["size_bytes"],
                            mime_type=item["mime_type"],
                            created_at=now,
                        )
                    )
        await self._mark_status(
            entity.generation_id,
            GENERATION_SUCCEEDED,
            provider_job_id=result.provider_job_id or entity.provider_job_id,
            result_version_id=version.version_id,
            completed_at=now,
            last_checked_at=now,
            clear_error=True,
        )
        await self._publish(
            "asset.generation.succeeded",
            {
                "generation_id": entity.generation_id,
                "asset_id": asset.asset_id,
                "asset_version_id": version.version_id,
                "provider_id": resolved.provider_id,
                "model_id": resolved.model_id,
            },
            project_id=asset.project_id,
        )
        return await self.get(entity.generation_id)

    async def _record_provider_job(
        self,
        entity: AssetGenerationModel,
        resolved: ResolvedAssetProvider,
        result: AssetGenerationResult,
        now: datetime,
    ) -> None:
        job_id = result.provider_job_id
        if not job_id:
            return
        async with self._database.session() as session, transaction(session):
            repository = AssetProviderJobRepository(session)
            existing = await repository.get_external(resolved.provider_id, job_id)
            if existing is not None:
                if existing.generation_id == entity.generation_id:
                    existing.status = _provider_job_status(result.status)
                    existing.last_checked_at = now
                    existing.result_reference = (
                        result.outputs[0].content_hash if result.outputs else None
                    )
                return
            await repository.add(
                AssetProviderJobModel(
                    record_id="apj_" + uuid4().hex[:12],
                    generation_id=entity.generation_id,
                    provider_id=resolved.provider_id,
                    model_id=resolved.model_id,
                    provider_job_id=job_id,
                    request_hash=entity.request_hash,
                    status=_provider_job_status(result.status),
                    result_reference=result.outputs[0].content_hash if result.outputs else None,
                    submitted_at=entity.submitted_at or now,
                    last_checked_at=now,
                    created_at=now,
                )
            )

    async def _mark_status(
        self,
        generation_id: str,
        status: str,
        *,
        clear_error: bool = False,
        **updates: Any,
    ) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await AssetGenerationRepository(session).get(generation_id)
            if entity is None:
                raise NotFoundError("资产生成任务不存在", details={"generation_id": generation_id})
            if status != entity.generation_status and status not in GENERATION_TRANSITIONS.get(
                entity.generation_status, frozenset()
            ):
                raise AssetStateInvalid(
                    "生成状态迁移非法",
                    details={
                        "generation_id": generation_id,
                        "from": entity.generation_status,
                        "to": status,
                    },
                )
            entity.generation_status = status
            if clear_error:
                entity.error_code = None
            for key, value in updates.items():
                setattr(entity, key, value)
            await session.flush()

    async def _current_status(self, generation_id: str) -> str:
        async with self._database.session() as session:
            entity = await AssetGenerationRepository(session).get(generation_id)
        if entity is None:
            raise NotFoundError("资产生成任务不存在", details={"generation_id": generation_id})
        return entity.generation_status

    async def _find_by_idempotency(self, idempotency_key: str) -> AssetGenerationModel | None:
        async with self._database.session() as session:
            entity = await AssetGenerationRepository(session).get_by_idempotency(idempotency_key)
            if entity is not None:
                # 在会话关闭前读取所有标量，避免 detached 属性访问。
                session.expunge(entity)
            return entity

    async def _view_for(self, entity: AssetGenerationModel, *, created: bool) -> GenerationView:
        async with self._database.session() as session:
            asset = await AssetRepository(session).get(entity.asset_id)
            if asset is None:
                raise NotFoundError(
                    "资产生成任务关联资产不存在", details={"asset_id": entity.asset_id}
                )
            project_id = asset.project_id
            outputs = await AssetGenerationOutputRepository(session).list_for_generation(
                entity.generation_id
            )
        return _generation_view(entity, project_id=project_id, outputs=outputs, created=created)

    async def _load_asset(self, project_id: str, asset_id: str) -> AssetModel:
        async with self._database.session() as session:
            asset = await AssetRepository(session).get_active(asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产不存在或不属于该项目",
                    details={"project_id": project_id, "asset_id": asset_id},
                )
            session.expunge(asset)
            return asset

    def _validate_asset(self, asset: AssetModel, kind: str) -> None:
        if asset.lifecycle_status == ASSET_ARCHIVED:
            raise AssetStateInvalid(
                "已归档资产不能生成新版本", details={"asset_id": asset.asset_id}
            )
        expected = _KIND_BY_CATEGORY.get(asset.category)
        if expected is None or expected != kind:
            raise AssetGenerationInvalid(
                "资产类别与生成类型不匹配",
                details={
                    "asset_id": asset.asset_id,
                    "category": asset.category,
                    "kind": kind,
                },
            )

    async def _validate_brief(self, request: GenerationRequest) -> None:
        if request.brief_id is None:
            return
        async with self._database.session() as session:
            entity = await AssetBriefRepository(session).get(request.brief_id)
            if entity is not None:
                session.expunge(entity)
        if entity is None or entity.project_id != request.project_id:
            raise NotFoundError(
                "Asset Brief 不存在或不属于该项目",
                details={"brief_id": request.brief_id, "project_id": request.project_id},
            )
        if entity.asset_id is not None and entity.asset_id != request.asset_id:
            raise AssetBriefInvalid(
                "Asset Brief 绑定了其他资产",
                details={"brief_id": request.brief_id, "asset_id": entity.asset_id},
            )
        if entity.status != BRIEF_APPROVED:
            raise AssetBriefInvalid(
                "只有已批准的 Asset Brief 可以生成资产",
                details={"brief_id": request.brief_id, "status": entity.status},
            )
        if entity.asset_category != request.kind:
            raise AssetBriefInvalid(
                "Asset Brief 类别与生成类型不匹配",
                details={
                    "brief_id": request.brief_id,
                    "category": entity.asset_category,
                    "kind": request.kind,
                },
            )
        constraints = _load(entity.technical_constraints_json, {})
        if not isinstance(constraints, dict):
            constraints = {}
        if (
            "output_count" in constraints
            and int(constraints["output_count"]) != request.output_count
        ):
            raise AssetBriefInvalid(
                "生成数量与 Brief 规格不一致",
                details={
                    "expected": constraints["output_count"],
                    "actual": request.output_count,
                },
            )
        for key in ("width", "height", "format", "transparent_background"):
            if key in constraints and key in request.parameters:
                expected = constraints[key]
                actual = request.parameters[key]
                if isinstance(expected, str) and isinstance(actual, str):
                    equal = expected.strip().lower() == actual.strip().lower()
                else:
                    equal = expected == actual
                if not equal:
                    raise AssetBriefInvalid(
                        "生成参数与 Brief 规格不一致",
                        details={"parameter": key, "expected": expected, "actual": actual},
                    )

    def _adapter_request(
        self,
        request: GenerationRequest,
        resolved: ResolvedAssetProvider,
        *,
        idempotency_key: str,
    ) -> AssetGenerationRequest:
        return AssetGenerationRequest(
            project_id=request.project_id,
            asset_id=request.asset_id,
            kind=request.kind,
            prompt=request.prompt,
            model_key=resolved.model_key,
            provider_id=resolved.provider_id,
            model_id=resolved.model_id,
            parameters=dict(request.parameters),
            output_count=request.output_count,
            timeout_seconds=request.timeout_seconds,
            idempotency_key=idempotency_key,
        )

    def _adapter_request_from_spec(
        self,
        entity: AssetGenerationModel,
        spec: dict[str, Any],
        resolved: ResolvedAssetProvider,
        *,
        project_id: str,
    ) -> AssetGenerationRequest:
        return AssetGenerationRequest(
            project_id=project_id,
            asset_id=entity.asset_id,
            kind=spec.get("kind", resolved.kind),
            prompt=str(spec.get("prompt", "")),
            model_key=resolved.model_key,
            provider_id=resolved.provider_id,
            model_id=resolved.model_id,
            parameters=dict(spec.get("parameters") or {}),
            output_count=int(spec.get("output_count", 1)),
            timeout_seconds=spec.get("timeout_seconds"),
            idempotency_key=entity.idempotency_key,
        )

    def _reserve_budget(
        self,
        request: GenerationRequest,
        resolved: ResolvedAssetProvider,
        adapter_request: AssetGenerationRequest,
    ) -> dict[str, Any]:
        budget = dict(request.budget or {})
        if not budget:
            return {"budget": None, "check": "NOT_CONFIGURED"}
        reservation: dict[str, Any] = {"budget": budget}
        max_outputs = budget.get("max_outputs")
        if max_outputs is not None:
            try:
                limit = int(max_outputs)
            except (TypeError, ValueError) as error:
                raise AssetGenerationInvalid("max_outputs 必须是整数") from error
            if request.output_count > limit:
                raise AssetGenerationInvalid(
                    "生成数量超出预算",
                    details={"requested": request.output_count, "max_outputs": limit},
                )
            reservation["max_outputs"] = limit
        max_cost = budget.get("max_cost")
        estimate = resolved.adapter.estimate_cost(adapter_request)
        if estimate is not None:
            reservation["estimated_cost"] = str(estimate)
        if max_cost is not None:
            try:
                limit_cost = Decimal(str(max_cost))
            except (InvalidOperation, ValueError) as error:
                raise AssetGenerationInvalid("max_cost 必须是数字") from error
            if limit_cost < 0:
                raise AssetGenerationInvalid("max_cost 不能为负数")
            reservation["max_cost"] = str(limit_cost)
            if estimate is None:
                reservation["check"] = "COST_UNAVAILABLE"
            elif estimate > limit_cost:
                raise AssetGenerationInvalid(
                    "预计生成成本超出预算",
                    details={"estimated_cost": str(estimate), "max_cost": str(limit_cost)},
                )
            else:
                reservation["check"] = "PASSED"
        else:
            reservation.setdefault("check", "OUTPUTS_ONLY")
        return reservation

    async def _publish(self, event_type: str, payload: dict[str, Any], *, project_id: str) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(Event.create(event_type, payload, project_id=project_id))
            log_event(
                self._logger,
                logging.INFO,
                "asset.generation.event_published",
                component="asset",
                error_code=None,
            )
        except Exception:  # noqa: BLE001 - 事件失败不阻断已提交元数据
            log_event(
                self._logger,
                logging.WARNING,
                "asset.generation.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )


def _extension(output_format: str) -> str:
    value = output_format.strip().lower()
    if not _EXTENSION_PATTERN.match(value):
        raise AssetGenerationInvalid("生成产物格式非法", details={"format": output_format})
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _provider_job_status(status: str) -> str:
    return {
        ASSET_JOB_SUCCEEDED: GENERATION_SUCCEEDED,
        ASSET_JOB_RUNNING: GENERATION_RUNNING,
        ASSET_JOB_FAILED: GENERATION_FAILED,
        ASSET_JOB_UNKNOWN: GENERATION_UNKNOWN,
    }.get(status, GENERATION_UNKNOWN)
