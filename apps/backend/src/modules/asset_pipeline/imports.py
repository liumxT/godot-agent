"""Godot 导入管线（E8-T11）。

原则：

- 文件写入成功不等于导入成功；只有 Godot Editor 真实完成资源导入才记录 ``IMPORTED``；
- 导入命令通过 Editor Bridge 下发，UID 必须来自 Godot 返回值，禁止自行生成或按路径推测；
- 目标文件必须已经存在于项目目录，且内容 Hash 属于该 AssetVersion 的存储对象，
  项目写入仍由 Tool System 完成；
- Editor 超时或断线时标记 ``UNKNOWN``，不重复导入，由 ``refresh`` 只读核验后恢复；
- 每次终态都保存导入证据（源文件 Hash、路径、会话、Godot 版本、结果与 UID）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.errors import (
    AssetImportInvalid,
    AssetStateInvalid,
    EditorCommandTimeout,
    EditorNotConnected,
    NotFoundError,
)
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    IMPORT_FAILED,
    IMPORT_IMPORTED,
    IMPORT_IMPORTING,
    IMPORT_REQUESTED,
    IMPORT_TRANSITIONS,
    IMPORT_UNKNOWN,
    AssetImportEvidenceModel,
    AssetImportJobModel,
)
from modules.asset_pipeline.repository import (
    AssetImportEvidenceRepository,
    AssetImportJobRepository,
    AssetRepository,
    AssetStorageObjectRepository,
    AssetVersionRepository,
)
from modules.editor_command.hub import EDITOR_COMMAND_ACTION
from modules.editor_session.models import BINDING_CONNECTED
from modules.editor_session.repository import EditorSessionRepository

_STATUS_SUCCEEDED = "SUCCEEDED"
_STATUS_FAILED = "FAILED"
_STATUS_UNKNOWN = "UNKNOWN"
_PHASE_IMPORTED = "IMPORTED"
_PHASE_IMPORTING = "IMPORTING"
_PHASE_FAILED = "FAILED"
_UID_PREFIX = "uid://"
_TERMINAL_IMPORT_STATUSES = frozenset({IMPORT_IMPORTED, IMPORT_FAILED})

__all__ = ["GodotImportService", "ImportJobView", "ImportRequest", "normalize_res_path"]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def normalize_res_path(path: str) -> str:
    """校验 Godot 资源路径，拒绝越界与编辑器缓存目录。"""

    value = (path or "").strip().replace("\\", "/")
    if not value.startswith("res://"):
        raise AssetImportInvalid("导入路径必须是 res:// 资源路径", details={"path": path})
    if value in ("res://", "res:///"):
        raise AssetImportInvalid("导入路径不能是项目根目录", details={"path": path})
    segments = value[len("res://") :].split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise AssetImportInvalid("导入路径包含非法路径段", details={"path": path})
    if value.startswith("res://.godot/"):
        raise AssetImportInvalid("不能导入 Godot 缓存目录", details={"path": path})
    return value


@dataclass(frozen=True, slots=True)
class ImportRequest:
    project_id: str
    asset_version_id: str
    target_path: str
    session_id: str | None = None
    changeset_id: str | None = None
    resource_type: str | None = None
    idempotency_key: str | None = None
    created_by: str | None = None
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise AssetImportInvalid("缺少项目 ID")
        if not self.asset_version_id.strip():
            raise AssetImportInvalid("缺少资产版本 ID")
        normalize_res_path(self.target_path)
        if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise AssetImportInvalid("导入超时时间必须大于 0")
        if self.idempotency_key is not None and len(self.idempotency_key) > 128:
            raise AssetImportInvalid("幂等键不能超过 128 个字符")


@dataclass(frozen=True, slots=True)
class ImportEvidenceView:
    evidence_id: str
    editor_session_id: str | None
    source_file_hash: str
    target_path: str
    import_started_at: datetime | None
    import_completed_at: datetime | None
    godot_version: str | None
    result: dict[str, Any]
    resource_uid: str | None
    resource_type: str | None
    metadata: dict[str, Any]
    evidence_reference: str | None


@dataclass(frozen=True, slots=True)
class ImportJobView:
    import_job_id: str
    project_id: str
    asset_version_id: str
    target_path: str
    godot_resource_type: str | None
    import_status: str
    godot_uid: str | None
    editor_session_id: str | None
    changeset_id: str | None
    idempotency_key: str | None
    error_code: str | None
    error_message: str | None
    evidence: ImportEvidenceView | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created: bool = True


def _evidence_view(entity: AssetImportEvidenceModel) -> ImportEvidenceView:
    result = _load(entity.import_result_json, {})
    return ImportEvidenceView(
        evidence_id=entity.evidence_id,
        editor_session_id=entity.editor_session_id,
        source_file_hash=entity.source_file_hash,
        target_path=entity.target_path,
        import_started_at=entity.import_started_at,
        import_completed_at=entity.import_completed_at,
        godot_version=entity.godot_version,
        result=result if isinstance(result, dict) else {},
        resource_uid=entity.resource_uid,
        resource_type=entity.resource_type,
        metadata=_load(entity.import_metadata_json, {}),
        evidence_reference=entity.evidence_reference,
    )


def _job_view(
    entity: AssetImportJobModel,
    *,
    evidence: AssetImportEvidenceModel | None,
    created: bool = True,
) -> ImportJobView:
    view = _evidence_view(evidence) if evidence is not None else None
    result = view.result if view is not None else {}
    return ImportJobView(
        import_job_id=entity.import_job_id,
        project_id=entity.project_id,
        asset_version_id=entity.asset_version_id,
        target_path=entity.target_path,
        godot_resource_type=entity.godot_resource_type,
        import_status=entity.import_status,
        godot_uid=entity.godot_uid,
        editor_session_id=entity.editor_session_id,
        changeset_id=entity.changeset_id,
        idempotency_key=entity.idempotency_key,
        error_code=result.get("error_code"),
        error_message=result.get("error_message"),
        evidence=view,
        created_at=entity.created_at,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        created=created,
    )


class GodotImportService:
    """真实 Godot 导入与证据收集。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        hub,
        projects,
        events: EventBus | None = None,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._hub = hub
        self._projects = projects
        self._events = events
        self._clock = clock
        self._logger = get_logger("backend.asset.import")

    async def submit(self, request: ImportRequest) -> ImportJobView:
        target_path = normalize_res_path(request.target_path)
        project = await self._projects.get(request.project_id)
        await self._load_version(request.project_id, request.asset_version_id)
        hashes = await self._version_hashes(request.asset_version_id)
        source_hash = self._project_file_hash(project.project_root, target_path)
        if source_hash not in hashes:
            raise AssetImportInvalid(
                "目标文件内容不属于该资产版本，请先通过工具系统完成项目写入",
                details={
                    "project_id": request.project_id,
                    "asset_version_id": request.asset_version_id,
                    "target_path": target_path,
                },
            )
        idempotency_key = request.idempotency_key or self._default_key(
            request.project_id, request.asset_version_id, target_path
        )
        existing = await self._find_by_idempotency(idempotency_key)
        if existing is not None:
            if (
                existing.asset_version_id != request.asset_version_id
                or existing.target_path != target_path
                or existing.project_id != request.project_id
            ):
                raise AssetImportInvalid(
                    "幂等键已被不同导入请求占用",
                    details={
                        "import_job_id": existing.import_job_id,
                        "idempotency_key": idempotency_key,
                    },
                )
            return await self._view_for(existing, created=False)

        session = await self._resolve_session(request.project_id, request.session_id)
        connection = self._hub.get(session.session_id)
        if connection is None:
            raise EditorNotConnected(
                "编辑器未连接，无法执行导入",
                details={
                    "project_id": request.project_id,
                    "session_id": session.session_id,
                },
            )
        job = await self._create_job(
            request,
            target_path=target_path,
            idempotency_key=idempotency_key,
            session_id=session.session_id,
        )
        await self._publish(
            "asset.import.requested",
            {
                "import_job_id": job.import_job_id,
                "asset_version_id": request.asset_version_id,
                "target_path": target_path,
            },
            project_id=request.project_id,
        )
        payload = {
            "execution_id": job.import_job_id,
            "tool_name": "godot.asset.import",
            "tool_version": 1,
            "arguments": {"path": target_path},
            "resource_scope": [f"file:{target_path}"],
            "timeout_seconds": request.timeout_seconds,
        }
        try:
            response = await connection.send_command(
                EDITOR_COMMAND_ACTION, payload, timeout=request.timeout_seconds
            )
        except EditorCommandTimeout as error:
            await self._finish(
                job.import_job_id,
                IMPORT_UNKNOWN,
                source_hash=source_hash,
                godot_version=session.godot_version,
                result={
                    "error_code": error.code,
                    "error_message": error.message,
                    "phase": "UNKNOWN",
                },
                uid=None,
                resource_type=None,
            )
            await self._publish_unknown(job.import_job_id, request, error.code)
            raise
        except EditorNotConnected as error:
            await self._finish(
                job.import_job_id,
                IMPORT_UNKNOWN,
                source_hash=source_hash,
                godot_version=session.godot_version,
                result={
                    "error_code": error.code,
                    "error_message": error.message,
                    "phase": "UNKNOWN",
                },
                uid=None,
                resource_type=None,
            )
            await self._publish_unknown(job.import_job_id, request, error.code)
            raise
        return await self._apply_response(
            job.import_job_id,
            response,
            source_hash=source_hash,
            godot_version=session.godot_version,
            raise_on_failure=True,
        )

    async def refresh(self, import_job_id: str) -> ImportJobView:
        """只读核验导入状态；用于超时/断线后的恢复判断，绝不重复导入。"""

        job = await self._get_entity(import_job_id)
        if job.import_status in _TERMINAL_IMPORT_STATUSES:
            return await self._view_for(job, created=False)
        if job.editor_session_id is None:
            await self._mark_unknown(import_job_id, "EDITOR_SESSION_MISSING")
            return await self.get(import_job_id)
        connection = self._hub.get(job.editor_session_id)
        if connection is None:
            await self._mark_unknown(import_job_id, "EDITOR_NOT_CONNECTED")
            return await self.get(import_job_id)
        project = await self._projects.get(job.project_id)
        current_hash = self._project_file_hash_or_none(project.project_root, job.target_path)
        if current_hash is None:
            await self._mark_unknown(import_job_id, "SOURCE_FILE_MISSING")
            return await self.get(import_job_id)
        hashes = await self._version_hashes(job.asset_version_id)
        if current_hash not in hashes:
            await self._finish(
                import_job_id,
                IMPORT_FAILED,
                source_hash=current_hash,
                godot_version=None,
                result={
                    "error_code": "SOURCE_HASH_MISMATCH",
                    "error_message": "源文件 Hash 与版本记录不一致",
                    "phase": _PHASE_FAILED,
                },
                uid=None,
                resource_type=None,
            )
            return await self.get(import_job_id)
        payload = {
            "execution_id": import_job_id,
            "tool_name": "godot.asset.import_status",
            "tool_version": 1,
            "arguments": {"path": job.target_path},
            "resource_scope": [f"file:{job.target_path}"],
        }
        try:
            response = await connection.send_command(EDITOR_COMMAND_ACTION, payload, timeout=5.0)
        except (EditorCommandTimeout, EditorNotConnected) as error:
            await self._mark_unknown(import_job_id, error.code)
            return await self.get(import_job_id)
        return await self._apply_response(
            import_job_id,
            response,
            source_hash=current_hash,
            godot_version=None,
            raise_on_failure=False,
        )

    async def get(self, import_job_id: str) -> ImportJobView:
        job = await self._get_entity(import_job_id)
        return await self._view_for(job, created=False)

    async def list_for_version(self, project_id: str, asset_version_id: str) -> list[ImportJobView]:
        await self._load_version(project_id, asset_version_id)
        async with self._database.session() as session:
            entities = await AssetImportJobRepository(session).list_for_version(asset_version_id)
            evidence = AssetImportEvidenceRepository(session)
            views: list[ImportJobView] = []
            for entity in entities:
                item = await evidence.get_for_job(entity.import_job_id)
                views.append(_job_view(entity, evidence=item, created=False))
            return views

    # ------------------------------------------------------------------
    # 内部流程
    # ------------------------------------------------------------------

    def _default_key(self, project_id: str, asset_version_id: str, target_path: str) -> str:
        seed = f"{project_id}:{asset_version_id}:{target_path}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return f"import:{digest[:48]}"

    async def _load_version(self, project_id: str, asset_version_id: str) -> None:
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
            session.expunge(version)
            session.expunge(asset)

    async def _version_hashes(self, asset_version_id: str) -> set[str]:
        async with self._database.session() as session:
            objects = await AssetStorageObjectRepository(session).list_for_version(asset_version_id)
            hashes = {item.content_hash for item in objects}
        if not hashes:
            raise AssetImportInvalid(
                "资产版本没有存储对象，无法核验导入",
                details={"asset_version_id": asset_version_id},
            )
        return hashes

    def _project_file_hash(self, project_root: str, target_path: str) -> str:
        digest = self._project_file_hash_or_none(project_root, target_path)
        if digest is None:
            raise AssetImportInvalid(
                "目标文件不存在或越界，不能导入",
                details={"target_path": target_path},
            )
        return digest

    def _project_file_hash_or_none(self, project_root: str, target_path: str) -> str | None:
        relative = target_path[len("res://") :]
        base = Path(project_root).resolve()
        candidate = (base / relative).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            return None
        try:
            return hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            return None

    async def _resolve_session(self, project_id: str, session_id: str | None):
        async with self._database.session() as session:
            repository = EditorSessionRepository(session)
            if session_id is not None:
                entity = await repository.get(session_id)
                if (
                    entity is None
                    or entity.project_id != project_id
                    or entity.binding_status != BINDING_CONNECTED
                ):
                    raise EditorNotConnected(
                        "编辑器会话未连接或不属于该项目",
                        details={"project_id": project_id, "session_id": session_id},
                    )
                session.expunge(entity)
                return entity
            candidates = await repository.list_by_project(project_id)
            for entity in candidates:
                if entity.binding_status == BINDING_CONNECTED:
                    session.expunge(entity)
                    return entity
        raise EditorNotConnected("项目没有已连接的编辑器会话", details={"project_id": project_id})

    async def _create_job(
        self,
        request: ImportRequest,
        *,
        target_path: str,
        idempotency_key: str,
        session_id: str,
    ) -> AssetImportJobModel:
        now = self._clock()
        entity = AssetImportJobModel(
            import_job_id="aimp_" + uuid4().hex[:12],
            project_id=request.project_id,
            asset_version_id=request.asset_version_id,
            target_path=target_path,
            godot_resource_type=request.resource_type,
            import_status=IMPORT_REQUESTED,
            godot_uid=None,
            import_evidence_id=None,
            changeset_id=request.changeset_id,
            editor_session_id=session_id,
            idempotency_key=idempotency_key,
            created_by=request.created_by,
            created_at=now,
            started_at=now,
            completed_at=None,
        )
        async with self._database.session() as session, transaction(session):
            await AssetImportJobRepository(session).add(entity)
        return entity

    async def _apply_response(
        self,
        import_job_id: str,
        response,
        *,
        source_hash: str,
        godot_version: str | None,
        raise_on_failure: bool,
    ) -> ImportJobView:
        data = response.data if isinstance(response.data, dict) else {}
        job = await self._get_entity(import_job_id)
        if job.import_status == IMPORT_REQUESTED:
            await self._mark_status(import_job_id, IMPORT_IMPORTING)
            job = await self._get_entity(import_job_id)
        output = data.get("output") if isinstance(data.get("output"), dict) else {}
        status = str(data.get("status", "")).upper()
        phase = str(output.get("phase", "")).upper()
        if not response.success:
            error = response.error if isinstance(response.error, dict) else {}
            code = str(error.get("code") or "TOOL_EXECUTION_FAILED")
            message = str(error.get("message") or "Godot 导入失败")
            await self._finish(
                import_job_id,
                IMPORT_FAILED,
                source_hash=source_hash,
                godot_version=godot_version,
                result={
                    "error_code": code,
                    "error_message": message,
                    "phase": _PHASE_FAILED,
                    "checks": data.get("checks"),
                },
                uid=None,
                resource_type=None,
            )
            if raise_on_failure:
                await self._publish_failed(import_job_id, job.project_id, code)
                raise AssetImportInvalid(
                    message,
                    details={"import_job_id": import_job_id, "error_code": code},
                )
            return await self.get(import_job_id)

        if status == _STATUS_UNKNOWN:
            await self._finish(
                import_job_id,
                IMPORT_UNKNOWN,
                source_hash=source_hash,
                godot_version=godot_version,
                result={
                    "error_code": "IMPORT_UNKNOWN",
                    "error_message": "Godot 导入结果未知",
                    "phase": "UNKNOWN",
                    "checks": data.get("checks"),
                },
                uid=None,
                resource_type=None,
            )
            return await self.get(import_job_id)

        if phase == _PHASE_IMPORTED:
            uid = str(output.get("resource_uid") or "").strip()
            if not uid.startswith(_UID_PREFIX):
                await self._finish(
                    import_job_id,
                    IMPORT_FAILED,
                    source_hash=source_hash,
                    godot_version=godot_version,
                    result={
                        "error_code": "IMPORT_UID_MISSING",
                        "error_message": "Godot 未返回真实资源 UID",
                        "phase": phase,
                        "checks": data.get("checks"),
                    },
                    uid=None,
                    resource_type=None,
                )
                await self._publish_failed(import_job_id, job.project_id, "IMPORT_UID_MISSING")
                raise AssetImportInvalid(
                    "Godot 未返回真实资源 UID，不能标记导入成功",
                    details={"import_job_id": import_job_id},
                )
            resource_type = str(output.get("resource_type") or "").strip() or None
            await self._finish(
                import_job_id,
                IMPORT_IMPORTED,
                source_hash=source_hash,
                godot_version=godot_version or str(output.get("godot_version") or "") or None,
                result={
                    "status": status or _STATUS_SUCCEEDED,
                    "phase": phase,
                    "checks": data.get("checks"),
                    "evidence_refs": data.get("evidence_refs"),
                    "file_size": output.get("file_size"),
                    "modified_time": output.get("modified_time"),
                },
                uid=uid,
                resource_type=resource_type,
                metadata={
                    "path": output.get("path"),
                    "scanning": output.get("scanning"),
                    "imported": output.get("imported"),
                },
            )
            await self._publish(
                "asset.import.succeeded",
                {
                    "import_job_id": import_job_id,
                    "resource_uid": uid,
                    "resource_type": resource_type,
                },
                project_id=job.project_id,
            )
            return await self.get(import_job_id)

        if status == _STATUS_FAILED or phase == _PHASE_FAILED:
            await self._finish(
                import_job_id,
                IMPORT_FAILED,
                source_hash=source_hash,
                godot_version=godot_version,
                result={
                    "error_code": "IMPORT_FAILED",
                    "error_message": "Godot 文件系统未完成资源导入",
                    "phase": _PHASE_FAILED,
                    "checks": data.get("checks"),
                },
                uid=None,
                resource_type=None,
            )
            if raise_on_failure:
                await self._publish_failed(import_job_id, job.project_id, "IMPORT_FAILED")
                raise AssetImportInvalid(
                    "Godot 文件系统未完成资源导入",
                    details={"import_job_id": import_job_id},
                )
            return await self.get(import_job_id)

        if phase == _PHASE_IMPORTING:
            await self._mark_status(import_job_id, IMPORT_IMPORTING)
            return await self.get(import_job_id)

        await self._finish(
            import_job_id,
            IMPORT_UNKNOWN,
            source_hash=source_hash,
            godot_version=godot_version,
            result={
                "error_code": "IMPORT_UNKNOWN",
                "error_message": "Godot 返回了无法识别的导入结果",
                "phase": phase or "UNKNOWN",
                "checks": data.get("checks"),
            },
            uid=None,
            resource_type=None,
        )
        return await self.get(import_job_id)

    async def _mark_status(self, import_job_id: str, status: str) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await AssetImportJobRepository(session).get(import_job_id)
            if entity is None:
                raise NotFoundError("资产导入任务不存在", details={"import_job_id": import_job_id})
            if status != entity.import_status and status not in IMPORT_TRANSITIONS.get(
                entity.import_status, frozenset()
            ):
                raise AssetStateInvalid(
                    "导入状态迁移非法",
                    details={
                        "import_job_id": import_job_id,
                        "from": entity.import_status,
                        "to": status,
                    },
                )
            entity.import_status = status
            await session.flush()

    async def _finish(
        self,
        import_job_id: str,
        status: str,
        *,
        source_hash: str,
        godot_version: str | None,
        result: dict[str, Any],
        uid: str | None,
        resource_type: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            job = await AssetImportJobRepository(session).get(import_job_id)
            if job is None:
                raise NotFoundError("资产导入任务不存在", details={"import_job_id": import_job_id})
            if status != job.import_status and status not in IMPORT_TRANSITIONS.get(
                job.import_status, frozenset()
            ):
                raise AssetStateInvalid(
                    "导入状态迁移非法",
                    details={
                        "import_job_id": import_job_id,
                        "from": job.import_status,
                        "to": status,
                    },
                )
            job.import_status = status
            job.completed_at = now
            job.godot_uid = uid
            if resource_type:
                job.godot_resource_type = resource_type
            evidence = AssetImportEvidenceModel(
                evidence_id="aiev_" + uuid4().hex[:12],
                import_job_id=import_job_id,
                project_id=job.project_id,
                editor_session_id=job.editor_session_id,
                asset_version_id=job.asset_version_id,
                source_file_hash=source_hash,
                target_path=job.target_path,
                import_started_at=job.started_at,
                import_completed_at=now,
                godot_version=godot_version,
                import_result_json=_dump(result),
                resource_uid=uid,
                resource_type=resource_type,
                import_metadata_json=_dump(metadata or {}),
                evidence_reference=uid,
                created_at=now,
            )
            await AssetImportEvidenceRepository(session).add(evidence)
            job.import_evidence_id = evidence.evidence_id
            await session.flush()

    async def _mark_unknown(self, import_job_id: str, error_code: str) -> None:
        async with self._database.session() as session:
            job = await AssetImportJobRepository(session).get(import_job_id)
            if job is None:
                return
            entity = job
            session.expunge(entity)
        if entity.import_status in _TERMINAL_IMPORT_STATUSES:
            return
        if entity.import_status == IMPORT_UNKNOWN:
            return
        source_hash = ""
        try:
            project = await self._projects.get(entity.project_id)
            current = self._project_file_hash_or_none(project.project_root, entity.target_path)
            source_hash = current or ""
        except Exception:  # noqa: BLE001 - 无法读取项目时保留空 Hash，不阻断 UNKNOWN 记录
            source_hash = ""
        await self._finish(
            import_job_id,
            IMPORT_UNKNOWN,
            source_hash=source_hash,
            godot_version=None,
            result={"error_code": error_code, "error_message": "无法确认导入结果"},
            uid=None,
            resource_type=None,
        )

    async def _publish_unknown(self, import_job_id: str, request: ImportRequest, code: str) -> None:
        await self._publish(
            "asset.import.unknown",
            {"import_job_id": import_job_id, "error_code": code},
            project_id=request.project_id,
        )

    async def _publish_failed(self, import_job_id: str, project_id: str, code: str) -> None:
        await self._publish(
            "asset.import.failed",
            {"import_job_id": import_job_id, "error_code": code},
            project_id=project_id,
        )

    async def _find_by_idempotency(self, idempotency_key: str) -> AssetImportJobModel | None:
        async with self._database.session() as session:
            entity = await AssetImportJobRepository(session).get_by_idempotency(idempotency_key)
            if entity is not None:
                session.expunge(entity)
            return entity

    async def _get_entity(self, import_job_id: str) -> AssetImportJobModel:
        async with self._database.session() as session:
            entity = await AssetImportJobRepository(session).get(import_job_id)
            if entity is None:
                raise NotFoundError("资产导入任务不存在", details={"import_job_id": import_job_id})
            session.expunge(entity)
            return entity

    async def _view_for(self, entity: AssetImportJobModel, *, created: bool) -> ImportJobView:
        async with self._database.session() as session:
            evidence = await AssetImportEvidenceRepository(session).get_for_job(
                entity.import_job_id
            )
        return _job_view(entity, evidence=evidence, created=created)

    async def _publish(
        self, event_type: str, payload: dict[str, Any], *, project_id: str | None
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(Event.create(event_type, payload, project_id=project_id))
        except Exception:  # noqa: BLE001 - 事件失败不阻断导入结果
            log_event(
                self._logger,
                logging.WARNING,
                "asset.import.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )
