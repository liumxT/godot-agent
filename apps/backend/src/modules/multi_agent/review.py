"""Agent 独立评审与 Peer Review（E7-T16）。

Review 只产出结构化结论，不替代 Verification System 的客观验证。审查人必须
与被审查 Assignment 保持独立性：不同 Agent Definition，或同一个 Definition
但不同执行实例；同一实例自审会被拒绝。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from core.errors import AgentReviewInvalid, NotFoundError
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.multi_agent.models import (
    ASSIGNMENT_COMPLETED,
    CONFLICT_SEVERITIES,
    REVIEW_ACCEPTANCE_STATUSES,
    REVIEW_ACCEPTED,
    REVIEW_COMPLETED,
    REVIEW_IN_PROGRESS,
    REVIEW_PENDING,
    REVIEW_TYPES,
    SEVERITY_MEDIUM,
    AgentReviewModel,
)
from modules.multi_agent.repository import (
    AgentReviewRepository,
)
from modules.multi_agent.service import AssignmentService, AssignmentView


@dataclass(frozen=True, slots=True)
class ReviewView:
    review_id: str
    team_id: str
    target_assignment_id: str
    reviewer_assignment_id: str | None
    review_type: str
    status: str
    findings: tuple[str, ...]
    severity: str
    evidence_reference: str | None
    recommendation: str | None
    acceptance_status: str | None
    requires_verification: bool
    created_at: datetime
    completed_at: datetime | None


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _review_view(entity: AgentReviewModel) -> ReviewView:
    return ReviewView(
        review_id=entity.review_id,
        team_id=entity.team_id,
        target_assignment_id=entity.target_assignment_id,
        reviewer_assignment_id=entity.reviewer_assignment_id,
        review_type=entity.review_type,
        status=entity.status,
        findings=tuple(json.loads(entity.findings or "[]")),
        severity=entity.severity,
        evidence_reference=entity.evidence_reference,
        recommendation=entity.recommendation,
        acceptance_status=entity.acceptance_status,
        requires_verification=True,
        created_at=ensure_utc(entity.created_at),
        completed_at=ensure_utc(entity.completed_at) if entity.completed_at else None,
    )


class ReviewService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        assignments: AssignmentService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._assignments = assignments
        self._clock = clock

    async def request(
        self,
        *,
        team_id: str,
        target_assignment_id: str,
        review_type: str,
        reviewer_assignment_id: str | None = None,
    ) -> ReviewView:
        if review_type not in REVIEW_TYPES:
            raise AgentReviewInvalid(
                "Review 类型非法",
                details={"reasons": ["UNKNOWN_REVIEW_TYPE"], "review_type": review_type},
            )
        target = await self._assignments.get(target_assignment_id)
        if target.team_id != team_id:
            raise AgentReviewInvalid(
                "被审查 Assignment 不属于该 Team",
                details={"reasons": ["TARGET_NOT_IN_TEAM"]},
            )
        if target.status != ASSIGNMENT_COMPLETED or not target.output_reference:
            raise AgentReviewInvalid(
                "只有已完成且有输出的 Assignment 可以评审",
                details={"reasons": ["TARGET_NOT_READY"], "status": target.status},
            )
        if reviewer_assignment_id is not None:
            reviewer = await self._assignments.get(reviewer_assignment_id)
            if reviewer.team_id != team_id:
                raise AgentReviewInvalid(
                    "审查人不属于该 Team",
                    details={"reasons": ["REVIEWER_NOT_IN_TEAM"]},
                )
            if not _is_independent(target, reviewer):
                raise AgentReviewInvalid(
                    "审查人必须与被审查者独立",
                    details={"reasons": ["INDEPENDENT_REVIEWER_REQUIRED"]},
                )
        now = self._clock()
        entity = AgentReviewModel(
            review_id=_new_id("rev_"),
            team_id=team_id,
            target_assignment_id=target_assignment_id,
            reviewer_assignment_id=reviewer_assignment_id,
            review_type=review_type,
            status=REVIEW_PENDING,
            findings="[]",
            severity=SEVERITY_MEDIUM,
            evidence_reference=None,
            recommendation=None,
            acceptance_status=None,
            created_at=now,
            completed_at=None,
        )
        async with self._database.session() as session, transaction(session):
            await AgentReviewRepository(session).add(entity)
        return _review_view(entity)

    async def get(self, review_id: str) -> ReviewView:
        async with self._database.session() as session:
            entity = await AgentReviewRepository(session).get(review_id)
        if entity is None:
            raise NotFoundError("Review 不存在", details={"review_id": review_id})
        return _review_view(entity)

    async def list_for_team(self, team_id: str) -> list[ReviewView]:
        async with self._database.session() as session:
            rows = await AgentReviewRepository(session).list_for_team(team_id)
        return [_review_view(row) for row in rows]

    async def list_for_target(self, assignment_id: str) -> list[ReviewView]:
        async with self._database.session() as session:
            rows = await AgentReviewRepository(session).list_for_target(assignment_id)
        return [_review_view(row) for row in rows]

    async def start(self, review_id: str) -> ReviewView:
        async with self._database.session() as session, transaction(session):
            repository = AgentReviewRepository(session)
            entity = await repository.get(review_id)
            if entity is None:
                raise NotFoundError("Review 不存在", details={"review_id": review_id})
            if entity.status != REVIEW_PENDING:
                raise AgentReviewInvalid(
                    "Review 当前状态不可开始",
                    details={"reasons": ["INVALID_TRANSITION"], "status": entity.status},
                )
            entity.status = REVIEW_IN_PROGRESS
            await session.flush()
            return _review_view(entity)

    async def complete(
        self,
        review_id: str,
        *,
        findings: Iterable[str],
        severity: str,
        acceptance_status: str,
        evidence_reference: str,
        recommendation: str | None = None,
    ) -> ReviewView:
        items = tuple(item.strip() for item in findings if item and item.strip())
        if severity not in CONFLICT_SEVERITIES:
            raise AgentReviewInvalid(
                "Review severity 非法",
                details={"reasons": ["UNKNOWN_SEVERITY"], "severity": severity},
            )
        if acceptance_status not in REVIEW_ACCEPTANCE_STATUSES:
            raise AgentReviewInvalid(
                "Review acceptance status 非法",
                details={"reasons": ["UNKNOWN_ACCEPTANCE"], "acceptance_status": acceptance_status},
            )
        if not (evidence_reference or "").strip():
            raise AgentReviewInvalid(
                "Review 必须提供证据", details={"reasons": ["EVIDENCE_REQUIRED"]}
            )
        if not items and acceptance_status != REVIEW_ACCEPTED:
            raise AgentReviewInvalid(
                "非通过评审必须包含 findings", details={"reasons": ["FINDINGS_REQUIRED"]}
            )
        if acceptance_status != REVIEW_ACCEPTED and not (recommendation or "").strip():
            raise AgentReviewInvalid(
                "非通过评审必须给出修改建议",
                details={"reasons": ["RECOMMENDATION_REQUIRED"]},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentReviewRepository(session)
            entity = await repository.get(review_id)
            if entity is None:
                raise NotFoundError("Review 不存在", details={"review_id": review_id})
            if entity.status != REVIEW_IN_PROGRESS:
                raise AgentReviewInvalid(
                    "Review 必须先开始才能完成",
                    details={"reasons": ["INVALID_TRANSITION"], "status": entity.status},
                )
            entity.status = REVIEW_COMPLETED
            entity.findings = json.dumps(list(items), ensure_ascii=False)
            entity.severity = severity
            entity.evidence_reference = evidence_reference
            entity.recommendation = recommendation
            entity.acceptance_status = acceptance_status
            entity.completed_at = now
            await session.flush()
            return _review_view(entity)


def _is_independent(target: AssignmentView, reviewer: AssignmentView) -> bool:
    if reviewer.assignment_id == target.assignment_id:
        return False
    if reviewer.agent_definition_id != target.agent_definition_id:
        return True
    return (
        reviewer.agent_instance_id is not None
        and target.agent_instance_id is not None
        and reviewer.agent_instance_id != target.agent_instance_id
    )


__all__ = ["ReviewService", "ReviewView"]
