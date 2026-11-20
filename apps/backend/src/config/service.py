"""配置服务（E1-T02）。

对外提供只读快照与受策略约束的运行时更新：

- ``IMMUTABLE`` / ``RESTART_REQUIRED`` 字段拒绝运行期修改并记录 ``config_rejected``；
- ``HOT_RELOAD`` 字段更新成功后记录 ``config_loaded``（值脱敏）；
- 加载与变更日志不输出敏感值。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from pydantic import ValidationError

from config.layers import load_layered_settings
from config.policies import ChangePolicy, policy_for
from config.settings import Settings
from core.errors import ConfigError
from core.logging import get_logger, log_event

_SENSITIVE_KEY = re.compile(r"api[_-]?key|token|secret|password|authorization", re.IGNORECASE)


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """屏蔽名称命中敏感词的配置值。"""

    return {
        key: ("***" if _SENSITIVE_KEY.search(key) and value else value)
        for key, value in values.items()
    }


class ConfigService:
    def __init__(
        self,
        settings: Settings,
        *,
        on_hot_reload: Callable[[Settings], None] | None = None,
    ) -> None:
        self._settings = settings
        self._on_hot_reload = on_hot_reload
        self._logger = get_logger("backend.config")

    @classmethod
    def load(
        cls,
        *,
        overrides: Mapping[str, Any] | None = None,
        config_file: str | None = None,
        env_file: str | None = ".env",
        on_hot_reload: Callable[[Settings], None] | None = None,
    ) -> ConfigService:
        settings = load_layered_settings(
            overrides=overrides, config_file=config_file, env_file=env_file
        )
        service = cls(settings, on_hot_reload=on_hot_reload)
        service.log_loaded("startup")
        return service

    @property
    def current(self) -> Settings:
        return self._settings

    def snapshot(self) -> Mapping[str, Any]:
        """返回只读配置快照（敏感字段已脱敏）。"""

        return MappingProxyType(redact_mapping(self._settings.model_dump(mode="json")))

    def update(self, **changes: Any) -> Settings:
        """按策略更新配置；任一字段被拒绝时整体不生效。"""

        if not changes:
            return self._settings

        unknown = sorted(field for field in changes if field not in Settings.model_fields)
        if unknown:
            self._reject(unknown[0], ChangePolicy.IMMUTABLE, reason="unknown_field")
            raise ConfigError("未知配置项", details={"fields": unknown})

        for field in changes:
            policy = policy_for(field)
            if policy is not ChangePolicy.HOT_RELOAD:
                self._reject(field, policy)
                hint = (
                    "该配置不可修改" if policy is ChangePolicy.IMMUTABLE else "该配置需要重启生效"
                )
                raise ConfigError(
                    f"配置不可热更新: {field}",
                    details={"field": field, "policy": policy.value, "hint": hint},
                )

        try:
            updated = Settings.model_validate({**self._settings.model_dump(), **changes})
        except ValidationError as exc:
            self._reject(next(iter(changes)), ChangePolicy.HOT_RELOAD, reason="invalid_value")
            raise ConfigError(
                "配置值非法",
                details={"fields": sorted(changes), "errors": exc.errors(include_url=False)},
            ) from exc

        self._settings = updated
        self.log_loaded("hot_reload", changes=changes)
        if self._on_hot_reload is not None:
            self._on_hot_reload(updated)
        return updated

    def log_loaded(self, reason: str, *, changes: Mapping[str, Any] | None = None) -> None:
        values = redact_mapping(changes) if changes else {}
        log_event(
            self._logger,
            logging.INFO,
            "config_loaded",
            f"config_loaded ({reason})",
            component="config",
        )
        if values:
            self._logger.debug("config changes: %s", values)

    def _reject(self, field: str, policy: ChangePolicy, *, reason: str = "policy") -> None:
        log_event(
            self._logger,
            logging.WARNING,
            "config_rejected",
            f"config_rejected: {field} ({policy.value})",
            component="config",
            error_code="CONFIG_ERROR",
        )
        self._logger.debug("config rejected: field=%s reason=%s", field, reason)
