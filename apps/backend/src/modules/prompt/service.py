"""Prompt 管理服务（E5-T15）。

- 版本化：每个版本独立不可变，激活新版本不影响已绑定的旧版本；
- 变量：内容占位符必须先在 ``variables_schema`` 中声明，渲染按 Schema 校验；
- 安全：渲染结果明确标记未受信变量，调用方不得把未受信内容提升为系统指令；
- 可追踪：Prompt 测试结果按版本记录，可关联具体模型请求。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from core.errors import NotFoundError, PromptVariableInvalid, ValidationFailed
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.prompt.models import (
    PROMPT_CATEGORIES,
    PROMPT_STATUS_ACTIVE,
    PROMPT_STATUS_ARCHIVED,
    PROMPT_STATUS_DRAFT,
    PROMPT_TEST_STATUSES,
    PromptDefinitionModel,
    PromptTestResultModel,
)
from modules.prompt.repository import (
    PromptDefinitionRepository,
    PromptTestResultRepository,
)

__all__ = ["PromptService", "PromptView", "RenderedPrompt", "TestResultView"]

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


@dataclass(frozen=True, slots=True)
class PromptView:
    prompt_id: str
    name: str
    category: str
    description: str | None
    version: int
    content: str
    variables_schema: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    prompt_id: str
    name: str
    version: int
    content: str
    variables_used: tuple[str, ...]
    untrusted_variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TestResultView:
    test_id: str
    prompt_id: str
    model_request_id: str | None
    status: str
    summary: str | None
    metadata: dict[str, Any]
    created_at: datetime


class PromptService:
    """Prompt 版本、渲染与测试记录。"""

    def __init__(self, database: DatabaseService, *, clock: Any = utcnow) -> None:
        self._database = database
        self._clock = clock

    # ---- 定义与版本 ----

    async def create(
        self,
        *,
        name: str,
        category: str,
        content: str,
        variables_schema: Mapping[str, Any] | None = None,
        description: str | None = None,
        status: str = PROMPT_STATUS_DRAFT,
    ) -> PromptView:
        name = name.strip()
        self._validate_definition(name, category, content, status)
        schema = self._validate_schema(variables_schema)
        _validate_placeholders(content, schema)
        now = self._clock()

        async with self._database.session() as session, transaction(session):
            repository = PromptDefinitionRepository(session)
            if await repository.latest_version(name) > 0:
                raise ValidationFailed(
                    "Prompt 名称已存在，请创建新版本",
                    details={"name": name},
                )
            entity = PromptDefinitionModel(
                prompt_id=_new_id("prm_"),
                name=name,
                category=category,
                description=description,
                version=1,
                content=content,
                variables_schema=json.dumps(schema, ensure_ascii=False, sort_keys=True),
                status=status,
                created_at=now,
                updated_at=now,
            )
            await repository.add(entity)
            view = _view(entity)
        return view

    async def create_version(
        self,
        name: str,
        *,
        content: str,
        variables_schema: Mapping[str, Any] | None = None,
        description: str | None = None,
    ) -> PromptView:
        schema = self._validate_schema(variables_schema)
        if not content.strip():
            raise ValidationFailed("Prompt 内容不能为空")
        _validate_placeholders(content, schema)
        now = self._clock()

        async with self._database.session() as session, transaction(session):
            repository = PromptDefinitionRepository(session)
            latest = await repository.latest_version(name)
            if latest == 0:
                raise NotFoundError("Prompt 不存在", details={"name": name})
            previous = await repository.get_by_name_version(name, latest)
            if previous is None:
                raise NotFoundError("Prompt 版本不存在", details={"name": name, "version": latest})
            entity = PromptDefinitionModel(
                prompt_id=_new_id("prm_"),
                name=name,
                category=previous.category,
                description=description if description is not None else previous.description,
                version=latest + 1,
                content=content,
                variables_schema=json.dumps(schema, ensure_ascii=False, sort_keys=True),
                status=PROMPT_STATUS_DRAFT,
                created_at=now,
                updated_at=now,
            )
            await repository.add(entity)
            view = _view(entity)
        return view

    async def activate(self, prompt_id: str) -> PromptView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = PromptDefinitionRepository(session)
            entity = await self._require(repository, prompt_id)
            if entity.status == PROMPT_STATUS_ARCHIVED:
                raise ValidationFailed(
                    "已归档的 Prompt 版本不能重新激活",
                    details={"prompt_id": prompt_id},
                )
            active = await repository.get_active(entity.name)
            if active is not None and active.prompt_id != prompt_id:
                active.status = PROMPT_STATUS_ARCHIVED
                active.updated_at = now
            entity.status = PROMPT_STATUS_ACTIVE
            entity.updated_at = now
            await session.flush()
            view = _view(entity)
        return view

    async def archive(self, prompt_id: str) -> PromptView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = PromptDefinitionRepository(session)
            entity = await self._require(repository, prompt_id)
            entity.status = PROMPT_STATUS_ARCHIVED
            entity.updated_at = now
            await session.flush()
            view = _view(entity)
        return view

    async def get(self, prompt_id: str) -> PromptView:
        async with self._database.session() as session:
            entity = await self._require(PromptDefinitionRepository(session), prompt_id)
            return _view(entity)

    async def get_version(self, name: str, version: int) -> PromptView:
        async with self._database.session() as session:
            entity = await PromptDefinitionRepository(session).get_by_name_version(name, version)
            if entity is None:
                raise NotFoundError(
                    "Prompt 版本不存在", details={"name": name, "version": version}
                )
            return _view(entity)

    async def get_active(self, name: str) -> PromptView:
        async with self._database.session() as session:
            entity = await PromptDefinitionRepository(session).get_active(name)
            if entity is None:
                raise NotFoundError("Prompt 没有激活版本", details={"name": name})
            return _view(entity)

    async def list_versions(
        self, name: str, *, limit: int = 50, offset: int = 0
    ) -> list[PromptView]:
        async with self._database.session() as session:
            page = await PromptDefinitionRepository(session).list_versions(
                name, limit=limit, offset=offset
            )
        return [_view(item) for item in page.items]

    # ---- 渲染 ----

    async def render(
        self,
        prompt_id: str,
        variables: Mapping[str, Any],
        *,
        trusted_variables: tuple[str, ...] = (),
    ) -> RenderedPrompt:
        view = await self.get(prompt_id)
        schema = view.variables_schema
        declared = _declared_variables(schema)

        unknown_trusted = set(trusted_variables) - set(declared)
        if unknown_trusted:
            raise ValidationFailed(
                "trusted_variables 包含未声明的变量",
                details={"variables": sorted(unknown_trusted)},
            )

        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(dict(variables)), key=lambda item: list(item.path))
        if errors:
            raise PromptVariableInvalid(
                "Prompt 变量未通过 Schema 校验",
                details={
                    "prompt_id": prompt_id,
                    "errors": [error.message for error in errors],
                },
            )

        missing = set(_template_variables(view.content)) - set(variables)
        if missing:
            raise PromptVariableInvalid(
                "Prompt 变量缺失",
                details={"prompt_id": prompt_id, "missing": sorted(missing)},
            )

        content = _PLACEHOLDER.sub(
            lambda match: _render_value(variables[match.group(1)]), view.content
        )
        used = tuple(sorted(set(_template_variables(view.content))))
        untrusted = tuple(name for name in used if name not in set(trusted_variables))
        return RenderedPrompt(
            prompt_id=view.prompt_id,
            name=view.name,
            version=view.version,
            content=content,
            variables_used=used,
            untrusted_variables=untrusted,
        )

    # ---- 测试记录 ----

    async def record_test(
        self,
        prompt_id: str,
        status: str,
        *,
        model_request_id: str | None = None,
        summary: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TestResultView:
        if status not in PROMPT_TEST_STATUSES:
            raise ValidationFailed(
                "Prompt 测试状态非法",
                details={"status": status, "allowed": sorted(PROMPT_TEST_STATUSES)},
            )
        async with self._database.session() as session, transaction(session):
            await self._require(PromptDefinitionRepository(session), prompt_id)
            entity = PromptTestResultModel(
                test_id=_new_id("ptt_"),
                prompt_id=prompt_id,
                model_request_id=model_request_id,
                status=status,
                summary=summary,
                metadata_json=json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                created_at=self._clock(),
            )
            await PromptTestResultRepository(session).add(entity)
            view = TestResultView(
                test_id=entity.test_id,
                prompt_id=entity.prompt_id,
                model_request_id=entity.model_request_id,
                status=entity.status,
                summary=entity.summary,
                metadata=dict(metadata or {}),
                created_at=entity.created_at,
            )
        return view

    async def list_tests(
        self, prompt_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[TestResultView]:
        async with self._database.session() as session:
            page = await PromptTestResultRepository(session).list_for_prompt(
                prompt_id, limit=limit, offset=offset
            )
        return [
            TestResultView(
                test_id=item.test_id,
                prompt_id=item.prompt_id,
                model_request_id=item.model_request_id,
                status=item.status,
                summary=item.summary,
                metadata=_load_json(item.metadata_json),
                created_at=item.created_at,
            )
            for item in page.items
        ]

    # ---- 校验 ----

    @staticmethod
    async def _require(
        repository: PromptDefinitionRepository, prompt_id: str
    ) -> PromptDefinitionModel:
        entity = await repository.get(prompt_id)
        if entity is None:
            raise NotFoundError("Prompt 不存在", details={"prompt_id": prompt_id})
        return entity

    @staticmethod
    def _validate_definition(name: str, category: str, content: str, status: str) -> None:
        if not name or len(name) > 128:
            raise ValidationFailed("Prompt 名称长度必须为 1–128", details={"name": name})
        if category not in PROMPT_CATEGORIES:
            raise ValidationFailed(
                "Prompt 分类非法",
                details={"category": category, "allowed": sorted(PROMPT_CATEGORIES)},
            )
        if not content.strip():
            raise ValidationFailed("Prompt 内容不能为空")
        if status not in {PROMPT_STATUS_DRAFT, PROMPT_STATUS_ACTIVE, PROMPT_STATUS_ARCHIVED}:
            raise ValidationFailed("Prompt 状态非法", details={"status": status})

    @staticmethod
    def _validate_schema(schema: Mapping[str, Any] | None) -> dict[str, Any]:
        normalized = dict(schema or _EMPTY_SCHEMA)
        if normalized.get("type", "object") != "object":
            raise ValidationFailed("variables_schema 必须是 object 类型")
        try:
            Draft202012Validator.check_schema(normalized)
        except SchemaError as exc:
            raise ValidationFailed(
                "variables_schema 不是合法 JSON Schema", details={"error": exc.message}
            ) from exc
        return normalized


def _view(entity: PromptDefinitionModel) -> PromptView:
    return PromptView(
        prompt_id=entity.prompt_id,
        name=entity.name,
        category=entity.category,
        description=entity.description,
        version=entity.version,
        content=entity.content,
        variables_schema=_load_json(entity.variables_schema),
        status=entity.status,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _declared_variables(schema: Mapping[str, Any]) -> set[str]:
    properties = schema.get("properties") or {}
    return set(properties) if isinstance(properties, Mapping) else set()


def _template_variables(content: str) -> list[str]:
    return _PLACEHOLDER.findall(content)


def _validate_placeholders(content: str, schema: Mapping[str, Any]) -> None:
    undeclared = set(_template_variables(content)) - _declared_variables(schema)
    if undeclared:
        raise ValidationFailed(
            "Prompt 占位符未在 variables_schema 中声明",
            details={"variables": sorted(undeclared)},
        )


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    loaded = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {}
