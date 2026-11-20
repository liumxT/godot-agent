"""Bridge 进程内计数（E3-T12 / T13 / T20）。

只用于诊断摘要，不落库、不引入外部监控依赖。计数在同一事件循环内自增，
无需额外加锁；``connections`` 为当前活动连接数，其余为累计值。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BridgeMetrics:
    connections: int = 0
    recovery_success: int = 0
    recovery_failed: int = 0
    fencing_rejections: int = 0

    def connection_opened(self) -> None:
        self.connections += 1

    def connection_closed(self) -> None:
        self.connections = max(0, self.connections - 1)

    def recovery_succeeded(self) -> None:
        self.recovery_success += 1

    def recovery_failed_count(self) -> None:
        self.recovery_failed += 1

    def fencing_rejected(self) -> None:
        self.fencing_rejections += 1

    def snapshot(self) -> dict[str, int]:
        return {
            "connections": self.connections,
            "recovery_success": self.recovery_success,
            "recovery_failed": self.recovery_failed,
            "fencing_rejections": self.fencing_rejections,
        }
