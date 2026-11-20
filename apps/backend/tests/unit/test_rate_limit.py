"""进程内滑动窗口限流测试（E2-T03 / T10）。"""

from __future__ import annotations

from infrastructure.security.rate_limit import SlidingWindowRateLimiter


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_allows_up_to_limit_then_blocks() -> None:
    clock = _Clock()
    limiter = SlidingWindowRateLimiter(2, window_seconds=60, clock=clock)

    assert limiter.check("cli_a").allowed
    limiter.record("cli_a")
    assert limiter.check("cli_a").allowed
    limiter.record("cli_a")

    decision = limiter.check("cli_a")
    assert decision.allowed is False
    assert decision.retry_after_seconds >= 1


def test_window_slides() -> None:
    clock = _Clock()
    limiter = SlidingWindowRateLimiter(1, window_seconds=60, clock=clock)
    limiter.record("cli_a")

    clock.advance(59)
    assert not limiter.check("cli_a").allowed

    clock.advance(1)
    assert limiter.check("cli_a").allowed


def test_reset_clears_key() -> None:
    clock = _Clock()
    limiter = SlidingWindowRateLimiter(1, clock=clock)
    limiter.record("cli_a")

    limiter.reset("cli_a")

    assert limiter.count("cli_a") == 0
    assert limiter.check("cli_a").allowed


def test_keys_are_independent() -> None:
    clock = _Clock()
    limiter = SlidingWindowRateLimiter(1, clock=clock)
    limiter.record("cli_a")

    assert limiter.check("cli_b").allowed
