"""模型响应到结构化 Agent Action 的严格解析（E6-T07 Step 6）。

只接受结构化 JSON（或单个 Tool Call），不接受把任意模型文本直接当成可执行命令。
解析失败一律抛出 ``AgentActionInvalid``，由执行循环按失败处理。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.errors import AgentActionInvalid
from modules.agent_runtime.models import (
    ACTION_ANALYZE,
    ACTION_COMPLETE_EXECUTION,
    ACTION_CREATE_PLAN,
    ACTION_EXECUTE_TOOL,
    ACTION_FAIL_EXECUTION,
    ACTION_REPORT_PROGRESS,
    ACTION_REQUEST_APPROVAL,
    ACTION_REQUEST_USER_INPUT,
    ACTION_UPDATE_PLAN,
    AGENT_ACTION_TYPES,
    STEP_TYPES,
)
from modules.model_gateway.schemas import ModelResponse


@dataclass(frozen=True, slots=True)
class AgentAction:
    action_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)


def _invalid(message: str, **details: Any) -> AgentActionInvalid:
    return AgentActionInvalid(message, details=details)


def _text(payload: Mapping[str, Any], key: str, action: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(
            f"{action} 缺少必需字段 {key}", action=action, field=key
        )
    return value.strip()


def _normalize_steps(payload: Mapping[str, Any], action: str) -> list[dict[str, Any]]:
    raw = payload.get("steps")
    if not isinstance(raw, list) or not raw:
        raise _invalid("计划必须包含至少一个 Step", action=action, field="steps")
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise _invalid("Step 必须是对象", action=action, index=index)
        step_type = str(item.get("type", "")).strip().upper()
        if step_type not in STEP_TYPES:
            raise _invalid(
                "未知的 Step 类型", action=action, index=index, step_type=step_type
            )
        description = str(item.get("description", "")).strip()
        if not description:
            raise _invalid("Step 描述不能为空", action=action, index=index)
        raw_dependencies = item.get("dependencies", [])
        if not isinstance(raw_dependencies, list):
            raise _invalid("Step 依赖必须是数组", action=action, index=index)
        dependencies: list[int] = []
        for dependency in raw_dependencies:
            try:
                number = int(dependency)
            except (TypeError, ValueError) as exc:
                raise _invalid(
                    "Step 依赖必须是 Step 序号", action=action, index=index
                ) from exc
            if number < 1 or number >= index:
                raise _invalid(
                    "Step 依赖必须指向更早的 Step",
                    action=action,
                    index=index,
                    dependency=number,
                )
            dependencies.append(number)
        steps.append(
            {
                "type": step_type,
                "description": description,
                "dependencies": dependencies,
            }
        )
    return steps


class AgentResponseParser:
    """把模型响应转换成受控的 Agent Action。"""

    def parse(self, response: ModelResponse) -> AgentAction:
        payload = self._payload(response)
        raw_action = payload.get("action")
        if not isinstance(raw_action, str):
            raise _invalid("模型响应缺少 action 字段")
        action = raw_action.strip().upper()
        if action not in AGENT_ACTION_TYPES:
            raise _invalid("未知的 Agent Action", action=action)

        normalized: dict[str, Any] = {"action": action}
        if action == ACTION_EXECUTE_TOOL:
            normalized["tool"] = _text(payload, "tool", action)
            tool_input = payload.get("input", {})
            if not isinstance(tool_input, Mapping):
                raise _invalid("工具输入必须是对象", action=action, field="input")
            normalized["input"] = dict(tool_input)
            scope = payload.get("resource_scope", [])
            if not isinstance(scope, list) or any(
                not isinstance(item, str) for item in scope
            ):
                raise _invalid("resource_scope 必须是字符串数组", action=action)
            normalized["resource_scope"] = list(scope)
            approval_id = payload.get("approval_id")
            if approval_id is not None and not isinstance(approval_id, str):
                raise _invalid("approval_id 必须是字符串", action=action)
            normalized["approval_id"] = approval_id
        elif action in {ACTION_CREATE_PLAN, ACTION_UPDATE_PLAN}:
            normalized["objective"] = _text(payload, "objective", action)
            normalized["steps"] = _normalize_steps(payload, action)
        elif action == ACTION_FAIL_EXECUTION:
            normalized["reason"] = _text(payload, "reason", action)
        elif action == ACTION_REQUEST_USER_INPUT:
            normalized["question"] = _text(payload, "question", action)
        elif action == ACTION_COMPLETE_EXECUTION:
            summary = payload.get("summary")
            normalized["summary"] = summary.strip() if isinstance(summary, str) else None
        elif action == ACTION_REQUEST_APPROVAL:
            reason = payload.get("reason")
            normalized["reason"] = reason.strip() if isinstance(reason, str) else None
        elif action in {ACTION_ANALYZE, ACTION_REPORT_PROGRESS}:
            summary = payload.get("summary")
            normalized["summary"] = summary.strip() if isinstance(summary, str) else None
        return AgentAction(action_type=action, payload=normalized)

    @staticmethod
    def _payload(response: ModelResponse) -> Mapping[str, Any]:
        content = (response.content or "").strip()
        if content:
            text = content
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.rstrip().endswith("```"):
                    text = text.rstrip()[:-3]
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise _invalid(
                    "模型响应不是合法 JSON", reason=str(exc), status=response.status
                ) from exc
            if not isinstance(data, Mapping):
                raise _invalid("模型响应必须是 JSON 对象")
            return data
        if response.tool_calls:
            if len(response.tool_calls) != 1:
                raise _invalid(
                    "一次只允许一个 Tool Call", tool_calls=len(response.tool_calls)
                )
            call = response.tool_calls[0]
            return {
                "action": ACTION_EXECUTE_TOOL,
                "tool": call.name,
                "input": dict(call.arguments),
            }
        raise _invalid("模型响应缺少内容", status=response.status)


__all__ = ["AgentAction", "AgentResponseParser"]
