"""Agent Definition Registry（E6-T02）。

职责：Definition 的创建、草稿更新、引用校验、发布与停用。

规则：

- 发布后的 Definition 不可原地修改；新版本只能通过发布产生；
- 每次发布生成不可变版本记录（``agent_definition_versions``）；
- 发布前校验能力声明、Model Policy、Prompt、Context Profile、
  Tool 白名单与 Permission Ceiling；
- 校验失败一律失败关闭，不做静默降级。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    AgentCapabilityUnsupported,
    AgentDefinitionInvalid,
    AgentVersionImmutable,
    NotFoundError,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.agent_runtime.models import (
    AGENT_CAPABILITIES,
    BUDGET_DEFAULT,
    BUDGET_EXCEED_POLICIES,
    BUDGET_KEYS,
    CONTEXT_PROFILE_DEFAULT,
    CONTEXT_PROFILES,
    DEFAULT_PERMISSION_CEILING,
    DEFINITION_ACTIVE,
    DEFINITION_DISABLED,
    DEFINITION_DRAFT,
    DEFINITION_STATUSES,
    MODEL_POLICY_DEFAULT,
    PERMISSION_CEILINGS,
    AgentDefinitionModel,
    AgentDefinitionVersionModel,
)
from modules.agent_runtime.repository import (
    AgentDefinitionRepository,
    AgentDefinitionVersionRepository,
)
from modules.prompt.service import PromptService
from modules.tool.models import RISK_RANK
from modules.tool.registry import ToolRegistryService, ToolView

_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_DEFAULT_CATEGORY = "GENERAL"


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    """Model Policy 的最小可用定义；具体模型选择由 Model Binding 解析。"""

    policy_id: str
    default_model_id: str | None = None
    required_capabilities: tuple[str, ...] = ()


DEFAULT_MODEL_POLICIES: dict[str, ModelPolicy] = {
    MODEL_POLICY_DEFAULT: ModelPolicy(
        policy_id=MODEL_POLICY_DEFAULT,
        default_model_id=None,
        required_capabilities=("TOOL_CALLING", "STRUCTURED_OUTPUT"),
    )
}


@dataclass(frozen=True, slots=True)
class DefinitionView:
    definition_id: str
    name: str
    description: str | None
    category: str
    status: str
    current_version: str | None
    capabilities: tuple[str, ...]
    model_policy_id: str
    prompt_profile_id: str
    prompt_version: int
    context_profile_id: str
    context_profile_version: str
    tool_whitelist: tuple[str, ...]
    permission_ceiling: str
    budget_profile_id: str
    budget: dict[str, Any]
    max_concurrency: int
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DefinitionVersionView:
    version_id: str
    definition_id: str
    version: str
    definition: dict[str, Any]
    content_hash: str
    published_at: datetime
    published_by: str | None
    compatibility_metadata: dict[str, Any]


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _content_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _definition_view(entity: AgentDefinitionModel) -> DefinitionView:
    return DefinitionView(
        definition_id=entity.definition_id,
        name=entity.name,
        description=entity.description,
        category=entity.category,
        status=entity.status,
        current_version=entity.current_version,
        capabilities=tuple(json.loads(entity.supported_capabilities)),
        model_policy_id=entity.model_policy_id,
        prompt_profile_id=entity.prompt_profile_id,
        prompt_version=entity.prompt_version,
        context_profile_id=entity.context_profile_id,
        context_profile_version=entity.context_profile_version,
        tool_whitelist=tuple(json.loads(entity.tool_whitelist)),
        permission_ceiling=entity.permission_ceiling,
        budget_profile_id=entity.budget_profile_id,
        budget=json.loads(entity.budget_json),
        max_concurrency=entity.max_concurrency,
        version=entity.version,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _version_view(entity: AgentDefinitionVersionModel) -> DefinitionVersionView:
    return DefinitionVersionView(
        version_id=entity.version_id,
        definition_id=entity.agent_definition_id,
        version=entity.version,
        definition=json.loads(entity.definition_json),
        content_hash=entity.content_hash,
        published_at=entity.published_at,
        published_by=entity.published_by,
        compatibility_metadata=(
            json.loads(entity.compatibility_metadata) if entity.compatibility_metadata else {}
        ),
    )


def definition_payload(view: DefinitionView, *, version: str) -> dict[str, Any]:
    """冻结到版本表中的 Definition 内容（不含 secrets 与运行时状态）。"""

    return {
        "agent": {
            "id": view.definition_id,
            "name": view.name,
            "version": version,
            "description": view.description,
            "category": view.category,
        },
        "capabilities": list(view.capabilities),
        "model_policy": {"policy_id": view.model_policy_id},
        "prompt": {"profile_id": view.prompt_profile_id, "version": view.prompt_version},
        "context": {
            "profile_id": view.context_profile_id,
            "version": view.context_profile_version,
        },
        "tools": {"allowed": list(view.tool_whitelist)},
        "permissions": {"maximum_risk_level": view.permission_ceiling},
        "budgets": dict(view.budget),
        "budget_profile_id": view.budget_profile_id,
        "max_concurrency": view.max_concurrency,
    }


class DefinitionRegistryService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        prompts: PromptService,
        tools: ToolRegistryService,
        model_policies: Mapping[str, ModelPolicy] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._prompts = prompts
        self._tools = tools
        self._policies = dict(model_policies or DEFAULT_MODEL_POLICIES)
        self._clock = clock

    # ---- 查询 ----

    async def get(self, definition_id: str) -> DefinitionView:
        async with self._database.session() as session:
            entity = await AgentDefinitionRepository(session).get(definition_id)
        if entity is None:
            raise NotFoundError("Agent Definition 不存在", details={"definition_id": definition_id})
        return _definition_view(entity)

    async def get_by_name(self, name: str) -> DefinitionView:
        async with self._database.session() as session:
            entity = await AgentDefinitionRepository(session).get_by_name(name)
        if entity is None:
            raise NotFoundError("Agent Definition 不存在", details={"name": name})
        return _definition_view(entity)

    async def list(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        if status is not None and status not in DEFINITION_STATUSES:
            raise AgentDefinitionInvalid(
                "Definition 状态非法", details={"reasons": ["UNKNOWN_STATUS"], "status": status}
            )
        async with self._database.session() as session:
            page = await AgentDefinitionRepository(session).list_page(
                status=status, limit=limit, offset=offset
            )
        return {
            "items": [_definition_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def list_versions(self, definition_id: str) -> list[DefinitionVersionView]:
        await self.get(definition_id)
        async with self._database.session() as session:
            rows = await AgentDefinitionVersionRepository(session).list_for_definition(
                definition_id
            )
        return [_version_view(row) for row in rows]

    async def get_version(self, definition_id: str, version: str) -> DefinitionVersionView:
        async with self._database.session() as session:
            entity = await AgentDefinitionVersionRepository(session).get_by_version(
                definition_id, version
            )
        if entity is None:
            raise NotFoundError(
                "Agent Definition 版本不存在",
                details={"definition_id": definition_id, "version": version},
            )
        return _version_view(entity)

    def model_policy(self, policy_id: str) -> ModelPolicy:
        """返回已登记的 Model Policy；不存在时失败关闭。"""

        policy = self._policies.get(policy_id or "")
        if policy is None:
            raise AgentDefinitionInvalid(
                "Model Policy 不存在",
                details={"reasons": ["UNKNOWN_MODEL_POLICY"], "policy_id": policy_id},
            )
        return policy

    # ---- 创建与更新 ----

    async def create(
        self,
        *,
        name: str,
        model_policy_id: str,
        prompt_profile_id: str,
        prompt_version: int,
        capabilities: tuple[str, ...],
        description: str | None = None,
        category: str = _DEFAULT_CATEGORY,
        context_profile_id: str = CONTEXT_PROFILE_DEFAULT,
        context_profile_version: str = "1",
        tool_whitelist: tuple[str, ...] = (),
        permission_ceiling: str = DEFAULT_PERMISSION_CEILING,
        budget_profile_id: str = "default",
        budget: Mapping[str, Any] | None = None,
        max_concurrency: int = 1,
        created_by: str | None = None,
    ) -> DefinitionView:
        name = (name or "").strip()
        if not name:
            raise AgentDefinitionInvalid(
                "Agent 名称不能为空", details={"reasons": ["NAME_REQUIRED"]}
            )
        capabilities = _normalize_capabilities(capabilities)
        budget_payload = _validate_budget(budget)
        tool_ids = await self._resolve_tools(tool_whitelist, permission_ceiling)
        await self._validate_policy(model_policy_id)
        await self._validate_prompt(prompt_profile_id, prompt_version)
        _validate_context(context_profile_id, context_profile_version)
        _validate_ceiling(permission_ceiling)

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentDefinitionRepository(session)
            if await repository.get_by_name(name) is not None:
                raise AgentDefinitionInvalid(
                    "Agent 名称已存在", details={"reasons": ["DUPLICATE_NAME"], "name": name}
                )
            entity = AgentDefinitionModel(
                definition_id=_new_id("agdef_"),
                name=name,
                description=description,
                category=category,
                status=DEFINITION_DRAFT,
                current_version=None,
                supported_capabilities=json.dumps(list(capabilities)),
                model_policy_id=model_policy_id,
                prompt_profile_id=prompt_profile_id,
                prompt_version=prompt_version,
                context_profile_id=context_profile_id,
                context_profile_version=context_profile_version,
                tool_whitelist=json.dumps(list(tool_ids)),
                permission_ceiling=permission_ceiling,
                budget_profile_id=budget_profile_id,
                budget_json=json.dumps(budget_payload, sort_keys=True),
                max_concurrency=max(1, int(max_concurrency)),
                version=1,
                created_at=now,
                updated_at=now,
            )
            await repository.add(entity)
            return _definition_view(entity)

    async def update(
        self,
        definition_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        capabilities: tuple[str, ...] | None = None,
        model_policy_id: str | None = None,
        prompt_profile_id: str | None = None,
        prompt_version: int | None = None,
        context_profile_id: str | None = None,
        context_profile_version: str | None = None,
        tool_whitelist: tuple[str, ...] | None = None,
        permission_ceiling: str | None = None,
        budget_profile_id: str | None = None,
        budget: Mapping[str, Any] | None = None,
        max_concurrency: int | None = None,
        expected_version: int | None = None,
    ) -> DefinitionView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentDefinitionRepository(session)
            entity = await repository.get(definition_id)
            if entity is None:
                raise NotFoundError(
                    "Agent Definition 不存在", details={"definition_id": definition_id}
                )
            if entity.current_version is not None:
                raise AgentVersionImmutable(
                    "已发布的 Definition 不可修改，请发布新版本",
                    details={"definition_id": definition_id, "current_version": entity.current_version},
                )
            if expected_version is not None and entity.version != expected_version:
                from core.errors import VersionConflict

                raise VersionConflict(
                    "Definition 版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )

            if name is not None:
                candidate = name.strip()
                if not candidate:
                    raise AgentDefinitionInvalid(
                        "Agent 名称不能为空", details={"reasons": ["NAME_REQUIRED"]}
                    )
                other = await repository.get_by_name(candidate)
                if other is not None and other.definition_id != definition_id:
                    raise AgentDefinitionInvalid(
                        "Agent 名称已存在",
                        details={"reasons": ["DUPLICATE_NAME"], "name": candidate},
                    )
                entity.name = candidate
            if description is not None:
                entity.description = description
            if category is not None:
                entity.category = category
            if capabilities is not None:
                entity.supported_capabilities = json.dumps(
                    list(_normalize_capabilities(capabilities))
                )
            if model_policy_id is not None:
                await self._validate_policy(model_policy_id)
                entity.model_policy_id = model_policy_id
            if prompt_profile_id is not None or prompt_version is not None:
                profile = prompt_profile_id or entity.prompt_profile_id
                version = prompt_version if prompt_version is not None else entity.prompt_version
                await self._validate_prompt(profile, version)
                entity.prompt_profile_id = profile
                entity.prompt_version = version
            if context_profile_id is not None or context_profile_version is not None:
                profile = context_profile_id or entity.context_profile_id
                version = context_profile_version or entity.context_profile_version
                _validate_context(profile, version)
                entity.context_profile_id = profile
                entity.context_profile_version = version
            if permission_ceiling is not None:
                _validate_ceiling(permission_ceiling)
            ceiling = permission_ceiling or entity.permission_ceiling
            if tool_whitelist is not None:
                entity.tool_whitelist = json.dumps(
                    list(await self._resolve_tools(tool_whitelist, ceiling))
                )
            elif permission_ceiling is not None:
                # 收紧上限后必须重新校验现有白名单
                existing = tuple(json.loads(entity.tool_whitelist))
                entity.tool_whitelist = json.dumps(
                    list(await self._resolve_tools(existing, ceiling))
                )
            if permission_ceiling is not None:
                entity.permission_ceiling = permission_ceiling
            if budget_profile_id is not None:
                entity.budget_profile_id = budget_profile_id
            if budget is not None:
                entity.budget_json = json.dumps(_validate_budget(budget), sort_keys=True)
            if max_concurrency is not None:
                entity.max_concurrency = max(1, int(max_concurrency))
            entity.version += 1
            entity.updated_at = now
            await session.flush()
            return _definition_view(entity)

    # ---- 发布与停用 ----

    async def publish(
        self,
        definition_id: str,
        *,
        version: str | None = None,
        published_by: str | None = None,
        compatibility_metadata: Mapping[str, Any] | None = None,
    ) -> DefinitionVersionView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentDefinitionRepository(session)
            entity = await repository.get(definition_id)
            if entity is None:
                raise NotFoundError(
                    "Agent Definition 不存在", details={"definition_id": definition_id}
                )
            if entity.status == DEFINITION_DISABLED:
                raise AgentDefinitionInvalid(
                    "已停用的 Definition 不能发布",
                    details={"reasons": ["DEFINITION_DISABLED"], "definition_id": definition_id},
                )
            view = _definition_view(entity)
            await self.validate(view)

            versions = AgentDefinitionVersionRepository(session)
            resolved_version = version or await self._next_version(versions, definition_id)
            if not _VERSION_PATTERN.match(resolved_version or ""):
                raise AgentDefinitionInvalid(
                    "版本号必须形如 1.0.0",
                    details={"reasons": ["INVALID_VERSION"], "version": resolved_version},
                )
            if await versions.get_by_version(definition_id, resolved_version) is not None:
                raise AgentVersionImmutable(
                    "该版本已发布，不能重复发布",
                    details={"definition_id": definition_id, "version": resolved_version},
                )

            payload = definition_payload(view, version=resolved_version)
            record = AgentDefinitionVersionModel(
                version_id=_new_id("agver_"),
                agent_definition_id=definition_id,
                version=resolved_version,
                definition_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                content_hash=_content_hash(payload),
                published_at=now,
                published_by=published_by,
                compatibility_metadata=(
                    json.dumps(dict(compatibility_metadata), ensure_ascii=False, sort_keys=True)
                    if compatibility_metadata
                    else None
                ),
            )
            await versions.add(record)
            entity.current_version = resolved_version
            entity.status = DEFINITION_ACTIVE
            entity.version += 1
            entity.updated_at = now
            await session.flush()
            return _version_view(record)

    async def deactivate(self, definition_id: str) -> DefinitionView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            repository = AgentDefinitionRepository(session)
            entity = await repository.get(definition_id)
            if entity is None:
                raise NotFoundError(
                    "Agent Definition 不存在", details={"definition_id": definition_id}
                )
            if entity.status != DEFINITION_DISABLED:
                entity.status = DEFINITION_DISABLED
                entity.version += 1
                entity.updated_at = now
                await session.flush()
            return _definition_view(entity)

    # ---- 校验 ----

    async def validate(self, view: DefinitionView) -> None:
        """对 Definition 当前内容做完整引用校验；失败关闭。"""

        _normalize_capabilities(view.capabilities)
        _validate_ceiling(view.permission_ceiling)
        _validate_context(view.context_profile_id, view.context_profile_version)
        _validate_budget(view.budget)
        await self._validate_policy(view.model_policy_id)
        await self._validate_prompt(view.prompt_profile_id, view.prompt_version)
        await self._resolve_tools(view.tool_whitelist, view.permission_ceiling)

    async def _validate_policy(self, policy_id: str) -> ModelPolicy:
        policy = self._policies.get(policy_id or "")
        if policy is None:
            raise AgentDefinitionInvalid(
                "Model Policy 不存在",
                details={"reasons": ["UNKNOWN_MODEL_POLICY"], "policy_id": policy_id},
            )
        return policy

    async def _validate_prompt(self, profile_id: str, version: int) -> None:
        if not profile_id:
            raise AgentDefinitionInvalid(
                "Prompt Profile 不能为空", details={"reasons": ["PROMPT_REQUIRED"]}
            )
        try:
            await self._prompts.get_version(profile_id, int(version))
        except NotFoundError as exc:
            raise AgentDefinitionInvalid(
                "Prompt 引用不存在",
                details={
                    "reasons": ["UNKNOWN_PROMPT"],
                    "prompt_profile_id": profile_id,
                    "prompt_version": version,
                },
            ) from exc

    async def _resolve_tools(
        self, tool_refs: tuple[str, ...], permission_ceiling: str
    ) -> tuple[str, ...]:
        _validate_ceiling(permission_ceiling)
        ceiling_rank = RISK_RANK[permission_ceiling]
        resolved: list[str] = []
        for ref in tool_refs:
            tool = await self._find_tool(ref)
            if tool is None:
                raise AgentDefinitionInvalid(
                    "Tool 未在 Tool Registry 登记",
                    details={"reasons": ["UNKNOWN_TOOL"], "tool": ref},
                )
            if not tool.enabled:
                raise AgentDefinitionInvalid(
                    "Tool 已停用",
                    details={"reasons": ["TOOL_DISABLED"], "tool": tool.tool_id},
                )
            if RISK_RANK[tool.risk_level] > ceiling_rank:
                raise AgentDefinitionInvalid(
                    "Tool 风险等级超过 Definition 权限上限",
                    details={
                        "reasons": ["TOOL_EXCEEDS_CEILING"],
                        "tool": tool.tool_id,
                        "risk_level": tool.risk_level,
                        "permission_ceiling": permission_ceiling,
                    },
                )
            resolved.append(tool.tool_id)
        return tuple(dict.fromkeys(resolved))

    async def _find_tool(self, ref: str) -> ToolView | None:
        if not ref:
            return None
        try:
            return await self._tools.get(ref)
        except NotFoundError:
            pass
        try:
            return await self._tools.get_by_name(ref)
        except NotFoundError:
            return None

    async def _next_version(
        self, versions: AgentDefinitionVersionRepository, definition_id: str
    ) -> str:
        count = await versions.count_for_definition(definition_id)
        return "1.0.0" if count == 0 else f"1.0.{count}"


def _normalize_capabilities(capabilities: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item for item in capabilities if item))
    if not normalized:
        raise AgentDefinitionInvalid(
            "必须声明至少一个能力", details={"reasons": ["CAPABILITY_REQUIRED"]}
        )
    unknown = [item for item in normalized if item not in AGENT_CAPABILITIES]
    if unknown:
        raise AgentCapabilityUnsupported(
            "能力声明不受支持",
            details={"reasons": ["UNKNOWN_CAPABILITY"], "capabilities": unknown},
        )
    return normalized


def _validate_ceiling(permission_ceiling: str) -> None:
    if permission_ceiling not in PERMISSION_CEILINGS:
        raise AgentDefinitionInvalid(
            "Permission Ceiling 非法",
            details={"reasons": ["INVALID_CEILING"], "permission_ceiling": permission_ceiling},
        )


def _validate_context(profile_id: str, version: str) -> None:
    if not profile_id:
        raise AgentDefinitionInvalid(
            "Context Profile 不能为空", details={"reasons": ["CONTEXT_REQUIRED"]}
        )
    if profile_id not in CONTEXT_PROFILES:
        raise AgentDefinitionInvalid(
            "Context Profile 不存在",
            details={"reasons": ["UNKNOWN_CONTEXT_PROFILE"], "profile_id": profile_id},
        )
    if not version:
        raise AgentDefinitionInvalid(
            "Context Profile 版本不能为空", details={"reasons": ["CONTEXT_VERSION_REQUIRED"]}
        )


def _validate_budget(budget: Mapping[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = dict(BUDGET_DEFAULT)
    if budget is None:
        return payload
    unknown = sorted(set(budget) - BUDGET_KEYS - {"on_exceed"})
    if unknown:
        raise AgentDefinitionInvalid(
            "预算包含未知字段",
            details={"reasons": ["UNKNOWN_BUDGET_FIELD"], "fields": unknown},
        )
    for key, value in budget.items():
        if key == "on_exceed":
            if value not in BUDGET_EXCEED_POLICIES:
                raise AgentDefinitionInvalid(
                    "预算超限策略非法",
                    details={"reasons": ["INVALID_BUDGET_POLICY"], "policy": value},
                )
            payload[key] = value
            continue
        if value is None:
            payload.pop(key, None)
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise AgentDefinitionInvalid(
                "预算必须是非负数",
                details={"reasons": ["INVALID_BUDGET_VALUE"], "field": key},
            )
        payload[key] = value
    return payload


def format_definition(view: DefinitionView) -> dict[str, Any]:
    from core.security.tokens import isoformat

    return {
        "definition_id": view.definition_id,
        "name": view.name,
        "description": view.description,
        "category": view.category,
        "status": view.status,
        "current_version": view.current_version,
        "capabilities": list(view.capabilities),
        "model_policy_id": view.model_policy_id,
        "prompt_profile_id": view.prompt_profile_id,
        "prompt_version": view.prompt_version,
        "context_profile_id": view.context_profile_id,
        "context_profile_version": view.context_profile_version,
        "tool_whitelist": list(view.tool_whitelist),
        "permission_ceiling": view.permission_ceiling,
        "budget_profile_id": view.budget_profile_id,
        "budget": view.budget,
        "max_concurrency": view.max_concurrency,
        "version": view.version,
        "created_at": isoformat(view.created_at),
        "updated_at": isoformat(view.updated_at),
    }


def format_version(view: DefinitionVersionView) -> dict[str, Any]:
    from core.security.tokens import isoformat

    return {
        "version_id": view.version_id,
        "definition_id": view.definition_id,
        "version": view.version,
        "definition": view.definition,
        "content_hash": view.content_hash,
        "published_at": isoformat(view.published_at),
        "published_by": view.published_by,
        "compatibility_metadata": view.compatibility_metadata,
    }
