"""跨模块通用类型与契约校验。"""

from shared.contracts import (
    ContractError,
    contracts_root,
    iter_manifest,
    load_json,
    load_schema,
    protocol_version,
    validate_instance,
)

__all__ = [
    "ContractError",
    "contracts_root",
    "iter_manifest",
    "load_json",
    "load_schema",
    "protocol_version",
    "validate_instance",
]
