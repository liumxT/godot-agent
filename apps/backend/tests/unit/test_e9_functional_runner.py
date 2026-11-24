"""E9-T09 功能测试框架单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from core.errors import ValidationFailed
from modules.verification.functional import (
    FunctionalInfrastructureError,
    FunctionalTestRunner,
    FunctionalTestSpec,
)
from modules.verification.models import (
    FUNCTIONAL_BLOCKED,
    FUNCTIONAL_FAILED,
    FUNCTIONAL_INFRASTRUCTURE_ERROR,
    FUNCTIONAL_PASSED,
    FUNCTIONAL_SKIPPED,
    FUNCTIONAL_TEST_KINDS,
    FUNCTIONAL_TIMEOUT,
)


def _spec(**overrides) -> FunctionalTestSpec:
    data = {
        "name": "玩家移动",
        "kind": "GAMEPLAY",
        "steps": ("按下右方向键", "等待 0.2 秒"),
        "expected_result": "玩家 x 坐标增大",
        "timeout_seconds": 1.0,
    }
    data.update(overrides)
    return FunctionalTestSpec(**data)


class FakeHandler:
    def __init__(self) -> None:
        self.setup_calls = 0
        self.cleanup_calls = 0
        self.stepped: list[int] = []
        self.fail_at: int | None = None
        self.raise_at: int | None = None
        self.verify_ok = True
        self.cleanup_error: Exception | None = None
        self.delay = 0.0

    async def setup(self, spec: FunctionalTestSpec) -> None:
        self.setup_calls += 1

    async def step(self, spec: FunctionalTestSpec, index: int, action: str) -> bool:
        self.stepped.append(index)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_at == index:
            raise RuntimeError("动作脚本异常")
        return index != self.fail_at

    async def verify(self, spec: FunctionalTestSpec) -> tuple[bool, str]:
        return self.verify_ok, "" if self.verify_ok else "坐标未变化"

    async def cleanup(self, spec: FunctionalTestSpec) -> None:
        self.cleanup_calls += 1
        if self.cleanup_error is not None:
            raise self.cleanup_error


@pytest.mark.asyncio
async def test_missing_handler_is_blocked_not_passed() -> None:
    execution = await FunctionalTestRunner().run(_spec(), None)
    assert execution.status == FUNCTIONAL_BLOCKED
    assert execution.failure_reason


@pytest.mark.asyncio
async def test_all_steps_pass() -> None:
    handler = FakeHandler()
    execution = await FunctionalTestRunner().run(_spec(), handler)

    assert execution.status == FUNCTIONAL_PASSED
    assert [item.status for item in execution.steps] == ["PASSED", "PASSED"]
    assert handler.setup_calls == handler.cleanup_calls == 1


@pytest.mark.asyncio
async def test_failing_step_is_traced() -> None:
    handler = FakeHandler()
    handler.fail_at = 2
    execution = await FunctionalTestRunner().run(_spec(), handler)

    assert execution.status == FUNCTIONAL_FAILED
    assert execution.failure_step == 2
    assert execution.failure_reason and "第 2 步" in execution.failure_reason
    assert [item.status for item in execution.steps] == ["PASSED", "FAILED"]


@pytest.mark.asyncio
async def test_expected_result_mismatch_fails() -> None:
    handler = FakeHandler()
    handler.verify_ok = False
    execution = await FunctionalTestRunner().run(_spec(), handler)

    assert execution.status == FUNCTIONAL_FAILED
    assert execution.failure_reason == "坐标未变化"


@pytest.mark.asyncio
async def test_step_exception_is_failed_with_step_number() -> None:
    handler = FakeHandler()
    handler.raise_at = 1
    execution = await FunctionalTestRunner().run(_spec(), handler)

    assert execution.status == FUNCTIONAL_FAILED
    assert execution.failure_step == 1


@pytest.mark.asyncio
async def test_timeout_is_not_failed() -> None:
    handler = FakeHandler()
    handler.delay = 0.2
    execution = await FunctionalTestRunner().run(_spec(timeout_seconds=0.05), handler)

    assert execution.status == FUNCTIONAL_TIMEOUT
    assert execution.failure_step == 1
    assert handler.cleanup_calls == 1


@pytest.mark.asyncio
async def test_infrastructure_error_is_not_functional_failure() -> None:
    class BrokenHandler(FakeHandler):
        async def step(self, spec, index, action):
            raise FunctionalInfrastructureError("bridge 断开")

    execution = await FunctionalTestRunner().run(_spec(), BrokenHandler())

    assert execution.status == FUNCTIONAL_INFRASTRUCTURE_ERROR
    assert execution.steps[0].status == "UNKNOWN"


@pytest.mark.asyncio
async def test_cleanup_failure_is_recorded_without_flipping_result() -> None:
    handler = FakeHandler()
    handler.cleanup_error = RuntimeError("节点已释放")
    execution = await FunctionalTestRunner().run(_spec(), handler)

    assert execution.status == FUNCTIONAL_PASSED
    assert execution.cleanup_errors == ("节点已释放",)


@pytest.mark.asyncio
async def test_empty_test_cannot_be_reported_passed() -> None:
    execution = await FunctionalTestRunner().run(
        _spec(steps=(), expected_result=""), FakeHandler()
    )
    assert execution.status == FUNCTIONAL_SKIPPED


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        FunctionalTestSpec(name="x", kind="LOAD")
    assert "GAMEPLAY" in FUNCTIONAL_TEST_KINDS
