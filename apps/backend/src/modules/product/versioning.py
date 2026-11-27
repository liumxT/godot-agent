"""产品版本、组件版本与公开契约（E12-T01 / T18）。

核心约束：

- Product Version 与 Game Artifact Version 属于两个完全独立的版本域；
- 所有正式组件必须声明版本，未知版本不得进入发布包；
- 公开契约必须有版本、兼容策略与废弃信息。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from core.errors import ValidationFailed

PRODUCT_NAME = "Godot AI Agent Platform"
PRODUCT_VERSION = "1.0.0"
PRODUCT_VERSION_DOMAIN = "product"
GAME_ARTIFACT_VERSION_DOMAIN = "game_artifact"
COMPATIBILITY_MATRIX_VERSION = "1.0.0"

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

COMPATIBILITY_BACKWARD = "BACKWARD_COMPATIBLE"
COMPATIBILITY_FORWARD = "FORWARD_COMPATIBLE"
COMPATIBILITY_STRICT = "STRICT"


@dataclass(frozen=True, slots=True)
class ProductComponent:
    component_id: str
    name: str
    component_type: str
    version: str
    contract_version: str
    required: bool = True
    notes: str = ""


COMPONENTS: tuple[ProductComponent, ...] = (
    ProductComponent("backend", "Local Backend", "SERVICE", PRODUCT_VERSION, "1.0.0"),
    ProductComponent("launcher", "Product Launcher", "TOOL", PRODUCT_VERSION, "1.0.0"),
    ProductComponent(
        "godot_plugin",
        "Godot Editor Plugin",
        "PLUGIN",
        "0.1.0",
        "1.0.0",
        notes="插件版本独立演进，协议版本必须为 1.x",
    ),
    ProductComponent("api_protocol", "HTTP/WebSocket Protocol", "CONTRACT", "1.0.0", "1.0.0"),
    ProductComponent("database_schema", "Database Schema", "DATA", "000033", "000033"),
    ProductComponent(
        "agent_definition_schema", "Agent Definition Schema", "CONTRACT", "1.0.0", "1.0.0"
    ),
    ProductComponent("tool_schema", "Tool Schema", "CONTRACT", "1.0.0", "1.0.0"),
    ProductComponent(
        "provider_adapter_contract", "Provider Adapter Contract", "CONTRACT", "1.0.0", "1.0.0"
    ),
    ProductComponent("installer", "Product Installer", "TOOL", PRODUCT_VERSION, "1.0.0"),
    ProductComponent("product_package", "Product Package", "ARTIFACT", PRODUCT_VERSION, "1.0.0"),
    ProductComponent(
        "documentation", "Product Documentation", "DOCUMENT", PRODUCT_VERSION, "1.0.0"
    ),
)

COMPONENT_INDEX: dict[str, ProductComponent] = {item.component_id: item for item in COMPONENTS}


@dataclass(frozen=True, slots=True)
class ContractRecord:
    contract_id: str
    contract_version: str
    owner_module: str
    compatibility_policy: str
    deprecated_since: str | None
    removed_since: str | None
    migration_strategy: str
    schema_hash: str


def _schema_hash(contract_id: str, version: str, owner: str, policy: str) -> str:
    material = f"{contract_id}|{version}|{owner}|{policy}".encode()
    return hashlib.sha256(material).hexdigest()


def _contract(
    contract_id: str,
    version: str,
    owner: str,
    policy: str,
    *,
    deprecated_since: str | None = None,
    removed_since: str | None = None,
    migration_strategy: str = "无破坏性变更；破坏性变更必须进入新的主版本",
) -> ContractRecord:
    return ContractRecord(
        contract_id=contract_id,
        contract_version=version,
        owner_module=owner,
        compatibility_policy=policy,
        deprecated_since=deprecated_since,
        removed_since=removed_since,
        migration_strategy=migration_strategy,
        schema_hash=_schema_hash(contract_id, version, owner, policy),
    )


CONTRACTS: tuple[ContractRecord, ...] = (
    _contract("product.http_api", "1.0.0", "modules/product", COMPATIBILITY_BACKWARD),
    _contract("product.ws_protocol", "1.0.0", "modules/bridge_event", COMPATIBILITY_BACKWARD),
    _contract("product.plugin_backend", "1.0.0", "app/api", COMPATIBILITY_BACKWARD),
    _contract("product.product_manifest", "1.0.0", "modules/product", COMPATIBILITY_STRICT),
    _contract("product.update_manifest", "1.0.0", "modules/product", COMPATIBILITY_STRICT),
    _contract("product.agent_definition", "1.0.0", "modules/agent_runtime", COMPATIBILITY_BACKWARD),
    _contract("product.tool_schema", "1.0.0", "modules/tool", COMPATIBILITY_BACKWARD),
    _contract("product.provider_adapter", "1.0.0", "modules/model_gateway", COMPATIBILITY_BACKWARD),
    _contract("product.build_adapter", "1.0.0", "modules/build_release", COMPATIBILITY_BACKWARD),
    _contract("product.asset_provider", "1.0.0", "modules/asset_pipeline", COMPATIBILITY_BACKWARD),
)

CONTRACT_INDEX: dict[str, ContractRecord] = {item.contract_id: item for item in CONTRACTS}

CONTRACT_SUPPORTED = "SUPPORTED"
CONTRACT_DEPRECATED = "DEPRECATED"
CONTRACT_REMOVED = "REMOVED"
CONTRACT_UNKNOWN = "UNKNOWN"


def parse_version(version: str) -> tuple[int, int, int]:
    """解析 ``MAJOR.MINOR.PATCH``；非法版本直接拒绝。"""

    match = _SEMVER.match((version or "").strip())
    if not match:
        raise ValidationFailed(
            "版本号必须为 MAJOR.MINOR.PATCH",
            details={"version": version},
        )
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def compare_versions(left: str, right: str) -> int:
    left_parts = parse_version(left)
    right_parts = parse_version(right)
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def is_newer(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) > 0


def ensure_version_isolation(domain: str) -> None:
    """产品版本域只能被产品发布使用；游戏制品不得复用。"""

    if domain != PRODUCT_VERSION_DOMAIN:
        raise ValidationFailed(
            "产品版本与游戏制品版本必须使用独立版本域",
            details={"expected": PRODUCT_VERSION_DOMAIN, "actual": domain},
        )


def component_manifest() -> dict[str, object]:
    return {
        "product_name": PRODUCT_NAME,
        "product_version": PRODUCT_VERSION,
        "version_domain": PRODUCT_VERSION_DOMAIN,
        "game_artifact_version_domain": GAME_ARTIFACT_VERSION_DOMAIN,
        "compatibility_matrix_version": COMPATIBILITY_MATRIX_VERSION,
        "components": [
            {
                "component_id": item.component_id,
                "name": item.name,
                "component_type": item.component_type,
                "version": item.version,
                "contract_version": item.contract_version,
                "required": item.required,
                "notes": item.notes,
            }
            for item in COMPONENTS
        ],
    }


def contract_manifest() -> list[dict[str, object]]:
    return [
        {
            "contract_id": item.contract_id,
            "contract_version": item.contract_version,
            "owner_module": item.owner_module,
            "compatibility_policy": item.compatibility_policy,
            "deprecated_since": item.deprecated_since,
            "removed_since": item.removed_since,
            "migration_strategy": item.migration_strategy,
            "schema_hash": item.schema_hash,
        }
        for item in CONTRACTS
    ]


def contract_status(contract_id: str, version: str) -> dict[str, object]:
    record = CONTRACT_INDEX.get(contract_id)
    if record is None:
        return {
            "contract_id": contract_id,
            "version": version,
            "status": CONTRACT_UNKNOWN,
            "reason": "契约未登记",
        }
    if record.removed_since and compare_versions(version, record.removed_since) >= 0:
        status, reason = CONTRACT_REMOVED, "该契约版本已移除"
    elif record.deprecated_since and compare_versions(version, record.deprecated_since) >= 0:
        status, reason = CONTRACT_DEPRECATED, "该契约版本已废弃"
    elif compare_versions(version, record.contract_version) > 0:
        status, reason = CONTRACT_UNKNOWN, "契约版本高于当前产品支持版本"
    else:
        status, reason = CONTRACT_SUPPORTED, ""
    return {
        "contract_id": contract_id,
        "version": version,
        "status": status,
        "reason": reason,
        "record": {
            "contract_version": record.contract_version,
            "compatibility_policy": record.compatibility_policy,
            "migration_strategy": record.migration_strategy,
            "schema_hash": record.schema_hash,
        },
    }


def declared_component_versions() -> dict[str, str]:
    return {item.component_id: item.version for item in COMPONENTS}
