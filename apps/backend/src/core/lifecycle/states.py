"""生命周期状态定义。

正常路径：``CREATED → INITIALIZING → STARTING → RUNNING → STOPPING → STOPPED``。
启动或运行期异常进入 ``FAILED``；未启动即关闭允许 ``CREATED → STOPPED``。
"""

from __future__ import annotations

from enum import Enum


class LifecycleState(str, Enum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.CREATED: frozenset({LifecycleState.INITIALIZING, LifecycleState.STOPPED}),
    LifecycleState.INITIALIZING: frozenset(
        {LifecycleState.STARTING, LifecycleState.STOPPING, LifecycleState.FAILED}
    ),
    LifecycleState.STARTING: frozenset(
        {LifecycleState.RUNNING, LifecycleState.STOPPING, LifecycleState.FAILED}
    ),
    LifecycleState.RUNNING: frozenset({LifecycleState.STOPPING, LifecycleState.FAILED}),
    LifecycleState.STOPPING: frozenset({LifecycleState.STOPPED, LifecycleState.FAILED}),
    LifecycleState.STOPPED: frozenset(),
    LifecycleState.FAILED: frozenset({LifecycleState.STOPPING, LifecycleState.STOPPED}),
}


def can_transition(current: LifecycleState, target: LifecycleState) -> bool:
    return target in _TRANSITIONS[current]
