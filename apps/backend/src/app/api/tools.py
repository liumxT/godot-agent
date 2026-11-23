"""Tool 接口（E5-T30）：工具目录、执行历史、取消与审计查询。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from core.security.principal import ACTION_E5_TOOL_MANAGE, ACTION_E5_TOOL_READ
from core.security.tokens import isoformat
from modules.tool.audit import ToolAuditService
from modules.tool.execution import ToolExecutionService, ToolExecutionView
from modules.tool.registry import ToolRegistryService, ToolView

router = APIRouter(
    tags=["tools"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    404: {"description": "工具或执行不存在（NOT_FOUND）"},
    409: {"description": "执行状态不允许取消（INVALID_STATE_TRANSITION）"},
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


class CancelExecutionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


def _tools(request: Request) -> ToolRegistryService:
    return request.app.state.services.get("tool_registry_service", ToolRegistryService)


def _executions(request: Request) -> ToolExecutionService:
    return request.app.state.services.get("tool_execution_service", ToolExecutionService)


def _audits(request: Request) -> ToolAuditService:
    return request.app.state.services.get("tool_audit_service", ToolAuditService)


def _format_tool(tool: ToolView) -> dict[str, Any]:
    return {
        "tool_id": tool.tool_id,
        "name": tool.name,
        "version": tool.version,
        "category": tool.category,
        "description": tool.description,
        "risk_level": tool.risk_level,
        "required_capabilities": list(tool.required_capabilities),
        "required_permissions": list(tool.required_permissions),
        "execution_mode": tool.execution_mode,
        "timeout_seconds": tool.timeout_seconds,
        "idempotency_policy": tool.idempotency_policy,
        "enabled": tool.enabled,
        "created_at": isoformat(tool.created_at),
        "updated_at": isoformat(tool.updated_at),
    }


def _format_execution(view: ToolExecutionView) -> dict[str, Any]:
    return {
        "execution_id": view.execution_id,
        "project_id": view.project_id,
        "tool_id": view.tool_id,
        "tool_name": view.tool_name,
        "tool_version": view.tool_version,
        "status": view.status,
        "risk_level": view.risk_level,
        "idempotency_key": view.idempotency_key,
        "task_id": view.task_id,
        "attempt_id": view.attempt_id,
        "agent_instance_id": view.agent_instance_id,
        "changeset_id": view.changeset_id,
        "approval_id": view.approval_id,
        "input": view.input,
        "output": view.output,
        "error_code": view.error_code,
        "error_message": view.error_message,
        "evidence_refs": list(view.evidence_refs),
        "verification_status": view.verification_status,
        "fencing_token": view.fencing_token,
        "started_at": _optional(view.started_at),
        "completed_at": _optional(view.completed_at),
        "created_at": isoformat(view.created_at),
    }


def _optional(value: datetime | None) -> str | None:
    return isoformat(value) if value is not None else None


@router.get(
    "/tools",
    summary="列出工具",
    description="按分类与启用状态列出已登记工具版本。",
    responses=_ERRORS,
)
async def list_tools(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
    category: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_TOOL_READ)
    items = await _tools(request).list(
        category=category, enabled=enabled, limit=limit, offset=offset
    )
    return {"items": [_format_tool(item) for item in items]}


@router.get(
    "/tools/{tool_id}",
    summary="查询工具",
    description="返回单个工具版本的完整定义。",
    responses=_ERRORS,
)
async def get_tool(
    tool_id: str,
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_TOOL_READ)
    return _format_tool(await _tools(request).get(tool_id))


@router.get(
    "/tools/{tool_id}/schema",
    summary="查询工具 Schema",
    description="返回工具的输入与输出 Schema。",
    responses=_ERRORS,
)
async def get_tool_schema(
    tool_id: str,
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_TOOL_READ)
    tool = await _tools(request).get(tool_id)
    return {
        "tool_id": tool.tool_id,
        "name": tool.name,
        "version": tool.version,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
    }


@router.get(
    "/tool-executions",
    summary="列出工具执行",
    description="按项目列出工具执行记录，可按状态过滤。",
    responses=_ERRORS,
)
async def list_executions(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_TOOL_READ)
    page = await _executions(request).list_for_project(
        project_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [_format_execution(item) for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get(
    "/tool-executions/{execution_id}",
    summary="查询工具执行",
    description="返回执行状态、输出、错误与验证结果。",
    responses=_ERRORS,
)
async def get_execution(execution_id: str, request: Request) -> dict:
    view = await _executions(request).get(execution_id)
    await authorize_project_action(request, view.project_id, ACTION_E5_TOOL_READ)
    return _format_execution(view)


@router.post(
    "/tool-executions/{execution_id}/cancel",
    summary="取消工具执行",
    description="仅能取消尚未分发的执行；执行中的工具需要等待或进入恢复流程。",
    responses=_ERRORS,
)
async def cancel_execution(
    execution_id: str,
    request: Request,
    payload: CancelExecutionRequest | None = None,
) -> dict:
    existing = await _executions(request).get(execution_id)
    await authorize_project_action(request, existing.project_id, ACTION_E5_TOOL_MANAGE)
    view = await _executions(request).cancel(
        execution_id,
        actor_id=request.state.principal.client_id,
        reason=payload.reason if payload else None,
    )
    return _format_execution(view)


@router.get(
    "/tool-audits",
    summary="列出工具审计",
    description="按项目列出工具操作审计记录，可按工具过滤。",
    responses=_ERRORS,
)
async def list_tool_audits(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
    tool_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_TOOL_READ)
    page = await _audits(request).list_project_records(
        project_id, tool_id=tool_id, limit=limit, offset=offset
    )
    return {
        "items": page["items"],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }
