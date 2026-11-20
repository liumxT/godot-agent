"""ChangeSet Manager（E4-T19）。

ChangeSet 只描述“要改什么”，不直接应用文件；审批必须绑定内容哈希。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    ApprovalHashMismatch,
    InvalidStateTransition,
    NotFoundError,
    ValidationFailed,
)
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.approval.models import (
    APPROVAL_APPROVED,
    APPROVAL_REJECTED,
    APPROVAL_TYPE_CHANGESET_APPLY,
    TARGET_CHANGESET_HASH,
)
from modules.approval.service import ApprovalService, ApprovalView
from modules.changeset.models import (
    CHANGESET_APPLIED,
    CHANGESET_APPLYING,
    CHANGESET_APPROVED,
    CHANGESET_CANCELLED,
    CHANGESET_DRAFT,
    CHANGESET_FAILED,
    CHANGESET_READY,
    CHANGESET_REJECTED,
    CHANGESET_UNKNOWN,
    OPERATION_TYPES,
    RISK_LEVELS,
    RISK_MEDIUM,
    VALIDATION_INVALID,
    VALIDATION_PENDING,
    VALIDATION_VALID,
    ChangeManifestItemModel,
    ChangeSetModel,
    ChangeSetValidationResultModel,
    ChangeSetVersionModel,
)
from modules.changeset.repository import (
    ChangeManifestItemRepository,
    ChangeSetRepository,
    ChangeSetValidationRepository,
    ChangeSetVersionRepository,
)

_MUTABLE_STATUSES = frozenset({CHANGESET_DRAFT, CHANGESET_READY, CHANGESET_REJECTED})
_TERMINAL_STATUSES = frozenset({CHANGESET_APPLIED, CHANGESET_CANCELLED})


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


@dataclass(frozen=True)
class ManifestItemView:
    item_id: str
    changeset_id: str
    resource_path: str
    operation_type: str
    old_content_hash: str | None
    new_content_hash: str | None
    resource_type: str | None
    risk_level: str
    validation_status: str


@dataclass(frozen=True)
class ChangeSetView:
    changeset_id: str
    project_id: str
    task_id: str | None
    attempt_id: str | None
    title: str
    description: str | None
    status: str
    content_hash: str | None
    base_revision: str | None
    created_by: str | None
    version: int
    created_at: datetime
    approved_at: datetime | None
    applied_at: datetime | None


def normalize_manifest(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        raise ValidationFailed("ChangeSet 必须包含至少一个变更项")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValidationFailed("变更项必须是对象")
        path = str(item.get("resource_path") or "").strip()
        if not path:
            raise ValidationFailed("resource_path 不能为空")
        if path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/"):
            raise ValidationFailed(
                "resource_path 必须是项目内相对路径", details={"resource_path": path}
            )
        if path in seen:
            raise ValidationFailed("resource_path 重复", details={"resource_path": path})
        seen.add(path)
        operation = str(item.get("operation_type") or "").upper()
        if operation not in OPERATION_TYPES:
            raise ValidationFailed("operation_type 非法", details={"operation_type": operation})
        risk = str(item.get("risk_level") or RISK_MEDIUM).upper()
        if risk not in RISK_LEVELS:
            raise ValidationFailed("risk_level 非法", details={"risk_level": risk})
        normalized.append(
            {
                "resource_path": path,
                "operation_type": operation,
                "old_content_hash": item.get("old_content_hash"),
                "new_content_hash": item.get("new_content_hash"),
                "resource_type": item.get("resource_type"),
                "risk_level": risk,
            }
        )
    return sorted(normalized, key=lambda value: value["resource_path"])


def compute_manifest_hash(items: Sequence[dict[str, Any]]) -> str:
    canonical = json.dumps(list(items), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _changeset_view(entity: ChangeSetModel) -> ChangeSetView:
    return ChangeSetView(
        changeset_id=entity.changeset_id,
        project_id=entity.project_id,
        task_id=entity.task_id,
        attempt_id=entity.attempt_id,
        title=entity.title,
        description=entity.description,
        status=entity.status,
        content_hash=entity.content_hash,
        base_revision=entity.base_revision,
        created_by=entity.created_by,
        version=entity.version,
        created_at=ensure_utc(entity.created_at),
        approved_at=ensure_utc(entity.approved_at) if entity.approved_at else None,
        applied_at=ensure_utc(entity.applied_at) if entity.applied_at else None,
    )


def _item_view(entity: ChangeManifestItemModel) -> ManifestItemView:
    return ManifestItemView(
        item_id=entity.item_id,
        changeset_id=entity.changeset_id,
        resource_path=entity.resource_path,
        operation_type=entity.operation_type,
        old_content_hash=entity.old_content_hash,
        new_content_hash=entity.new_content_hash,
        resource_type=entity.resource_type,
        risk_level=entity.risk_level,
        validation_status=entity.validation_status,
    )


class ChangeSetService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        approvals: ApprovalService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._approvals = approvals
        self._clock = clock
        self._logger = get_logger("backend.changeset")

    async def create(
        self,
        *,
        project_id: str,
        title: str,
        items: Sequence[dict[str, Any]],
        description: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        base_revision: str | None = None,
        created_by: str | None = None,
    ) -> ChangeSetView:
        manifest = normalize_manifest(items)
        content_hash = compute_manifest_hash(manifest)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = ChangeSetModel(
                changeset_id=_new_id("chs_"),
                project_id=project_id,
                task_id=task_id,
                attempt_id=attempt_id,
                title=title.strip()[:256] or "changeset",
                description=description,
                status=CHANGESET_DRAFT,
                content_hash=content_hash,
                base_revision=base_revision,
                created_by=created_by,
                version=1,
                created_at=now,
                approved_at=None,
                applied_at=None,
            )
            await ChangeSetRepository(session).add(entity)
            await self._write_manifest(session, entity.changeset_id, manifest)
            await self._write_version(session, entity, 1, content_hash, manifest, now)
            await session.flush()
            view = _changeset_view(entity)
        log_event(self._logger, logging.INFO, "changeset_created", component="changeset")
        return view

    async def get(self, changeset_id: str) -> ChangeSetView:
        async with self._database.session() as session:
            entity = await ChangeSetRepository(session).get(changeset_id)
        if entity is None:
            raise NotFoundError("ChangeSet 不存在", details={"changeset_id": changeset_id})
        return _changeset_view(entity)

    async def detail(self, changeset_id: str) -> dict[str, Any]:
        await self.get(changeset_id)
        async with self._database.session() as session:
            items = await ChangeManifestItemRepository(session).list_by_changeset(changeset_id)
            validation = await ChangeSetValidationRepository(session).latest(changeset_id)
            versions = await ChangeSetVersionRepository(session).list_by_changeset(changeset_id)
        return {
            "manifest": [format_item(item) for item in items],
            "validation": {
                "status": validation.status,
                "errors": json.loads(validation.errors) if validation.errors else [],
                "validated_at": isoformat(validation.validated_at),
            }
            if validation
            else None,
            "versions": [
                {
                    "version_id": version.version_id,
                    "version_no": version.version_no,
                    "content_hash": version.content_hash,
                    "created_at": isoformat(version.created_at),
                }
                for version in versions
            ],
        }

    async def list(
        self, project_id: str, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await ChangeSetRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [format_changeset(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def replace_manifest(
        self,
        changeset_id: str,
        items: Sequence[dict[str, Any]],
    ) -> ChangeSetView:
        manifest = normalize_manifest(items)
        content_hash = compute_manifest_hash(manifest)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ChangeSetRepository(session).get(changeset_id)
            if entity is None:
                raise NotFoundError("ChangeSet 不存在", details={"changeset_id": changeset_id})
            if entity.status not in _MUTABLE_STATUSES:
                raise InvalidStateTransition(
                    "ChangeSet 当前状态不能修改清单",
                    details={"changeset_id": changeset_id, "status": entity.status},
                )
            entity.status = CHANGESET_DRAFT
            entity.approved_at = None
            entity.version += 1
            entity.content_hash = content_hash
            await self._replace_manifest_rows(session, changeset_id, manifest)
            await self._write_version(session, entity, entity.version, content_hash, manifest, now)
            await session.flush()
            return _changeset_view(entity)

    async def validate(self, changeset_id: str) -> dict[str, Any]:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ChangeSetRepository(session).get(changeset_id)
            if entity is None:
                raise NotFoundError("ChangeSet 不存在", details={"changeset_id": changeset_id})
            if entity.status in _TERMINAL_STATUSES:
                raise InvalidStateTransition("已结束的 ChangeSet 不能再校验")
            items = await ChangeManifestItemRepository(session).list_by_changeset(changeset_id)
            errors: list[str] = []
            for item in items:
                if item.operation_type in ("UPDATE", "DELETE") and not item.old_content_hash:
                    errors.append(
                        f"{item.resource_path}: {item.operation_type} 需要 old_content_hash"
                    )
                if item.operation_type in ("CREATE", "UPDATE") and not item.new_content_hash:
                    errors.append(
                        f"{item.resource_path}: {item.operation_type} 需要 new_content_hash"
                    )
                item.validation_status = VALIDATION_VALID if not errors else VALIDATION_INVALID
            status = VALIDATION_VALID if not errors else VALIDATION_INVALID
            await ChangeSetValidationRepository(session).add(
                ChangeSetValidationResultModel(
                    result_id=_new_id("cvr_"),
                    changeset_id=changeset_id,
                    status=status,
                    errors=json.dumps(errors, ensure_ascii=False),
                    validated_at=now,
                )
            )
            entity.status = CHANGESET_READY if not errors else CHANGESET_DRAFT
            await session.flush()
            return {"status": status, "errors": errors}

    async def submit_for_approval(
        self,
        changeset_id: str,
        *,
        requested_by: str | None = None,
        ttl_seconds: int = 24 * 3600,
    ) -> ApprovalView:
        entity = await self.get(changeset_id)
        if entity.status != CHANGESET_READY:
            raise InvalidStateTransition(
                "只有 READY_FOR_APPROVAL 的 ChangeSet 才能提交审批",
                details={"changeset_id": changeset_id, "status": entity.status},
            )
        if not entity.content_hash:
            raise ValidationFailed("ChangeSet 缺少内容哈希")
        return await self._approvals.create(
            project_id=entity.project_id,
            target_type=TARGET_CHANGESET_HASH,
            target_id=entity.changeset_id,
            target_hash=entity.content_hash,
            approval_type=APPROVAL_TYPE_CHANGESET_APPLY,
            task_id=entity.task_id,
            attempt_id=entity.attempt_id,
            target_version=entity.version,
            requested_by=requested_by,
            ttl_seconds=ttl_seconds,
        )

    async def approve(
        self,
        changeset_id: str,
        approval_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
    ) -> ChangeSetView:
        entity = await self.get(changeset_id)
        if entity.status not in (CHANGESET_READY, CHANGESET_APPROVED):
            raise InvalidStateTransition("ChangeSet 当前状态不能审批")
        existing = await self._approvals.get(approval_id)
        if existing.target_id != changeset_id or existing.project_id != entity.project_id:
            raise ValidationFailed("审批目标与 ChangeSet 不匹配")
        approval = await self._approvals.approve(
            approval_id,
            actor_id=actor_id,
            reason=reason,
            current_target_hash=entity.content_hash,
        )
        if approval.status != APPROVAL_APPROVED:
            raise InvalidStateTransition("审批未通过")
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            current = await ChangeSetRepository(session).get(changeset_id)
            if current is None:
                raise NotFoundError("ChangeSet 不存在")
            current.status = CHANGESET_APPROVED
            current.approved_at = now
            current.version += 1
            await session.flush()
            return _changeset_view(current)

    async def reject(
        self,
        changeset_id: str,
        approval_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
    ) -> ChangeSetView:
        entity = await self.get(changeset_id)
        existing = await self._approvals.get(approval_id)
        if existing.target_id != changeset_id or existing.project_id != entity.project_id:
            raise ValidationFailed("审批目标与 ChangeSet 不匹配")
        approval = await self._approvals.reject(
            approval_id,
            actor_id=actor_id,
            reason=reason,
            current_target_hash=entity.content_hash,
        )
        if approval.status != APPROVAL_REJECTED:
            raise InvalidStateTransition("审批未拒绝")
        async with self._database.session() as session, transaction(session):
            current = await ChangeSetRepository(session).get(changeset_id)
            if current is None:
                raise NotFoundError("ChangeSet 不存在")
            current.status = CHANGESET_REJECTED
            current.version += 1
            current.applied_at = None
            await session.flush()
            return _changeset_view(current)

    async def start_apply(
        self,
        changeset_id: str,
        approval_id: str,
        *,
        actor_id: str,
    ) -> ChangeSetView:
        entity = await self.get(changeset_id)
        if entity.status != CHANGESET_APPROVED:
            raise InvalidStateTransition("只有 APPROVED 的 ChangeSet 才能应用")
        approval = await self._approvals.get(approval_id)
        if (
            approval.target_id != changeset_id
            or approval.project_id != entity.project_id
            or approval.target_type != TARGET_CHANGESET_HASH
            or approval.status != APPROVAL_APPROVED
        ):
            raise InvalidStateTransition("审批无效或未通过")
        if approval.target_hash != entity.content_hash:
            raise ApprovalHashMismatch(
                "ChangeSet 内容已变化，原审批不能继续使用",
                details={"changeset_id": changeset_id},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            current = await ChangeSetRepository(session).get(changeset_id)
            if current is None:
                raise NotFoundError("ChangeSet 不存在")
            current.status = CHANGESET_APPLYING
            current.version += 1
            current.applied_at = now
            await session.flush()
            return _changeset_view(current)

    async def finish_apply(
        self, changeset_id: str, *, status: str = CHANGESET_APPLIED
    ) -> ChangeSetView:
        if status not in (CHANGESET_APPLIED, CHANGESET_FAILED, CHANGESET_UNKNOWN):
            raise ValidationFailed("应用结果状态非法", details={"status": status})
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ChangeSetRepository(session).get(changeset_id)
            if entity is None:
                raise NotFoundError("ChangeSet 不存在")
            if entity.status not in (CHANGESET_APPLYING, CHANGESET_UNKNOWN):
                raise InvalidStateTransition("ChangeSet 不在应用中")
            entity.status = status
            entity.version += 1
            if status == CHANGESET_APPLIED:
                entity.applied_at = now
            await session.flush()
            return _changeset_view(entity)

    async def cancel(self, changeset_id: str, *, actor_id: str | None = None) -> ChangeSetView:
        async with self._database.session() as session, transaction(session):
            entity = await ChangeSetRepository(session).get(changeset_id)
            if entity is None:
                raise NotFoundError("ChangeSet 不存在")
            if entity.status in _TERMINAL_STATUSES:
                raise InvalidStateTransition("ChangeSet 已结束")
            entity.status = CHANGESET_CANCELLED
            entity.version += 1
            await session.flush()
            return _changeset_view(entity)

    async def verify_hash(self, changeset_id: str) -> dict[str, Any]:
        entity = await self.get(changeset_id)
        async with self._database.session() as session:
            items = await ChangeManifestItemRepository(session).list_by_changeset(changeset_id)
        manifest = [
            {
                "resource_path": item.resource_path,
                "operation_type": item.operation_type,
                "old_content_hash": item.old_content_hash,
                "new_content_hash": item.new_content_hash,
                "resource_type": item.resource_type,
                "risk_level": item.risk_level,
            }
            for item in items
        ]
        computed = compute_manifest_hash(manifest)
        return {"valid": computed == entity.content_hash, "content_hash": computed}

    async def _write_manifest(
        self, session, changeset_id: str, manifest: Sequence[dict[str, Any]]
    ) -> None:
        for item in manifest:
            await ChangeManifestItemRepository(session).add(
                ChangeManifestItemModel(
                    item_id=_new_id("cmi_"),
                    changeset_id=changeset_id,
                    resource_path=item["resource_path"],
                    operation_type=item["operation_type"],
                    old_content_hash=item.get("old_content_hash"),
                    new_content_hash=item.get("new_content_hash"),
                    resource_type=item.get("resource_type"),
                    risk_level=item["risk_level"],
                    validation_status=VALIDATION_PENDING,
                )
            )

    async def _replace_manifest_rows(
        self, session, changeset_id: str, manifest: Sequence[dict[str, Any]]
    ) -> None:
        repository = ChangeManifestItemRepository(session)
        for item in await repository.list_by_changeset(changeset_id):
            await session.delete(item)
        await session.flush()
        await self._write_manifest(session, changeset_id, manifest)

    async def _write_version(
        self,
        session,
        entity: ChangeSetModel,
        version_no: int,
        content_hash: str,
        manifest: Sequence[dict[str, Any]],
        now: datetime,
    ) -> None:
        await ChangeSetVersionRepository(session).add(
            ChangeSetVersionModel(
                version_id=_new_id("csv_"),
                changeset_id=entity.changeset_id,
                version_no=version_no,
                content_hash=content_hash,
                manifest_json=json.dumps(list(manifest), ensure_ascii=False, sort_keys=True),
                created_at=now,
            )
        )


def format_changeset(view: ChangeSetView) -> dict[str, Any]:
    return {
        "changeset_id": view.changeset_id,
        "project_id": view.project_id,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "title": view.title,
        "description": view.description,
        "status": view.status,
        "content_hash": view.content_hash,
        "base_revision": view.base_revision,
        "created_by": view.created_by,
        "version": view.version,
        "created_at": isoformat(view.created_at),
        "approved_at": isoformat(view.approved_at) if view.approved_at else None,
        "applied_at": isoformat(view.applied_at) if view.applied_at else None,
    }


def format_item(view: ManifestItemView) -> dict[str, Any]:
    return {
        "item_id": view.item_id,
        "changeset_id": view.changeset_id,
        "resource_path": view.resource_path,
        "operation_type": view.operation_type,
        "old_content_hash": view.old_content_hash,
        "new_content_hash": view.new_content_hash,
        "resource_type": view.resource_type,
        "risk_level": view.risk_level,
        "validation_status": view.validation_status,
    }


__all__ = [
    "ChangeSetService",
    "ChangeSetView",
    "compute_manifest_hash",
    "format_changeset",
    "format_item",
    "normalize_manifest",
]
