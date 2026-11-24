"""E9-T08 Runtime 引擎单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from modules.verification.models import (
    RUNTIME_COMPLETED,
    RUNTIME_CRASHED,
    RUNTIME_FAILED,
    RUNTIME_TIMEOUT,
    RUNTIME_UNKNOWN,
)
from modules.verification.runtime import (
    RuntimeEnvironment,
    RuntimeErrorRecord,
    RuntimeExecution,
    RuntimeTestEngine,
    RuntimeTestSpec,
    map_runtime_result,
)

_ENV = RuntimeEnvironment(
    environment_id="vre_1",
    project_id="proj_1",
    project_revision="rev-1",
    godot_version="4.3",
    platform="windows",
    display_resolution="1920x1080",
    renderer="vulkan",
)


class FakeDriver:
    def __init__(self, execution: RuntimeExecution | None = None) -> None:
        self.execution = execution or RuntimeExecution(
            status=RUNTIME_COMPLETED, exit_code=0, logs=("ready", "done")
        )
        self.launched: list[str] = []
        self.stopped: list[str] = []
        self.run_error: Exception | None = None
        self.launch_error: Exception | None = None
        self.status_error: bool = False

    async def launch(self, environment: RuntimeEnvironment) -> str:
        if self.launch_error is not None:
            raise self.launch_error
        instance = f"inst_{len(self.launched) + 1}"
        self.launched.append(instance)
        return instance

    async def run(self, runtime_instance_id: str, spec: RuntimeTestSpec) -> RuntimeExecution:
        if self.run_error is not None:
            raise self.run_error
        return self.execution

    async def status(self, runtime_instance_id: str) -> str:
        if self.status_error:
            raise RuntimeError("bridge down")
        return RUNTIME_COMPLETED

    async def logs(self, runtime_instance_id: str) -> tuple[str, ...]:
        return ("log-a",)

    async def stop(self, runtime_instance_id: str) -> None:
        self.stopped.append(runtime_instance_id)


@pytest.mark.asyncio
async def test_engine_launches_runs_and_stops() -> None:
    driver = FakeDriver()
    engine = RuntimeTestEngine(driver)

    execution = await engine.run(_ENV, RuntimeTestSpec(test_id="t1"))

    assert execution.status == RUNTIME_COMPLETED
    assert execution.runtime_instance_id == "inst_1"
    assert driver.launched == ["inst_1"]
    assert driver.stopped == ["inst_1"]


@pytest.mark.asyncio
async def test_launch_failure_is_unknown_not_failed() -> None:
    driver = FakeDriver()
    driver.launch_error = RuntimeError("godot missing")
    engine = RuntimeTestEngine(driver)

    execution = await engine.run(_ENV, RuntimeTestSpec(test_id="t1"))

    assert execution.status == RUNTIME_UNKNOWN
    assert "godot missing" in execution.failure_reason()


@pytest.mark.asyncio
async def test_driver_failure_is_unknown_and_keeps_logs() -> None:
    driver = FakeDriver()
    driver.run_error = RuntimeError("connection reset")
    engine = RuntimeTestEngine(driver)

    execution = await engine.run(_ENV, RuntimeTestSpec(test_id="t1"))

    assert execution.status == RUNTIME_UNKNOWN
    assert execution.errors[0].category == "RUNTIME_ERROR"
    assert execution.runtime_instance_id == "inst_1"
    assert driver.stopped == ["inst_1"]


@pytest.mark.asyncio
async def test_shared_instance_is_rejected_while_leased() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowDriver(FakeDriver):
        async def run(self, runtime_instance_id: str, spec: RuntimeTestSpec):
            entered.set()
            await release.wait()
            return RuntimeExecution(status=RUNTIME_COMPLETED)

    driver = SlowDriver()
    engine = RuntimeTestEngine(driver)
    environment = RuntimeEnvironment(
        environment_id="vre_2",
        project_id="proj_1",
        runtime_instance_id="inst_shared",
    )

    first = asyncio.create_task(engine.run(environment, RuntimeTestSpec(test_id="a")))
    await entered.wait()
    second = await engine.run(environment, RuntimeTestSpec(test_id="b"))
    release.set()
    first_result = await first

    assert first_result.status == RUNTIME_COMPLETED
    assert second.status == RUNTIME_UNKNOWN
    assert "占用" in second.failure_reason()
    # 外部实例由调用方管理，结束时不得擅自停止
    assert driver.stopped == []


@pytest.mark.asyncio
async def test_query_status_failure_is_unknown() -> None:
    driver = FakeDriver()
    driver.status_error = True
    engine = RuntimeTestEngine(driver)

    assert await engine.query_status("inst_1") == RUNTIME_UNKNOWN


def test_map_runtime_result_is_conservative() -> None:
    assert map_runtime_result(RUNTIME_COMPLETED) == "PASSED"
    for status in (RUNTIME_FAILED, RUNTIME_TIMEOUT, RUNTIME_CRASHED):
        assert map_runtime_result(status) == "FAILED"
    assert map_runtime_result(RUNTIME_UNKNOWN) == "UNKNOWN"
    assert map_runtime_result("WHATEVER") == "UNKNOWN"


def test_runtime_execution_hash_is_stable() -> None:
    execution = RuntimeExecution(
        status=RUNTIME_COMPLETED,
        logs=("a",),
        errors=(RuntimeErrorRecord(category="RUNTIME_ERROR", severity="ERROR", message="x"),),
    )
    assert execution.content_hash() == execution.content_hash()
    assert len(execution.content_hash()) == 64
