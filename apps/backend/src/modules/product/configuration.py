"""产品配置中心与 Secrets 边界（E12-T04 / T11）。

分层优先级：

``SYSTEM_DEFAULT < USER_GLOBAL < PROJECT_OVERRIDE < SESSION_OVERRIDE``

安全与权限策略只能来自系统默认层，低或高层配置均不得弱化。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.models import ProductConfigurationModel
from modules.product.repository import ConfigurationRepository

SCOPE_SYSTEM = "SYSTEM_DEFAULT"
SCOPE_USER = "USER_GLOBAL"
SCOPE_PROJECT = "PROJECT_OVERRIDE"
SCOPE_SESSION = "SESSION_OVERRIDE"
SCOPES = (SCOPE_SYSTEM, SCOPE_USER, SCOPE_PROJECT, SCOPE_SESSION)
SCOPE_PRIORITY = {scope: index for index, scope in enumerate(SCOPES)}
PROFILE_ACTIVE = "ACTIVE"
PROFILE_ARCHIVED = "ARCHIVED"

PROTECTED_PREFIXES = (
    "security.",
    "permissions.",
    "privacy.telemetry_default",
    "update.require_signature",
    "update.require_user_approval",
    "agent.install_allowed",
)

SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|credential|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{12,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,})"
)
CREDENTIAL_REFERENCE = re.compile(r"^(cred|secret|keyring|env)://|^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/Users/|/home/|/root/)")


def _now() -> datetime:
    return datetime.now(UTC)


def canonical_json(values: Mapping[str, Any]) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def configuration_hash(values: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(values).encode()).hexdigest()


def is_protected_key(key: str) -> bool:
    return any(key == prefix or key.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def assert_no_plaintext_secrets(values: Mapping[str, Any]) -> None:
    for key, value in _walk_items(values):
        if isinstance(value, str) and SECRET_VALUE_PATTERN.search(value):
            raise ValidationFailed("配置中不允许出现明文凭证", details={"key": key})
        if (
            SECRET_KEY_PATTERN.search(key)
            and isinstance(value, str)
            and value
            and not CREDENTIAL_REFERENCE.match(value)
        ):
            raise ValidationFailed("敏感配置必须使用凭证引用", details={"key": key})


def _walk_items(values: Mapping[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key, value in values.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping):
            yield from _walk_items(value, f"{path}.")
        else:
            yield path, value


def redact_configuration(values: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, Mapping):
            cleaned[key] = redact_configuration(value)
            continue
        if SECRET_KEY_PATTERN.search(key):
            cleaned[key] = "<redacted>"
            continue
        if isinstance(value, str):
            if SECRET_VALUE_PATTERN.search(value):
                cleaned[key] = "<redacted>"
                continue
            if ABSOLUTE_PATH.match(value):
                cleaned[key] = "<path>"
                continue
        cleaned[key] = value
    return cleaned


def _profile_dict(row: ProductConfigurationModel) -> dict[str, Any]:
    return {
        "profile_id": row.profile_id,
        "profile_name": row.profile_name,
        "scope": row.scope,
        "profile_version": row.profile_version,
        "values": json.loads(row.values_json),
        "configuration_hash": row.configuration_hash,
        "status": row.status,
        "updated_at": row.updated_at.isoformat(),
    }


class ProductConfigurationService:
    """配置 Profile 的持久化与有效值解析。"""

    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def upsert_profile(
        self,
        *,
        profile_name: str,
        scope: str,
        values: Mapping[str, Any],
        profile_version: int = 1,
        status: str = PROFILE_ACTIVE,
    ) -> dict[str, Any]:
        if scope not in SCOPES:
            raise ValidationFailed("未知的配置层级", details={"scope": scope})
        if status not in {PROFILE_ACTIVE, PROFILE_ARCHIVED}:
            raise ValidationFailed("未知的配置状态", details={"status": status})
        assert_no_plaintext_secrets(values)
        digest = configuration_hash(values)
        now = _now()
        async with self._database.session() as session, transaction(session):
            repository = ConfigurationRepository(session)
            existing = await repository.get_by_name_scope(profile_name, scope)
            if existing is None:
                existing = ProductConfigurationModel(
                    profile_id=f"cfg_{uuid.uuid4().hex[:16]}",
                    profile_name=profile_name,
                    scope=scope,
                    profile_version=profile_version,
                    values_json=canonical_json(values),
                    configuration_hash=digest,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
                await repository.add(existing)
            else:
                existing.values_json = canonical_json(values)
                existing.profile_version = profile_version
                existing.configuration_hash = digest
                existing.status = status
                existing.updated_at = now
            await session.flush()
            return _profile_dict(existing)

    async def list_profiles(self) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            rows = await ConfigurationRepository(session).list_all()
            return [_profile_dict(row) for row in rows]

    async def resolve_effective(
        self,
        profiles: Iterable[ProductConfigurationModel] | None = None,
    ) -> dict[str, Any]:
        if profiles is None:
            async with self._database.session() as session:
                rows = await ConfigurationRepository(session).list_all()
        else:
            rows = list(profiles)
        active = [row for row in rows if row.status == PROFILE_ACTIVE]
        active.sort(key=lambda row: SCOPE_PRIORITY.get(row.scope, 0))

        values: dict[str, Any] = {}
        ignored: set[str] = set()
        for row in active:
            layer = json.loads(row.values_json)
            for key, value in layer.items():
                if is_protected_key(key) and row.scope != SCOPE_SYSTEM:
                    ignored.add(key)
                    continue
                values[key] = value
        return {
            "values": values,
            "configuration_hash": configuration_hash(values),
            "scopes": sorted({row.scope for row in active}, key=SCOPE_PRIORITY.get),
            "ignored_protected": sorted(ignored),
        }

    async def export_safe(self) -> dict[str, Any]:
        effective = await self.resolve_effective()
        return {
            "configuration": redact_configuration(effective["values"]),
            "configuration_hash": effective["configuration_hash"],
            "scopes": effective["scopes"],
            "ignored_protected": effective["ignored_protected"],
            "contains_project_source": False,
        }


def resolve_model(
    *,
    user_model: str,
    user_provider: str,
    available_models: Mapping[str, Iterable[str]],
) -> dict[str, str]:
    """用户显式选择的模型不可用时直接失败，禁止静默替换。"""

    models = {str(item) for item in available_models.get(user_provider, ())}
    if user_model not in models:
        raise ValidationFailed(
            "用户指定的模型不可用",
            details={
                "provider": user_provider,
                "model": user_model,
                "available": sorted(models),
            },
        )
    return {"provider": user_provider, "model": user_model, "fallback": "none"}
