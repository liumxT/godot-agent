"""资产管线恢复（E8-T16）。

UNKNOWN 不等于 FAILED。恢复流程必须基于真实证据：

1. 查询 Provider / 外部 Job；
2. 检查已有产物与 Hash；
3. 检查处理任务、项目文件与 Godot Import 状态；
4. 能确认时修正状态，不能确认时保持 UNKNOWN 并交给人工处理。

恢复操作只读取外部状态或修正本模块状态，不重复提交生成、写入或导入。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.errors import (
    AssetGenerationInvalid,
    AssetRecoveryRequired,
    AssetStateInvalid,
    NotFoundError,
)
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.generation import GenerationView
from modules.asset_pipeline.imports import ImportJobView
from modules.asset_pipeline.models import (
    DELIVERY_UNKNOWN,
    GENERATION_UNKNOWN,
    IMPORT_UNKNOWN,
    PROCESSING_SUCCEEDED,
    PROCESSING_UNKNOWN,
)
from modules.asset_pipeline.repository import (
    AssetDeliveryRepository,
    AssetGenerationRepository,
    AssetImportJobRepository,
    AssetProcessingJobRepository,
    AssetRepository,
)

__all__ = ["AssetRecoveryService", "RecoveryInventory"]

_IDEMPOTENCY_PREFIXES = {
    "generation": "generation",
    "processing": "processing",
    "project_write": "project_write",
    "import": "import",
    "delivery": "delivery",
}


@dataclass(frozen=True, slots=True)
class RecoveryInventory:
    generation_ids: tuple[str, ...] = ()
    processing_job_ids: tuple[str, ...] = ()
    import_job_ids: tuple[str, ...] = ()
    delivery_ids: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return (
            len(self.generation_ids)
            + len(self.processing_job_ids)
            + len(self.import_job_ids)
            + len(self.delivery_ids)
        )


class AssetRecoveryService:
    """跨 Provider、Processing、Import 与 Delivery 的恢复协调。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        generations,
        processing,
        imports,
        deliveries,
        events: EventBus | None = None,
    ) -> None:
        self._database = database
        self._generations = generations
        self._processing = processing
        self._imports = imports
        self._deliveries = deliveries
        self._events = events
        self._logger = get_logger("backend.asset.recovery")

    @staticmethod
    def idempotency_key(operation: str, identifier: str) -> str:
        prefix = _IDEMPOTENCY_PREFIXES.get(operation)
        if prefix is None:
            raise AssetRecoveryRequired(
                "未知幂等操作类型", details={"operation": operation}
            )
        if not identifier.strip():
            raise AssetRecoveryRequired("幂等键缺少标识")
        return f"{prefix}:{identifier.strip()}"

    async def list_unknown(self, project_id: str) -> RecoveryInventory:
        async with self._database.session() as session:
            asset_projects = {
                asset.asset_id: asset.project_id
                for asset in await AssetRepository(session).list_all_for_project(
                    project_id
                )
            }
            generation_ids = [
                item.generation_id
                for item in await AssetGenerationRepository(session).list_by_status(
                    GENERATION_UNKNOWN
                )
                if asset_projects.get(item.asset_id) == project_id
            ]
            processing_ids = [
                item.job_id
                for item in await AssetProcessingJobRepository(session).list_by_status(
                    PROCESSING_UNKNOWN
                )
                if asset_projects.get(item.asset_id) == project_id
            ]
            import_ids = [
                item.import_job_id
                for item in await AssetImportJobRepository(session).list_by_status(
                    IMPORT_UNKNOWN
                )
                if item.project_id == project_id
            ]
            delivery_ids = [
                item.delivery_id
                for item in await AssetDeliveryRepository(session).list_by_status(
                    DELIVERY_UNKNOWN
                )
                if item.project_id == project_id
            ]
        return RecoveryInventory(
            generation_ids=tuple(generation_ids),
            processing_job_ids=tuple(processing_ids),
            import_job_ids=tuple(import_ids),
            delivery_ids=tuple(delivery_ids),
        )

    async def resolve_generation(
        self, project_id: str, generation_id: str
    ) -> GenerationView:
        await self._assert_generation_owner(project_id, generation_id)
        try:
            view = await self._generations.refresh(generation_id)
        except (AssetGenerationInvalid, AssetStateInvalid) as error:
            raise AssetRecoveryRequired(
                "无法通过 Provider 确认生成状态，保持 UNKNOWN",
                details={"generation_id": generation_id},
            ) from error
        if view.status == GENERATION_UNKNOWN:
            raise AssetRecoveryRequired(
                "生成状态仍不确定，不能盲目重试",
                details={"generation_id": generation_id},
            )
        await self._publish(
            "asset.recovery.resolved",
            {"kind": "generation", "id": generation_id, "status": view.status},
            project_id=project_id,
        )
        return view

    async def resolve_processing(
        self, project_id: str, job_id: str
    ) -> str:
        view = await self._processing.get(job_id)
        if view.project_id != project_id:
            raise NotFoundError(
                "处理任务不属于该项目",
                details={"project_id": project_id, "job_id": job_id},
            )
        if view.status != PROCESSING_UNKNOWN:
            return view.status
        if not view.output_version_id:
            raise AssetRecoveryRequired(
                "处理结果不存在，保持 UNKNOWN",
                details={"job_id": job_id},
            )
        async with self._database.session() as session, transaction(session):
            entity = await AssetProcessingJobRepository(session).get(job_id)
            if entity is None:
                raise NotFoundError("处理任务不存在", details={"job_id": job_id})
            entity.processing_status = PROCESSING_SUCCEEDED
            await session.flush()
        await self._publish(
            "asset.recovery.resolved",
            {"kind": "processing", "id": job_id, "status": PROCESSING_SUCCEEDED},
            project_id=project_id,
        )
        return PROCESSING_SUCCEEDED

    async def resolve_import(
        self, project_id: str, import_job_id: str
    ) -> ImportJobView:
        view = await self._imports.refresh(import_job_id)
        if view.project_id != project_id:
            raise NotFoundError(
                "导入任务不属于该项目",
                details={"project_id": project_id, "import_job_id": import_job_id},
            )
        if view.import_status == IMPORT_UNKNOWN:
            raise AssetRecoveryRequired(
                "导入状态仍不确定，保持 UNKNOWN",
                details={"import_job_id": import_job_id},
            )
        await self._publish(
            "asset.recovery.resolved",
            {
                "kind": "import",
                "id": import_job_id,
                "status": view.import_status,
            },
            project_id=project_id,
        )
        return view

    async def resolve_delivery(self, project_id: str, delivery_id: str):
        view = await self._deliveries.reconcile(delivery_id)
        if view.project_id != project_id:
            raise NotFoundError(
                "交付记录不属于该项目",
                details={"project_id": project_id, "delivery_id": delivery_id},
            )
        await self._publish(
            "asset.recovery.resolved",
            {
                "kind": "delivery",
                "id": delivery_id,
                "status": view.delivery_status,
            },
            project_id=project_id,
        )
        return view

    async def recover(self, project_id: str) -> dict[str, Any]:
        """按 UNKNOWN 清单逐项核对；无法确认的保持 UNKNOWN 并返回。"""

        inventory = await self.list_unknown(project_id)
        resolved: list[dict[str, str]] = []
        pending: list[dict[str, str]] = []
        tasks: list[tuple[str, str, Any]] = [
            ("generation", item, self.resolve_generation(project_id, item))
            for item in inventory.generation_ids
        ]
        tasks.extend(
            ("processing", item, self.resolve_processing(project_id, item))
            for item in inventory.processing_job_ids
        )
        tasks.extend(
            ("import", item, self.resolve_import(project_id, item))
            for item in inventory.import_job_ids
        )
        tasks.extend(
            ("delivery", item, self.resolve_delivery(project_id, item))
            for item in inventory.delivery_ids
        )
        for kind, identifier, coroutine in tasks:
            try:
                await coroutine
            except AssetRecoveryRequired:
                pending.append({"kind": kind, "id": identifier})
            except Exception:  # noqa: BLE001 - 单项失败不阻断整体核对
                log_event(
                    self._logger,
                    logging.WARNING,
                    "asset.recovery.item_failed",
                    component="asset",
                    error_code="RECOVERY_ITEM_FAILED",
                )
                pending.append({"kind": kind, "id": identifier})
            else:
                resolved.append({"kind": kind, "id": identifier})
        return {
            "inventory": inventory,
            "resolved": resolved,
            "pending": pending,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _assert_generation_owner(
        self, project_id: str, generation_id: str
    ) -> None:
        async with self._database.session() as session:
            entity = await AssetGenerationRepository(session).get(generation_id)
            if entity is None:
                raise NotFoundError(
                    "生成任务不存在", details={"generation_id": generation_id}
                )
            asset = await AssetRepository(session).get_active(entity.asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "生成任务不属于该项目",
                    details={"project_id": project_id, "generation_id": generation_id},
                )

    async def _publish(
        self, event_type: str, payload: dict[str, Any], *, project_id: str
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(
                Event.create(event_type, payload, project_id=project_id)
            )
        except Exception:  # noqa: BLE001 - 事件失败不阻断恢复
            log_event(
                self._logger,
                logging.WARNING,
                "asset.recovery.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )
