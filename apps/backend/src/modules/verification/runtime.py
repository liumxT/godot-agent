"""Godot Runtime 测试引擎（E9-T08）。

通过可替换的 ``RuntimeDriver`` 与 Godot 运行实例通信。默认实现留空，
由 E3 Runtime/Debug Bridge 或测试替身注入，避免把环境故障伪装成功能通过。

规则：

- 同一 Runtime 实例不允许被并发测试租用；
- 驱动异常一律落为 UNKNOWN，并保留日志与错误原因；
- 测试结束必须停止实例并清理临时状态；
- 断线后可通过 ``query_status`` 查询实际状态。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from modules.verification.models import (
    RUNTIME_COMPLETED,
    RUNTIME_CRASHED,
    RUNTIME_FAILED,
    RUNTIME_TIMEOUT,
    RUNTIME_UNKNOWN,
)


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    """与 RuntimeTestEnvironment 记录对应的运行环境快照。"""

    environment_id: str
    project_id: str
    project_revision: str = ""
    godot_version: str = ""
    platform: str = ""
    display_resolution: str = ""
    renderer: str = ""
    runtime_instance_id: str | None = None
    test_configuration: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeTestSpec:
    test_id: str
    scene: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 120.0
    keep_alive: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeErrorRecord:
    category: str
    severity: str
    message: str
    source: str = ""
    scene: str | None = None
    node: str | None = None
    script: str | None = None
    stack_trace: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "source": self.source,
            "scene": self.scene,
            "node": self.node,
            "script": self.script,
            "stack_trace": self.stack_trace,
        }


@dataclass(frozen=True, slots=True)
class RuntimeExecution:
    status: str
    exit_code: int | None = None
    logs: tuple[str, ...] = ()
    game_state: dict[str, Any] = field(default_factory=dict)
    errors: tuple[RuntimeErrorRecord, ...] = ()
    duration_ms: int = 0
    runtime_instance_id: str | None = None

    def to_report(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "logs": list(self.logs),
            "game_state": self.game_state,
            "errors": [item.to_dict() for item in self.errors],
            "duration_ms": self.duration_ms,
            "runtime_instance_id": self.runtime_instance_id,
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_report(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def failure_reason(self) -> str | None:
        if self.status == RUNTIME_COMPLETED:
            return None
        if self.errors:
            return f"{self.errors[0].category}: {self.errors[0].message}"
        return f"Runtime 测试状态: {self.status}"


class RuntimeDriver(Protocol):
    """Runtime 通信适配器。实现方负责真正的 Godot 进程或 Bridge 调用。"""

    async def launch(self, environment: RuntimeEnvironment) -> str: ...

    async def run(self, runtime_instance_id: str, spec: RuntimeTestSpec) -> RuntimeExecution: ...

    async def status(self, runtime_instance_id: str) -> str: ...

    async def logs(self, runtime_instance_id: str) -> tuple[str, ...]: ...

    async def stop(self, runtime_instance_id: str) -> None: ...


class RuntimeTestEngine:
    """串行、隔离地执行 Runtime 测试。"""

    def __init__(self, driver: RuntimeDriver) -> None:
        self._driver = driver
        self._leased: set[str] = set()

    async def run(self, environment: RuntimeEnvironment, spec: RuntimeTestSpec) -> RuntimeExecution:
        instance_id = environment.runtime_instance_id
        try:
            if instance_id is None:
                instance_id = await self._driver.launch(environment)
        except Exception as exc:  # noqa: BLE001 - 环境故障必须保留为 UNKNOWN
            return self._unknown(spec, None, f"启动 Runtime 失败: {_reason(exc)}")

        if instance_id in self._leased:
            return self._unknown(spec, instance_id, "Runtime 实例正在被其他测试占用，禁止共享")
        self._leased.add(instance_id)
        try:
            execution = await self._driver.run(instance_id, spec)
        except TimeoutError:
            return RuntimeExecution(
                status=RUNTIME_TIMEOUT,
                logs=await self._safe_logs(instance_id),
                duration_ms=int(spec.timeout_seconds * 1000),
                runtime_instance_id=instance_id,
            )
        except Exception as exc:  # noqa: BLE001 - 驱动故障不得判定功能失败
            return self._unknown(spec, instance_id, _reason(exc))
        finally:
            self._leased.discard(instance_id)
            if not spec.keep_alive and environment.runtime_instance_id is None:
                await self._safe_stop(instance_id)

        return RuntimeExecution(
            status=execution.status,
            exit_code=execution.exit_code,
            logs=execution.logs,
            game_state=execution.game_state,
            errors=execution.errors,
            duration_ms=execution.duration_ms,
            runtime_instance_id=instance_id,
        )

    async def query_status(self, runtime_instance_id: str) -> str:
        """断线后查询实际运行状态；查询失败不推测结果。"""

        try:
            return await self._driver.status(runtime_instance_id)
        except Exception:  # noqa: BLE001
            return RUNTIME_UNKNOWN

    async def collect_logs(self, runtime_instance_id: str) -> tuple[str, ...]:
        return await self._safe_logs(runtime_instance_id)

    async def _safe_logs(self, runtime_instance_id: str) -> tuple[str, ...]:
        try:
            return tuple(await self._driver.logs(runtime_instance_id))
        except Exception:  # noqa: BLE001
            return ()

    async def _safe_stop(self, runtime_instance_id: str) -> None:
        try:
            await self._driver.stop(runtime_instance_id)
        except Exception:  # noqa: BLE001 - 清理失败不改变测试结论
            return

    def _unknown(
        self, spec: RuntimeTestSpec, instance_id: str | None, reason: str
    ) -> RuntimeExecution:
        return RuntimeExecution(
            status=RUNTIME_UNKNOWN,
            errors=(
                RuntimeErrorRecord(
                    category="RUNTIME_ERROR",
                    severity="ERROR",
                    message=reason,
                    source="RUNTIME_ENGINE",
                    scene=spec.scene,
                ),
            ),
            duration_ms=0,
            runtime_instance_id=instance_id,
        )


def map_runtime_result(status: str) -> str:
    """Runtime 状态到正式验证结果的保守映射。"""

    if status == RUNTIME_COMPLETED:
        return "PASSED"
    if status in {RUNTIME_FAILED, RUNTIME_TIMEOUT, RUNTIME_CRASHED}:
        return "FAILED"
    return "UNKNOWN"


def _reason(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"
