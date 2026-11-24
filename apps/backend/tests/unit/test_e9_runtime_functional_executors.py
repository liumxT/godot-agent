"""E9-T08/T09 Runtime 与 Functional 执行器单元测试。"""

from __future__ import annotations

import pytest

from modules.verification.functional import FunctionalTestRunner, FunctionalTestSpec
from modules.verification.godot.executors import (
    FunctionalTestExecutor,
    RuntimeTestExecutor,
)
from modules.verification.runtime import (
    RuntimeEnvironment,
    RuntimeExecution,
    RuntimeTestEngine,
    RuntimeTestSpec,
)


class Driver:
    def __init__(self, execution: RuntimeExecution) -> None:
        self.execution = execution
        self.stopped: list[str] = []

    async def launch(self, environment: RuntimeEnvironment) -> str:
        return "inst_1"

    async def run(self, runtime_instance_id: str, spec: RuntimeTestSpec) -> RuntimeExecution:
        return self.execution

    async def status(self, runtime_instance_id: str) -> str:
        return self.execution.status

    async def logs(self, runtime_instance_id: str) -> tuple[str, ...]:
        return self.execution.logs

    async def stop(self, runtime_instance_id: str) -> None:
        self.stopped.append(runtime_instance_id)


_ENV = RuntimeEnvironment(environment_id="vre_1", project_id="proj_1")


@pytest.mark.asyncio
async def test_runtime_executor_passes_completed_execution() -> None:
    driver = Driver(RuntimeExecution(status="COMPLETED", exit_code=0, logs=("ok",)))
    executor = RuntimeTestExecutor(
        RuntimeTestEngine(driver), _ENV, RuntimeTestSpec(test_id="t1")
    )

    outcome = await executor(None)  # type: ignore[arg-type]

    assert outcome.result_status == "PASSED"
    assert outcome.execution_status == "COMPLETED"
    assert outcome.evidence[0].evidence_type == "RUNTIME_TRACE"
    assert outcome.evidence[0].source_type == "GODOT_RUNTIME"


@pytest.mark.asyncio
async def test_runtime_executor_unknown_stays_unknown() -> None:
    class BrokenDriver(Driver):
        async def run(self, runtime_instance_id, spec):
            raise RuntimeError("bridge down")

    executor = RuntimeTestExecutor(
        RuntimeTestEngine(BrokenDriver(RuntimeExecution(status="COMPLETED"))),
        _ENV,
        RuntimeTestSpec(test_id="t1"),
    )

    outcome = await executor(None)  # type: ignore[arg-type]

    assert outcome.result_status == "UNKNOWN"
    assert outcome.execution_status == "UNKNOWN"
    assert outcome.evidence


class Handler:
    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at = fail_at
        self.cleaned = 0

    async def setup(self, spec):
        return None

    async def step(self, spec, index, action):
        return index != self.fail_at

    async def verify(self, spec):
        return True, ""

    async def cleanup(self, spec):
        self.cleaned += 1


def _spec() -> FunctionalTestSpec:
    return FunctionalTestSpec(
        name="move",
        kind="GAMEPLAY",
        steps=("press", "wait"),
        expected_result="x increased",
        timeout_seconds=1,
    )


@pytest.mark.asyncio
async def test_functional_executor_passes() -> None:
    executor = FunctionalTestExecutor(FunctionalTestRunner(), _spec(), Handler())
    outcome = await executor(None)  # type: ignore[arg-type]

    assert outcome.result_status == "PASSED"
    assert outcome.evidence[0].evidence_type == "TEST_REPORT"
    assert outcome.evidence[0].metadata["report"]["status"] == "PASSED"


@pytest.mark.asyncio
async def test_functional_executor_failure_keeps_step_and_evidence() -> None:
    executor = FunctionalTestExecutor(FunctionalTestRunner(), _spec(), Handler(fail_at=2))
    outcome = await executor(None)  # type: ignore[arg-type]

    assert outcome.result_status == "FAILED"
    assert "第 2 步" in (outcome.failure_reason or "")
    assert outcome.evidence


@pytest.mark.asyncio
async def test_functional_executor_blocked_is_not_passed() -> None:
    executor = FunctionalTestExecutor(FunctionalTestRunner(), _spec(), None)
    outcome = await executor(None)  # type: ignore[arg-type]

    assert outcome.result_status == "NOT_RUN"
    assert outcome.execution_status == "UNKNOWN"
    assert outcome.details["functional_status"] == "BLOCKED"
