"""构建来源与发布证据（E10-T13）。

Provenance 与 Evidence 均为只追加记录：

- Provenance 绑定构建输入、配置快照哈希、环境指纹与产物哈希；
- Evidence 记录验证、完整性、冒烟、审批、签名和分发证据；
- 已写入记录不得覆盖，只能追加新的证据引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.models import BuildProvenanceModel, ReleaseEvidenceModel
from modules.build_release.repository import (
    BuildProvenanceRepository,
    ReleaseEvidenceRepository,
)
from modules.build_release.service import _dump, _hash_payload, _load, _new_id

EVIDENCE_VERIFICATION = "verification"
EVIDENCE_ARTIFACT_INTEGRITY = "artifact_integrity"
EVIDENCE_SMOKE_TEST = "smoke_test"
EVIDENCE_APPROVAL = "approval"
EVIDENCE_SIGNING = "signing"
EVIDENCE_DISTRIBUTION = "distribution"
EVIDENCE_TYPES = frozenset(
    {
        EVIDENCE_VERIFICATION,
        EVIDENCE_ARTIFACT_INTEGRITY,
        EVIDENCE_SMOKE_TEST,
        EVIDENCE_APPROVAL,
        EVIDENCE_SIGNING,
        EVIDENCE_DISTRIBUTION,
    }
)


@dataclass(frozen=True, slots=True)
class ProvenanceView:
    provenance_id: str
    project_id: str
    build_id: str
    attempt_id: str
    artifact_id: str | None
    source_revision: str
    config_snapshot_hash: str
    environment_fingerprint: str
    command_template_id: str
    executor_id: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceView:
    evidence_id: str
    project_id: str
    release_candidate_id: str | None
    artifact_id: str | None
    package_id: str | None
    evidence_type: str
    reference: str
    content_hash: str
    details: dict[str, Any]
    created_at: datetime


def _provenance_view(entity: BuildProvenanceModel) -> ProvenanceView:
    return ProvenanceView(
        provenance_id=entity.provenance_id,
        project_id=entity.project_id,
        build_id=entity.build_id,
        attempt_id=entity.attempt_id,
        artifact_id=entity.artifact_id,
        source_revision=entity.source_revision,
        config_snapshot_hash=entity.config_snapshot_hash,
        environment_fingerprint=entity.environment_fingerprint,
        command_template_id=entity.command_template_id,
        executor_id=entity.executor_id,
        inputs=_load(entity.inputs_json, {}),
        outputs=_load(entity.outputs_json, {}),
        created_at=entity.created_at,
    )


def _evidence_view(entity: ReleaseEvidenceModel) -> EvidenceView:
    return EvidenceView(
        evidence_id=entity.evidence_id,
        project_id=entity.project_id,
        release_candidate_id=entity.release_candidate_id,
        artifact_id=entity.artifact_id,
        package_id=entity.package_id,
        evidence_type=entity.evidence_type,
        reference=entity.reference,
        content_hash=entity.content_hash,
        details=_load(entity.details_json, {}),
        created_at=entity.created_at,
    )


class BuildProvenanceService:
    """构建来源与发布证据。"""

    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def record_provenance(
        self,
        *,
        project_id: str,
        build_id: str,
        attempt_id: str,
        artifact_id: str | None = None,
        source_revision: str = "",
        config_snapshot_hash: str = "",
        environment_fingerprint: str = "",
        command_template_id: str = "",
        executor_id: str = "",
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> ProvenanceView:
        async with self._database.session() as session, transaction(session):
            repo = BuildProvenanceRepository(session)
            existing = await repo.get_by_build_attempt(build_id, attempt_id)
            if existing is not None:
                return _provenance_view(existing)
            entity = BuildProvenanceModel(
                provenance_id=_new_id("prov"),
                project_id=project_id,
                build_id=build_id,
                attempt_id=attempt_id,
                artifact_id=artifact_id,
                source_revision=source_revision,
                config_snapshot_hash=config_snapshot_hash,
                environment_fingerprint=environment_fingerprint,
                command_template_id=command_template_id,
                executor_id=executor_id,
                inputs_json=_dump(inputs or {}),
                outputs_json=_dump(outputs or {}),
                created_at=utcnow(),
            )
            await repo.add(entity)
        return _provenance_view(entity)

    async def get_provenance(self, build_id: str, attempt_id: str) -> ProvenanceView | None:
        async with self._database.session() as session:
            entity = await BuildProvenanceRepository(session).get_by_build_attempt(
                build_id, attempt_id
            )
        return _provenance_view(entity) if entity is not None else None

    async def list_provenance(self, build_id: str) -> list[ProvenanceView]:
        async with self._database.session() as session:
            rows = await BuildProvenanceRepository(session).list_for_build(build_id)
        return [_provenance_view(row) for row in rows]

    async def add_evidence(
        self,
        *,
        project_id: str,
        evidence_type: str,
        artifact_id: str | None = None,
        package_id: str | None = None,
        release_candidate_id: str | None = None,
        reference: str = "",
        content_hash: str = "",
        details: dict[str, Any] | None = None,
    ) -> EvidenceView:
        if evidence_type not in EVIDENCE_TYPES:
            from core.errors import ValidationFailed

            raise ValidationFailed("未知证据类型", details={"evidence_type": evidence_type})
        payload = details or {}
        if not content_hash:
            content_hash = _hash_payload(
                {
                    "evidence_type": evidence_type,
                    "reference": reference,
                    "details": payload,
                }
            )
        entity = ReleaseEvidenceModel(
            evidence_id=_new_id("evd"),
            project_id=project_id,
            release_candidate_id=release_candidate_id,
            artifact_id=artifact_id,
            package_id=package_id,
            evidence_type=evidence_type,
            reference=reference,
            content_hash=content_hash,
            details_json=_dump(payload),
            created_at=utcnow(),
        )
        async with self._database.session() as session, transaction(session):
            await ReleaseEvidenceRepository(session).add(entity)
        return _evidence_view(entity)

    async def list_evidence(
        self,
        project_id: str,
        *,
        evidence_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await ReleaseEvidenceRepository(session).list_page(
                project_id=project_id,
                evidence_type=evidence_type,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [_evidence_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def list_candidate_evidence(self, release_candidate_id: str) -> list[EvidenceView]:
        async with self._database.session() as session:
            rows = await ReleaseEvidenceRepository(session).list_for_candidate(release_candidate_id)
        return [_evidence_view(row) for row in rows]
