"""工具 Adapter 协议与注册表（E5-T22）。

Adapter 是执行引擎与具体执行环境（Godot Editor、文件系统等）之间的唯一边界。
Adapter 只负责执行与观测，不由它判断最终验证结论；验证由
``ToolVerificationService`` 基于 Adapter 返回的检查项与证据给出。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from modules.tool.models import (
    EXECUTION_CANCELLED,
    EXECUTION_FAILED,
    EXECUTION_SUCCEEDED,
    EXECUTION_TIMEOUT,
    EXECUTION_UNKNOWN,
)
from modules.tool.registry import ToolView

ADAPTER_RESULT_STATUSES = frozenset(
    {EXECUTION_SUCCEEDED, EXECUTION_FAILED, EXECUTION_CANCELLED, EXECUTION_TIMEOUT, EXECUTION_UNKNOWN}
)


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    """Adapter 观测到的一项后置检查；``passed`` 为 ``None`` 表示无法判断。"""

    name: str
    passed: bool | None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ToolDispatchContext:
    """派发给 Adapter 的执行上下文；不包含审批对象等内部句柄。"""

    execution_id: str
    project_id: str
    tool_id: str
    tool_name: str
    tool_version: int
    input: Mapping[str, Any]
    session_id: str | None = None
    task_id: str | None = None
    attempt_id: str | None = None
    resource_scope: tuple[str, ...] = ()
    fencing_token: int | None = None
    timeout_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Adapter 执行结果；``checks`` 与 ``evidence_refs`` 用于后置验证与恢复。"""

    status: str
    output: Mapping[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    checks: tuple[VerificationCheck, ...] = ()
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in ADAPTER_RESULT_STATUSES:
            raise ValueError(f"AdapterResult.status 非法: {self.status}")


@runtime_checkable
class ToolAdapter(Protocol):
    """执行 Adapter 协议。``inspect`` 用于执行结果核验与中断恢复。"""

    name: str

    def supports(self, tool: ToolView) -> bool:  # pragma: no cover - 协议声明
        ...

    async def execute(self, context: ToolDispatchContext) -> AdapterResult:  # pragma: no cover
        ...

    async def inspect(self, context: ToolDispatchContext) -> AdapterResult | None:  # pragma: no cover
        ...


class ToolAdapterRegistry:
    """按工具定义解析 Adapter；同一工具只能命中第一个匹配项。"""

    def __init__(self) -> None:
        self._adapters: list[ToolAdapter] = []

    def register(self, adapter: ToolAdapter) -> None:
        if any(existing.name == adapter.name for existing in self._adapters):
            raise ValueError(f"Adapter 名称重复: {adapter.name}")
        self._adapters.append(adapter)

    def get(self, name: str) -> ToolAdapter | None:
        return next((adapter for adapter in self._adapters if adapter.name == name), None)

    def resolve(self, tool: ToolView) -> ToolAdapter | None:
        return next((adapter for adapter in self._adapters if adapter.supports(tool)), None)

    def names(self) -> tuple[str, ...]:
        return tuple(adapter.name for adapter in self._adapters)


__all__ = [
    "AdapterResult",
    "ToolAdapter",
    "ToolAdapterRegistry",
    "ToolDispatchContext",
    "VerificationCheck",
]
