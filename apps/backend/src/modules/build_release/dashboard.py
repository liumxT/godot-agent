"""构建与发布看板聚合（E10-T18）。

只做只读聚合，不改变任何构建、制品或发布状态；
数据不足时返回空列表，不伪造统计结果。
"""

from __future__ import annotations

from typing import Any

from infrastructure.database.service import DatabaseService
from modules.build_release.distribution import build_default_registry
from modules.build_release.models import (
    APPROVAL_STATUSES,
    ARTIFACT_STATUSES,
    BUILD_STATUSES,
    PACKAGE_VERIFIED,
    RC_STATUSES,
    RELEASE_STATUSES,
)
from modules.build_release.repository import (
    ArtifactRepository,
    BuildConfigurationRepository,
    BuildEnvironmentRepository,
    BuildJobRepository,
    PackageRepository,
    ReleaseApprovalRepository,
    ReleaseCandidateRepository,
    ReleaseRepository,
)


class BuildReleaseDashboardService:
    """构建队列、制品、候选与发布看板。"""

    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def overview(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            configurations = await BuildConfigurationRepository(session).list_page(
                project_id=project_id, limit=5
            )
            environments = await BuildEnvironmentRepository(session).list_page(
                project_id=project_id, limit=5
            )
            build_totals = {
                status: (
                    await BuildJobRepository(session).list_page(
                        project_id=project_id, status=status, limit=1
                    )
                ).total
                for status in sorted(BUILD_STATUSES)
            }
            recent_builds = await BuildJobRepository(session).list_page(
                project_id=project_id, limit=10
            )
            artifact_total = (
                await ArtifactRepository(session).list_page(project_id=project_id, limit=1)
            ).total
            recent_artifacts = await ArtifactRepository(session).list_page(
                project_id=project_id, limit=10
            )
            package_total = (
                await PackageRepository(session).list_page(project_id=project_id, limit=1)
            ).total
            verified_packages = (
                await PackageRepository(session).list_page(
                    project_id=project_id, status=PACKAGE_VERIFIED, limit=1
                )
            ).total
            candidate_totals = {
                status: (
                    await ReleaseCandidateRepository(session).list_page(
                        project_id=project_id, status=status, limit=1
                    )
                ).total
                for status in sorted(RC_STATUSES)
            }
            recent_candidates = await ReleaseCandidateRepository(session).list_page(
                project_id=project_id, limit=10
            )
            approval_totals = {
                status: (
                    await ReleaseApprovalRepository(session).list_page(
                        project_id=project_id, status=status, limit=1
                    )
                ).total
                for status in sorted(APPROVAL_STATUSES)
            }
            recent_approvals = await ReleaseApprovalRepository(session).list_page(
                project_id=project_id, limit=10
            )
            release_totals = {
                status: (
                    await ReleaseRepository(session).list_page(
                        project_id=project_id, status=status, limit=1
                    )
                ).total
                for status in sorted(RELEASE_STATUSES)
            }
            recent_releases = await ReleaseRepository(session).list_page(
                project_id=project_id, limit=10
            )

        return {
            "project_id": project_id,
            "configurations": [_configuration_row(item) for item in configurations.items],
            "environments": [_environment_row(item) for item in environments.items],
            "builds": {
                "totals": build_totals,
                "recent": [_build_row(item) for item in recent_builds.items],
            },
            "artifacts": {
                "total": artifact_total,
                "statuses": sorted(ARTIFACT_STATUSES),
                "recent": [_artifact_row(item) for item in recent_artifacts.items],
            },
            "packages": {"total": package_total, "verified": verified_packages},
            "release_candidates": {
                "totals": candidate_totals,
                "recent": [_candidate_row(item) for item in recent_candidates.items],
            },
            "approvals": {
                "totals": approval_totals,
                "recent": [_approval_row(item) for item in recent_approvals.items],
            },
            "releases": {
                "totals": release_totals,
                "recent": [_release_row(item) for item in recent_releases.items],
            },
            "distribution_capabilities": [
                {
                    "channel": item.channel,
                    "supported": item.supported,
                    "requires_authorization": item.requires_authorization,
                    "supports_withdraw": item.supports_withdraw,
                    "description": item.description,
                }
                for item in build_default_registry().capabilities()
            ],
        }


def _configuration_row(entity) -> dict[str, Any]:
    return {
        "configuration_id": entity.configuration_id,
        "name": entity.name,
        "target_platform": entity.target_platform,
        "architecture": entity.architecture,
        "current_version": entity.current_version,
        "updated_at": entity.updated_at.isoformat(),
    }


def _environment_row(entity) -> dict[str, Any]:
    return {
        "environment_id": entity.environment_id,
        "os_name": entity.os_name,
        "godot_version": entity.godot_version,
        "status": entity.status,
        "environment_fingerprint": entity.environment_fingerprint,
        "created_at": entity.created_at.isoformat(),
    }


def _build_row(entity) -> dict[str, Any]:
    return {
        "build_id": entity.build_id,
        "build_config_id": entity.build_config_id,
        "build_config_version": entity.build_config_version,
        "status": entity.status,
        "current_attempt_id": entity.current_attempt_id,
        "requested_by": entity.requested_by,
        "created_at": entity.created_at.isoformat(),
        "started_at": entity.started_at.isoformat() if entity.started_at else None,
        "finished_at": entity.finished_at.isoformat() if entity.finished_at else None,
    }


def _artifact_row(entity) -> dict[str, Any]:
    return {
        "artifact_id": entity.artifact_id,
        "build_id": entity.build_id,
        "artifact_version": entity.artifact_version,
        "platform": entity.platform,
        "architecture": entity.architecture,
        "format": entity.format,
        "file_size": entity.file_size,
        "content_hash": entity.content_hash,
        "verification_status": entity.verification_status,
        "created_at": entity.created_at.isoformat(),
    }


def _candidate_row(entity) -> dict[str, Any]:
    return {
        "release_candidate_id": entity.release_candidate_id,
        "version": entity.version,
        "artifact_id": entity.artifact_id,
        "package_id": entity.package_id,
        "status": entity.status,
        "candidate_manifest_hash": entity.candidate_manifest_hash,
        "created_at": entity.created_at.isoformat(),
    }


def _approval_row(entity) -> dict[str, Any]:
    return {
        "approval_id": entity.approval_id,
        "release_candidate_id": entity.release_candidate_id,
        "distribution_channel": entity.distribution_channel,
        "status": entity.status,
        "approved_by": entity.approved_by,
        "requested_at": entity.requested_at.isoformat(),
    }


def _release_row(entity) -> dict[str, Any]:
    return {
        "release_id": entity.release_id,
        "release_candidate_id": entity.release_candidate_id,
        "channel": entity.channel,
        "version": entity.version,
        "status": entity.status,
        "distribution_reference": entity.distribution_reference,
        "published_at": entity.published_at.isoformat() if entity.published_at else None,
    }
