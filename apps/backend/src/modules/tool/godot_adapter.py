"""Godot Editor 工具 Adapter（E5-T28）。

所有 Godot 工具都必须经 Editor Plugin 的真实 Editor API 执行，
本 Adapter 只负责把工具调用转成 ``editor.command.execute`` 命令帧。
命令超时只说明结果未知，不能据此宣布失败或重复执行。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from core.errors import EditorCommandTimeout, EditorNotConnected
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from modules.editor_command.hub import (
    EDITOR_COMMAND_ACTION,
    EditorCommandHub,
    EditorCommandResponse,
)
from modules.tool.adapters import AdapterResult, ToolDispatchContext, VerificationCheck
from modules.tool.models import EXECUTION_FAILED, EXECUTION_SUCCEEDED, EXECUTION_UNKNOWN
from modules.tool.registry import ToolView

GODOT_ADAPTER_CATEGORIES = frozenset(
    {
        "GODOT_EDITOR",
        "GODOT_RUNTIME",
        "SCENE",
        "NODE",
        "INSPECTOR",
        "SIGNAL",
        "GROUP",
        "ANIMATION",
        "TILEMAP",
        "RESOURCE",
        "DEBUG",
    }
)

PHASE_EXECUTE = "EXECUTE"
PHASE_INSPECT = "INSPECT"

__all__ = ["GODOT_ADAPTER_CATEGORIES", "GodotToolAdapter"]


class GodotToolAdapter:
    """通过 Editor WebSocket 命令通道执行 Godot 工具。"""

    name = "godot_editor"

    def __init__(
        self,
        hub: EditorCommandHub,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._hub = hub
        self._clock = clock
        self._logger = get_logger("backend.tool.godot")

    def supports(self, tool: ToolView) -> bool:
        return tool.category in GODOT_ADAPTER_CATEGORIES

    async def execute(self, context: ToolDispatchContext) -> AdapterResult:
        connection = self._hub.get(context.session_id or "")
        if connection is None:
            return AdapterResult(
                status=EXECUTION_FAILED,
                error_code="EDITOR_NOT_CONNECTED",
                error_message="编辑器未连接，无法执行 Godot 工具",
                checks=(VerificationCheck("editor_connected", False, "session 未建立命令通道"),),
            )
        try:
            response = await connection.send_command(
                EDITOR_COMMAND_ACTION,
                self._payload(context, PHASE_EXECUTE),
                timeout=context.timeout_seconds,
            )
        except EditorCommandTimeout as exc:
            return AdapterResult(
                status=EXECUTION_UNKNOWN,
                error_code=exc.code,
                error_message=str(exc),
                checks=(VerificationCheck("editor_response", None, "命令超时，结果未知"),),
            )
        except EditorNotConnected as exc:
            return AdapterResult(
                status=EXECUTION_FAILED,
                error_code=exc.code,
                error_message=str(exc),
                checks=(VerificationCheck("editor_connected", False, str(exc)),),
            )
        return self._parse(response)

    async def inspect(self, context: ToolDispatchContext) -> AdapterResult | None:
        connection = self._hub.get(context.session_id or "")
        if connection is None:
            return None
        try:
            response = await connection.send_command(
                EDITOR_COMMAND_ACTION,
                self._payload(context, PHASE_INSPECT),
                timeout=context.timeout_seconds,
            )
        except (EditorCommandTimeout, EditorNotConnected):
            return None
        if not response.success:
            return None
        return self._parse(response)

    @staticmethod
    def _payload(context: ToolDispatchContext, phase: str) -> dict[str, Any]:
        return {
            "execution_id": context.execution_id,
            "tool_name": context.tool_name,
            "tool_version": context.tool_version,
            "arguments": dict(context.input),
            "resource_scope": list(context.resource_scope),
            "fencing_token": context.fencing_token,
            "phase": phase,
        }

    def _parse(self, response: EditorCommandResponse) -> AdapterResult:
        if not response.success:
            error = response.error or {}
            code = str(error.get("code") or "EDITOR_COMMAND_FAILED")
            message = str(error.get("message") or "编辑器命令执行失败")
            log_event(
                self._logger,
                logging.WARNING,
                "editor_command_failed",
                component="tool",
                error_code=code,
            )
            return AdapterResult(
                status=EXECUTION_FAILED,
                error_code=code,
                error_message=message[:512],
                checks=(VerificationCheck("editor_success", False, message),),
            )
        data = response.data
        status = str(data.get("status") or EXECUTION_SUCCEEDED)
        if status not in (EXECUTION_SUCCEEDED, EXECUTION_FAILED, EXECUTION_UNKNOWN):
            status = EXECUTION_SUCCEEDED
        output = data.get("output")
        checks = _checks(data.get("checks"))
        evidence = _strings(data.get("evidence_refs"))
        return AdapterResult(
            status=status,
            output=output if isinstance(output, Mapping) else None,
            error_code=str(data.get("error_code")) if data.get("error_code") else None,
            error_message=str(data.get("error_message")) if data.get("error_message") else None,
            checks=checks,
            evidence_refs=evidence,
        )


def _checks(raw: Any) -> tuple[VerificationCheck, ...]:
    if not isinstance(raw, list):
        return ()
    checks: list[VerificationCheck] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        passed = item.get("passed")
        detail = item.get("detail")
        checks.append(
            VerificationCheck(
                name=name,
                passed=passed if isinstance(passed, bool) else None,
                detail=str(detail)[:256] if detail else None,
            )
        )
    return tuple(checks)


def _strings(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(str(item)[:512] for item in raw if isinstance(item, str) and item)
