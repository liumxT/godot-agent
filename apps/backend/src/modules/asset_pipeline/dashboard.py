"""资产浏览器与仪表盘聚合（E8-T17）。

为管理界面提供只读聚合视图：资产当前版本、来源、质量、License、导入、交付
与依赖状态，以及生成/处理/导入的 UNKNOWN 清单。所有数据来自既有服务，
不改变任何状态。
"""

from __future__ import annotations

from typing import Any

from core.errors import NotFoundError
from infrastructure.database.service import DatabaseService
from modules.asset_pipeline.repository import AssetVersionRepository

__all__ = ["AssetDashboardService"]


def _latest(items):
    if not items:
        return None
    return max(items, key=lambda item: getattr(item, "created_at", None))


class AssetDashboardService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        assets,
        generations,
        processing,
        quality,
        licenses,
        imports,
        deliveries,
        dependencies,
        recovery,
    ) -> None:
        self._database = database
        self._assets = assets
        self._generations = generations
        self._processing = processing
        self._quality = quality
        self._licenses = licenses
        self._imports = imports
        self._deliveries = deliveries
        self._dependencies = dependencies
        self._recovery = recovery

    async def snapshot(self, project_id: str, *, limit: int = 50) -> dict[str, Any]:
        page = await self._assets.list(project_id=project_id, limit=limit)
        rows: list[dict[str, Any]] = []
        for view in page["items"]:
            rows.append(await self._asset_row(project_id, view))
        inventory = await self._recovery.list_unknown(project_id)
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["lifecycle_status"]] = counts.get(row["lifecycle_status"], 0) + 1
        return {
            "items": rows,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "status_counts": counts,
            "unknown": {
                "generations": list(inventory.generation_ids),
                "processing_jobs": list(inventory.processing_job_ids),
                "imports": list(inventory.import_job_ids),
                "deliveries": list(inventory.delivery_ids),
                "total": inventory.total,
            },
        }

    async def _asset_row(self, project_id: str, view) -> dict[str, Any]:
        asset_id = view.asset_id
        async with self._database.session() as session:
            versions = await AssetVersionRepository(session).list_for_asset(asset_id)
        current_version_id = view.current_version_id
        quality_status = None
        license_status = None
        import_status = None
        godot_uid = None
        dependency_count = 0
        if current_version_id:
            quality_status = await self._quality_status(
                project_id, asset_id, current_version_id
            )
            try:
                license_view = await self._licenses.latest_for_version(
                    project_id, current_version_id
                )
            except NotFoundError:
                license_view = None
            license_status = (
                license_view.verification_status if license_view is not None else None
            )
            imports = await self._imports.list_for_version(
                project_id, current_version_id
            )
            latest_import = _latest(imports)
            if latest_import is not None:
                import_status = latest_import.import_status
                godot_uid = latest_import.godot_uid
            dependencies = await self._dependencies.list_for_version(
                project_id, current_version_id
            )
            dependency_count = len(dependencies)
        generations = await self._generations.list_for_asset(project_id, asset_id)
        processing_jobs = await self._processing.list_for_asset(project_id, asset_id)
        deliveries = await self._deliveries.list_for_asset(project_id, asset_id)
        latest_generation = _latest(generations)
        latest_processing = _latest(processing_jobs)
        latest_delivery = _latest(deliveries)
        return {
            "asset_id": asset_id,
            "name": view.name,
            "category": view.category,
            "asset_type": view.asset_type,
            "tags": list(view.tags),
            "lifecycle_status": view.lifecycle_status,
            "current_version_id": current_version_id,
            "version_count": len(versions),
            "quality_status": quality_status,
            "license_status": license_status,
            "import_status": import_status,
            "godot_uid": godot_uid,
            "delivery_status": (
                latest_delivery.delivery_status if latest_delivery is not None else None
            ),
            "generation_status": (
                latest_generation.status if latest_generation is not None else None
            ),
            "processing_status": (
                latest_processing.status if latest_processing is not None else None
            ),
            "dependency_count": dependency_count,
            "updated_at": view.updated_at,
        }

    async def _quality_status(
        self, project_id: str, asset_id: str, version_id: str
    ) -> str | None:
        reviews = await self._quality.list_for_version(
            project_id, asset_id, version_id
        )
        latest = _latest(reviews)
        return latest.review_status if latest is not None else None
