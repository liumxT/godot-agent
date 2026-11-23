"""多 Agent 共享上下文协调（E7-T09）。

共享 Context 以版本化引用传递：数据库只保存引用、哈希与状态，实际内容由
Context 层提供。``PRIVATE`` 范围禁止登记为共享 Context；替换既有版本必须
显式给出期望版本，并保留被替换记录的 ``superseded_by``，不允许无记录覆盖。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import AgentContextInvalid, AgentContextStale, NotFoundError, VersionConflict
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.multi_agent.models import (
    CONTEXT_ACTIVE,
    CONTEXT_SCOPE_TEAM,
    CONTEXT_STALE_PAUSE,
    CONTEXT_STALE_POLICIES,
    CONTEXT_STALE_REFRESH,
    CONTEXT_SUPERSEDED,
    SHARED_CONTEXT_SCOPES,
    AgentAssignmentModel,
    AgentSharedContextModel,
)
from modules.multi_agent.repository import (
    AgentAssignmentRepository,
    AgentSharedContextRepository,
    AgentTeamRepository,
)


@dataclass(frozen=True, slots=True)
class SharedContextView:
    context_id: str
    team_id: str
    context_version: int
    scope: str
    content_reference: str
    content_hash: str
    created_by_assignment_id: str | None
    status: str
    superseded_by: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ContextUsage:
    """Agent 使用共享 Context 时的版本判定结果。"""

    context: SharedContextView
    stale: bool
    policy: str


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _content_hash(content: Mapping[str, Any] | None, content_reference: str) -> str:
    payload = dict(content) if content is not None else {"reference": content_reference}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _context_view(entity: AgentSharedContextModel) -> SharedContextView:
    return SharedContextView(
        context_id=entity.context_id,
        team_id=entity.team_id,
        context_version=entity.context_version,
        scope=entity.scope,
        content_reference=entity.content_reference,
        content_hash=entity.content_hash,
        created_by_assignment_id=entity.created_by_assignment_id,
        status=entity.status,
        superseded_by=entity.superseded_by,
        created_at=entity.created_at,
    )


class SharedContextService:
    def __init__(
        self, database: DatabaseService, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._database = database
        self._clock = clock

    async def publish(
        self,
        team_id: str,
        *,
        content_reference: str,
        scope: str = CONTEXT_SCOPE_TEAM,
        content: Mapping[str, Any] | None = None,
        created_by_assignment_id: str | None = None,
        expected_version: int | None = None,
    ) -> SharedContextView:
        if scope not in SHARED_CONTEXT_SCOPES:
            raise AgentContextInvalid(
                "共享 Context 范围非法",
                details={"reasons": ["SCOPE_NOT_SHARABLE"], "scope": scope},
            )
        if not (content_reference or "").strip():
            raise AgentContextInvalid(
                "共享 Context 必须引用内容", details={"reasons": ["REFERENCE_REQUIRED"]}
            )
        now = self._clock()
        digest = _content_hash(content, content_reference)
        async with self._database.session() as session, transaction(session):
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            if created_by_assignment_id is not None:
                await self._require_member(session, team_id, created_by_assignment_id)
            repository = AgentSharedContextRepository(session)
            latest = await repository.latest(team_id)
            if expected_version is not None:
                actual = latest.context_version if latest is not None else 0
                if actual != expected_version:
                    raise VersionConflict(
                        "共享 Context 版本已变化",
                        details={"expected": expected_version, "actual": actual},
                    )
            if latest is not None and latest.content_hash == digest and latest.scope == scope:
                return _context_view(latest)
            if latest is not None and latest.status == CONTEXT_ACTIVE:
                latest.status = CONTEXT_SUPERSEDED
            entity = AgentSharedContextModel(
                context_id=_new_id("ctx_"),
                team_id=team_id,
                context_version=(latest.context_version + 1) if latest is not None else 1,
                scope=scope,
                content_reference=content_reference,
                content_hash=digest,
                created_by_assignment_id=created_by_assignment_id,
                status=CONTEXT_ACTIVE,
                superseded_by=None,
                created_at=now,
            )
            await repository.add(entity)
            if latest is not None:
                latest.superseded_by = entity.context_id
            await session.flush()
            return _context_view(entity)

    async def get(self, context_id: str) -> SharedContextView:
        async with self._database.session() as session:
            entity = await AgentSharedContextRepository(session).get(context_id)
        if entity is None:
            raise NotFoundError("共享 Context 不存在", details={"context_id": context_id})
        return _context_view(entity)

    async def latest(self, team_id: str) -> SharedContextView:
        async with self._database.session() as session:
            team = await AgentTeamRepository(session).get(team_id)
            if team is None:
                raise NotFoundError("Agent Team 不存在", details={"team_id": team_id})
            entity = await AgentSharedContextRepository(session).latest(team_id)
        if entity is None:
            raise NotFoundError("共享 Context 不存在", details={"team_id": team_id})
        return _context_view(entity)

    async def list_for_team(self, team_id: str) -> list[SharedContextView]:
        async with self._database.session() as session:
            rows = await AgentSharedContextRepository(session).list_for_team(team_id)
        return [_context_view(row) for row in rows]

    async def check(
        self,
        team_id: str,
        expected_version: int,
        *,
        policy: str = CONTEXT_STALE_REFRESH,
    ) -> ContextUsage:
        """判断 Agent 使用的 Context 是否过期，并按策略返回或拒绝。"""

        if policy not in CONTEXT_STALE_POLICIES:
            raise AgentContextInvalid(
                "Context 过期策略非法",
                details={"reasons": ["UNKNOWN_STALE_POLICY"], "policy": policy},
            )
        latest = await self.latest(team_id)
        stale = latest.context_version != expected_version
        if stale and policy == CONTEXT_STALE_PAUSE:
            raise AgentContextStale(
                "共享 Context 已过期，必须暂停等待刷新",
                details={
                    "reasons": ["CONTEXT_STALE"],
                    "expected": expected_version,
                    "actual": latest.context_version,
                },
            )
        return ContextUsage(context=latest, stale=stale, policy=policy)

    @staticmethod
    async def _require_member(
        session: Any, team_id: str, assignment_id: str
    ) -> AgentAssignmentModel:
        assignment = await AgentAssignmentRepository(session).get(assignment_id)
        if assignment is None or assignment.team_id != team_id:
            raise AgentContextInvalid(
                "创建者不属于该 Team",
                details={"reasons": ["UNKNOWN_CREATOR"], "assignment_id": assignment_id},
            )
        return assignment


__all__ = ["ContextUsage", "SharedContextService", "SharedContextView"]
