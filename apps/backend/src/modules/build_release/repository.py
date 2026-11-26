"""Build & Release 仓储（E10-T02 / T03 / T04）。

Repository 只读写 build_release 自己的表，不提交事务、不修改其他模块状态。
所有按项目查询都必须显式带 ``project_id``。
"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.database.repository import BaseRepository, Page
from modules.build_release.models import (
    APPROVAL_APPROVED,
    ArtifactManifestModel,
    ArtifactModel,
    BuildAttemptModel,
    BuildConfigurationModel,
    BuildConfigurationVersionModel,
    BuildEnvironmentModel,
    BuildJobModel,
    BuildLogModel,
    BuildProvenanceModel,
    DistributionOperationModel,
    ExportPresetModel,
    PackageManifestModel,
    PackageModel,
    PlatformCapabilityModel,
    ReleaseApprovalModel,
    ReleaseCandidateModel,
    ReleaseEvidenceModel,
    ReleaseModel,
    SigningAttemptModel,
    SigningProfileModel,
    SmokeTestResultModel,
)


class BuildConfigurationRepository(BaseRepository[BuildConfigurationModel]):
    model = BuildConfigurationModel

    async def get_by_name(self, project_id: str, name: str) -> BuildConfigurationModel | None:
        return await self.session.scalar(
            select(BuildConfigurationModel).where(
                BuildConfigurationModel.project_id == project_id,
                BuildConfigurationModel.name == name,
            )
        )

    async def list_page(
        self,
        *,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[BuildConfigurationModel]:
        return await self.paginate(
            limit=limit,
            offset=offset,
            filters=[BuildConfigurationModel.project_id == project_id],
        )

    async def list_all(self, project_id: str) -> list[BuildConfigurationModel]:
        rows = await self.session.scalars(
            select(BuildConfigurationModel)
            .where(BuildConfigurationModel.project_id == project_id)
            .order_by(BuildConfigurationModel.created_at)
        )
        return list(rows.all())


class BuildConfigurationVersionRepository(BaseRepository[BuildConfigurationVersionModel]):
    model = BuildConfigurationVersionModel

    async def get_version(
        self, configuration_id: str, version: int
    ) -> BuildConfigurationVersionModel | None:
        return await self.session.scalar(
            select(BuildConfigurationVersionModel).where(
                BuildConfigurationVersionModel.configuration_id == configuration_id,
                BuildConfigurationVersionModel.version == version,
            )
        )

    async def latest(self, configuration_id: str) -> BuildConfigurationVersionModel | None:
        return await self.session.scalar(
            select(BuildConfigurationVersionModel)
            .where(BuildConfigurationVersionModel.configuration_id == configuration_id)
            .order_by(BuildConfigurationVersionModel.version.desc())
        )

    async def list_for_configuration(
        self, configuration_id: str
    ) -> list[BuildConfigurationVersionModel]:
        rows = await self.session.scalars(
            select(BuildConfigurationVersionModel)
            .where(BuildConfigurationVersionModel.configuration_id == configuration_id)
            .order_by(BuildConfigurationVersionModel.version)
        )
        return list(rows.all())


class ExportPresetRepository(BaseRepository[ExportPresetModel]):
    model = ExportPresetModel

    async def get_by_name(self, project_id: str, preset_name: str) -> ExportPresetModel | None:
        return await self.session.scalar(
            select(ExportPresetModel).where(
                ExportPresetModel.project_id == project_id,
                ExportPresetModel.preset_name == preset_name,
            )
        )

    async def list_page(
        self,
        *,
        project_id: str,
        platform: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ExportPresetModel]:
        filters = [ExportPresetModel.project_id == project_id]
        if platform is not None:
            filters.append(ExportPresetModel.platform == platform)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_for_project(self, project_id: str) -> list[ExportPresetModel]:
        rows = await self.session.scalars(
            select(ExportPresetModel)
            .where(ExportPresetModel.project_id == project_id)
            .order_by(ExportPresetModel.preset_name)
        )
        return list(rows.all())


class BuildEnvironmentRepository(BaseRepository[BuildEnvironmentModel]):
    model = BuildEnvironmentModel

    async def get_by_fingerprint(
        self, project_id: str | None, fingerprint: str
    ) -> BuildEnvironmentModel | None:
        statement = select(BuildEnvironmentModel).where(
            BuildEnvironmentModel.environment_fingerprint == fingerprint
        )
        if project_id is None:
            statement = statement.where(BuildEnvironmentModel.project_id.is_(None))
        else:
            statement = statement.where(BuildEnvironmentModel.project_id == project_id)
        return await self.session.scalar(
            statement.order_by(BuildEnvironmentModel.created_at.desc())
        )

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[BuildEnvironmentModel]:
        filters = [BuildEnvironmentModel.project_id == project_id]
        if status is not None:
            filters.append(BuildEnvironmentModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)


class PlatformCapabilityRepository(BaseRepository[PlatformCapabilityModel]):
    model = PlatformCapabilityModel

    async def get_by_platform(self, platform_id: str) -> PlatformCapabilityModel | None:
        return await self.session.scalar(
            select(PlatformCapabilityModel).where(
                PlatformCapabilityModel.platform_id == platform_id
            )
        )

    async def list_all(self) -> list[PlatformCapabilityModel]:
        rows = await self.session.scalars(
            select(PlatformCapabilityModel).order_by(PlatformCapabilityModel.platform_id)
        )
        return list(rows.all())


class BuildJobRepository(BaseRepository[BuildJobModel]):
    model = BuildJobModel

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[BuildJobModel]:
        filters = [BuildJobModel.project_id == project_id]
        if status is not None:
            filters.append(BuildJobModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_active_for_project(self, project_id: str) -> list[BuildJobModel]:
        rows = await self.session.scalars(
            select(BuildJobModel).where(
                BuildJobModel.project_id == project_id,
                BuildJobModel.status.in_(
                    ("QUEUED", "PREPARING", "RUNNING", "EXPORTING", "COLLECTING", "UNKNOWN")
                ),
            )
        )
        return list(rows.all())


class BuildAttemptRepository(BaseRepository[BuildAttemptModel]):
    model = BuildAttemptModel

    async def list_for_build(self, build_id: str) -> list[BuildAttemptModel]:
        rows = await self.session.scalars(
            select(BuildAttemptModel)
            .where(BuildAttemptModel.build_id == build_id)
            .order_by(BuildAttemptModel.attempt_number)
        )
        return list(rows.all())

    async def next_number(self, build_id: str) -> int:
        rows = await self.list_for_build(build_id)
        return (rows[-1].attempt_number + 1) if rows else 1


class BuildLogRepository(BaseRepository[BuildLogModel]):
    model = BuildLogModel

    async def list_for_attempt(self, attempt_id: str) -> list[BuildLogModel]:
        rows = await self.session.scalars(
            select(BuildLogModel)
            .where(BuildLogModel.attempt_id == attempt_id)
            .order_by(BuildLogModel.sequence)
        )
        return list(rows.all())

    async def next_sequence(self, attempt_id: str) -> int:
        rows = await self.list_for_attempt(attempt_id)
        return (rows[-1].sequence + 1) if rows else 0


class ArtifactRepository(BaseRepository[ArtifactModel]):
    model = ArtifactModel

    async def list_page(
        self,
        *,
        project_id: str,
        platform: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ArtifactModel]:
        filters = [ArtifactModel.project_id == project_id]
        if platform is not None:
            filters.append(ArtifactModel.platform == platform)
        if status is not None:
            filters.append(ArtifactModel.verification_status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_for_build(self, build_id: str) -> list[ArtifactModel]:
        rows = await self.session.scalars(
            select(ArtifactModel)
            .where(ArtifactModel.build_id == build_id)
            .order_by(ArtifactModel.artifact_version)
        )
        return list(rows.all())

    async def list_for_project(self, project_id: str) -> list[ArtifactModel]:
        rows = await self.session.scalars(
            select(ArtifactModel)
            .where(ArtifactModel.project_id == project_id)
            .order_by(ArtifactModel.artifact_version)
        )
        return list(rows.all())

    async def next_version(self, project_id: str, build_id: str | None) -> int:
        rows = (
            await self.list_for_build(build_id)
            if build_id
            else await self.list_for_project(project_id)
        )
        return (rows[-1].artifact_version + 1) if rows else 1

    async def find_by_hash(self, project_id: str, content_hash: str) -> ArtifactModel | None:
        return await self.session.scalar(
            select(ArtifactModel)
            .where(
                ArtifactModel.project_id == project_id,
                ArtifactModel.content_hash == content_hash,
            )
            .order_by(ArtifactModel.created_at.desc())
        )


class ArtifactManifestRepository(BaseRepository[ArtifactManifestModel]):
    model = ArtifactManifestModel

    async def get_for_artifact(self, artifact_id: str) -> ArtifactManifestModel | None:
        return await self.session.scalar(
            select(ArtifactManifestModel).where(ArtifactManifestModel.artifact_id == artifact_id)
        )


class PackageRepository(BaseRepository[PackageModel]):
    model = PackageModel

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[PackageModel]:
        filters = [PackageModel.project_id == project_id]
        if status is not None:
            filters.append(PackageModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_for_artifact(self, artifact_id: str) -> list[PackageModel]:
        rows = await self.session.scalars(
            select(PackageModel)
            .where(PackageModel.artifact_id == artifact_id)
            .order_by(PackageModel.package_version)
        )
        return list(rows.all())

    async def next_version(self, artifact_id: str) -> int:
        rows = await self.list_for_artifact(artifact_id)
        return (rows[-1].package_version + 1) if rows else 1


class PackageManifestRepository(BaseRepository[PackageManifestModel]):
    model = PackageManifestModel

    async def get_for_package(self, package_id: str) -> PackageManifestModel | None:
        return await self.session.scalar(
            select(PackageManifestModel).where(PackageManifestModel.package_id == package_id)
        )


class BuildProvenanceRepository(BaseRepository[BuildProvenanceModel]):
    model = BuildProvenanceModel

    async def get_by_build_attempt(
        self, build_id: str, attempt_id: str
    ) -> BuildProvenanceModel | None:
        return await self.session.scalar(
            select(BuildProvenanceModel).where(
                BuildProvenanceModel.build_id == build_id,
                BuildProvenanceModel.attempt_id == attempt_id,
            )
        )

    async def list_for_build(self, build_id: str) -> list[BuildProvenanceModel]:
        rows = await self.session.scalars(
            select(BuildProvenanceModel)
            .where(BuildProvenanceModel.build_id == build_id)
            .order_by(BuildProvenanceModel.created_at)
        )
        return list(rows.all())


class ReleaseEvidenceRepository(BaseRepository[ReleaseEvidenceModel]):
    model = ReleaseEvidenceModel

    async def list_for_candidate(self, release_candidate_id: str) -> list[ReleaseEvidenceModel]:
        rows = await self.session.scalars(
            select(ReleaseEvidenceModel)
            .where(ReleaseEvidenceModel.release_candidate_id == release_candidate_id)
            .order_by(ReleaseEvidenceModel.created_at)
        )
        return list(rows.all())

    async def list_for_artifact(self, artifact_id: str) -> list[ReleaseEvidenceModel]:
        rows = await self.session.scalars(
            select(ReleaseEvidenceModel)
            .where(ReleaseEvidenceModel.artifact_id == artifact_id)
            .order_by(ReleaseEvidenceModel.created_at)
        )
        return list(rows.all())

    async def list_page(
        self,
        *,
        project_id: str,
        evidence_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ReleaseEvidenceModel]:
        filters = [ReleaseEvidenceModel.project_id == project_id]
        if evidence_type is not None:
            filters.append(ReleaseEvidenceModel.evidence_type == evidence_type)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def find_by_reference(
        self, project_id: str, evidence_type: str, reference: str
    ) -> ReleaseEvidenceModel | None:
        rows = await self.session.scalars(
            select(ReleaseEvidenceModel).where(
                ReleaseEvidenceModel.project_id == project_id,
                ReleaseEvidenceModel.evidence_type == evidence_type,
                ReleaseEvidenceModel.reference == reference,
            )
        )
        return rows.first()


class ReleaseCandidateRepository(BaseRepository[ReleaseCandidateModel]):
    model = ReleaseCandidateModel

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ReleaseCandidateModel]:
        filters = [ReleaseCandidateModel.project_id == project_id]
        if status is not None:
            filters.append(ReleaseCandidateModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_by_version(self, project_id: str, version: str) -> list[ReleaseCandidateModel]:
        rows = await self.session.scalars(
            select(ReleaseCandidateModel)
            .where(
                ReleaseCandidateModel.project_id == project_id,
                ReleaseCandidateModel.version == version,
            )
            .order_by(ReleaseCandidateModel.created_at)
        )
        return list(rows.all())


class SmokeTestResultRepository(BaseRepository[SmokeTestResultModel]):
    model = SmokeTestResultModel

    async def list_for_artifact(self, artifact_id: str) -> list[SmokeTestResultModel]:
        rows = await self.session.scalars(
            select(SmokeTestResultModel)
            .where(SmokeTestResultModel.artifact_id == artifact_id)
            .order_by(SmokeTestResultModel.created_at)
        )
        return list(rows.all())

    async def list_for_package(self, package_id: str) -> list[SmokeTestResultModel]:
        rows = await self.session.scalars(
            select(SmokeTestResultModel)
            .where(SmokeTestResultModel.package_id == package_id)
            .order_by(SmokeTestResultModel.created_at)
        )
        return list(rows.all())

    async def list_for_candidate(self, release_candidate_id: str) -> list[SmokeTestResultModel]:
        rows = await self.session.scalars(
            select(SmokeTestResultModel)
            .where(SmokeTestResultModel.release_candidate_id == release_candidate_id)
            .order_by(SmokeTestResultModel.created_at)
        )
        return list(rows.all())

    async def has_passed_for_artifact(self, artifact_id: str) -> bool:
        rows = await self.list_for_artifact(artifact_id)
        return any(row.status == "PASSED" for row in rows)


class SigningProfileRepository(BaseRepository[SigningProfileModel]):
    model = SigningProfileModel

    async def get_for_scope(
        self, project_id: str, platform: str, signing_method: str
    ) -> SigningProfileModel | None:
        return await self.session.scalar(
            select(SigningProfileModel).where(
                SigningProfileModel.project_id == project_id,
                SigningProfileModel.platform == platform,
                SigningProfileModel.signing_method == signing_method,
            )
        )

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[SigningProfileModel]:
        filters = [SigningProfileModel.project_id == project_id]
        if status is not None:
            filters.append(SigningProfileModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)


class SigningAttemptRepository(BaseRepository[SigningAttemptModel]):
    model = SigningAttemptModel

    async def list_for_artifact(self, artifact_id: str) -> list[SigningAttemptModel]:
        rows = await self.session.scalars(
            select(SigningAttemptModel)
            .where(SigningAttemptModel.artifact_id == artifact_id)
            .order_by(SigningAttemptModel.created_at)
        )
        return list(rows.all())

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[SigningAttemptModel]:
        filters = [SigningAttemptModel.project_id == project_id]
        if status is not None:
            filters.append(SigningAttemptModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)


class ReleaseApprovalRepository(BaseRepository[ReleaseApprovalModel]):
    model = ReleaseApprovalModel

    async def list_for_candidate(self, release_candidate_id: str) -> list[ReleaseApprovalModel]:
        rows = await self.session.scalars(
            select(ReleaseApprovalModel)
            .where(ReleaseApprovalModel.release_candidate_id == release_candidate_id)
            .order_by(ReleaseApprovalModel.requested_at)
        )
        return list(rows.all())

    async def find_approved(self, release_candidate_id: str) -> ReleaseApprovalModel | None:
        return await self.session.scalar(
            select(ReleaseApprovalModel).where(
                ReleaseApprovalModel.release_candidate_id == release_candidate_id,
                ReleaseApprovalModel.status == APPROVAL_APPROVED,
            )
        )

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ReleaseApprovalModel]:
        filters = [ReleaseApprovalModel.project_id == project_id]
        if status is not None:
            filters.append(ReleaseApprovalModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)


class ReleaseRepository(BaseRepository[ReleaseModel]):
    model = ReleaseModel

    async def list_page(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ReleaseModel]:
        filters = [ReleaseModel.project_id == project_id]
        if status is not None:
            filters.append(ReleaseModel.status == status)
        return await self.paginate(limit=limit, offset=offset, filters=filters)

    async def list_for_candidate(self, release_candidate_id: str) -> list[ReleaseModel]:
        rows = await self.session.scalars(
            select(ReleaseModel)
            .where(ReleaseModel.release_candidate_id == release_candidate_id)
            .order_by(ReleaseModel.created_at)
        )
        return list(rows.all())


class DistributionOperationRepository(BaseRepository[DistributionOperationModel]):
    model = DistributionOperationModel

    async def find_by_idempotency_key(
        self, idempotency_key: str
    ) -> DistributionOperationModel | None:
        return await self.session.scalar(
            select(DistributionOperationModel).where(
                DistributionOperationModel.idempotency_key == idempotency_key
            )
        )

    async def list_for_release(self, release_id: str) -> list[DistributionOperationModel]:
        rows = await self.session.scalars(
            select(DistributionOperationModel)
            .where(DistributionOperationModel.release_id == release_id)
            .order_by(DistributionOperationModel.started_at)
        )
        return list(rows.all())
