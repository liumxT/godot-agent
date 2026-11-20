"""服务注册表：启动步骤登记服务，其余组件按名获取。"""

from __future__ import annotations

from typing import Any, TypeVar

from core.errors import StartupError

T = TypeVar("T")


class ServiceRegistry:
    """按名称持有 Core 服务实例。

    只在启动阶段注册；重复注册视为装配错误，避免后注册者悄悄覆盖。
    """

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        if name in self._services:
            raise StartupError("服务重复注册", details={"service": name})
        self._services[name] = service

    def get(self, name: str, expected_type: type[T] | None = None) -> T:
        if name not in self._services:
            raise StartupError("服务未注册", details={"service": name})
        service = self._services[name]
        if expected_type is not None and not isinstance(service, expected_type):
            raise StartupError(
                "服务类型不匹配",
                details={
                    "service": name,
                    "expected": expected_type.__name__,
                    "actual": type(service).__name__,
                },
            )
        return service

    def try_get(self, name: str) -> Any | None:
        return self._services.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._services)

    def clear(self) -> None:
        self._services.clear()
