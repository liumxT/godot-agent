"""工具注册与 Schema 注册（E5-T17 / T18）。

注册的工具必须提供严格的输入 / 输出 JSON Schema；
任何工具输入在执行前都必须经过 Schema 校验，不允许把未验证 JSON 直接执行。
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

from core.errors import (
    NotFoundError,
    ToolAlreadyRegistered,
    ToolInputInvalid,
    ToolOutputInvalid,
    ToolSchemaInvalid,
    ValidationFailed,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.tool.models import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    EXECUTION_MODES,
    IDEMPOTENCY_POLICIES,
    TOOL_CAPABILITIES,
    TOOL_CATEGORIES,
    TOOL_RISK_LEVELS,
    ToolDefinitionModel,
)
from modules.tool.repository import ToolDefinitionRepository

__all__ = ["ToolRegistryService", "ToolView"]

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


@dataclass(frozen=True, slots=True)
class ToolView:
    tool_id: str
    name: str
    version: int
    category: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str
    required_capabilities: tuple[str, ...]
    required_permissions: tuple[str, ...]
    execution_mode: str
    timeout_seconds: int
    idempotency_policy: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ToolRegistryService:
    def __init__(self, database: DatabaseService, *, clock: Any = utcnow) -> None:
        self._database = database
        self._clock = clock

    async def register(
        self,
        *,
        name: str,
        category: str,
        description: str,
        input_schema: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        risk_level: str,
        required_capabilities: tuple[str, ...] = (),
        required_permissions: tuple[str, ...] = (),
        execution_mode: str = "SYNC",
        timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
        idempotency_policy: str = "NONE",
    ) -> ToolView:
        definition = self._validate_definition(
            name=name,
            category=category,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            risk_level=risk_level,
            required_capabilities=required_capabilities,
            required_permissions=required_permissions,
            execution_mode=execution_mode,
            timeout_seconds=timeout_seconds,
            idempotency_policy=idempotency_policy,
        )
        now = self._clock()

        async with self._database.session() as session, transaction(session):
            repository = ToolDefinitionRepository(session)
            if await repository.latest_version(definition["name"]) > 0:
                raise ToolAlreadyRegistered(
                    "工具名称已注册，请登记新版本",
                    details={"name": definition["name"]},
                )
            entity = ToolDefinitionModel(
                tool_id="tol_" + uuid4().hex[:12],
                version=1,
                enabled=True,
                created_at=now,
                updated_at=now,
                **definition,
            )
            await repository.add(entity)
            return _view(entity)

    async def register_version(
        self,
        name: str,
        *,
        description: str,
        input_schema: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        risk_level: str,
        category: str | None = None,
        required_capabilities: tuple[str, ...] = (),
        required_permissions: tuple[str, ...] = (),
        execution_mode: str = "SYNC",
        timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
        idempotency_policy: str = "NONE",
    ) -> ToolView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = ToolDefinitionRepository(session)
            latest = await repository.latest_version(name)
            if latest == 0:
                raise NotFoundError("工具不存在", details={"name": name})
            previous = await repository.get_by_name_version(name, latest)
            if previous is None:
                raise NotFoundError("工具版本不存在", details={"name": name, "version": latest})
            definition = self._validate_definition(
                name=name,
                category=category or previous.category,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                risk_level=risk_level,
                required_capabilities=required_capabilities,
                required_permissions=required_permissions,
                execution_mode=execution_mode,
                timeout_seconds=timeout_seconds,
                idempotency_policy=idempotency_policy,
            )
            entity = ToolDefinitionModel(
                tool_id="tol_" + uuid4().hex[:12],
                version=latest + 1,
                enabled=True,
                created_at=now,
                updated_at=now,
                **definition,
            )
            await repository.add(entity)
            return _view(entity)

    async def set_enabled(self, tool_id: str, enabled: bool) -> ToolView:
        async with self._database.session() as session, transaction(session):
            repository = ToolDefinitionRepository(session)
            entity = await self._require(repository, tool_id)
            entity.enabled = enabled
            entity.updated_at = self._clock()
            await session.flush()
            return _view(entity)

    async def get(self, tool_id: str) -> ToolView:
        async with self._database.session() as session:
            return _view(await self._require(ToolDefinitionRepository(session), tool_id))

    async def get_by_name(self, name: str, version: int | None = None) -> ToolView:
        async with self._database.session() as session:
            repository = ToolDefinitionRepository(session)
            if version is None:
                version = await repository.latest_version(name)
                if version == 0:
                    raise NotFoundError("工具不存在", details={"name": name})
            entity = await repository.get_by_name_version(name, version)
            if entity is None:
                raise NotFoundError("工具版本不存在", details={"name": name, "version": version})
            return _view(entity)

    async def list(
        self,
        *,
        category: str | None = None,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ToolView]:
        async with self._database.session() as session:
            page = await ToolDefinitionRepository(session).list_definitions(
                category=category, enabled=enabled, limit=limit, offset=offset
            )
        return [_view(item) for item in page.items]

    async def validate_input(self, tool: ToolView, payload: Mapping[str, Any]) -> dict[str, Any]:
        errors = _schema_errors(tool.input_schema, payload)
        if errors:
            raise ToolInputInvalid(
                "工具输入未通过 Schema 校验",
                details={"tool_id": tool.tool_id, "tool_version": tool.version, "errors": errors},
            )
        return dict(payload)

    async def validate_output(self, tool: ToolView, payload: Mapping[str, Any]) -> dict[str, Any]:
        errors = _schema_errors(tool.output_schema, payload)
        if errors:
            raise ToolOutputInvalid(
                "工具输出未通过 Schema 校验",
                details={"tool_id": tool.tool_id, "tool_version": tool.version, "errors": errors},
            )
        return dict(payload)

    @staticmethod
    async def _require(
        repository: ToolDefinitionRepository, tool_id: str
    ) -> ToolDefinitionModel:
        entity = await repository.get(tool_id)
        if entity is None:
            raise NotFoundError("工具不存在", details={"tool_id": tool_id})
        return entity

    @staticmethod
    def _validate_definition(
        *,
        name: str,
        category: str,
        description: str,
        input_schema: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        risk_level: str,
        required_capabilities: tuple[str, ...],
        required_permissions: tuple[str, ...],
        execution_mode: str,
        timeout_seconds: int,
        idempotency_policy: str,
    ) -> dict[str, Any]:
        if not _NAME_PATTERN.match(name):
            raise ValidationFailed(
                "工具名称必须为小写点分标识符", details={"name": name}
            )
        if category not in TOOL_CATEGORIES:
            raise ValidationFailed(
                "工具分类非法", details={"category": category, "allowed": sorted(TOOL_CATEGORIES)}
            )
        if not description.strip():
            raise ValidationFailed("工具描述不能为空")
        if risk_level not in TOOL_RISK_LEVELS:
            raise ValidationFailed(
                "风险等级非法", details={"risk_level": risk_level, "allowed": TOOL_RISK_LEVELS}
            )
        unknown = sorted(set(required_capabilities) - TOOL_CAPABILITIES)
        if unknown:
            raise ValidationFailed(
                "工具引用了未知能力", details={"capabilities": unknown}
            )
        if any(not item.strip() for item in required_permissions):
            raise ValidationFailed("required_permissions 不能包含空字符串")
        if execution_mode not in EXECUTION_MODES:
            raise ValidationFailed(
                "执行模式非法", details={"execution_mode": execution_mode}
            )
        if idempotency_policy not in IDEMPOTENCY_POLICIES:
            raise ValidationFailed(
                "幂等策略非法", details={"idempotency_policy": idempotency_policy}
            )
        if timeout_seconds <= 0:
            raise ValidationFailed("timeout_seconds 必须为正整数")
        return {
            "name": name,
            "category": category,
            "description": description,
            "input_schema": json.dumps(
                _checked_schema(input_schema, "input_schema"), ensure_ascii=False, sort_keys=True
            ),
            "output_schema": json.dumps(
                _checked_schema(output_schema, "output_schema"), ensure_ascii=False, sort_keys=True
            ),
            "risk_level": risk_level,
            "required_capabilities": json.dumps(
                sorted(set(required_capabilities)), ensure_ascii=False
            ),
            "required_permissions": json.dumps(
                sorted(set(required_permissions)), ensure_ascii=False
            ),
            "execution_mode": execution_mode,
            "timeout_seconds": timeout_seconds,
            "idempotency_policy": idempotency_policy,
        }


def _checked_schema(schema: Mapping[str, Any], field: str) -> dict[str, Any]:
    normalized = dict(schema)
    if normalized.get("type", "object") != "object":
        raise ToolSchemaInvalid(f"{field} 必须是 object 类型")
    try:
        Draft202012Validator.check_schema(normalized)
    except SchemaError as exc:
        raise ToolSchemaInvalid(
            f"{field} 不是合法 JSON Schema", details={"field": field, "error": exc.message}
        ) from exc
    return normalized


def _schema_errors(schema: Mapping[str, Any], payload: Mapping[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(dict(payload)), key=lambda item: list(item.path))
    return [f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors]


def _view(entity: ToolDefinitionModel) -> ToolView:
    return ToolView(
        tool_id=entity.tool_id,
        name=entity.name,
        version=entity.version,
        category=entity.category,
        description=entity.description,
        input_schema=json.loads(entity.input_schema),
        output_schema=json.loads(entity.output_schema),
        risk_level=entity.risk_level,
        required_capabilities=tuple(json.loads(entity.required_capabilities)),
        required_permissions=tuple(json.loads(entity.required_permissions)),
        execution_mode=entity.execution_mode,
        timeout_seconds=entity.timeout_seconds,
        idempotency_policy=entity.idempotency_policy,
        enabled=entity.enabled,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )
