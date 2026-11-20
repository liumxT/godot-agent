"""配置字段变更策略（E1-T02）。"""

from __future__ import annotations

from enum import Enum


class ChangePolicy(str, Enum):
    """运行期修改配置字段时的处理方式。"""

    IMMUTABLE = "IMMUTABLE"
    RESTART_REQUIRED = "RESTART_REQUIRED"
    HOT_RELOAD = "HOT_RELOAD"


FIELD_POLICIES: dict[str, ChangePolicy] = {
    # 决定进程身份与持久化位置，运行期修改会破坏一致性
    "app_name": ChangePolicy.IMMUTABLE,
    "environment": ChangePolicy.IMMUTABLE,
    "database_url": ChangePolicy.IMMUTABLE,
    # 需要重建监听或目录句柄
    "host": ChangePolicy.RESTART_REQUIRED,
    "port": ChangePolicy.RESTART_REQUIRED,
    "data_dir": ChangePolicy.RESTART_REQUIRED,
    "log_dir": ChangePolicy.RESTART_REQUIRED,
    # 可安全热更新
    "log_level": ChangePolicy.HOT_RELOAD,
}

DEFAULT_POLICY = ChangePolicy.RESTART_REQUIRED


def policy_for(field: str) -> ChangePolicy:
    return FIELD_POLICIES.get(field, DEFAULT_POLICY)
