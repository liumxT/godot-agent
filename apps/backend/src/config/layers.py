"""配置分层加载（E1-T02）。

优先级（高 → 低）：

1. 运行时 ``overrides``（装配与测试注入）；
2. 环境变量 ``GODOT_AI_*``；
3. TOML 配置文件（``GODOT_AI_CONFIG_FILE``，默认 ``config/backend.toml``）；
4. ``.env``（本地开发；可用 ``env_file=None`` 关闭）；
5. ``Settings`` 代码默认值。

Secrets 不参与本流程，仍由 ``infrastructure.secrets`` 提供。
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from config.settings import Settings, load_settings
from core.errors import ConfigError

ENV_PREFIX = "GODOT_AI_"
CONFIG_FILE_ENV = "GODOT_AI_CONFIG_FILE"
DEFAULT_CONFIG_FILE = Path("config/backend.toml")


def resolve_config_file(config_file: str | Path | None = None) -> Path:
    if config_file is not None:
        return Path(config_file)
    configured = os.environ.get(CONFIG_FILE_ENV)
    return Path(configured) if configured else DEFAULT_CONFIG_FILE


def read_config_file(path: Path) -> dict[str, Any]:
    """读取 TOML；文件不存在时返回空字典（允许纯环境变量运行）。"""

    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            "配置文件无法读取",
            details={"file": str(path), "reason": str(exc)},
        ) from exc
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            "配置文件格式非法",
            details={"file": str(path), "reason": str(exc)},
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError("配置文件根节点必须是表", details={"file": str(path)})
    return data


def environment_values(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """收集 ``GODOT_AI_*`` 环境变量并还原为字段名。"""

    source = environ if environ is not None else os.environ
    values: dict[str, str] = {}
    for key, value in source.items():
        if not key.startswith(ENV_PREFIX) or key == CONFIG_FILE_ENV:
            continue
        field = key[len(ENV_PREFIX) :].lower()
        if field:
            values[field] = value
    return values


def load_layered_settings(
    *,
    overrides: Mapping[str, Any] | None = None,
    config_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    env_file: str | None = ".env",
) -> Settings:
    """按分层优先级合并并校验配置；非法文件配置阻断启动（E1-FI-010）。"""

    file_values = read_config_file(resolve_config_file(config_file))
    _reject_unknown_fields(file_values, source="配置文件")
    merged: dict[str, Any] = {
        **file_values,
        **environment_values(environ),
        **dict(overrides or {}),
    }
    return load_settings(_env_file=env_file, **merged)


def _reject_unknown_fields(values: Mapping[str, Any], *, source: str) -> None:
    known = Settings.model_fields
    unknown = sorted(key for key in values if key not in known)
    if not unknown:
        return
    raise ConfigError(
        f"{source}包含未知配置项",
        details={"fields": unknown, "allowed": sorted(known)},
    )
