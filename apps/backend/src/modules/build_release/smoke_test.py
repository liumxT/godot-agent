"""制品验证与冒烟测试（E10-T14）。

规则：

- 只有在清单哈希与登记内容一致时才能标记 VERIFIED；
- SKIPPED / UNKNOWN 不能计为通过；
- 冒烟结果只追加，并生成 release evidence；
- 发布候选择优必须存在 PASSED 冒烟记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import ArtifactVerificationInvalid, ValidationFailed
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.models import (
    SMOKE_FAILED,
    SMOKE_PASSED,
    SMOKE_SKIPPED,
    SMOKE_STATUSES,
    SmokeTestResultModel,
)
from modules.build_release.provenance import BuildProvenanceService
from modules.build_release.repository import SmokeTestResultRepository
from modules.build_release.service import _dump, _load, _new_id


@dataclass(frozen=True, slots=True)
class SmokeTestView:
    smoke_test_id: str
    project_id: str
    artifact_id: str | None
    package_id: str | None
    release_candidate_id: str | None
    status: str
    checks: tuple[dict[str, Any], ...]
    evidence_reference: str
    duration_ms: int
    created_at: datetime


def _smoke_view(entity: SmokeTestResultModel) -> SmokeTestView:
    return SmokeTestView(
        smoke_test_id=entity.smoke_test_id,
        project_id=entity.project_id,
        artifact_id=entity.artifact_id,
        package_id=entity.package_id,
        release_candidate_id=entity.release_candidate_id,
        status=entity.status,
        checks=tuple(_load(entity.checks_json, [])),
        evidence_reference=entity.evidence_reference,
        duration_ms=entity.duration_ms,
        created_at=entity.created_at,
    )


def evaluate_checks(checks: list[dict[str, Any]]) -> str:
    """根据已执行检查计算整体状态，未执行不计为通过。"""

    if not checks:
        return SMOKE_SKIPPED
    statuses = [str(check.get("status", "UNKNOWN")).upper() for check in checks]
    if SMOKE_FAILED in statuses:
        return SMOKE_FAILED
    if all(status == SMOKE_PASSED for status in statuses):
        return SMOKE_PASSED
    return SMOKE_SKIPPED


class ArtifactVerificationService:
    """制品验证门禁：先核对内容哈希，再迁移验证状态。"""

    def __init__(self, database: DatabaseService, *, artifacts: ArtifactRegistryService) -> None:
        self._database = database
        self._artifacts = artifacts

    async def verify_artifact(self, artifact_id: str, files: list[dict[str, Any]]) -> Any:
        artifact = await self._artifacts.get_artifact(artifact_id)
        await self._artifacts.verify_integrity(artifact_id, files)
        return await self._artifacts.mark_verified(artifact.artifact_id)


class SmokeTestService:
    """记录冒烟测试结果并生成证据。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        provenance: BuildProvenanceService | None = None,
    ) -> None:
        self._database = database
        self._provenance = provenance

    async def record_smoke_test(
        self,
        *,
        project_id: str,
        checks: list[dict[str, Any]],
        artifact_id: str | None = None,
        package_id: str | None = None,
        release_candidate_id: str | None = None,
        evidence_reference: str = "",
        duration_ms: int = 0,
    ) -> SmokeTestView:
        if not artifact_id and not package_id:
            raise ValidationFailed("冒烟测试必须关联制品或交付包")
        if duration_ms < 0:
            raise ValidationFailed("duration_ms 不能为负")
        status = evaluate_checks(checks)
        if status not in SMOKE_STATUSES:
            raise ArtifactVerificationInvalid("冒烟测试状态非法")
        now = utcnow()
        entity = SmokeTestResultModel(
            smoke_test_id=_new_id("smk"),
            project_id=project_id,
            artifact_id=artifact_id,
            package_id=package_id,
            release_candidate_id=release_candidate_id,
            status=status,
            checks_json=_dump(checks),
            evidence_reference=evidence_reference,
            duration_ms=duration_ms,
            created_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await SmokeTestResultRepository(session).add(entity)
        if self._provenance is not None:
            await self._provenance.add_evidence(
                project_id=project_id,
                evidence_type="smoke_test",
                artifact_id=artifact_id,
                package_id=package_id,
                release_candidate_id=release_candidate_id,
                reference=evidence_reference or entity.smoke_test_id,
                details={"status": status, "checks": checks},
            )
        return _smoke_view(entity)

    async def list_for_candidate(self, release_candidate_id: str) -> list[SmokeTestView]:
        async with self._database.session() as session:
            rows = await SmokeTestResultRepository(session).list_for_candidate(release_candidate_id)
        return [_smoke_view(row) for row in rows]

    async def has_passed_for_artifact(self, artifact_id: str) -> bool:
        async with self._database.session() as session:
            return await SmokeTestResultRepository(session).has_passed_for_artifact(artifact_id)
