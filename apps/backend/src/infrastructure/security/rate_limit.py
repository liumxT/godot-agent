"""进程内滑动窗口限流（E2-T10 基础实现）。

E2 明确单进程；引入多 worker 前需替换为共享存储（E2-Q4）。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    """按 key 记录事件时间；窗口外的记录不再计入。"""

    def __init__(
        self,
        max_events: int,
        *,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events 必须大于 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds 必须大于 0")
        self._max_events = max_events
        self._window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateDecision:
        events = self._prune(key)
        if len(events) < self._max_events:
            return RateDecision(True)
        oldest = events[0]
        retry_after = max(1, round(self._window - (self._clock() - oldest)))
        return RateDecision(False, retry_after)

    def record(self, key: str) -> None:
        events = self._prune(key)
        events.append(self._clock())

    def reset(self, key: str) -> None:
        self._events.pop(key, None)

    def count(self, key: str) -> int:
        return len(self._prune(key))

    def _prune(self, key: str) -> deque[float]:
        events = self._events[key]
        threshold = self._clock() - self._window
        while events and events[0] <= threshold:
            events.popleft()
        return events


class ConcurrencyLimiter:
    """进程内并发请求计数（E2-T10）。"""

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent 必须大于 0")
        self._max = max_concurrent
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    @property
    def max_concurrent(self) -> int:
        return self._max

    def try_acquire(self) -> bool:
        if self._active >= self._max:
            return False
        self._active += 1
        return True

    def release(self) -> None:
        if self._active > 0:
            self._active -= 1
