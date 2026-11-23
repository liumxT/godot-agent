"""Asset Pipeline 仓储（E8-T01 / T02）。

Repository 只读写本模块的表，不提交事务、不跨模块访问其他 Repository。
项目隔离一律在查询条件中显式带上 ``project_id``。
"""

from __future__ import annotations

from sqlalchemy import exists, func, select, update

from infrastructure.database.repository import BaseRepository, Page
from modules.asset_pipeline.models import (
    AssetBriefModel,
    AssetDeliveryModel,
    AssetDependencyModel,
    AssetGenerationModel,
    AssetGenerationOutputModel,
    AssetImportEvidenceModel,
    AssetImportJobModel,
    AssetLicenseModel,
    AssetModel,
    AssetProcessingJobModel,
    AssetProcessingStepModel,
    AssetProvenanceModel,
    AssetProviderJobModel,
    AssetQualityReviewModel,
    AssetStorageObjectModel,
    AssetVariantModel,
    AssetVersionModel,
)


class AssetRepository(BaseRepository[AssetModel]):
    model = AssetModel

    async def get_active(self, asset_id: str) -> AssetModel | None:
        return await self.session.scalar(
            select(AssetModel).where(
                AssetModel.asset_id == asset_id, AssetModel.deleted_at.is_(None)
            )
        )

    async def get_by_name(self, project_id: str, name: str) -> AssetModel | None:
        return await self.session.scalar(
            select(AssetModel).where(
                AssetModel.project_id == project_id,
                AssetModel.name == name,
                AssetModel.deleted_at.is_(None),
            )
        )

    async def list_page(
        self,
        *,
        project_id: str,
        category: str | None = None,
        asset_type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        source_type: str | None = None,
        license_status: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[AssetModel]:
        filters = [AssetModel.project_id == project_id]
        if not include_deleted:
            filters.append(AssetModel.deleted_at.is_(None))
        if category is not None:
            filters.append(AssetModel.category == category)
        if asset_type is not None:
            filters.append(AssetModel.asset_type == asset_type)
        if status is not None:
            filters.append(AssetModel.lifecycle_status == status)
        if tag is not None:
            filters.append(AssetModel.tags_json.like(f'%"{tag}"%'))
        if source_type is not None:
            filters.append(
                exists(
                    select(AssetVersionModel.version_id).where(
                        AssetVersionModel.version_id == AssetModel.current_version_id,
                        AssetVersionModel.source_type == source_type,
                    )
                )
            )
        if license_status is not None:
            filters.append(
                exists(
                    select(AssetLicenseModel.license_id).where(
                        AssetLicenseModel.asset_version_id == AssetModel.current_version_id,
                        AssetLicenseModel.verification_status == license_status,
                    )
                )
            )
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def transition_status(
        self,
        asset_id: str,
        *,
        from_statuses: frozenset[str],
        to_status: str,
        expected_version: int,
        now,
        deleted_at=None,
    ) -> bool:
        values = {
            "lifecycle_status": to_status,
            "version": AssetModel.version + 1,
            "updated_at": now,
        }
        if deleted_at is not None:
            values["deleted_at"] = deleted_at
        result = await self.session.execute(
            update(AssetModel)
            .where(
                AssetModel.asset_id == asset_id,
                AssetModel.version == expected_version,
                AssetModel.lifecycle_status.in_(from_statuses),
                AssetModel.deleted_at.is_(None),
            )
            .values(**values)
        )
        return result.rowcount == 1

    async def update_metadata(
        self,
        asset_id: str,
        *,
        expected_version: int,
        values: dict[str, object],
    ) -> bool:
        payload = dict(values)
        payload["version"] = AssetModel.version + 1
        result = await self.session.execute(
            update(AssetModel)
            .where(
                AssetModel.asset_id == asset_id,
                AssetModel.version == expected_version,
                AssetModel.deleted_at.is_(None),
            )
            .values(**payload)
        )
        return result.rowcount == 1

    async def set_current_version(self, asset_id: str, version_id: str, now) -> bool:
        result = await self.session.execute(
            update(AssetModel)
            .where(AssetModel.asset_id == asset_id, AssetModel.deleted_at.is_(None))
            .values(
                current_version_id=version_id,
                version=AssetModel.version + 1,
                updated_at=now,
            )
        )
        return result.rowcount == 1

    async def duplicate_hashes(self, project_id: str) -> list[dict[str, object]]:
        statement = (
            select(
                AssetVersionModel.content_hash,
                func.count(func.distinct(AssetVersionModel.asset_id)).label("asset_count"),
            )
            .join(AssetModel, AssetModel.asset_id == AssetVersionModel.asset_id)
            .where(AssetModel.project_id == project_id, AssetModel.deleted_at.is_(None))
            .group_by(AssetVersionModel.content_hash)
            .having(func.count(func.distinct(AssetVersionModel.asset_id)) > 1)
            .order_by(AssetVersionModel.content_hash)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            {"content_hash": row.content_hash, "asset_count": int(row.asset_count)}
            for row in rows
        ]

    async def orphan_asset_ids(self, project_id: str) -> list[str]:
        statement = (
            select(AssetModel.asset_id)
            .where(
                AssetModel.project_id == project_id,
                AssetModel.deleted_at.is_(None),
                AssetModel.current_version_id.is_not(None),
                ~exists(
                    select(AssetDependencyModel.dependency_id).where(
                        AssetDependencyModel.asset_version_id == AssetModel.current_version_id
                    )
                ),
            )
            .order_by(AssetModel.asset_id)
        )
        return list((await self.session.scalars(statement)).all())

    async def count_for_project(self, project_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(AssetModel)
                .where(
                    AssetModel.project_id == project_id, AssetModel.deleted_at.is_(None)
                )
            )
            or 0
        )


class AssetVersionRepository(BaseRepository[AssetVersionModel]):
    model = AssetVersionModel

    async def list_for_asset(self, asset_id: str) -> list[AssetVersionModel]:
        rows = await self.session.scalars(
            select(AssetVersionModel)
            .where(AssetVersionModel.asset_id == asset_id)
            .order_by(AssetVersionModel.version_number)
        )
        return list(rows)

    async def get_by_number(
        self, asset_id: str, version_number: int
    ) -> AssetVersionModel | None:
        return await self.session.scalar(
            select(AssetVersionModel).where(
                AssetVersionModel.asset_id == asset_id,
                AssetVersionModel.version_number == version_number,
            )
        )

    async def latest(self, asset_id: str) -> AssetVersionModel | None:
        return await self.session.scalar(
            select(AssetVersionModel)
            .where(AssetVersionModel.asset_id == asset_id)
            .order_by(AssetVersionModel.version_number.desc())
            .limit(1)
        )


class AssetVariantRepository(BaseRepository[AssetVariantModel]):
    model = AssetVariantModel

    async def list_for_asset(self, asset_id: str) -> list[AssetVariantModel]:
        rows = await self.session.scalars(
            select(AssetVariantModel)
            .where(AssetVariantModel.asset_id == asset_id)
            .order_by(AssetVariantModel.variant_type, AssetVariantModel.variant_key)
        )
        return list(rows)

    async def get_by_key(
        self, asset_id: str, variant_type: str, variant_key: str
    ) -> AssetVariantModel | None:
        return await self.session.scalar(
            select(AssetVariantModel).where(
                AssetVariantModel.asset_id == asset_id,
                AssetVariantModel.variant_type == variant_type,
                AssetVariantModel.variant_key == variant_key,
            )
        )


class AssetBriefRepository(BaseRepository[AssetBriefModel]):
    model = AssetBriefModel

    async def list_for_project(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[AssetBriefModel]:
        filters = [AssetBriefModel.project_id == project_id]
        if status is not None:
            filters.append(AssetBriefModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)


class AssetDependencyRepository(BaseRepository[AssetDependencyModel]):
    model = AssetDependencyModel

    async def list_for_version(self, asset_version_id: str) -> list[AssetDependencyModel]:
        rows = await self.session.scalars(
            select(AssetDependencyModel)
            .where(AssetDependencyModel.asset_version_id == asset_version_id)
            .order_by(AssetDependencyModel.created_at)
        )
        return list(rows)

    async def list_referencing(
        self, project_id: str, target_reference: str
    ) -> list[AssetDependencyModel]:
        rows = await self.session.scalars(
            select(AssetDependencyModel)
            .where(
                AssetDependencyModel.project_id == project_id,
                AssetDependencyModel.target_reference == target_reference,
            )
            .order_by(AssetDependencyModel.created_at)
        )
        return list(rows)


class AssetGenerationRepository(BaseRepository[AssetGenerationModel]):
    model = AssetGenerationModel

    async def get_by_idempotency(self, key: str) -> AssetGenerationModel | None:
        return await self.session.scalar(
            select(AssetGenerationModel).where(AssetGenerationModel.idempotency_key == key)
        )

    async def list_for_asset(self, asset_id: str) -> list[AssetGenerationModel]:
        rows = await self.session.scalars(
            select(AssetGenerationModel)
            .where(AssetGenerationModel.asset_id == asset_id)
            .order_by(AssetGenerationModel.created_at)
        )
        return list(rows)


class AssetGenerationOutputRepository(BaseRepository[AssetGenerationOutputModel]):
    model = AssetGenerationOutputModel

    async def list_for_generation(
        self, generation_id: str
    ) -> list[AssetGenerationOutputModel]:
        rows = await self.session.scalars(
            select(AssetGenerationOutputModel)
            .where(AssetGenerationOutputModel.generation_id == generation_id)
            .order_by(AssetGenerationOutputModel.created_at)
        )
        return list(rows)


class AssetProcessingJobRepository(BaseRepository[AssetProcessingJobModel]):
    model = AssetProcessingJobModel

    async def list_for_asset(self, asset_id: str) -> list[AssetProcessingJobModel]:
        rows = await self.session.scalars(
            select(AssetProcessingJobModel)
            .where(AssetProcessingJobModel.asset_id == asset_id)
            .order_by(AssetProcessingJobModel.created_at)
        )
        return list(rows)

    async def get_by_idempotency(self, key: str) -> AssetProcessingJobModel | None:
        return await self.session.scalar(
            select(AssetProcessingJobModel).where(
                AssetProcessingJobModel.idempotency_key == key
            )
        )


class AssetProcessingStepRepository(BaseRepository[AssetProcessingStepModel]):
    model = AssetProcessingStepModel

    async def list_for_job(self, job_id: str) -> list[AssetProcessingStepModel]:
        rows = await self.session.scalars(
            select(AssetProcessingStepModel)
            .where(AssetProcessingStepModel.job_id == job_id)
            .order_by(AssetProcessingStepModel.node_id)
        )
        return list(rows)


class AssetImportJobRepository(BaseRepository[AssetImportJobModel]):
    model = AssetImportJobModel

    async def list_for_version(self, asset_version_id: str) -> list[AssetImportJobModel]:
        rows = await self.session.scalars(
            select(AssetImportJobModel)
            .where(AssetImportJobModel.asset_version_id == asset_version_id)
            .order_by(AssetImportJobModel.created_at)
        )
        return list(rows)


class AssetImportEvidenceRepository(BaseRepository[AssetImportEvidenceModel]):
    model = AssetImportEvidenceModel

    async def get_for_job(self, import_job_id: str) -> AssetImportEvidenceModel | None:
        return await self.session.scalar(
            select(AssetImportEvidenceModel)
            .where(AssetImportEvidenceModel.import_job_id == import_job_id)
            .order_by(AssetImportEvidenceModel.created_at.desc())
            .limit(1)
        )


class AssetProvenanceRepository(BaseRepository[AssetProvenanceModel]):
    model = AssetProvenanceModel

    async def get_for_version(self, asset_version_id: str) -> AssetProvenanceModel | None:
        return await self.session.scalar(
            select(AssetProvenanceModel).where(
                AssetProvenanceModel.asset_version_id == asset_version_id
            )
        )


class AssetLicenseRepository(BaseRepository[AssetLicenseModel]):
    model = AssetLicenseModel

    async def latest_for_version(self, asset_version_id: str) -> AssetLicenseModel | None:
        return await self.session.scalar(
            select(AssetLicenseModel)
            .where(AssetLicenseModel.asset_version_id == asset_version_id)
            .order_by(AssetLicenseModel.created_at.desc())
            .limit(1)
        )

    async def list_for_version(self, asset_version_id: str) -> list[AssetLicenseModel]:
        rows = await self.session.scalars(
            select(AssetLicenseModel)
            .where(AssetLicenseModel.asset_version_id == asset_version_id)
            .order_by(AssetLicenseModel.created_at)
        )
        return list(rows)


class AssetQualityReviewRepository(BaseRepository[AssetQualityReviewModel]):
    model = AssetQualityReviewModel

    async def list_for_version(self, asset_version_id: str) -> list[AssetQualityReviewModel]:
        rows = await self.session.scalars(
            select(AssetQualityReviewModel)
            .where(AssetQualityReviewModel.asset_version_id == asset_version_id)
            .order_by(AssetQualityReviewModel.created_at)
        )
        return list(rows)


class AssetDeliveryRepository(BaseRepository[AssetDeliveryModel]):
    model = AssetDeliveryModel

    async def list_for_asset(self, asset_id: str) -> list[AssetDeliveryModel]:
        rows = await self.session.scalars(
            select(AssetDeliveryModel)
            .where(AssetDeliveryModel.asset_id == asset_id)
            .order_by(AssetDeliveryModel.created_at)
        )
        return list(rows)


class AssetStorageObjectRepository(BaseRepository[AssetStorageObjectModel]):
    model = AssetStorageObjectModel

    async def list_for_version(self, asset_version_id: str) -> list[AssetStorageObjectModel]:
        rows = await self.session.scalars(
            select(AssetStorageObjectModel)
            .where(AssetStorageObjectModel.asset_version_id == asset_version_id)
            .order_by(AssetStorageObjectModel.created_at)
        )
        return list(rows)

    async def get_by_path(
        self, project_id: str, relative_path: str
    ) -> AssetStorageObjectModel | None:
        return await self.session.scalar(
            select(AssetStorageObjectModel).where(
                AssetStorageObjectModel.project_id == project_id,
                AssetStorageObjectModel.relative_path == relative_path,
            )
        )


class AssetProviderJobRepository(BaseRepository[AssetProviderJobModel]):
    model = AssetProviderJobModel

    async def get_external(
        self, provider_id: str, provider_job_id: str
    ) -> AssetProviderJobModel | None:
        return await self.session.scalar(
            select(AssetProviderJobModel).where(
                AssetProviderJobModel.provider_id == provider_id,
                AssetProviderJobModel.provider_job_id == provider_job_id,
            )
        )
