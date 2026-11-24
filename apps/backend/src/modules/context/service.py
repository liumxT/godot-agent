"""Context Assembly 基础服务（E5-T16）。

- 统一入口：Agent 通过 ``assemble`` 获取分层上下文，不直接拼装事实；
- 来源可追踪：每层记录来源引用，固定 Context 引用缺失时显式失败；
- 不静默裁剪：超出 token 预算只报告 ``budget_exceeded``，不丢弃固定层；
- 事实与推断分离：每层标注 ``FACT`` / ``INFERENCE``；
- 无 tokenizer：``token_estimate`` 按字符数 / 4 估算，仅用于预算比较。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core.errors import ContextSourceMissing, NotFoundError, ValidationFailed
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.context.models import (
    CONTEXT_LAYER_ORDER,
    CONTEXT_LAYERS,
    CONTEXT_ORIGINS,
    CONTEXT_PROFILE_DEFAULT,
    CONTEXT_PROFILES,
    LAYER_POLICY,
    LAYER_PROJECT,
    LAYER_TASK,
    LAYER_WORKFLOW,
    ORIGIN_FACT,
    ContextAssemblyModel,
)
from modules.context.repository import ContextAssemblyRepository
from modules.project_registry.service import (
    ProjectConfigurationService,
    ProjectRegistryService,
)
from modules.task.service import AttemptService, TaskService
from modules.workflow.service import WorkflowInstanceService

__all__ = [
    "ContextAssemblyRequest",
    "ContextAssemblyResult",
    "ContextAssemblyService",
    "ContextLayer",
    "estimate_tokens",
]

TOKEN_ESTIMATE_METHOD = "CHARS_DIV_4"
_BUDGET_EXCEEDED_WARNING = "CONTEXT_BUDGET_EXCEEDED"


@dataclass(frozen=True, slots=True)
class ContextLayer:
    layer: str
    content: Mapping[str, Any]
    source_refs: tuple[str, ...] = ()
    origin: str = ORIGIN_FACT


@dataclass(frozen=True, slots=True)
class ContextAssemblyRequest:
    project_id: str
    task_id: str | None = None
    attempt_id: str | None = None
    agent_definition_id: str | None = None
    context_profile: str = CONTEXT_PROFILE_DEFAULT
    required_sources: tuple[str, ...] = ()
    token_budget: int | None = None
    fixed_context_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextAssemblyResult:
    context_id: str
    context_version: int
    project_id: str
    context_profile: str
    layers: tuple[ContextLayer, ...]
    source_refs: tuple[str, ...]
    fixed_context_refs: tuple[str, ...]
    token_estimate: int
    token_estimate_method: str
    token_budget: int | None
    budget_exceeded: bool
    warnings: tuple[str, ...]


def estimate_tokens(payload: Any) -> int:
    """按 JSON 字符数 / 4 估算 token，避免引入额外 tokenizer 依赖。"""

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return max(1, math.ceil(len(text) / 4))


class ContextAssemblyService:
    """从 E4 项目 / 任务数据装配分层上下文。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        projects: ProjectRegistryService,
        configurations: ProjectConfigurationService,
        tasks: TaskService,
        attempts: AttemptService,
        workflows: WorkflowInstanceService,
        clock: Any = utcnow,
    ) -> None:
        self._database = database
        self._projects = projects
        self._configurations = configurations
        self._tasks = tasks
        self._attempts = attempts
        self._workflows = workflows
        self._clock = clock

    async def assemble(
        self,
        request: ContextAssemblyRequest,
        *,
        layers: tuple[ContextLayer, ...] = (),
    ) -> ContextAssemblyResult:
        self._validate_request(request)
        assembled = list(await self._default_layers(request))
        assembled.extend(self._validate_layers(request, layers))
        assembled.sort(key=lambda item: CONTEXT_LAYER_ORDER.index(item.layer))

        source_refs = tuple(dict.fromkeys(ref for item in assembled for ref in item.source_refs))
        missing_refs = [ref for ref in request.fixed_context_refs if ref not in source_refs]
        if missing_refs:
            raise ContextSourceMissing(
                "固定 Context 引用缺失，不能静默移除",
                details={"missing_refs": missing_refs},
            )

        present = {item.layer for item in assembled}
        missing_sources = [name for name in request.required_sources if name not in present]
        if missing_sources:
            raise ContextSourceMissing(
                "Context 必需来源缺失",
                details={"missing_sources": missing_sources},
            )

        token_estimate = estimate_tokens(_serialize(assembled))
        warnings: list[str] = []
        budget_exceeded = False
        if request.token_budget is not None and token_estimate > request.token_budget:
            budget_exceeded = True
            warnings.append(_BUDGET_EXCEEDED_WARNING)

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = ContextAssemblyRepository(session)
            version = await repository.latest_version(request.project_id) + 1
            entity = ContextAssemblyModel(
                context_id="ctx_" + uuid4().hex[:12],
                project_id=request.project_id,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                agent_definition_id=request.agent_definition_id,
                context_profile=request.context_profile,
                context_version=version,
                token_estimate=token_estimate,
                token_budget=request.token_budget,
                budget_exceeded=budget_exceeded,
                layers_json=json.dumps(_serialize(assembled), ensure_ascii=False),
                source_refs_json=json.dumps(list(source_refs), ensure_ascii=False),
                fixed_refs_json=json.dumps(list(request.fixed_context_refs), ensure_ascii=False),
                created_at=now,
            )
            await repository.add(entity)

        return self._result(
            entity_id=entity.context_id,
            version=version,
            request=request,
            layers=tuple(assembled),
            source_refs=source_refs,
            token_estimate=token_estimate,
            budget_exceeded=budget_exceeded,
            warnings=tuple(warnings),
        )

    async def get(self, context_id: str) -> ContextAssemblyResult:
        async with self._database.session() as session:
            entity = await ContextAssemblyRepository(session).get(context_id)
            if entity is None:
                raise NotFoundError("Context 不存在", details={"context_id": context_id})
            return _from_entity(entity)

    async def list_for_project(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ContextAssemblyResult]:
        async with self._database.session() as session:
            page = await ContextAssemblyRepository(session).list_for_project(
                project_id, limit=limit, offset=offset
            )
            return [_from_entity(item) for item in page.items]

    # ---- 内部 ----

    async def _default_layers(self, request: ContextAssemblyRequest) -> list[ContextLayer]:
        layers = [await self._project_layer(request.project_id)]
        if request.task_id is not None:
            task_layer, workflow_layer = await self._task_layers(request)
            layers.append(task_layer)
            if workflow_layer is not None:
                layers.append(workflow_layer)
        policy_layer = await self._policy_layer(request.project_id)
        if policy_layer is not None:
            layers.append(policy_layer)
        return layers

    async def _project_layer(self, project_id: str) -> ContextLayer:
        project = await self._projects.get(project_id)
        return ContextLayer(
            layer=LAYER_PROJECT,
            content={
                "project_id": project.project_id,
                "name": project.name,
                "description": project.description,
                "project_root": project.project_root,
                "project_type": project.project_type,
                "godot_version": project.godot_version,
                "status": project.status,
                "version": project.version,
            },
            source_refs=(f"project:{project_id}",),
        )

    async def _task_layers(
        self, request: ContextAssemblyRequest
    ) -> tuple[ContextLayer, ContextLayer | None]:
        assert request.task_id is not None
        task = await self._tasks.get(request.task_id)
        if task.project_id != request.project_id:
            raise ValidationFailed(
                "任务不属于指定项目",
                details={"task_id": task.task_id, "project_id": request.project_id},
            )
        content: dict[str, Any] = {
            "task_id": task.task_id,
            "title": task.title,
            "description": task.description,
            "task_type": task.task_type,
            "priority": task.priority,
            "status": task.status,
            "workflow_instance_id": task.workflow_instance_id,
            "current_attempt_id": task.current_attempt_id,
        }
        refs = [f"task:{task.task_id}"]
        workflow_instance_id = task.workflow_instance_id

        if request.attempt_id is not None:
            attempt = await self._attempts.get(request.attempt_id)
            if attempt.task_id != task.task_id:
                raise ValidationFailed(
                    "Attempt 不属于指定任务",
                    details={"attempt_id": attempt.attempt_id, "task_id": task.task_id},
                )
            content["attempt"] = {
                "attempt_id": attempt.attempt_id,
                "attempt_number": attempt.attempt_number,
                "status": attempt.status,
                "agent_instance_id": attempt.agent_instance_id,
                "execution_summary": attempt.execution_summary,
                "failure_code": attempt.failure_code,
                "failure_reason": attempt.failure_reason,
            }
            refs.append(f"attempt:{attempt.attempt_id}")
            workflow_instance_id = workflow_instance_id or attempt.workflow_instance_id

        workflow_layer = None
        if workflow_instance_id is not None:
            instance = await self._workflows.get(workflow_instance_id)
            workflow_layer = ContextLayer(
                layer=LAYER_WORKFLOW,
                content={
                    "instance_id": instance.instance_id,
                    "definition_id": instance.definition_id,
                    "definition_version": instance.definition_version,
                    "status": instance.status,
                    "current_node_id": instance.current_node_id,
                    "current_phase_id": instance.current_phase_id,
                },
                source_refs=(f"workflow:{instance.instance_id}",),
            )

        return (
            ContextLayer(layer=LAYER_TASK, content=content, source_refs=tuple(refs)),
            workflow_layer,
        )

    async def _policy_layer(self, project_id: str) -> ContextLayer | None:
        try:
            configuration = await self._configurations.get(project_id)
        except NotFoundError:
            return None
        return ContextLayer(
            layer=LAYER_POLICY,
            content={
                "configuration_version": configuration.version,
                "values": configuration.values,
            },
            source_refs=(f"project-configuration:{project_id}",),
        )

    @staticmethod
    def _validate_request(request: ContextAssemblyRequest) -> None:
        if request.context_profile not in CONTEXT_PROFILES:
            raise ValidationFailed(
                "context_profile 非法",
                details={"context_profile": request.context_profile},
            )
        if request.token_budget is not None and request.token_budget <= 0:
            raise ValidationFailed("token_budget 必须为正整数")
        for name in request.required_sources:
            if name not in CONTEXT_LAYERS:
                raise ValidationFailed("required_sources 含未知层", details={"layer": name})

    @staticmethod
    def _validate_layers(
        request: ContextAssemblyRequest, layers: tuple[ContextLayer, ...]
    ) -> list[ContextLayer]:
        seen: set[str] = set()
        for item in layers:
            if item.layer not in CONTEXT_LAYERS:
                raise ValidationFailed("Context 层名称非法", details={"layer": item.layer})
            if item.origin not in CONTEXT_ORIGINS:
                raise ValidationFailed("Context 层来源标记非法", details={"origin": item.origin})
            if item.layer in seen:
                raise ValidationFailed(
                    "Context 层重复，需在调用方合并", details={"layer": item.layer}
                )
            seen.add(item.layer)

        reserved = {LAYER_PROJECT, LAYER_TASK, LAYER_WORKFLOW, LAYER_POLICY}
        if request.task_id is None:
            reserved.discard(LAYER_TASK)
            reserved.discard(LAYER_WORKFLOW)
        conflicts = sorted(seen & reserved)
        if conflicts:
            raise ValidationFailed(
                "调用方不能覆盖系统装配的 Context 层", details={"layers": conflicts}
            )
        return list(layers)

    @staticmethod
    def _result(
        *,
        entity_id: str,
        version: int,
        request: ContextAssemblyRequest,
        layers: tuple[ContextLayer, ...],
        source_refs: tuple[str, ...],
        token_estimate: int,
        budget_exceeded: bool,
        warnings: tuple[str, ...],
    ) -> ContextAssemblyResult:
        return ContextAssemblyResult(
            context_id=entity_id,
            context_version=version,
            project_id=request.project_id,
            context_profile=request.context_profile,
            layers=layers,
            source_refs=source_refs,
            fixed_context_refs=request.fixed_context_refs,
            token_estimate=token_estimate,
            token_estimate_method=TOKEN_ESTIMATE_METHOD,
            token_budget=request.token_budget,
            budget_exceeded=budget_exceeded,
            warnings=warnings,
        )


def _serialize(layers: list[ContextLayer]) -> list[dict[str, Any]]:
    return [
        {
            "layer": item.layer,
            "origin": item.origin,
            "content": dict(item.content),
            "source_refs": list(item.source_refs),
        }
        for item in layers
    ]


def _from_entity(entity: ContextAssemblyModel) -> ContextAssemblyResult:
    layers = tuple(
        ContextLayer(
            layer=item["layer"],
            content=item["content"],
            source_refs=tuple(item.get("source_refs") or ()),
            origin=item.get("origin", ORIGIN_FACT),
        )
        for item in json.loads(entity.layers_json)
    )
    return ContextAssemblyResult(
        context_id=entity.context_id,
        context_version=entity.context_version,
        project_id=entity.project_id,
        context_profile=entity.context_profile,
        layers=layers,
        source_refs=tuple(json.loads(entity.source_refs_json)),
        fixed_context_refs=tuple(json.loads(entity.fixed_refs_json)),
        token_estimate=entity.token_estimate or 0,
        token_estimate_method=TOKEN_ESTIMATE_METHOD,
        token_budget=entity.token_budget,
        budget_exceeded=entity.budget_exceeded,
        warnings=((_BUDGET_EXCEEDED_WARNING,) if entity.budget_exceeded else ()),
    )
