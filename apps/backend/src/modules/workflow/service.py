"""Workflow Engine（E4-T12…T17 / T21）。

Workflow / Node / Phase 状态只能由本模块修改。Workflow 完成后通过
``TaskService.request_review`` 把 Task 推进到 REVIEW_PENDING，而不是直接写 Task 表。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from core.errors import InvalidStateTransition, NotFoundError, ValidationFailed
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.task.models import TASK_RUNNING
from modules.task.repository import TaskAttemptRepository, TaskRepository
from modules.task.service import TaskService
from modules.workflow.models import (
    DEFINITION_ACTIVE,
    INSTANCE_BLOCKED,
    INSTANCE_COMPLETED,
    INSTANCE_FAILED,
    INSTANCE_PAUSED,
    INSTANCE_PAUSING,
    INSTANCE_READY,
    INSTANCE_RESUMING,
    INSTANCE_RUNNING,
    INSTANCE_TRANSITIONS,
    NODE_CANCELLED,
    NODE_FAILED,
    NODE_PENDING,
    NODE_READY,
    NODE_RUNNING,
    NODE_SKIPPED,
    NODE_SUCCEEDED,
    NODE_TYPE_AI_EXECUTION,
    NODE_TYPES,
    PHASE_ACCEPTED,
    PHASE_IN_PROGRESS,
    PHASE_NEEDS_REVISION,
    PHASE_PENDING,
    PHASE_READY,
    PHASE_REVIEW_PENDING,
    REVIEW_ACCEPTED,
    REVIEW_DRAFT,
    REVIEW_NEEDS_REVISION,
    REVIEW_SUBMITTED,
    WorkflowDefinitionModel,
    WorkflowDefinitionVersionModel,
    WorkflowInstanceModel,
    WorkflowNodeDefinitionModel,
    WorkflowNodeInstanceModel,
    WorkflowPhaseModel,
    WorkflowPhaseReviewModel,
)
from modules.workflow.repository import (
    WorkflowDefinitionRepository,
    WorkflowDefinitionVersionRepository,
    WorkflowInstanceRepository,
    WorkflowNodeDefinitionRepository,
    WorkflowNodeInstanceRepository,
    WorkflowPhaseRepository,
    WorkflowPhaseReviewRepository,
)

_SCHEMA_VERSION = "1.0"
_TERMINAL_NODE_STATUSES = frozenset({NODE_SUCCEEDED, NODE_SKIPPED})


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


@dataclass(frozen=True)
class DefinitionView:
    definition_id: str
    name: str
    description: str | None
    category: str
    status: str
    version: int
    nodes: list[dict[str, Any]]
    phases: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class InstanceView:
    instance_id: str
    project_id: str
    task_id: str
    definition_id: str
    definition_version: int
    status: str
    current_node_id: str | None
    current_phase_id: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class NodeView:
    node_instance_id: str
    workflow_instance_id: str
    node_key: str
    node_type: str
    phase_key: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    input_ref: str | None
    output_ref: str | None
    error_ref: str | None


@dataclass(frozen=True)
class PhaseView:
    phase_id: str
    workflow_instance_id: str
    phase_key: str
    name: str
    sequence: int
    status: str
    review_required: bool
    accepted_at: datetime | None
    accepted_by: str | None


@dataclass(frozen=True)
class ReviewView:
    review_id: str
    project_id: str
    workflow_instance_id: str
    phase_id: str
    summary: str | None
    deliverables: list[str]
    evidence_refs: list[str]
    verification_summary: str | None
    status: str
    submitted_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by: str | None


def parse_definition(document: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化 Workflow 定义（纯函数，便于单测）。"""

    if not isinstance(document, dict):
        raise ValidationFailed("workflow 定义必须是对象")
    raw_nodes = document.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValidationFailed("workflow 定义必须包含非空 nodes 列表")
    raw_phases = document.get("phases", []) or []
    if not isinstance(raw_phases, list):
        raise ValidationFailed("phases 必须是列表")

    phases: list[dict[str, Any]] = []
    phase_keys: set[str] = set()
    for index, phase in enumerate(raw_phases):
        if not isinstance(phase, dict):
            raise ValidationFailed("phase 必须是对象")
        key = str(phase.get("phase_key") or "").strip()
        if not key:
            raise ValidationFailed("phase_key 不能为空")
        if key in phase_keys:
            raise ValidationFailed("phase_key 重复", details={"phase_key": key})
        phase_keys.add(key)
        phases.append(
            {
                "phase_key": key,
                "name": str(phase.get("name") or key),
                "description": phase.get("description"),
                "sequence": int(phase.get("sequence", index + 1)),
                "entry_criteria": phase.get("entry_criteria"),
                "exit_criteria": phase.get("exit_criteria"),
                "review_required": bool(phase.get("review_required", True)),
            }
        )

    nodes: list[dict[str, Any]] = []
    node_keys: set[str] = set()
    for node in raw_nodes:
        if not isinstance(node, dict):
            raise ValidationFailed("node 必须是对象")
        key = str(node.get("node_key") or "").strip()
        if not key:
            raise ValidationFailed("node_key 不能为空")
        if key in node_keys:
            raise ValidationFailed("node_key 重复", details={"node_key": key})
        node_type = str(node.get("node_type") or NODE_TYPE_AI_EXECUTION)
        if node_type not in NODE_TYPES:
            raise ValidationFailed("node_type 非法", details={"node_type": node_type})
        node_keys.add(key)
        nodes.append(
            {
                "node_key": key,
                "node_type": node_type,
                "config": node.get("config") or {},
                "next_node_rules": [str(item) for item in node.get("next_node_rules", [])],
                "dependency_keys": [str(item) for item in node.get("dependency_keys", [])],
                "phase_key": node.get("phase_key"),
            }
        )

    for node in nodes:
        for referenced in node["next_node_rules"] + node["dependency_keys"]:
            if referenced not in node_keys:
                raise ValidationFailed(
                    "node 引用了不存在的节点",
                    details={"node_key": node["node_key"], "referenced": referenced},
                )
        if node["phase_key"] is not None and node["phase_key"] not in phase_keys:
            raise ValidationFailed(
                "node 引用了不存在的 phase",
                details={"node_key": node["node_key"], "phase_key": node["phase_key"]},
            )

    return {"nodes": nodes, "phases": phases, "schema_version": _SCHEMA_VERSION}


def _definition_view(
    entity: WorkflowDefinitionModel, version: WorkflowDefinitionVersionModel
) -> DefinitionView:
    document = json.loads(version.definition_json)
    return DefinitionView(
        definition_id=entity.definition_id,
        name=entity.name,
        description=entity.description,
        category=entity.category,
        status=entity.status,
        version=version.version,
        nodes=document.get("nodes", []),
        phases=document.get("phases", []),
        created_at=ensure_utc(entity.created_at),
        updated_at=ensure_utc(entity.updated_at),
    )


def _instance_view(entity: WorkflowInstanceModel) -> InstanceView:
    return InstanceView(
        instance_id=entity.instance_id,
        project_id=entity.project_id,
        task_id=entity.task_id,
        definition_id=entity.definition_id,
        definition_version=entity.definition_version,
        status=entity.status,
        current_node_id=entity.current_node_id,
        current_phase_id=entity.current_phase_id,
        started_at=ensure_utc(entity.started_at) if entity.started_at else None,
        ended_at=ensure_utc(entity.ended_at) if entity.ended_at else None,
        created_at=ensure_utc(entity.created_at),
    )


def _node_view(entity: WorkflowNodeInstanceModel) -> NodeView:
    return NodeView(
        node_instance_id=entity.node_instance_id,
        workflow_instance_id=entity.workflow_instance_id,
        node_key=entity.node_key,
        node_type=entity.node_type,
        phase_key=entity.phase_key,
        status=entity.status,
        started_at=ensure_utc(entity.started_at) if entity.started_at else None,
        completed_at=ensure_utc(entity.completed_at) if entity.completed_at else None,
        input_ref=entity.input_ref,
        output_ref=entity.output_ref,
        error_ref=entity.error_ref,
    )


def _phase_view(entity: WorkflowPhaseModel) -> PhaseView:
    return PhaseView(
        phase_id=entity.phase_id,
        workflow_instance_id=entity.workflow_instance_id,
        phase_key=entity.phase_key,
        name=entity.name,
        sequence=entity.sequence,
        status=entity.status,
        review_required=bool(entity.review_required),
        accepted_at=ensure_utc(entity.accepted_at) if entity.accepted_at else None,
        accepted_by=entity.accepted_by,
    )


def _review_view(entity: WorkflowPhaseReviewModel) -> ReviewView:
    return ReviewView(
        review_id=entity.review_id,
        project_id=entity.project_id,
        workflow_instance_id=entity.workflow_instance_id,
        phase_id=entity.phase_id,
        summary=entity.summary,
        deliverables=json.loads(entity.deliverables) if entity.deliverables else [],
        evidence_refs=json.loads(entity.evidence_refs) if entity.evidence_refs else [],
        verification_summary=entity.verification_summary,
        status=entity.status,
        submitted_at=ensure_utc(entity.submitted_at) if entity.submitted_at else None,
        reviewed_at=ensure_utc(entity.reviewed_at) if entity.reviewed_at else None,
        reviewed_by=entity.reviewed_by,
    )


class WorkflowDefinitionService:
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
        name: str,
        category: str,
        document: dict[str, Any],
        description: str | None = None,
    ) -> DefinitionView:
        parsed = parse_definition(document)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            definition = WorkflowDefinitionModel(
                definition_id=_new_id("wfd_"),
                name=name.strip()[:256] or "workflow",
                description=description,
                category=category,
                status=DEFINITION_ACTIVE,
                created_at=now,
                updated_at=now,
            )
            await WorkflowDefinitionRepository(session).add(definition)
            version = await self._add_version(session, definition, parsed, 1, now)
            await session.flush()
            return _definition_view(definition, version)

    async def add_version(self, definition_id: str, document: dict[str, Any]) -> DefinitionView:
        parsed = parse_definition(document)
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            definition = await WorkflowDefinitionRepository(session).get(definition_id)
            if definition is None:
                raise NotFoundError("Workflow 定义不存在", details={"definition_id": definition_id})
            version_no = await WorkflowDefinitionVersionRepository(session).next_version(
                definition_id
            )
            version = await self._add_version(session, definition, parsed, version_no, now)
            definition.updated_at = now
            await session.flush()
            return _definition_view(definition, version)

    async def get(self, definition_id: str, *, version: int | None = None) -> DefinitionView:
        async with self._database.session() as session:
            definition = await WorkflowDefinitionRepository(session).get(definition_id)
            if definition is None:
                raise NotFoundError("Workflow 定义不存在", details={"definition_id": definition_id})
            repository = WorkflowDefinitionVersionRepository(session)
            entity = (
                await repository.get_version(definition_id, version)
                if version is not None
                else await repository.latest(definition_id)
            )
        if entity is None:
            raise NotFoundError("Workflow 定义版本不存在", details={"definition_id": definition_id})
        return _definition_view(definition, entity)

    async def list(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await WorkflowDefinitionRepository(session).list_page(limit=limit, offset=offset)
            items = []
            versions = WorkflowDefinitionVersionRepository(session)
            for definition in page.items:
                latest = await versions.latest(definition.definition_id)
                items.append(_definition_view(definition, latest) if latest else None)
        return {
            "items": [format_definition(item) for item in items if item is not None],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def _add_version(
        self,
        session,
        definition: WorkflowDefinitionModel,
        parsed: dict[str, Any],
        version_no: int,
        now: datetime,
    ) -> WorkflowDefinitionVersionModel:
        version = WorkflowDefinitionVersionModel(
            version_id=_new_id("wfv_"),
            definition_id=definition.definition_id,
            version=version_no,
            schema_version=parsed["schema_version"],
            definition_json=json.dumps(
                {"nodes": parsed["nodes"], "phases": parsed["phases"]},
                ensure_ascii=False,
                sort_keys=True,
            ),
            status=DEFINITION_ACTIVE,
            created_at=now,
        )
        await WorkflowDefinitionVersionRepository(session).add(version)
        nodes = WorkflowNodeDefinitionRepository(session)
        for node in parsed["nodes"]:
            await nodes.add(
                WorkflowNodeDefinitionModel(
                    node_definition_id=_new_id("wfn_"),
                    version_id=version.version_id,
                    node_key=node["node_key"],
                    node_type=node["node_type"],
                    config=json.dumps(node["config"], ensure_ascii=False, sort_keys=True),
                    next_node_rules=json.dumps(node["next_node_rules"], ensure_ascii=False),
                    dependency_keys=json.dumps(node["dependency_keys"], ensure_ascii=False),
                    phase_key=node["phase_key"],
                )
            )
        return version


class WorkflowInstanceService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        tasks: TaskService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._tasks = tasks
        self._clock = clock
        self._logger = get_logger("backend.workflow")

    async def create(
        self,
        *,
        project_id: str,
        task_id: str,
        definition_id: str,
        definition_version: int | None = None,
        actor_id: str | None = None,
    ) -> InstanceView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            task = await TaskRepository(session).get(task_id)
            if task is None or task.project_id != project_id:
                raise NotFoundError("任务不存在或不属于该项目", details={"task_id": task_id})
            definition = await WorkflowDefinitionRepository(session).get(definition_id)
            if definition is None:
                raise NotFoundError("Workflow 定义不存在", details={"definition_id": definition_id})
            versions = WorkflowDefinitionVersionRepository(session)
            version = (
                await versions.get_version(definition_id, definition_version)
                if definition_version is not None
                else await versions.latest(definition_id)
            )
            if version is None:
                raise NotFoundError("Workflow 定义版本不存在")
            document = json.loads(version.definition_json)
            instance = WorkflowInstanceModel(
                instance_id=_new_id("wfi_"),
                project_id=project_id,
                task_id=task_id,
                definition_id=definition_id,
                definition_version=version.version,
                status=INSTANCE_READY,
                current_node_id=None,
                current_phase_id=None,
                started_at=None,
                ended_at=None,
                created_at=now,
            )
            await WorkflowInstanceRepository(session).add(instance)
            phases = document.get("phases", [])
            phase_entities: dict[str, WorkflowPhaseModel] = {}
            for index, phase in enumerate(phases):
                entity = WorkflowPhaseModel(
                    phase_id=_new_id("wfp_"),
                    workflow_instance_id=instance.instance_id,
                    phase_key=phase["phase_key"],
                    name=phase.get("name") or phase["phase_key"],
                    description=phase.get("description"),
                    sequence=int(phase.get("sequence", index + 1)),
                    status=PHASE_PENDING,
                    entry_criteria=phase.get("entry_criteria"),
                    exit_criteria=phase.get("exit_criteria"),
                    review_required=bool(phase.get("review_required", True)),
                    accepted_at=None,
                    accepted_by=None,
                )
                await WorkflowPhaseRepository(session).add(entity)
                phase_entities[entity.phase_key] = entity
            if phase_entities:
                first = min(phase_entities.values(), key=lambda item: item.sequence)
                first.status = PHASE_READY
                instance.current_phase_id = first.phase_id

            nodes = WorkflowNodeInstanceRepository(session)
            for node in document.get("nodes", []):
                await nodes.add(
                    WorkflowNodeInstanceModel(
                        node_instance_id=_new_id("wni_"),
                        workflow_instance_id=instance.instance_id,
                        node_key=node["node_key"],
                        node_type=node["node_type"],
                        phase_key=node.get("phase_key"),
                        status=NODE_PENDING,
                        started_at=None,
                        completed_at=None,
                        input_ref=None,
                        output_ref=None,
                        error_ref=None,
                    )
                )
            task.workflow_instance_id = instance.instance_id
            task.updated_at = now
            await session.flush()
            view = _instance_view(instance)
        log_event(self._logger, logging.INFO, "workflow_instance_created", component="workflow")
        return view

    async def get(self, instance_id: str) -> InstanceView:
        async with self._database.session() as session:
            entity = await WorkflowInstanceRepository(session).get(instance_id)
        if entity is None:
            raise NotFoundError("Workflow 实例不存在", details={"instance_id": instance_id})
        return _instance_view(entity)

    async def get_entity(self, instance_id: str) -> WorkflowInstanceModel:
        async with self._database.session() as session:
            entity = await WorkflowInstanceRepository(session).get(instance_id)
        if entity is None:
            raise NotFoundError("Workflow 实例不存在", details={"instance_id": instance_id})
        return entity

    async def list_by_task(self, task_id: str) -> list[InstanceView]:
        async with self._database.session() as session:
            rows = await WorkflowInstanceRepository(session).list_by_task(task_id)
        return [_instance_view(row) for row in rows]

    async def transition(
        self, instance_id: str, target: str, *, reason: str | None = None
    ) -> InstanceView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await WorkflowInstanceRepository(session).get(instance_id)
            if entity is None:
                raise NotFoundError("Workflow 实例不存在", details={"instance_id": instance_id})
            self._apply_transition(entity, target, now)
            if target == INSTANCE_RUNNING and entity.started_at is None:
                entity.started_at = now
            if target in (INSTANCE_COMPLETED, INSTANCE_FAILED) and entity.ended_at is None:
                entity.ended_at = now
            await session.flush()
            return _instance_view(entity)

    async def pause(self, instance_id: str) -> InstanceView:
        view = await self.transition(instance_id, INSTANCE_PAUSING)
        return await self.transition(view.instance_id, INSTANCE_PAUSED)

    async def resume(self, instance_id: str) -> InstanceView:
        view = await self.transition(instance_id, INSTANCE_RESUMING)
        return await self.transition(view.instance_id, INSTANCE_RUNNING)

    async def cancel(self, instance_id: str) -> InstanceView:
        return await self.transition(instance_id, "CANCELLED")

    def _apply_transition(self, entity: WorkflowInstanceModel, target: str, now: datetime) -> None:
        if entity.status == target:
            return
        if target not in INSTANCE_TRANSITIONS.get(entity.status, frozenset()):
            raise InvalidStateTransition(
                f"非法 Workflow 状态迁移: {entity.status} → {target}",
                details={"instance_id": entity.instance_id},
            )
        entity.status = target


class WorkflowNodeService:
    """Node 执行与推进；所有 Node/Phase 状态变更在同一事务内完成。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        tasks: TaskService | None = None,
        instances: WorkflowInstanceService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._tasks = tasks
        self._instances = instances
        self._clock = clock
        self._logger = get_logger("backend.workflow")

    async def list_nodes(self, instance_id: str) -> list[NodeView]:
        async with self._database.session() as session:
            rows = await WorkflowNodeInstanceRepository(session).list_by_instance(instance_id)
        return [_node_view(row) for row in rows]

    async def advance(self, instance_id: str) -> list[NodeView]:
        """把依赖满足的 PENDING 节点标记 READY。"""

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            instance = await WorkflowInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError("Workflow 实例不存在")
            nodes = await WorkflowNodeInstanceRepository(session).list_by_instance(instance_id)
            await self._mark_ready(session, instance, nodes, now)
            await session.flush()
            return [_node_view(node) for node in nodes]

    async def start_node(self, instance_id: str, node_key: str) -> NodeView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            instance = await WorkflowInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError("Workflow 实例不存在")
            if instance.status == INSTANCE_READY:
                instance.status = INSTANCE_RUNNING
                instance.started_at = now
            if instance.status != INSTANCE_RUNNING:
                raise InvalidStateTransition(
                    "Workflow 未在运行中，不能启动节点",
                    details={"instance_id": instance_id, "status": instance.status},
                )
            repository = WorkflowNodeInstanceRepository(session)
            node = await repository.get_by_key(instance_id, node_key)
            if node is None:
                raise NotFoundError("Workflow 节点不存在", details={"node_key": node_key})
            self._apply_node_transition(node, NODE_READY, now)
            self._apply_node_transition(node, NODE_RUNNING, now)
            node.started_at = now
            instance.current_node_id = node.node_instance_id
            await self._on_node_started(session, instance, node, now)
            await session.flush()
            return _node_view(node)

    async def complete_node(
        self,
        instance_id: str,
        node_key: str,
        *,
        output_ref: str | None = None,
    ) -> NodeView:
        now = self._clock()
        completed = False
        async with self._database.session() as session, transaction(session):
            instance = await WorkflowInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError("Workflow 实例不存在")
            repository = WorkflowNodeInstanceRepository(session)
            node = await repository.get_by_key(instance_id, node_key)
            if node is None:
                raise NotFoundError("Workflow 节点不存在", details={"node_key": node_key})
            self._apply_node_transition(node, NODE_SUCCEEDED, now)
            node.completed_at = now
            node.output_ref = output_ref
            completed = await self._on_node_completed(session, instance, node, now)
            await session.flush()
            view = _node_view(node)
        if completed:
            await self._notify_task_review(instance_id)
        return view

    async def fail_node(
        self, instance_id: str, node_key: str, *, error_ref: str | None = None
    ) -> NodeView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            instance = await WorkflowInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError("Workflow 实例不存在")
            node = await WorkflowNodeInstanceRepository(session).get_by_key(instance_id, node_key)
            if node is None:
                raise NotFoundError("Workflow 节点不存在", details={"node_key": node_key})
            self._apply_node_transition(node, NODE_FAILED, now)
            node.completed_at = now
            node.error_ref = error_ref
            if instance.status in (INSTANCE_RUNNING, INSTANCE_READY):
                instance.status = INSTANCE_FAILED
                instance.ended_at = now
            await session.flush()
            return _node_view(node)

    async def skip_node(self, instance_id: str, node_key: str) -> NodeView:
        now = self._clock()
        completed = False
        async with self._database.session() as session, transaction(session):
            instance = await WorkflowInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError("Workflow 实例不存在")
            node = await WorkflowNodeInstanceRepository(session).get_by_key(instance_id, node_key)
            if node is None:
                raise NotFoundError("Workflow 节点不存在", details={"node_key": node_key})
            self._apply_node_transition(node, NODE_SKIPPED, now)
            node.completed_at = now
            completed = await self._on_node_completed(session, instance, node, now)
            await session.flush()
            view = _node_view(node)
        if completed:
            await self._notify_task_review(instance_id)
        return view

    async def _notify_task_review(self, instance_id: str) -> None:
        """事务提交后再调用 Task System，避免跨会话嵌套写事务。"""

        if self._tasks is None:
            return
        instance = await self._instances.get(instance_id) if self._instances else None
        if instance is None:
            async with self._database.session() as session:
                entity = await WorkflowInstanceRepository(session).get(instance_id)
            task_id = entity.task_id if entity is not None else None
        else:
            task_id = instance.task_id
        if task_id is None:
            return
        task = await self._tasks.get(task_id)
        if task.status == TASK_RUNNING:
            await self._tasks.request_review(task_id)

    async def _mark_ready(
        self,
        session,
        instance: WorkflowInstanceModel,
        nodes: list[WorkflowNodeInstanceModel],
        now: datetime,
    ) -> None:
        by_key = {node.node_key: node for node in nodes}
        definitions = await self._definition_nodes(session, instance)
        for node in nodes:
            if node.status != NODE_PENDING:
                continue
            definition = definitions.get(node.node_key)
            if definition is None:
                continue
            dependency_keys = json.loads(definition.dependency_keys or "[]")
            satisfied = all(
                by_key.get(key) is not None and by_key[key].status in _TERMINAL_NODE_STATUSES
                for key in dependency_keys
            )
            if satisfied:
                node.status = NODE_READY

    async def _definition_nodes(
        self, session, instance: WorkflowInstanceModel
    ) -> dict[str, WorkflowNodeDefinitionModel]:
        version = await WorkflowDefinitionVersionRepository(session).get_version(
            instance.definition_id, instance.definition_version
        )
        if version is None:
            return {}
        rows = await WorkflowNodeDefinitionRepository(session).list_by_version(version.version_id)
        return {row.node_key: row for row in rows}

    async def _on_node_started(
        self,
        session,
        instance: WorkflowInstanceModel,
        node: WorkflowNodeInstanceModel,
        now: datetime,
    ) -> None:
        if node.phase_key is None:
            return
        phase = await WorkflowPhaseRepository(session).get_by_key(
            instance.instance_id, node.phase_key
        )
        if phase is None:
            return
        if phase.status in (PHASE_PENDING, PHASE_READY):
            phase.status = PHASE_IN_PROGRESS
        instance.current_phase_id = phase.phase_id

    async def _on_node_completed(
        self,
        session,
        instance: WorkflowInstanceModel,
        node: WorkflowNodeInstanceModel,
        now: datetime,
    ) -> bool:
        nodes = await WorkflowNodeInstanceRepository(session).list_by_instance(instance.instance_id)
        if node.phase_key is not None:
            phase = await WorkflowPhaseRepository(session).get_by_key(
                instance.instance_id, node.phase_key
            )
            if phase is not None:
                phase_nodes = [item for item in nodes if item.phase_key == phase.phase_key]
                if phase_nodes and all(
                    item.status in _TERMINAL_NODE_STATUSES for item in phase_nodes
                ):
                    if phase.review_required:
                        phase.status = PHASE_REVIEW_PENDING
                        await self._ensure_review(session, instance, phase, now)
                    else:
                        phase.status = PHASE_ACCEPTED
                        phase.accepted_at = now
                        await self._activate_next_phase(session, instance, phase)
        if all(item.status in _TERMINAL_NODE_STATUSES for item in nodes):
            return await self._complete_instance(session, instance, now)
        return False

    async def _ensure_review(
        self,
        session,
        instance: WorkflowInstanceModel,
        phase: WorkflowPhaseModel,
        now: datetime,
    ) -> None:
        repository = WorkflowPhaseReviewRepository(session)
        if await repository.get_by_phase(phase.phase_id) is None:
            await repository.add(
                WorkflowPhaseReviewModel(
                    review_id=_new_id("wpr_"),
                    project_id=instance.project_id,
                    workflow_instance_id=instance.instance_id,
                    phase_id=phase.phase_id,
                    summary=None,
                    deliverables=None,
                    evidence_refs=None,
                    verification_summary=None,
                    status=REVIEW_DRAFT,
                    submitted_at=None,
                    reviewed_at=None,
                    reviewed_by=None,
                )
            )

    async def _activate_next_phase(
        self, session, instance: WorkflowInstanceModel, current: WorkflowPhaseModel
    ) -> None:
        phases = await WorkflowPhaseRepository(session).list_by_instance(instance.instance_id)
        following = [
            phase
            for phase in phases
            if phase.sequence > current.sequence and phase.status == PHASE_PENDING
        ]
        if following:
            next_phase = min(following, key=lambda item: item.sequence)
            next_phase.status = PHASE_READY
            instance.current_phase_id = next_phase.phase_id

    async def _complete_instance(
        self, session, instance: WorkflowInstanceModel, now: datetime
    ) -> bool:
        if instance.status == INSTANCE_COMPLETED:
            return False
        instance.status = INSTANCE_COMPLETED
        instance.ended_at = now
        log_event(self._logger, logging.INFO, "workflow_completed", component="workflow")
        return True

    def _apply_node_transition(
        self, node: WorkflowNodeInstanceModel, target: str, now: datetime
    ) -> None:
        allowed: dict[str, frozenset[str]] = {
            NODE_PENDING: frozenset({NODE_READY, NODE_CANCELLED, NODE_SKIPPED}),
            NODE_READY: frozenset({NODE_RUNNING, NODE_CANCELLED, NODE_SKIPPED}),
            NODE_RUNNING: frozenset({NODE_SUCCEEDED, NODE_FAILED, NODE_CANCELLED, NODE_SKIPPED}),
            NODE_SUCCEEDED: frozenset(),
            NODE_FAILED: frozenset({NODE_READY, NODE_CANCELLED}),
            NODE_SKIPPED: frozenset(),
            NODE_CANCELLED: frozenset(),
        }
        if node.status == target:
            return
        if target not in allowed.get(node.status, frozenset()):
            raise InvalidStateTransition(
                f"非法节点状态迁移: {node.status} → {target}",
                details={"node_key": node.node_key},
            )
        node.status = target


class WorkflowScheduler:
    """最小调度器：推进 READY 节点并启动一个节点。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        nodes: WorkflowNodeService,
        instances: WorkflowInstanceService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._nodes = nodes
        self._instances = instances
        self._clock = clock

    async def tick(self, instance_id: str) -> dict[str, Any]:
        instance = await self._instances.get(instance_id)
        if instance.status in (INSTANCE_COMPLETED, "CANCELLED", INSTANCE_FAILED):
            return {"instance": format_instance(instance), "started": None}
        if instance.status == INSTANCE_READY:
            await self._instances.transition(instance_id, INSTANCE_RUNNING)
        await self._nodes.advance(instance_id)
        nodes = await self._nodes.list_nodes(instance_id)
        ready = sorted(
            (node for node in nodes if node.status == NODE_READY), key=lambda item: item.node_key
        )
        started = None
        if ready and not any(node.status == NODE_RUNNING for node in nodes):
            started = await self._nodes.start_node(instance_id, ready[0].node_key)
        return {
            "instance": format_instance(await self._instances.get(instance_id)),
            "started": format_node(started) if started else None,
        }


class WorkflowPhaseService:
    """Phase 与用户验收（E4-T15 / T21）。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        nodes: WorkflowNodeService,
        instances: WorkflowInstanceService,
        tasks: TaskService | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._nodes = nodes
        self._instances = instances
        self._tasks = tasks
        self._clock = clock
        self._logger = get_logger("backend.workflow")

    async def list_phases(self, instance_id: str) -> list[PhaseView]:
        async with self._database.session() as session:
            rows = await WorkflowPhaseRepository(session).list_by_instance(instance_id)
        return [_phase_view(row) for row in rows]

    async def submit_review(
        self,
        instance_id: str,
        phase_key: str,
        *,
        summary: str | None = None,
        deliverables: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        verification_summary: str | None = None,
    ) -> ReviewView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            instance = await WorkflowInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError("Workflow 实例不存在")
            phase = await WorkflowPhaseRepository(session).get_by_key(instance_id, phase_key)
            if phase is None:
                raise NotFoundError("Workflow 阶段不存在", details={"phase_key": phase_key})
            if phase.status not in (PHASE_READY, PHASE_IN_PROGRESS, PHASE_REVIEW_PENDING):
                raise InvalidStateTransition(
                    "阶段当前状态不能提交验收",
                    details={"phase_key": phase_key, "status": phase.status},
                )
            repository = WorkflowPhaseReviewRepository(session)
            review = await repository.get_by_phase(phase.phase_id)
            if review is None:
                review = WorkflowPhaseReviewModel(
                    review_id=_new_id("wpr_"),
                    project_id=instance.project_id,
                    workflow_instance_id=instance.instance_id,
                    phase_id=phase.phase_id,
                    summary=summary,
                    deliverables=json.dumps(deliverables or [], ensure_ascii=False),
                    evidence_refs=json.dumps(evidence_refs or [], ensure_ascii=False),
                    verification_summary=verification_summary,
                    status=REVIEW_SUBMITTED,
                    submitted_at=now,
                    reviewed_at=None,
                    reviewed_by=None,
                )
                await repository.add(review)
            else:
                review.summary = summary or review.summary
                if deliverables is not None:
                    review.deliverables = json.dumps(deliverables, ensure_ascii=False)
                if evidence_refs is not None:
                    review.evidence_refs = json.dumps(evidence_refs, ensure_ascii=False)
                review.verification_summary = verification_summary or review.verification_summary
                review.status = REVIEW_SUBMITTED
                review.submitted_at = now
            phase.status = PHASE_REVIEW_PENDING
            await session.flush()
            return _review_view(review)

    async def accept_phase(
        self,
        instance_id: str,
        phase_key: str,
        *,
        actor_id: str | None = None,
    ) -> PhaseView:
        now = self._clock()
        completed = False
        task_id: str | None = None
        async with self._database.session() as session, transaction(session):
            instance = await WorkflowInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError("Workflow 实例不存在")
            task_id = instance.task_id
            phase = await WorkflowPhaseRepository(session).get_by_key(instance_id, phase_key)
            if phase is None:
                raise NotFoundError("Workflow 阶段不存在", details={"phase_key": phase_key})
            if phase.status != PHASE_REVIEW_PENDING:
                raise InvalidStateTransition(
                    "只有 REVIEW_PENDING 阶段可以验收",
                    details={"phase_key": phase_key, "status": phase.status},
                )
            repository = WorkflowPhaseReviewRepository(session)
            review = await repository.get_by_phase(phase.phase_id)
            if review is None:
                review = WorkflowPhaseReviewModel(
                    review_id=_new_id("wpr_"),
                    project_id=instance.project_id,
                    workflow_instance_id=instance.instance_id,
                    phase_id=phase.phase_id,
                    summary=None,
                    deliverables=None,
                    evidence_refs=None,
                    verification_summary=None,
                    status=REVIEW_ACCEPTED,
                    submitted_at=now,
                    reviewed_at=now,
                    reviewed_by=actor_id,
                )
                await repository.add(review)
            else:
                review.status = REVIEW_ACCEPTED
                review.reviewed_at = now
                review.reviewed_by = actor_id
            phase.status = PHASE_ACCEPTED
            phase.accepted_at = now
            phase.accepted_by = actor_id
            await self._nodes._activate_next_phase(session, instance, phase)
            phases = await WorkflowPhaseRepository(session).list_by_instance(instance_id)
            if all(item.status == PHASE_ACCEPTED for item in phases):
                completed = await self._nodes._complete_instance(session, instance, now)
            await session.flush()
            view = _phase_view(phase)
        if completed and self._tasks is not None and task_id is not None:
            task = await self._tasks.get(task_id)
            if task.status == TASK_RUNNING:
                await self._tasks.request_review(task_id)
        return view

    async def request_revision(
        self,
        instance_id: str,
        phase_key: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> PhaseView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            instance = await WorkflowInstanceRepository(session).get(instance_id)
            if instance is None:
                raise NotFoundError("Workflow 实例不存在")
            phase = await WorkflowPhaseRepository(session).get_by_key(instance_id, phase_key)
            if phase is None:
                raise NotFoundError("Workflow 阶段不存在", details={"phase_key": phase_key})
            if phase.status != PHASE_REVIEW_PENDING:
                raise InvalidStateTransition("只有 REVIEW_PENDING 阶段可以退回修改")
            review = await WorkflowPhaseReviewRepository(session).get_by_phase(phase.phase_id)
            if review is not None:
                review.status = REVIEW_NEEDS_REVISION
                review.reviewed_at = now
                review.reviewed_by = actor_id
                review.summary = reason or review.summary
            phase.status = PHASE_NEEDS_REVISION
            await session.flush()
            return _phase_view(phase)

    async def get_review(self, instance_id: str, phase_key: str) -> ReviewView | None:
        async with self._database.session() as session:
            phase = await WorkflowPhaseRepository(session).get_by_key(instance_id, phase_key)
            if phase is None:
                raise NotFoundError("Workflow 阶段不存在", details={"phase_key": phase_key})
            review = await WorkflowPhaseReviewRepository(session).get_by_phase(phase.phase_id)
        return _review_view(review) if review is not None else None


class WorkflowRecoveryService:
    """重启恢复：未完成 Attempt 一律标记 UNKNOWN，Task/Workflow 进入可恢复状态。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        tasks: TaskService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._tasks = tasks
        self._clock = clock
        self._logger = get_logger("backend.workflow")

    async def recover(self) -> dict[str, int]:
        now = self._clock()
        recovered_attempts = 0
        recovered_workflows = 0
        task_targets: list[tuple[str, str]] = []
        async with self._database.session() as session, transaction(session):
            attempts = TaskAttemptRepository(session)
            tasks = TaskRepository(session)
            for task in await tasks.list_unfinished():
                latest = await attempts.latest(task.task_id)
                if latest is not None and latest.status in ("RUNNING", "STARTING"):
                    latest.status = "UNKNOWN"
                    latest.ended_at = now
                    recovered_attempts += 1
                allowed = TASK_TRANSITIONS_FOR_RECOVERY.get(task.status, frozenset())
                if "BLOCKED" in allowed:
                    task_targets.append((task.task_id, "BLOCKED"))
                elif "PAUSED" in allowed:
                    task_targets.append((task.task_id, "PAUSED"))
            rows = await session.scalars(
                select(WorkflowInstanceModel).where(
                    WorkflowInstanceModel.status.in_(("RUNNING", "PAUSING", "RESUMING"))
                )
            )
            for instance in rows.all():
                if INSTANCE_BLOCKED in INSTANCE_TRANSITIONS.get(instance.status, frozenset()):
                    instance.status = INSTANCE_BLOCKED
                    recovered_workflows += 1
            await session.flush()
        for task_id, target in task_targets:
            if target == "BLOCKED":
                await self._tasks.mark_blocked(task_id, reason="recovery_required")
            else:
                await self._tasks.transition(
                    task_id,
                    target,
                    actor_type="SYSTEM",
                    reason="recovery_paused",
                )
        report = {
            "recovered_attempts": recovered_attempts,
            "recovered_tasks": len(task_targets),
            "recovered_workflows": recovered_workflows,
        }
        log_event(
            self._logger, logging.WARNING, "workflow_recovery_completed", component="workflow"
        )
        return report


TASK_TRANSITIONS_FOR_RECOVERY: dict[str, frozenset[str]] = {
    "RUNNING": frozenset({"BLOCKED"}),
    "PAUSING": frozenset({"PAUSED"}),
    "RESUMING": frozenset({"FAILED"}),
    "WAITING_APPROVAL": frozenset({"BLOCKED"}),
    "WAITING_USER": frozenset({"RUNNING"}),
    "QUEUED": frozenset({"BLOCKED"}),
    "PAUSED": frozenset(),
    "BLOCKED": frozenset(),
    "REVIEW_PENDING": frozenset(),
}


def format_definition(view: DefinitionView) -> dict[str, Any]:
    return {
        "definition_id": view.definition_id,
        "name": view.name,
        "description": view.description,
        "category": view.category,
        "status": view.status,
        "version": view.version,
        "nodes": view.nodes,
        "phases": view.phases,
        "created_at": isoformat(view.created_at),
        "updated_at": isoformat(view.updated_at),
    }


def format_instance(view: InstanceView) -> dict[str, Any]:
    return {
        "instance_id": view.instance_id,
        "project_id": view.project_id,
        "task_id": view.task_id,
        "definition_id": view.definition_id,
        "definition_version": view.definition_version,
        "status": view.status,
        "current_node_id": view.current_node_id,
        "current_phase_id": view.current_phase_id,
        "started_at": isoformat(view.started_at) if view.started_at else None,
        "ended_at": isoformat(view.ended_at) if view.ended_at else None,
        "created_at": isoformat(view.created_at),
    }


def format_node(view: NodeView) -> dict[str, Any]:
    return {
        "node_instance_id": view.node_instance_id,
        "workflow_instance_id": view.workflow_instance_id,
        "node_key": view.node_key,
        "node_type": view.node_type,
        "phase_key": view.phase_key,
        "status": view.status,
        "started_at": isoformat(view.started_at) if view.started_at else None,
        "completed_at": isoformat(view.completed_at) if view.completed_at else None,
        "input_ref": view.input_ref,
        "output_ref": view.output_ref,
        "error_ref": view.error_ref,
    }


def format_phase(view: PhaseView) -> dict[str, Any]:
    return {
        "phase_id": view.phase_id,
        "workflow_instance_id": view.workflow_instance_id,
        "phase_key": view.phase_key,
        "name": view.name,
        "sequence": view.sequence,
        "status": view.status,
        "review_required": view.review_required,
        "accepted_at": isoformat(view.accepted_at) if view.accepted_at else None,
        "accepted_by": view.accepted_by,
    }


def format_review(view: ReviewView) -> dict[str, Any]:
    return {
        "review_id": view.review_id,
        "project_id": view.project_id,
        "workflow_instance_id": view.workflow_instance_id,
        "phase_id": view.phase_id,
        "summary": view.summary,
        "deliverables": view.deliverables,
        "evidence_refs": view.evidence_refs,
        "verification_summary": view.verification_summary,
        "status": view.status,
        "submitted_at": isoformat(view.submitted_at) if view.submitted_at else None,
        "reviewed_at": isoformat(view.reviewed_at) if view.reviewed_at else None,
        "reviewed_by": view.reviewed_by,
    }
