"""功能测试框架（E9-T09）。

支持 Unit / Integration / Gameplay / End-to-End 四类测试。执行过程必须：

- 记录每一步的实际状态，失败时能定位具体步骤；
- 超时不等于失败，归为 TIMEOUT；
- 缺少执行器时为 BLOCKED，绝不假装通过；
- cleanup 无论成败都要执行，清理失败只记录不改变测试结论。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from core.errors import ValidationFailed
from modules.verification.models import (
    FUNCTIONAL_BLOCKED,
    FUNCTIONAL_FAILED,
    FUNCTIONAL_INFRASTRUCTURE_ERROR,
    FUNCTIONAL_PASSED,
    FUNCTIONAL_SKIPPED,
    FUNCTIONAL_TEST_KINDS,
    FUNCTIONAL_TIMEOUT,
)


class FunctionalInfrastructureError(RuntimeError):
    """执行器自身或环境故障；不得据此判定游戏功能失败。"""


@dataclass(frozen=True, slots=True)
class FunctionalTestSpec:
    name: str
    kind: str
    steps: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    setup: tuple[str, ...] = ()
    expected_result: str = ""
    cleanup: tuple[str, ...] = ()
    timeout_seconds: float = 300.0
    evidence_requirements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in FUNCTIONAL_TEST_KINDS:
            raise ValidationFailed(
                "未知功能测试类型",
                details={"kind": self.kind, "allowed": sorted(FUNCTIONAL_TEST_KINDS)},
            )
        if not self.name.strip():
            raise ValidationFailed("功能测试必须包含名称")
        if self.timeout_seconds <= 0:
            raise ValidationFailed("功能测试超时必须大于 0")


@dataclass(frozen=True, slots=True)
class FunctionalStepResult:
    index: int
    action: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class FunctionalExecution:
    status: str
    steps: tuple[FunctionalStepResult, ...] = ()
    failure_step: int | None = None
    failure_reason: str | None = None
    cleanup_errors: tuple[str, ...] = ()
    duration_ms: int = 0

    def to_report(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "steps": [item.to_dict() for item in self.steps],
            "failure_step": self.failure_step,
            "failure_reason": self.failure_reason,
            "cleanup_errors": list(self.cleanup_errors),
            "duration_ms": self.duration_ms,
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_report(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FunctionalStepHandler(Protocol):
    """由 Agent / E3 Bridge / 测试替身实现的具体动作。"""

    async def setup(self, spec: FunctionalTestSpec) -> None: ...

    async def step(self, spec: FunctionalTestSpec, index: int, action: str) -> bool: ...

    async def verify(self, spec: FunctionalTestSpec) -> tuple[bool, str]: ...

    async def cleanup(self, spec: FunctionalTestSpec) -> None: ...


class FunctionalTestRunner:
    """可重复执行的功能测试运行器；自身不保存状态。"""

    async def run(
        self,
        spec: FunctionalTestSpec,
        handler: FunctionalStepHandler | None,
    ) -> FunctionalExecution:
        started = asyncio.get_running_loop().time()
        if handler is None:
            return FunctionalExecution(
                status=FUNCTIONAL_BLOCKED,
                failure_reason="缺少功能测试执行器，未执行",
            )

        steps: list[FunctionalStepResult] = []
        cleanup_errors: list[str] = []
        status = FUNCTIONAL_PASSED
        failure_step: int | None = None
        failure_reason: str | None = None

        try:
            async with asyncio.timeout(spec.timeout_seconds):
                try:
                    await handler.setup(spec)
                except FunctionalInfrastructureError as exc:
                    status = FUNCTIONAL_INFRASTRUCTURE_ERROR
                    failure_reason = f"环境准备失败: {exc}"
                    return self._result(
                        status, steps, cleanup_errors, started, None, failure_reason
                    )
                except Exception as exc:  # noqa: BLE001
                    status = FUNCTIONAL_FAILED
                    failure_reason = f"setup 失败: {exc}"
                    return self._result(
                        status, steps, cleanup_errors, started, None, failure_reason
                    )

                for index, action in enumerate(spec.steps, start=1):
                    try:
                        passed = await handler.step(spec, index, action)
                    except FunctionalInfrastructureError as exc:
                        status = FUNCTIONAL_INFRASTRUCTURE_ERROR
                        failure_step = index
                        failure_reason = f"第 {index} 步环境故障: {exc}"
                        steps.append(
                            FunctionalStepResult(index, action, "UNKNOWN", str(exc))
                        )
                        break
                    except Exception as exc:  # noqa: BLE001
                        status = FUNCTIONAL_FAILED
                        failure_step = index
                        failure_reason = f"第 {index} 步异常: {exc}"
                        steps.append(
                            FunctionalStepResult(index, action, "FAILED", str(exc))
                        )
                        break
                    if not passed:
                        status = FUNCTIONAL_FAILED
                        failure_step = index
                        failure_reason = f"第 {index} 步未通过: {action}"
                        steps.append(FunctionalStepResult(index, action, "FAILED"))
                        break
                    steps.append(FunctionalStepResult(index, action, "PASSED"))

                if status == FUNCTIONAL_PASSED:
                    try:
                        satisfied, detail = await handler.verify(spec)
                    except FunctionalInfrastructureError as exc:
                        status = FUNCTIONAL_INFRASTRUCTURE_ERROR
                        failure_reason = f"结果校验环境故障: {exc}"
                    except Exception as exc:  # noqa: BLE001
                        status = FUNCTIONAL_FAILED
                        failure_reason = f"结果校验异常: {exc}"
                    else:
                        if not satisfied:
                            status = FUNCTIONAL_FAILED
                            failure_reason = detail or "预期结果未满足"
        except TimeoutError:
            status = FUNCTIONAL_TIMEOUT
            failure_reason = f"测试超过 {spec.timeout_seconds} 秒"
            failure_step = len(steps) + 1 if steps else 1
        finally:
            try:
                await handler.cleanup(spec)
            except Exception as exc:  # noqa: BLE001
                cleanup_errors.append(str(exc))

        if status == FUNCTIONAL_PASSED and not spec.steps and not spec.expected_result:
            # 没有任何步骤和预期时不能宣布通过
            status = FUNCTIONAL_SKIPPED
            failure_reason = "测试未定义步骤或预期结果，未形成有效验证"

        return self._result(
            status, steps, cleanup_errors, started, failure_step, failure_reason
        )

    def _result(
        self,
        status: str,
        steps: list[FunctionalStepResult],
        cleanup_errors: list[str],
        started: float,
        failure_step: int | None,
        failure_reason: str | None,
    ) -> FunctionalExecution:
        elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
        return FunctionalExecution(
            status=status,
            steps=tuple(steps),
            failure_step=failure_step,
            failure_reason=failure_reason,
            cleanup_errors=tuple(cleanup_errors),
            duration_ms=max(elapsed, 0),
        )
