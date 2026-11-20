"""快照校验、存储、TTL 与保留策略（E3-T11）。

字段集合与 ``packages/contracts/bridge/snapshot.schema.json`` 保持一致：
未知字段一律拒绝，避免契约漂移。 ``snapshot_version`` 在同一 Session 内
必须严格递增；重复 ``snapshot_id`` 视为幂等重传。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.errors import RequestTooLarge, SnapshotUnavailable, ValidationFailed
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.snapshot.models import SnapshotModel
from modules.snapshot.repository import SnapshotRepository

MAX_SNAPSHOT_BYTES = 256 * 1024
DEFAULT_TTL_SECONDS = 900
DEFAULT_KEEP_PER_SESSION = 5

SNAPSHOT_FIELDS = frozenset(
    {
        "snapshot_id",
        "session_id",
        "project_id",
        "editor_instance_id",
        "snapshot_version",
        "last_event_sequence",
        "created_at",
        "editor_status",
        "project_status",
        "active_scene",
        "current_selection",
        "unsaved_resources",
        "run_status",
        "import_status",
        "truncated",
    }
)
EDITOR_STATUSES = frozenset({"READY", "BUSY", "IMPORTING", "UNKNOWN"})
PROJECT_STATUSES = frozenset({"READY", "LOADING", "MISSING"})
RUN_STATUSES = frozenset({"STOPPED", "RUNNING", "PAUSED"})
IMPORT_STATUSES = frozenset({"IDLE", "IMPORTING", "FAILED"})

_SNAPSHOT_ID_PATTERN = re.compile(r"^snp_[a-z0-9]{12}$")
_EDITOR_INSTANCE_PATTERN = re.compile(r"^edi_[a-z0-9]{12}$")
_RESOURCE_PATH_PATTERN = re.compile(r"^(res|user)://.+$")


@dataclass(frozen=True)
class SnapshotView:
    snapshot_id: str
    session_id: str
    project_id: str
    editor_instance_id: str
    snapshot_version: int
    last_event_sequence: int
    created_at: datetime
    payload: dict


def _view(entity: SnapshotModel) -> SnapshotView:
    return SnapshotView(
        snapshot_id=entity.snapshot_id,
        session_id=entity.session_id,
        project_id=entity.project_id,
        editor_instance_id=entity.editor_instance_id,
        snapshot_version=entity.snapshot_version,
        last_event_sequence=entity.last_event_sequence,
        created_at=ensure_utc(entity.created_at),
        payload=dict(entity.payload),
    )


class SnapshotService:
    """快照存储与恢复读取。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        keep_per_session: int = DEFAULT_KEEP_PER_SESSION,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._ttl = ttl_seconds
        self._keep = keep_per_session
        self._clock = clock

    async def store(
        self,
        snapshot: dict,
        *,
        session_id: str,
        project_id: str,
    ) -> SnapshotView:
        normalized = validate_snapshot(snapshot, session_id=session_id, project_id=project_id)
        version = int(normalized["snapshot_version"])

        async with self._database.session() as session, transaction(session):
            repository = SnapshotRepository(session)
            existing = await repository.get(str(normalized["snapshot_id"]))
            if existing is not None:
                if existing.session_id != session_id:
                    raise ValidationFailed("snapshot_id 已被其他 Session 使用")
                return _view(existing)
            max_version = await repository.max_version(session_id)
            if version <= max_version:
                raise ValidationFailed(
                    "snapshot_version 必须严格递增",
                    details={"snapshot_version": version, "latest": max_version},
                )
            entity = SnapshotModel(
                snapshot_id=str(normalized["snapshot_id"]),
                session_id=session_id,
                project_id=project_id,
                editor_instance_id=str(normalized["editor_instance_id"]),
                snapshot_version=version,
                last_event_sequence=int(normalized["last_event_sequence"]),
                created_at=_parse_timestamp(normalized["created_at"]),
                payload=normalized,
            )
            await repository.add(entity)
            stale = await repository.list_beyond(session_id, self._keep)
            await repository.delete_ids(stale)
            view = _view(entity)

        return view

    async def latest(self, session_id: str) -> SnapshotView:
        async with self._database.session() as session:
            entity = await SnapshotRepository(session).latest(session_id)
        if entity is None:
            raise SnapshotUnavailable("没有可用快照")
        view = _view(entity)
        if view.created_at + timedelta(seconds=self._ttl) < self._clock():
            raise SnapshotUnavailable(
                "最新快照已超过 TTL",
                details={"snapshot_id": view.snapshot_id},
            )
        return view

    async def prune_session(self, session_id: str) -> int:
        async with self._database.session() as session, transaction(session):
            repository = SnapshotRepository(session)
            stale = await repository.list_beyond(session_id, self._keep)
            return await repository.delete_ids(stale)

    async def prune_expired(self) -> int:
        cutoff = self._clock() - timedelta(seconds=self._ttl)
        async with self._database.session() as session, transaction(session):
            return await SnapshotRepository(session).delete_before(cutoff)


def validate_snapshot(
    snapshot: dict,
    *,
    session_id: str,
    project_id: str,
) -> dict:
    """校验并裁剪快照；返回可直接入库的字典副本。"""

    if not isinstance(snapshot, dict):
        raise ValidationFailed("快照必须是对象")
    unknown = set(snapshot) - SNAPSHOT_FIELDS
    if unknown:
        raise ValidationFailed(
            "快照包含未登记字段",
            details={"fields": sorted(unknown)},
        )
    missing = SNAPSHOT_FIELDS - set(snapshot)
    if missing:
        raise ValidationFailed(
            "快照缺少必需字段",
            details={"fields": sorted(missing)},
        )

    normalized = dict(snapshot)
    if not _SNAPSHOT_ID_PATTERN.match(str(normalized["snapshot_id"])):
        raise ValidationFailed("snapshot_id 必须匹配 snp_[a-z0-9]{12}")
    if normalized["session_id"] != session_id:
        raise ValidationFailed("快照 session_id 与当前连接不一致")
    if normalized["project_id"] != project_id:
        raise ValidationFailed("快照 project_id 与当前连接不一致")
    if not _EDITOR_INSTANCE_PATTERN.match(str(normalized["editor_instance_id"])):
        raise ValidationFailed("editor_instance_id 必须匹配 edi_[a-z0-9]{12}")
    _require_int(normalized, "snapshot_version", minimum=1)
    _require_int(normalized, "last_event_sequence", minimum=0)
    _parse_timestamp(normalized["created_at"])
    _require_enum(normalized, "editor_status", EDITOR_STATUSES)
    _require_enum(normalized, "project_status", PROJECT_STATUSES)
    _require_enum(normalized, "run_status", RUN_STATUSES)
    _require_enum(normalized, "import_status", IMPORT_STATUSES)
    if not isinstance(normalized["truncated"], bool):
        raise ValidationFailed("truncated 必须是布尔值")
    active_scene = normalized["active_scene"]
    if active_scene is not None and (
        not isinstance(active_scene, str) or not _RESOURCE_PATH_PATTERN.match(active_scene)
    ):
        raise ValidationFailed("active_scene 必须是资源路径或 null")
    _validate_selection(normalized["current_selection"])
    _validate_unsaved(normalized["unsaved_resources"])

    return _shrink(normalized)


def _shrink(snapshot: dict) -> dict:
    """超过 256 KiB 时按优先级裁剪，携带 ``truncated=true``。"""

    if _size(snapshot) <= MAX_SNAPSHOT_BYTES:
        return snapshot
    trimmed = dict(snapshot)
    trimmed["current_selection"] = list(trimmed["current_selection"])[:8]
    trimmed["unsaved_resources"] = list(trimmed["unsaved_resources"])[:50]
    trimmed["truncated"] = True
    if _size(trimmed) > MAX_SNAPSHOT_BYTES:
        raise RequestTooLarge("快照裁剪后仍超过 256 KiB")
    return trimmed


def _size(snapshot: dict) -> int:
    return len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _require_int(snapshot: dict, field: str, *, minimum: int) -> None:
    value = snapshot[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationFailed(f"{field} 必须是 >= {minimum} 的整数")


def _require_enum(snapshot: dict, field: str, allowed: frozenset[str]) -> None:
    if snapshot[field] not in allowed:
        raise ValidationFailed(f"{field} 取值非法")


def _validate_selection(value: object) -> None:
    if not isinstance(value, list) or len(value) > 64:
        raise ValidationFailed("current_selection 必须是最多 64 项的数组")
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item) <= 512:
            raise ValidationFailed("current_selection 项必须是 1–512 字符的字符串")


def _validate_unsaved(value: object) -> None:
    if not isinstance(value, list) or len(value) > 500:
        raise ValidationFailed("unsaved_resources 必须是最多 500 项的数组")
    for item in value:
        if not isinstance(item, dict):
            raise ValidationFailed("unsaved_resources 项必须是对象")
        if set(item) != {"path", "resource_type"}:
            raise ValidationFailed("unsaved_resources 项字段必须为 path/resource_type")
        if not isinstance(item["path"], str) or not _RESOURCE_PATH_PATTERN.match(item["path"]):
            raise ValidationFailed("unsaved_resources.path 必须是资源路径")
        resource_type = item["resource_type"]
        if not isinstance(resource_type, str) or not 1 <= len(resource_type) <= 64:
            raise ValidationFailed("unsaved_resources.resource_type 长度非法")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValidationFailed("created_at 必须为字符串")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationFailed("created_at 必须是 ISO-8601") from exc
    return ensure_utc(parsed)
