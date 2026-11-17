"""Shared Contracts 协议加载与校验。

契约事实源位于仓库根目录 ``packages/contracts``，本模块只负责读取与校验，
不得在此重复定义协议字段。
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_MANIFEST = "schemas/manifest.json"


class ContractError(Exception):
    """契约文件缺失或不可解析。"""


def _resource_root() -> Path:
    """资源根目录：PyInstaller 打包后为解包目录，开发时为仓库根目录。"""

    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parents[4]


def contracts_root() -> Path:
    """契约根目录。打包后可通过环境变量覆盖。"""

    override = os.environ.get("GODOT_AI_CONTRACTS_DIR")
    if override:
        return Path(override).resolve()
    return _resource_root() / "packages" / "contracts"


def load_json(relative_path: str) -> Any:
    path = contracts_root() / relative_path
    if not path.is_file():
        raise ContractError(f"契约文件不存在: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ContractError(f"契约文件不是合法 JSON: {path}") from exc


@lru_cache(maxsize=16)
def load_schema(relative_path: str) -> dict[str, Any]:
    schema = load_json(relative_path)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_instance(instance: Any, schema_path: str) -> list[str]:
    """返回错误信息列表；空列表表示通过。"""

    validator = Draft202012Validator(load_schema(schema_path))
    messages: list[str] = []
    for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    return messages


def protocol_version() -> str:
    return str(load_json("common/protocol.json")["protocol_version"])


def iter_manifest() -> Iterator[dict[str, Any]]:
    yield from load_json(SCHEMA_MANIFEST)["cases"]
