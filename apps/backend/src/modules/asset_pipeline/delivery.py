"""资产交付与 ChangeSet 管理（E8-T15）。

原则：

- 正式交付必须先通过来源完整性、质量审核、License 与审批门禁；
- 交付只生成 ChangeSet 与审批请求，不直接写入项目文件；真实写入必须由
  Tool System 在 Resource Lock 与 Fencing Token 保护下完成；
- 审批绑定 ChangeSet Hash，内容或路径变化后必须重新审批；
- 导入必须使用真实 Godot Import 回执，验证通过后才进入 ``DELIVERED``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    AssetDeliveryBlocked,
    AssetImportInvalid,
    AssetRecoveryRequired,
    AssetStateInvalid,
    NotFoundError,
)
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.approval.service import ApprovalView
from modules.asset_pipeline.imports import normalize_res_path
from modules.asset_pipeline.models import (
    DELIVERY_APPLYING,
    DELIVERY_APPROVED,
    DELIVERY_CANCELLED,
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DELIVERY_IMPORTING,
    DELIVERY_READY,
    DELIVERY_TRANSITIONS,
    DELIVERY_UNKNOWN,
    DELIVERY_WAITING_APPROVAL,
    IMPORT_FAILED,
    IMPORT_IMPORTED,
    QUALITY_HUMAN_APPROVED,
    QUALITY_MACHINE_PASSED,
    AssetDeliveryModel,
)
from modules.asset_pipeline.repository import (
    AssetDeliveryRepository,
    AssetImportJobRepository,
    AssetRepository,
    AssetVersionRepository,
)
from modules.changeset.models import RISK_LEVELS, RISK_MEDIUM, VALIDATION_VALID
from modules.changeset.service import ChangeSetService

__all__ = [
    "AssetDeliveryService",
    "DeliveryRequest",
    "DeliveryView",
]

_TERMINAL_STATUSES = frozenset({DELIVERY_DELIVERED, DELIVERY_FAILED, DELIVERY_CANCELLED})


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    project_id: str
    asset_id: str
    asset_version_id: str
    target_path: str
    resource_type: str | None = None
    operation_type: str = "CREATE"
    old_content_hash: str | None = None
    risk_level: str = RISK_MEDIUM
    title: str | None = None
    require_human_review: bool = True
    require_commercial_use: bool = True
    require_redistribution: bool = False
    created_by: str | None = None
    approval_ttl_seconds: int = 24 * 3600

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise AssetDeliveryBlocked("缺少项目 ID")
        if not self.asset_id.strip() or not self.asset_version_id.strip():
            raise AssetDeliveryBlocked("缺少资产或资产版本 ID")
        try:
            normalize_res_path(self.target_path)
        except Exception as error:
            raise AssetDeliveryBlocked(
                "目标路径必须是 res:// 路径",
                details={"target_path": self.target_path},
            ) from error
        if self.risk_level not in RISK_LEVELS:
            raise AssetDeliveryBlocked(
                "风险等级非法", details={"risk_level": self.risk_level}
            )
        if self.approval_ttl_seconds <= 0:
            raise AssetDeliveryBlocked("审批有效期必须大于 0")


@dataclass(frozen=True, slots=True)
class DeliveryView:
    delivery_id: str
    project_id: str
    asset_id: str
    asset_version_id: str
    changeset_id: str | None
    approval_id: str | None
    import_job_id: str | None
    delivery_status: str
    target_path: str | None
    delivered_at: datetime | None
    created_by: str | None
    created_at: datetime


def _view(entity: AssetDeliveryModel, *, target_path: str | None = None) -> DeliveryView:
    return DeliveryView(
        delivery_id=entity.delivery_id,
        project_id=entity.project_id,
        asset_id=entity.asset_id,
        asset_version_id=entity.asset_version_id,
        changeset_id=entity.changeset_id,
        approval_id=entity.approval_id,
        import_job_id=entity.import_job_id,
        delivery_status=entity.delivery_status,
        target_path=target_path,
        delivered_at=entity.delivered_at,
        created_by=entity.created_by,
        created_at=entity.created_at,
    )


class AssetDeliveryService:
    """资产交付门禁、ChangeSet 与审批编排。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        changesets: ChangeSetService,
        quality,
        licenses,
        provenance,
        approvals=None,
        events: EventBus | None = None,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._changesets = changesets
        self._quality = quality
        self._licenses = licenses
        self._provenance = provenance
        self._approvals = approvals
        self._events = events
        self._clock = clock
        self._logger = get_logger("backend.asset.delivery")

    async def prepare(self, request: DeliveryRequest) -> DeliveryView:
        version = await self._load_version(
            request.project_id, request.asset_id, request.asset_version_id
        )
        await self._provenance.assert_complete(
            request.project_id, request.asset_version_id
        )
        await self._assert_quality(request)
        await self._licenses.check_deliverable(
            request.project_id,
            request.asset_version_id,
            require_commercial_use=request.require_commercial_use,
            require_redistribution=request.require_redistribution,
        )
        resource_path = self._resource_path(request.target_path)
        changeset = await self._changesets.create(
            project_id=request.project_id,
            title=request.title or f"交付资产 {request.asset_id}",
            items=[
                {
                    "resource_path": resource_path,
                    "operation_type": request.operation_type,
                    "old_content_hash": request.old_content_hash,
                    "new_content_hash": version.content_hash,
                    "resource_type": request.resource_type,
                    "risk_level": request.risk_level,
                }
            ],
            description="Asset Pipeline 资产交付",
            created_by=request.created_by,
        )
        validation = await self._changesets.validate(changeset.changeset_id)
        if validation["status"] != VALIDATION_VALID:
            raise AssetDeliveryBlocked(
                "ChangeSet 校验未通过",
                details={
                    "changeset_id": changeset.changeset_id,
                    "errors": validation["errors"],
                },
            )
        now = self._clock()
        entity = AssetDeliveryModel(
            delivery_id="adl_" + uuid4().hex[:12],
            asset_id=request.asset_id,
            asset_version_id=request.asset_version_id,
            project_id=request.project_id,
            changeset_id=changeset.changeset_id,
            approval_id=None,
            import_job_id=None,
            delivery_status=DELIVERY_READY,
            delivered_at=None,
            created_by=request.created_by,
            created_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await AssetDeliveryRepository(session).add(entity)
        await self._publish(
            "asset.delivery.created",
            {
                "delivery_id": entity.delivery_id,
                "asset_version_id": request.asset_version_id,
                "changeset_id": changeset.changeset_id,
            },
            project_id=request.project_id,
        )
        return await self.get(entity.delivery_id)

    async def submit_for_approval(
        self,
        delivery_id: str,
        *,
        requested_by: str | None = None,
        ttl_seconds: int = 24 * 3600,
    ) -> ApprovalView:
        entity = await self._get_entity(delivery_id)
        self._assert_transition(entity.delivery_status, DELIVERY_WAITING_APPROVAL)
        if not entity.changeset_id:
            raise AssetStateInvalid(
                "交付缺少 ChangeSet", details={"delivery_id": delivery_id}
            )
        approval = await self._changesets.submit_for_approval(
            entity.changeset_id,
            requested_by=requested_by,
            ttl_seconds=ttl_seconds,
        )
        await self._update(
            delivery_id,
            status=DELIVERY_WAITING_APPROVAL,
            approval_id=approval.approval_id,
        )
        await self._publish(
            "asset.delivery.submitted",
            {"delivery_id": delivery_id, "approval_id": approval.approval_id},
            project_id=entity.project_id,
        )
        return approval

    async def approve(
        self,
        delivery_id: str,
        approval_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
    ) -> DeliveryView:
        entity = await self._get_entity(delivery_id)
        if entity.delivery_status != DELIVERY_WAITING_APPROVAL:
            raise AssetStateInvalid(
                "交付不在等待审批状态",
                details={"delivery_id": delivery_id, "status": entity.delivery_status},
            )
        if not entity.changeset_id:
            raise AssetStateInvalid(
                "交付缺少 ChangeSet", details={"delivery_id": delivery_id}
            )
        self._assert_transition(entity.delivery_status, DELIVERY_APPROVED)
        await self._changesets.approve(
            entity.changeset_id, approval_id, actor_id=actor_id, reason=reason
        )
        await self._update(
            delivery_id, status=DELIVERY_APPROVED, approval_id=approval_id
        )
        await self._publish(
            "asset.delivery.approved",
            {"delivery_id": delivery_id, "approval_id": approval_id},
            project_id=entity.project_id,
        )
        return await self.get(delivery_id)

    async def begin_apply(
        self, delivery_id: str, approval_id: str, *, actor_id: str
    ) -> DeliveryView:
        entity = await self._get_entity(delivery_id)
        if entity.delivery_status != DELIVERY_APPROVED:
            raise AssetStateInvalid(
                "交付未审批通过，不能应用",
                details={"delivery_id": delivery_id, "status": entity.delivery_status},
            )
        if not entity.changeset_id:
            raise AssetStateInvalid(
                "交付缺少 ChangeSet", details={"delivery_id": delivery_id}
            )
        await self._changesets.start_apply(
            entity.changeset_id, approval_id, actor_id=actor_id
        )
        await self._update(delivery_id, status=DELIVERY_APPLYING)
        await self._publish(
            "asset.delivery.applying",
            {"delivery_id": delivery_id, "changeset_id": entity.changeset_id},
            project_id=entity.project_id,
        )
        return await self.get(delivery_id)

    async def mark_importing(
        self, delivery_id: str, import_job_id: str
    ) -> DeliveryView:
        entity = await self._get_entity(delivery_id)
        self._assert_transition(entity.delivery_status, DELIVERY_IMPORTING)
        async with self._database.session() as session:
            job = await AssetImportJobRepository(session).get(import_job_id)
            if job is None or job.project_id != entity.project_id:
                raise NotFoundError(
                    "导入任务不存在或不属于该项目",
                    details={"import_job_id": import_job_id},
                )
            if job.asset_version_id != entity.asset_version_id:
                raise AssetImportInvalid(
                    "导入任务与交付版本不一致",
                    details={"import_job_id": import_job_id},
                )
        await self._update(
            delivery_id, status=DELIVERY_IMPORTING, import_job_id=import_job_id
        )
        await self._publish(
            "asset.delivery.importing",
            {"delivery_id": delivery_id, "import_job_id": import_job_id},
            project_id=entity.project_id,
        )
        return await self.get(delivery_id)

    async def mark_delivered(
        self, delivery_id: str, *, import_job_id: str | None = None
    ) -> DeliveryView:
        entity = await self._get_entity(delivery_id)
        if entity.delivery_status == DELIVERY_DELIVERED:
            return await self.get(delivery_id)
        job_id = import_job_id or entity.import_job_id
        if not job_id:
            raise AssetDeliveryBlocked(
                "缺少真实导入记录，不能交付", details={"delivery_id": delivery_id}
            )
        async with self._database.session() as session:
            job = await AssetImportJobRepository(session).get(job_id)
        if (
            job is None
            or job.project_id != entity.project_id
            or job.asset_version_id != entity.asset_version_id
        ):
            raise NotFoundError(
                "导入记录与交付不匹配", details={"import_job_id": job_id}
            )
        if job.import_status != IMPORT_IMPORTED or not job.godot_uid:
            raise AssetDeliveryBlocked(
                "Godot 导入尚未成功，不能交付",
                details={"import_job_id": job_id, "status": job.import_status},
            )
        now = self._clock()
        path = self._path_to(entity.delivery_status, DELIVERY_DELIVERED)
        for index, status in enumerate(path):
            await self._update(
                delivery_id,
                status=status,
                import_job_id=job_id,
                delivered_at=now if index == len(path) - 1 else None,
            )
        await self._publish(
            "asset.delivery.delivered",
            {
                "delivery_id": delivery_id,
                "asset_version_id": entity.asset_version_id,
                "import_job_id": job_id,
            },
            project_id=entity.project_id,
        )
        return await self.get(delivery_id)

    async def mark_failed(self, delivery_id: str, *, reason: str) -> DeliveryView:
        entity = await self._get_entity(delivery_id)
        if entity.delivery_status in _TERMINAL_STATUSES:
            raise AssetStateInvalid(
                "交付已结束", details={"delivery_id": delivery_id}
            )
        self._assert_transition(entity.delivery_status, DELIVERY_FAILED)
        await self._update(delivery_id, status=DELIVERY_FAILED)
        await self._publish(
            "asset.delivery.failed",
            {"delivery_id": delivery_id, "reason": reason},
            project_id=entity.project_id,
        )
        return await self.get(delivery_id)

    async def mark_unknown(self, delivery_id: str, *, reason: str) -> DeliveryView:
        entity = await self._get_entity(delivery_id)
        self._assert_transition(entity.delivery_status, DELIVERY_UNKNOWN)
        await self._update(delivery_id, status=DELIVERY_UNKNOWN)
        await self._publish(
            "asset.delivery.unknown",
            {"delivery_id": delivery_id, "reason": reason},
            project_id=entity.project_id,
        )
        return await self.get(delivery_id)

    async def reconcile(self, delivery_id: str) -> DeliveryView:
        """UNKNOWN / 进行中的交付按真实导入证据恢复，不重复写入或导入。"""

        entity = await self._get_entity(delivery_id)
        if entity.delivery_status in _TERMINAL_STATUSES:
            return await self.get(delivery_id)
        if not entity.import_job_id:
            raise AssetRecoveryRequired(
                "交付缺少导入记录，需人工核对",
                details={"delivery_id": delivery_id, "status": entity.delivery_status},
            )
        async with self._database.session() as session:
            job = await AssetImportJobRepository(session).get(entity.import_job_id)
        if job is None:
            raise AssetRecoveryRequired(
                "导入记录丢失，需人工核对",
                details={"delivery_id": delivery_id},
            )
        if job.import_status == IMPORT_IMPORTED and job.godot_uid:
            return await self.mark_delivered(delivery_id)
        if job.import_status == IMPORT_FAILED:
            return await self.mark_failed(delivery_id, reason="IMPORT_FAILED")
        raise AssetRecoveryRequired(
            "导入状态仍不确定，保持 UNKNOWN",
            details={"delivery_id": delivery_id, "import_status": job.import_status},
        )

    async def check_approval(self, delivery_id: str) -> dict[str, Any]:
        entity = await self._get_entity(delivery_id)
        if not entity.changeset_id:
            raise AssetStateInvalid(
                "交付缺少 ChangeSet", details={"delivery_id": delivery_id}
            )
        result = await self._changesets.verify_hash(entity.changeset_id)
        valid = bool(result["valid"])
        if not entity.approval_id or self._approvals is None:
            valid = False
        else:
            approval = await self._approvals.get(entity.approval_id)
            valid = (
                valid
                and approval.status == "APPROVED"
                and approval.target_hash == result["content_hash"]
            )
        return {
            "valid": valid,
            "content_hash": result["content_hash"],
            "delivery_status": entity.delivery_status,
        }

    async def get(self, delivery_id: str) -> DeliveryView:
        entity = await self._get_entity(delivery_id)
        return _view(entity, target_path=await self._target_path(entity))

    async def list_for_asset(
        self, project_id: str, asset_id: str
    ) -> list[DeliveryView]:
        async with self._database.session() as session:
            asset = await AssetRepository(session).get_active(asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产不存在或不属于该项目",
                    details={"project_id": project_id, "asset_id": asset_id},
                )
            entities = await AssetDeliveryRepository(session).list_for_asset(asset_id)
            for item in entities:
                session.expunge(item)
        return [_view(item, target_path=await self._target_path(item)) for item in entities]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _assert_quality(self, request: DeliveryRequest) -> None:
        reviews = await self._quality.list_for_version(
            request.project_id, request.asset_id, request.asset_version_id
        )
        statuses = {item.review_status for item in reviews}
        if QUALITY_HUMAN_APPROVED in statuses:
            return
        if request.require_human_review:
            raise AssetDeliveryBlocked(
                "资产缺少人工审核通过记录，不能正式交付",
                details={
                    "asset_version_id": request.asset_version_id,
                    "statuses": sorted(statuses),
                },
            )
        if QUALITY_MACHINE_PASSED in statuses:
            return
        raise AssetDeliveryBlocked(
            "资产未通过质量审核，不能正式交付",
            details={
                "asset_version_id": request.asset_version_id,
                "statuses": sorted(statuses),
            },
        )

    async def _load_version(
        self, project_id: str, asset_id: str, asset_version_id: str
    ):
        async with self._database.session() as session:
            version = await AssetVersionRepository(session).get(asset_version_id)
            if version is None or version.asset_id != asset_id:
                raise NotFoundError(
                    "资产版本不属于该资产",
                    details={"asset_id": asset_id, "asset_version_id": asset_version_id},
                )
            asset = await AssetRepository(session).get_active(asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产不存在或不属于该项目",
                    details={"project_id": project_id, "asset_id": asset_id},
                )
            session.expunge(version)
            return version

    async def _get_entity(self, delivery_id: str) -> AssetDeliveryModel:
        async with self._database.session() as session:
            entity = await AssetDeliveryRepository(session).get(delivery_id)
            if entity is None:
                raise NotFoundError(
                    "交付记录不存在", details={"delivery_id": delivery_id}
                )
            session.expunge(entity)
            return entity

    async def _update(
        self,
        delivery_id: str,
        *,
        status: str,
        approval_id: str | None = None,
        import_job_id: str | None = None,
        delivered_at: datetime | None = None,
    ) -> None:
        async with self._database.session() as session, transaction(session):
            entity = await AssetDeliveryRepository(session).get(delivery_id)
            if entity is None:
                raise NotFoundError(
                    "交付记录不存在", details={"delivery_id": delivery_id}
                )
            self._assert_transition(entity.delivery_status, status)
            entity.delivery_status = status
            if approval_id is not None:
                entity.approval_id = approval_id
            if import_job_id is not None:
                entity.import_job_id = import_job_id
            if delivered_at is not None:
                entity.delivered_at = delivered_at
            await session.flush()

    async def _target_path(self, entity: AssetDeliveryModel) -> str | None:
        if not entity.changeset_id:
            return None
        try:
            detail = await self._changesets.detail(entity.changeset_id)
        except Exception:  # noqa: BLE001 - 展示用途，失败不影响交付状态
            return None
        manifest = detail.get("manifest") or []
        if not manifest:
            return None
        return "res://" + str(manifest[0]["resource_path"])

    def _assert_transition(self, current: str, target: str) -> None:
        if current == target:
            return
        if target not in DELIVERY_TRANSITIONS.get(current, frozenset()):
            raise AssetStateInvalid(
                "交付状态迁移非法", details={"from": current, "to": target}
            )

    @staticmethod
    def _path_to(current: str, target: str) -> list[str]:
        if current == target:
            return []
        queue: list[list[str]] = [[current]]
        visited = {current}
        while queue:
            path = queue.pop(0)
            for nxt in sorted(DELIVERY_TRANSITIONS.get(path[-1], frozenset())):
                if nxt == target:
                    return [*path[1:], nxt]
                if nxt == DELIVERY_UNKNOWN and current != DELIVERY_UNKNOWN:
                    # UNKNOWN 仅用于异常恢复，正常正向流转不经过 UNKNOWN
                    continue
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append([*path, nxt])
        raise AssetStateInvalid(
            "交付状态无法到达目标状态", details={"from": current, "to": target}
        )

    @staticmethod
    def _resource_path(target_path: str) -> str:
        return normalize_res_path(target_path)[len("res://") :]

    async def _publish(
        self, event_type: str, payload: dict[str, Any], *, project_id: str
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(
                Event.create(event_type, payload, project_id=project_id)
            )
        except Exception:  # noqa: BLE001 - 事件失败不阻断交付流程
            log_event(
                self._logger,
                logging.WARNING,
                "asset.delivery.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )
