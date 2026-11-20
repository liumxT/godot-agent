"""Bridge 只读诊断接口（E3-T12 / T13 / T14）。

- ``GET /api/v1/bridge/status``：当前 Session 的绑定、租约、项目身份与未确认事件数；
- ``GET /api/v1/bridge/sessions``：按项目分组的活动连接，admin 可看全部，
  普通客户端只能看自己绑定的项目。

两个接口都不触发任何写操作，也不返回 token 或 payload 全文。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import (
    enforce_rate_limit,
    require_action,
    require_authenticated,
    require_session,
)
from core.errors import NotFoundError, PermissionDenied
from core.security.principal import ACTION_BRIDGE_READ, ROLE_ADMIN
from modules.bridge_event.service import BridgeEventService
from modules.editor_session.service import EditorSessionService, format_binding
from modules.lease.service import LeaseService, format_lease
from modules.project.service import ProjectService

router = APIRouter(
    tags=["bridge"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)


@router.get(
    "/bridge/status",
    summary="获取当前 Bridge 状态",
    description="返回当前 Session 的绑定、租约、项目身份与未确认事件数；需要 bridge.read。",
    dependencies=[Depends(require_action(ACTION_BRIDGE_READ))],
    responses={
        401: {"description": "缺少或无效的凭证"},
        403: {"description": "缺少 bridge.read 权限（PERMISSION_DENIED）"},
        404: {"description": "当前 Session 没有 Editor 绑定（NOT_FOUND）"},
    },
)
async def bridge_status(request: Request) -> dict[str, object]:
    session = await require_session(request)
    services = request.app.state.services
    binding_service = services.get("editor_session_service", EditorSessionService)
    lease_service = services.get("lease_service", LeaseService)
    project_service = services.get("project_service", ProjectService)
    event_service = services.get("bridge_event_service", BridgeEventService)

    binding = await binding_service.get(session.session_id)
    if binding is None:
        raise NotFoundError("当前 Session 没有 Editor 绑定")
    lease = await lease_service.active_for_session(session.session_id)
    project = await project_service.get(binding.project_id)
    pending = await event_service.count_unacked(session_id=session.session_id)
    return {
        "session_id": session.session_id,
        "binding": format_binding(binding),
        "lease": format_lease(lease) if lease is not None else None,
        "project": _project_payload(project),
        "events_pending_ack": pending,
    }


@router.get(
    "/bridge/sessions",
    summary="按项目分组列出活动连接",
    description="admin 可查看全部项目；普通客户端只能查看自己绑定的项目。需要 bridge.read。",
    dependencies=[Depends(require_action(ACTION_BRIDGE_READ))],
    responses={
        401: {"description": "缺少或无效的凭证"},
        403: {"description": "跨项目查询（PERMISSION_DENIED）"},
    },
)
async def bridge_sessions(request: Request, project_id: str | None = None) -> dict[str, object]:
    services = request.app.state.services
    binding_service = services.get("editor_session_service", EditorSessionService)
    lease_service = services.get("lease_service", LeaseService)
    project_service = services.get("project_service", ProjectService)
    principal = request.state.principal
    is_admin = principal.role == ROLE_ADMIN

    allowed_project: str | None = None
    if not is_admin:
        # 普通客户端只能查看自己当前绑定项目，避免跨项目读取。
        session = await require_session(request)
        own = await binding_service.get(session.session_id)
        if own is None:
            raise PermissionDenied("当前 Session 没有 Editor 绑定")
        if project_id is not None and project_id != own.project_id:
            raise PermissionDenied("不允许查询其他项目", details={"project_id": project_id})
        allowed_project = own.project_id

    bindings = await binding_service.list_active(project_id)
    groups: dict[str, dict] = {}
    for binding in bindings:
        if allowed_project is not None and binding.project_id != allowed_project:
            continue
        lease = await lease_service.active_for_session(binding.session_id)
        group = groups.setdefault(
            binding.project_id,
            {"project_id": binding.project_id, "project_name": None, "sessions": []},
        )
        group["sessions"].append(
            {
                "session_id": binding.session_id,
                "editor_instance_id": binding.editor_instance_id,
                "binding_status": binding.binding_status,
                "godot_version": binding.godot_version,
                "plugin_version": binding.plugin_version,
                "lease": format_lease(lease) if lease is not None else None,
            }
        )

    result: list[dict] = []
    for pid in sorted(groups):
        group = groups[pid]
        project = await project_service.get(pid)
        group["project_name"] = project.project_name if project is not None else None
        group["session_count"] = len(group["sessions"])
        group["conflict"] = len(group["sessions"]) > 1
        result.append(group)
    return {"projects": result}


def _project_payload(project: object) -> dict[str, object] | None:
    if project is None:
        return None
    return {
        "project_id": getattr(project, "project_id", None),
        "project_root": getattr(project, "project_root", None),
        "project_fingerprint": getattr(project, "project_fingerprint", None),
        "project_name": getattr(project, "project_name", None),
        "godot_version": getattr(project, "godot_version", None),
    }
