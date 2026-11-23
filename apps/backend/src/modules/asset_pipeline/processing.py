"""资产处理流水线服务（E8-T09）。

流程：

1. 解析并校验 Processing Graph（DAG、唯一输出、处理器已注册、参数合法）；
2. 校验资产、输入版本与内部存储对象归属；
3. 创建 ``QUEUED`` 任务，执行时转为 ``RUNNING``；
4. 按拓扑顺序执行处理器，逐节点记录 Hash、参数、耗时与资源占用；
5. 成功时把终态产物写入 ``processed`` 区域，创建新的不可变版本并登记存储对象；
6. 失败时记录结构化错误并把任务标记为 ``FAILED``，绝不静默吞掉异常。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.errors import AssetProcessingInvalid, AssetStateInvalid, NotFoundError
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    PROCESSING_FAILED,
    PROCESSING_QUEUED,
    PROCESSING_RUNNING,
    PROCESSING_SUCCEEDED,
    PROCESSING_TRANSITIONS,
    SOURCE_PROJECT_DERIVED,
    STORAGE_PROCESSED,
    AssetProcessingJobModel,
    AssetProcessingStepModel,
    AssetProvenanceModel,
    AssetStorageObjectModel,
)
from modules.asset_pipeline.processing_types import (
    ProcessingArtifact,
    ProcessingContext,
    ProcessingGraph,
    ProcessingLimits,
    ProcessingPayload,
    parse_processing_graph,
)
from modules.asset_pipeline.processors import default_processing_registry
from modules.asset_pipeline.repository import (
    AssetProcessingJobRepository,
    AssetProcessingStepRepository,
    AssetProvenanceRepository,
    AssetRepository,
    AssetStorageObjectRepository,
    AssetVersionRepository,
)
from modules.asset_pipeline.storage import AssetStorage
from modules.asset_pipeline.versioning import AssetVersionService

_MIME_TYPES = {
    "png": "image/png",
    "webp": "image/webp",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "bmp": "image/bmp",
    "gif": "image/gif",
    "tiff": "image/tiff",
    "wav": "audio/wav",
    "glb": "model/gltf-binary",
    "gltf": "model/gltf+json",
    "obj": "model/obj",
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


def _payload_hash(payload: ProcessingPayload) -> str:
    digest = hashlib.sha256()
    for artifact in payload.artifacts:
        digest.update(artifact.format.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(bytes.fromhex(artifact.content_hash))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    project_id: str
    asset_id: str
    input_version_id: str
    graph: Mapping[str, Any] | ProcessingGraph
    idempotency_key: str | None = None
    created_by: str | None = None
    limits: ProcessingLimits | None = None

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise AssetProcessingInvalid("缺少项目 ID")
        if not self.asset_id.strip():
            raise AssetProcessingInvalid("缺少资产 ID")
        if not self.input_version_id.strip():
            raise AssetProcessingInvalid("缺少输入版本 ID")
        if self.idempotency_key is not None and len(self.idempotency_key) > 128:
            raise AssetProcessingInvalid("幂等键不能超过 128 个字符")
        if self.limits is not None and not isinstance(self.limits, ProcessingLimits):
            raise AssetProcessingInvalid("处理限制类型非法")


@dataclass(frozen=True, slots=True)
class ProcessingStepView:
    node_id: str
    processor_id: str
    processor_version: str
    input_hash: str | None
    output_hash: str | None
    parameters: dict[str, Any]
    execution_status: str
    resource_usage: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProcessingOutputView:
    reference: str
    storage_area: str
    content_hash: str
    size_bytes: int
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class ProcessingView:
    job_id: str
    project_id: str
    asset_id: str
    input_version_id: str
    output_version_id: str | None
    status: str
    graph: dict[str, Any]
    steps: tuple[ProcessingStepView, ...]
    outputs: tuple[ProcessingOutputView, ...]
    error_code: str | None
    error_message: str | None
    idempotency_key: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created: bool = True


@dataclass(frozen=True, slots=True)
class _InputSnapshot:
    version_id: str
    content_hash: str
    artifacts: tuple[ProcessingArtifact, ...]


def _step_view(entity: AssetProcessingStepModel) -> ProcessingStepView:
    return ProcessingStepView(
        node_id=entity.node_id,
        processor_id=entity.processor_id,
        processor_version=entity.processor_version,
        input_hash=entity.input_hash,
        output_hash=entity.output_hash,
        parameters=_load(entity.parameters_json, {}),
        execution_status=entity.execution_status,
        resource_usage=_load(entity.resource_usage_json, {}),
        started_at=entity.started_at,
        completed_at=entity.completed_at,
    )


def _output_view(entity: AssetStorageObjectModel) -> ProcessingOutputView:
    return ProcessingOutputView(
        reference=entity.relative_path,
        storage_area=entity.storage_area,
        content_hash=entity.content_hash,
        size_bytes=entity.size_bytes,
        mime_type=entity.mime_type,
    )


def _job_view(
    entity: AssetProcessingJobModel,
    *,
    project_id: str,
    steps: list[AssetProcessingStepModel],
    outputs: list[AssetStorageObjectModel],
    created: bool = True,
) -> ProcessingView:
    metadata = _load(entity.execution_metadata_json, {})
    return ProcessingView(
        job_id=entity.job_id,
        project_id=project_id,
        asset_id=entity.asset_id,
        input_version_id=entity.input_version_id,
        output_version_id=entity.output_version_id,
        status=entity.processing_status,
        graph=_load(entity.processing_graph_json, {}),
        steps=tuple(_step_view(item) for item in steps),
        outputs=tuple(_output_view(item) for item in outputs),
        error_code=metadata.get("error_code"),
        error_message=metadata.get("error_message"),
        idempotency_key=entity.idempotency_key,
        created_at=entity.created_at,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        created=created,
    )


class ProcessingPipelineService:
    """可组合、可复现的资产处理流水线。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        storage: AssetStorage,
        versions: AssetVersionService,
        processors=None,
        events: EventBus | None = None,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._storage = storage
        self._versions = versions
        self._processors = processors or default_processing_registry()
        self._events = events
        self._clock = clock
        self._logger = get_logger("backend.asset.processing")

    async def submit(self, request: ProcessingRequest) -> ProcessingView:
        graph = self._resolve_graph(request)
        self._validate_processors(graph)
        graph_mapping = graph.as_mapping()
        request_hash = self._request_hash(request, graph_mapping)
        idempotency_key = request.idempotency_key or f"proc:{request_hash[:48]}"
        existing = await self._find_by_idempotency(idempotency_key)
        if existing is not None:
            metadata = _load(existing.execution_metadata_json, {})
            if metadata.get("request_hash") != request_hash:
                raise AssetProcessingInvalid(
                    "幂等键已被不同请求占用",
                    details={
                        "job_id": existing.job_id,
                        "idempotency_key": idempotency_key,
                    },
                )
            return await self._view_for(existing, created=False)

        limits = request.limits or ProcessingLimits()
        snapshot = await self._load_input(
            request.project_id, request.asset_id, request.input_version_id, limits
        )
        now = self._clock()
        entity = AssetProcessingJobModel(
            job_id="apjb_" + uuid4().hex[:12],
            asset_id=request.asset_id,
            input_version_id=request.input_version_id,
            output_version_id=None,
            processing_graph_json=_dump(graph_mapping),
            processing_status=PROCESSING_QUEUED,
            execution_metadata_json=_dump(
                {
                    "request_hash": request_hash,
                    "input_content_hash": snapshot.content_hash,
                    "limits": {
                        "max_input_bytes": limits.max_input_bytes,
                        "max_pixels": limits.max_pixels,
                        "max_artifacts": limits.max_artifacts,
                        "max_output_bytes": limits.max_output_bytes,
                        "timeout_seconds": limits.timeout_seconds,
                    },
                }
            ),
            idempotency_key=idempotency_key,
            created_by=request.created_by,
            created_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await AssetProcessingJobRepository(session).add(entity)
        await self._publish(
            "asset.processing.created",
            {
                "job_id": entity.job_id,
                "asset_id": request.asset_id,
                "input_version_id": request.input_version_id,
            },
            project_id=request.project_id,
        )
        await self._execute(
            entity.job_id,
            request,
            graph,
            snapshot.artifacts,
            limits,
            snapshot.content_hash,
        )
        return await self.get(entity.job_id)

    async def get(self, job_id: str) -> ProcessingView:
        async with self._database.session() as session:
            entity = await AssetProcessingJobRepository(session).get(job_id)
            if entity is None:
                raise NotFoundError(
                    "资产处理任务不存在", details={"job_id": job_id}
                )
            asset = await AssetRepository(session).get(entity.asset_id)
            if asset is None:
                raise NotFoundError(
                    "资产处理任务关联资产不存在", details={"asset_id": entity.asset_id}
                )
            steps = await AssetProcessingStepRepository(session).list_for_job(job_id)
            outputs = await self._load_outputs(session, entity.output_version_id)
            return _job_view(
                entity,
                project_id=asset.project_id,
                steps=list(steps),
                outputs=outputs,
                created=False,
            )

    async def list_for_asset(
        self, project_id: str, asset_id: str
    ) -> list[ProcessingView]:
        async with self._database.session() as session:
            asset = await AssetRepository(session).get_active(asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产不存在或不属于该项目",
                    details={"project_id": project_id, "asset_id": asset_id},
                )
            entities = await AssetProcessingJobRepository(session).list_for_asset(asset_id)
            steps = AssetProcessingStepRepository(session)
            views: list[ProcessingView] = []
            for entity in entities:
                node_steps = await steps.list_for_job(entity.job_id)
                outputs = await self._load_outputs(session, entity.output_version_id)
                views.append(
                    _job_view(
                        entity,
                        project_id=asset.project_id,
                        steps=list(node_steps),
                        outputs=outputs,
                        created=False,
                    )
                )
            return views

    # ------------------------------------------------------------------
    # 内部流程
    # ------------------------------------------------------------------

    def _resolve_graph(self, request: ProcessingRequest) -> ProcessingGraph:
        if isinstance(request.graph, ProcessingGraph):
            graph = request.graph
        else:
            graph = parse_processing_graph(request.graph)
        graph.ordered()
        return graph

    def _validate_processors(self, graph: ProcessingGraph) -> None:
        for node in graph.nodes:
            processor = self._processors.get(node.processor)
            processor.validate(node.parameters)

    def _request_hash(self, request: ProcessingRequest, graph: Mapping[str, Any]) -> str:
        payload = {
            "project_id": request.project_id,
            "asset_id": request.asset_id,
            "input_version_id": request.input_version_id,
            "graph": graph,
            "limits": (
                {
                    "max_input_bytes": request.limits.max_input_bytes,
                    "max_pixels": request.limits.max_pixels,
                    "max_artifacts": request.limits.max_artifacts,
                    "max_output_bytes": request.limits.max_output_bytes,
                    "timeout_seconds": request.limits.timeout_seconds,
                }
                if request.limits is not None
                else None
            ),
        }
        return hashlib.sha256(_dump(payload).encode("utf-8")).hexdigest()

    async def _load_input(
        self,
        project_id: str,
        asset_id: str,
        version_id: str,
        limits: ProcessingLimits,
    ) -> _InputSnapshot:
        async with self._database.session() as session:
            asset = await AssetRepository(session).get_active(asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产不存在或不属于该项目",
                    details={"project_id": project_id, "asset_id": asset_id},
                )
            version = await AssetVersionRepository(session).get(version_id)
            if version is None or version.asset_id != asset_id:
                raise NotFoundError(
                    "输入版本不属于该资产",
                    details={"asset_id": asset_id, "version_id": version_id},
                )
            objects = await AssetStorageObjectRepository(session).list_for_version(
                version_id
            )
            if not objects:
                raise AssetProcessingInvalid(
                    "输入版本没有可处理的存储对象",
                    details={"asset_id": asset_id, "version_id": version_id},
                )
            references = [
                {
                    "area": item.storage_area,
                    "path": item.relative_path,
                    "hash": item.content_hash,
                    "size": item.size_bytes,
                }
                for item in objects
            ]
            content_hash = version.content_hash
        total_bytes = sum(int(item["size"]) for item in references)
        if total_bytes > limits.max_input_bytes:
            raise AssetProcessingInvalid(
                "输入文件超过处理大小限制",
                details={"size": total_bytes, "limit": limits.max_input_bytes},
            )
        artifacts: list[ProcessingArtifact] = []
        for item in references:
            data = self._storage.read_bytes(
                project_id, str(item["area"]), str(item["path"])
            )
            if hashlib.sha256(data).hexdigest() != item["hash"]:
                raise AssetProcessingInvalid(
                    "输入文件 Hash 与存储记录不一致",
                    details={"path": item["path"]},
                )
            artifacts.append(
                ProcessingArtifact(
                    data=data,
                    format=_format_from_reference(str(item["path"])),
                    filename_hint=Path(str(item["path"])).name,
                    metadata={"source_area": item["area"]},
                )
            )
        return _InputSnapshot(
            version_id=version_id,
            content_hash=content_hash,
            artifacts=tuple(artifacts),
        )

    async def _execute(
        self,
        job_id: str,
        request: ProcessingRequest,
        graph: ProcessingGraph,
        input_artifacts: tuple[ProcessingArtifact, ...],
        limits: ProcessingLimits,
        input_content_hash: str,
    ) -> None:
        await self._mark_job(job_id, PROCESSING_RUNNING, started_at=self._clock())
        await self._publish(
            "asset.processing.started",
            {"job_id": job_id, "asset_id": request.asset_id},
            project_id=request.project_id,
        )
        context = ProcessingContext.create(request.project_id, request.asset_id, limits)
        payloads: dict[str, ProcessingPayload] = {
            "input": ProcessingPayload(input_artifacts)
        }
        try:
            for node in graph.ordered():
                context.check_deadline()
                dependencies: list[ProcessingArtifact] = []
                for dependency in node.depends_on:
                    dependencies.extend(payloads[dependency].artifacts)
                payload = ProcessingPayload(tuple(dependencies))
                processor = self._processors.get(node.processor)
                started = self._clock()
                input_hash = _payload_hash(payload)
                try:
                    output = processor.process(payload, node.parameters, context)
                except AssetProcessingInvalid as error:
                    await self._record_step(
                        job_id,
                        node.node_id,
                        processor.processor_id,
                        processor.version,
                        input_hash,
                        None,
                        node.parameters,
                        "FAILED",
                        {
                            "error_code": error.code,
                            "error_message": error.message,
                            "input_bytes": _payload_bytes(payload),
                        },
                        started,
                        self._clock(),
                    )
                    raise
                context.check_deadline()
                context.check_artifacts(len(output.artifacts))
                output_bytes = _payload_bytes(output)
                if output_bytes > limits.max_output_bytes:
                    raise AssetProcessingInvalid(
                        "处理产物超过大小限制",
                        details={
                            "size": output_bytes,
                            "limit": limits.max_output_bytes,
                        },
                    )
                completed = self._clock()
                output_hash = _payload_hash(output)
                await self._record_step(
                    job_id,
                    node.node_id,
                    processor.processor_id,
                    processor.version,
                    input_hash,
                    output_hash,
                    node.parameters,
                    "SUCCEEDED",
                    {
                        "input_bytes": _payload_bytes(payload),
                        "output_bytes": output_bytes,
                        "artifacts": len(output.artifacts),
                        "elapsed_ms": max(
                            0,
                            int((completed - started).total_seconds() * 1000),
                        ),
                    },
                    started,
                    completed,
                )
                payloads[node.node_id] = output
            await self._finalize(
                job_id,
                request,
                graph,
                payloads[graph.terminal],
                input_content_hash,
            )
        except Exception as error:
            await self._fail(job_id, error)
            await self._publish(
                "asset.processing.failed",
                {
                    "job_id": job_id,
                    "asset_id": request.asset_id,
                    "error_code": _error_code(error),
                },
                project_id=request.project_id,
            )
            raise

    async def _finalize(
        self,
        job_id: str,
        request: ProcessingRequest,
        graph: ProcessingGraph,
        payload: ProcessingPayload,
        input_content_hash: str,
    ) -> None:
        outputs: list[dict[str, Any]] = []
        hashes: list[str] = []
        for index, artifact in enumerate(payload.artifacts):
            extension = artifact.format.strip().lower()
            filename = f"{job_id}_{index:02d}.{extension}"
            relative_path = f"{request.asset_id}/{filename}"
            written = self._storage.write_bytes(
                request.project_id,
                STORAGE_PROCESSED,
                relative_path,
                artifact.data,
            )
            hashes.append(str(written["content_hash"]))
            outputs.append(
                {
                    **written,
                    "mime_type": _MIME_TYPES.get(extension, "application/octet-stream"),
                    "artifact": artifact,
                }
            )
        composite_hash = hashlib.sha256("".join(hashes).encode("ascii")).hexdigest()
        processors = [
            {"node_id": node.node_id, "processor_id": node.processor}
            for node in graph.nodes
        ]
        processor_versions = []
        for node in graph.nodes:
            processor = self._processors.get(node.processor)
            processor_versions.append(
                {
                    "node_id": node.node_id,
                    "processor_id": processor.processor_id,
                    "processor_version": processor.version,
                }
            )
        version = await self._versions.create_version(
            request.asset_id,
            content_hash=composite_hash,
            source_type=SOURCE_PROJECT_DERIVED,
            metadata={
                "processing_job_id": job_id,
                "input_version_id": request.input_version_id,
                "graph": graph.as_mapping(),
                "processors": processors,
                "outputs": [
                    {
                        "content_hash": item["content_hash"],
                        "format": item["artifact"].format,
                        "size_bytes": item["size_bytes"],
                    }
                    for item in outputs
                ],
            },
            change_reason="asset_processing",
            parent_version_id=request.input_version_id,
            created_by=request.created_by,
            make_current=True,
        )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            provenance_repository = AssetProvenanceRepository(session)
            if await provenance_repository.get_for_version(version.version_id) is None:
                await provenance_repository.add(
                    AssetProvenanceModel(
                        provenance_id="prv_" + uuid4().hex[:12],
                        asset_id=request.asset_id,
                        asset_version_id=version.version_id,
                        source_type=SOURCE_PROJECT_DERIVED,
                        provider_id=None,
                        model_id=None,
                        model_version=None,
                        generation_id=None,
                        request_reference=job_id,
                        prompt_version_id=None,
                        seed=None,
                        input_hashes_json=_dump([input_content_hash]),
                        output_hashes_json=_dump(hashes),
                        processing_graph_json=_dump(graph.as_mapping()),
                        processor_versions_json=_dump(processor_versions),
                        operator_agent_id=None,
                        operator_user_id=request.created_by,
                        license_reference=None,
                        external_source_reference=None,
                        created_at=now,
                    )
                )
            storage_repository = AssetStorageObjectRepository(session)
            for item in outputs:
                await storage_repository.add(
                    AssetStorageObjectModel(
                        object_id="asob_" + uuid4().hex[:12],
                        project_id=request.project_id,
                        asset_version_id=version.version_id,
                        storage_area=STORAGE_PROCESSED,
                        relative_path=item["relative_path"],
                        content_hash=item["content_hash"],
                        size_bytes=item["size_bytes"],
                        mime_type=item["mime_type"],
                        created_at=now,
                    )
                )
        await self._mark_job(
            job_id,
            PROCESSING_SUCCEEDED,
            output_version_id=version.version_id,
            completed_at=now,
        )
        await self._publish(
            "asset.processing.succeeded",
            {
                "job_id": job_id,
                "asset_id": request.asset_id,
                "input_version_id": request.input_version_id,
                "output_version_id": version.version_id,
            },
            project_id=request.project_id,
        )

    async def _record_step(
        self,
        job_id: str,
        node_id: str,
        processor_id: str,
        processor_version: str,
        input_hash: str | None,
        output_hash: str | None,
        parameters: Mapping[str, Any],
        execution_status: str,
        resource_usage: Mapping[str, Any],
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        async with self._database.session() as session, transaction(session):
            await AssetProcessingStepRepository(session).add(
                AssetProcessingStepModel(
                    step_id="apst_" + uuid4().hex[:12],
                    job_id=job_id,
                    node_id=node_id,
                    processor_id=processor_id,
                    processor_version=processor_version,
                    input_hash=input_hash,
                    output_hash=output_hash,
                    parameters_json=_dump(parameters),
                    execution_status=execution_status,
                    resource_usage_json=_dump(dict(resource_usage)),
                    started_at=started_at,
                    completed_at=completed_at,
                )
            )

    async def _mark_job(
        self,
        job_id: str,
        status: str,
        *,
        metadata_updates: Mapping[str, Any] | None = None,
        **updates: Any,
    ) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await AssetProcessingJobRepository(session).get(job_id)
            if entity is None:
                raise NotFoundError(
                    "资产处理任务不存在", details={"job_id": job_id}
                )
            if status != entity.processing_status and status not in PROCESSING_TRANSITIONS.get(
                entity.processing_status, frozenset()
            ):
                raise AssetStateInvalid(
                    "处理状态迁移非法",
                    details={
                        "job_id": job_id,
                        "from": entity.processing_status,
                        "to": status,
                    },
                )
            entity.processing_status = status
            for key, value in updates.items():
                setattr(entity, key, value)
            if metadata_updates:
                metadata = _load(entity.execution_metadata_json, {})
                metadata.update(metadata_updates)
                entity.execution_metadata_json = _dump(metadata)
            await session.flush()

    async def _fail(self, job_id: str, error: Exception) -> None:
        async with self._database.session() as session:
            entity = await AssetProcessingJobRepository(session).get(job_id)
        if entity is None:
            return
        try:
            await self._mark_job(
                job_id,
                PROCESSING_FAILED,
                metadata_updates={
                    "error_code": _error_code(error),
                    "error_message": str(error),
                },
                completed_at=self._clock(),
            )
        except AssetStateInvalid:
            log_event(
                self._logger,
                logging.WARNING,
                "asset.processing.fail_transition_rejected",
                component="asset",
                error_code="ASSET_STATE_INVALID",
            )

    async def _find_by_idempotency(
        self, idempotency_key: str
    ) -> AssetProcessingJobModel | None:
        async with self._database.session() as session:
            entity = await AssetProcessingJobRepository(session).get_by_idempotency(
                idempotency_key
            )
            if entity is not None:
                session.expunge(entity)
            return entity

    async def _view_for(
        self, entity: AssetProcessingJobModel, *, created: bool
    ) -> ProcessingView:
        async with self._database.session() as session:
            asset = await AssetRepository(session).get(entity.asset_id)
            if asset is None:
                raise NotFoundError(
                    "资产处理任务关联资产不存在", details={"asset_id": entity.asset_id}
                )
            steps = await AssetProcessingStepRepository(session).list_for_job(
                entity.job_id
            )
            outputs = await self._load_outputs(session, entity.output_version_id)
            return _job_view(
                entity,
                project_id=asset.project_id,
                steps=list(steps),
                outputs=outputs,
                created=created,
            )

    async def _load_outputs(
        self, session, output_version_id: str | None
    ) -> list[AssetStorageObjectModel]:
        if not output_version_id:
            return []
        objects = await AssetStorageObjectRepository(session).list_for_version(
            output_version_id
        )
        return [item for item in objects if item.storage_area == STORAGE_PROCESSED]

    async def _publish(
        self, event_type: str, payload: dict[str, Any], *, project_id: str
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(
                Event.create(event_type, payload, project_id=project_id)
            )
        except Exception:  # noqa: BLE001 - 事件失败不阻断已提交任务
            log_event(
                self._logger,
                logging.WARNING,
                "asset.processing.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )


def _payload_bytes(payload: ProcessingPayload) -> int:
    return sum(len(artifact.data) for artifact in payload.artifacts)


def _format_from_reference(reference: str) -> str:
    suffix = Path(reference).suffix.lstrip(".").strip().lower()
    if not suffix or len(suffix) > 8 or not suffix.isalnum():
        return "bin"
    return suffix


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    return "ASSET_PROCESSING_FAILED"
