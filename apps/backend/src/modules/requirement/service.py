"""Requirement Tracking（E4-T18）：需求、验收标准与追踪关系。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import NotFoundError, ValidationFailed
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.requirement.models import (
    CATEGORY_FUNCTIONAL,
    CRITERION_MET,
    CRITERION_NOT_MET,
    CRITERION_PENDING,
    CRITERION_STATUSES,
    CRITERION_WAIVED,
    REQUIREMENT_ACTIVE,
    REQUIREMENT_CATEGORIES,
    REQUIREMENT_DRAFT,
    REQUIREMENT_IMPLEMENTED,
    REQUIREMENT_VERIFIED,
    AcceptanceCriterionModel,
    RequirementModel,
    RequirementTraceModel,
)
from modules.requirement.repository import (
    AcceptanceCriterionRepository,
    RequirementRepository,
    RequirementTraceRepository,
)


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


@dataclass(frozen=True)
class CriterionView:
    criterion_id: str
    criterion_key: str
    description: str
    verification_method: str | None
    required_evidence: list[str]
    status: str


@dataclass(frozen=True)
class RequirementView:
    requirement_id: str
    project_id: str
    requirement_key: str
    title: str
    description: str | None
    category: str
    priority: str
    status: str
    source: str | None
    created_at: datetime
    updated_at: datetime
    criteria: list[CriterionView]


def _criterion_view(entity: AcceptanceCriterionModel) -> CriterionView:
    return CriterionView(
        criterion_id=entity.criterion_id,
        criterion_key=entity.criterion_key,
        description=entity.description,
        verification_method=entity.verification_method,
        required_evidence=[item for item in (entity.required_evidence or "").split("|") if item],
        status=entity.status,
    )


def _requirement_view(
    entity: RequirementModel, criteria: Sequence[AcceptanceCriterionModel]
) -> RequirementView:
    return RequirementView(
        requirement_id=entity.requirement_id,
        project_id=entity.project_id,
        requirement_key=entity.requirement_key,
        title=entity.title,
        description=entity.description,
        category=entity.category,
        priority=entity.priority,
        status=entity.status,
        source=entity.source,
        created_at=ensure_utc(entity.created_at),
        updated_at=ensure_utc(entity.updated_at),
        criteria=[_criterion_view(item) for item in criteria],
    )


class RequirementService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._clock = clock

    async def create(
        self,
        *,
        project_id: str,
        requirement_key: str,
        title: str,
        criteria: Sequence[dict[str, Any]] = (),
        description: str | None = None,
        category: str = CATEGORY_FUNCTIONAL,
        priority: str = "MEDIUM",
        source: str | None = None,
        status: str = REQUIREMENT_DRAFT,
    ) -> RequirementView:
        if category not in REQUIREMENT_CATEGORIES:
            raise ValidationFailed("需求分类非法", details={"category": category})
        if status not in (REQUIREMENT_DRAFT, REQUIREMENT_ACTIVE):
            raise ValidationFailed("需求初始状态非法")
        if not requirement_key.strip():
            raise ValidationFailed("requirement_key 不能为空")
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = RequirementRepository(session)
            if await repository.get_by_key(project_id, requirement_key) is not None:
                raise ValidationFailed(
                    "requirement_key 已存在", details={"requirement_key": requirement_key}
                )
            entity = RequirementModel(
                requirement_id=_new_id("req_"),
                project_id=project_id,
                requirement_key=requirement_key.strip(),
                title=title.strip()[:256],
                description=description,
                category=category,
                priority=priority,
                status=status,
                source=source,
                created_at=now,
                updated_at=now,
            )
            await repository.add(entity)
            criteria_entities = []
            for index, item in enumerate(criteria):
                criterion = AcceptanceCriterionModel(
                    criterion_id=_new_id("crt_"),
                    requirement_id=entity.requirement_id,
                    criterion_key=str(item.get("criterion_key") or f"AC-{index + 1}"),
                    description=str(item.get("description") or ""),
                    verification_method=item.get("verification_method"),
                    required_evidence="|".join(item.get("required_evidence") or []),
                    status=CRITERION_PENDING,
                )
                await AcceptanceCriterionRepository(session).add(criterion)
                criteria_entities.append(criterion)
            await session.flush()
            return _requirement_view(entity, criteria_entities)

    async def get(self, requirement_id: str) -> RequirementView:
        async with self._database.session() as session:
            entity = await RequirementRepository(session).get(requirement_id)
            if entity is None:
                raise NotFoundError("需求不存在", details={"requirement_id": requirement_id})
            criteria = await AcceptanceCriterionRepository(session).list_by_requirement(
                requirement_id
            )
        return _requirement_view(entity, criteria)

    async def list(self, project_id: str, *, status: str | None = None) -> list[RequirementView]:
        async with self._database.session() as session:
            rows = await RequirementRepository(session).list_by_project(project_id, status=status)
            criteria_repository = AcceptanceCriterionRepository(session)
            criteria = {
                row.requirement_id: await criteria_repository.list_by_requirement(
                    row.requirement_id
                )
                for row in rows
            }
        return [_requirement_view(row, criteria[row.requirement_id]) for row in rows]

    async def update_status(self, requirement_id: str, status: str) -> RequirementView:
        allowed = {
            REQUIREMENT_DRAFT,
            REQUIREMENT_ACTIVE,
            REQUIREMENT_IMPLEMENTED,
            REQUIREMENT_VERIFIED,
            "REJECTED",
            "DEFERRED",
        }
        if status not in allowed:
            raise ValidationFailed("需求状态非法", details={"status": status})
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await RequirementRepository(session).get(requirement_id)
            if entity is None:
                raise NotFoundError("需求不存在", details={"requirement_id": requirement_id})
            entity.status = status
            entity.updated_at = now
            criteria = await AcceptanceCriterionRepository(session).list_by_requirement(
                requirement_id
            )
            await session.flush()
            return _requirement_view(entity, criteria)

    async def set_criterion_status(
        self, requirement_id: str, criterion_key: str, status: str, *, evidence: str | None = None
    ) -> RequirementView:
        if status not in CRITERION_STATUSES:
            raise ValidationFailed("验收标准状态非法", details={"status": status})
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await RequirementRepository(session).get(requirement_id)
            if entity is None:
                raise NotFoundError("需求不存在", details={"requirement_id": requirement_id})
            repository = AcceptanceCriterionRepository(session)
            criterion = await repository.get_by_key(requirement_id, criterion_key)
            if criterion is None:
                raise NotFoundError("验收标准不存在", details={"criterion_key": criterion_key})
            criterion.status = status
            if evidence:
                criterion.required_evidence = (
                    f"{criterion.required_evidence}|{evidence}"
                    if criterion.required_evidence
                    else evidence
                )
            criteria = await repository.list_by_requirement(requirement_id)
            if criteria and all(
                item.status in (CRITERION_MET, CRITERION_WAIVED) for item in criteria
            ):
                entity.status = REQUIREMENT_VERIFIED
            elif any(item.status == CRITERION_NOT_MET for item in criteria):
                entity.status = REQUIREMENT_IMPLEMENTED
            entity.updated_at = now
            await session.flush()
            return _requirement_view(entity, criteria)

    async def trace(
        self,
        requirement_id: str,
        *,
        task_id: str | None = None,
        phase_id: str | None = None,
        changeset_id: str | None = None,
        verification_result_id: str | None = None,
    ) -> dict[str, Any]:
        if not any((task_id, phase_id, changeset_id, verification_result_id)):
            raise ValidationFailed("追踪关系至少需要一个目标")
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            if await RequirementRepository(session).get(requirement_id) is None:
                raise NotFoundError("需求不存在", details={"requirement_id": requirement_id})
            entity = RequirementTraceModel(
                trace_id=_new_id("rtr_"),
                requirement_id=requirement_id,
                task_id=task_id,
                phase_id=phase_id,
                changeset_id=changeset_id,
                verification_result_id=verification_result_id,
                created_at=now,
            )
            await RequirementTraceRepository(session).add(entity)
            await session.flush()
            return format_trace(entity)

    async def list_traces(self, requirement_id: str) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            rows = await RequirementTraceRepository(session).list_by_requirement(requirement_id)
        return [format_trace(row) for row in rows]


def format_requirement(view: RequirementView) -> dict[str, Any]:
    return {
        "requirement_id": view.requirement_id,
        "project_id": view.project_id,
        "requirement_key": view.requirement_key,
        "title": view.title,
        "description": view.description,
        "category": view.category,
        "priority": view.priority,
        "status": view.status,
        "source": view.source,
        "created_at": isoformat(view.created_at),
        "updated_at": isoformat(view.updated_at),
        "criteria": [
            {
                "criterion_id": item.criterion_id,
                "criterion_key": item.criterion_key,
                "description": item.description,
                "verification_method": item.verification_method,
                "required_evidence": item.required_evidence,
                "status": item.status,
            }
            for item in view.criteria
        ],
    }


def format_trace(entity: RequirementTraceModel) -> dict[str, Any]:
    return {
        "trace_id": entity.trace_id,
        "requirement_id": entity.requirement_id,
        "task_id": entity.task_id,
        "phase_id": entity.phase_id,
        "changeset_id": entity.changeset_id,
        "verification_result_id": entity.verification_result_id,
        "created_at": isoformat(entity.created_at),
    }
