"""工具幂等键（E5-T23）。

幂等键由项目、任务、尝试、工具与逻辑操作共同决定，保证断线重试或重复请求
不会产生重复的项目修改。键本身不含敏感信息，长度固定为 64。
"""

from __future__ import annotations

import hashlib
import json

__all__ = ["build_idempotency_key"]


def build_idempotency_key(
    *,
    project_id: str,
    tool_id: str,
    logical_operation_id: str,
    task_id: str | None = None,
    attempt_id: str | None = None,
) -> str:
    if not project_id.strip() or not tool_id.strip() or not logical_operation_id.strip():
        raise ValueError("project_id、tool_id 与 logical_operation_id 不能为空")
    payload = {
        "project_id": project_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "tool_id": tool_id,
        "logical_operation_id": logical_operation_id,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
