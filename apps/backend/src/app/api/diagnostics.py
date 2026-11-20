"""诊断接口（E1-T13 / E2-T12）。

- ``GET /diagnostics/summary``：E1 兼容入口，开发/测试免鉴权，生产要求
  ``X-Diagnostics-Token``；
- ``GET /api/v1/diagnostics/summary``：E2 正式入口，要求 Bearer 认证与
  ``diagnostics.read`` Action，并记录 ``high_risk.call`` 审计事件。

诊断输出只包含脱敏摘要，不返回 Secrets、完整数据库路径或事件 payload。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from secrets import compare_digest
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import enforce_rate_limit, require_action, require_authenticated
from config.settings import Environment, Settings
from core.diagnostics import recent_errors
from core.errors import AppError, PermissionDenied
from core.logging import LOG_FILE_NAME, get_logger
from core.security.principal import ACTION_DIAGNOSTICS_READ
from infrastructure.database.backup import BackupService
from infrastructure.database.manager import MigrationService
from infrastructure.database.service import DatabaseService
from infrastructure.events.dispatcher import EventDispatcher
from infrastructure.events.inbox import InboxRepository
from infrastructure.events.outbox import OutboxRepository
from infrastructure.secrets.store import KeyringSecretStore
from modules.audit.models import AUDIT_HIGH_RISK_CALL
from modules.audit.service import AuditService
from modules.bridge_event.service import BridgeEventService
from modules.bridge_metrics import BridgeMetrics
from modules.editor_session.service import EditorSessionService
from modules.lease.service import LeaseService

router = APIRouter(tags=["system"])

v1_router = APIRouter(
    tags=["system"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

DIAGNOSTICS_TOKEN_HEADER = "X-Diagnostics-Token"
DIAGNOSTICS_TOKEN_SECRET = "backend.diagnostics_token"
logger = get_logger("backend.diagnostics")


@router.get("/diagnostics/summary")
async def summary(request: Request) -> dict[str, object]:
    _ensure_authorized(request)
    return await _build_summary(request)


@v1_router.get(
    "/diagnostics/summary",
    summary="获取诊断摘要",
    description="需要 Bearer 认证与 diagnostics.read 权限；访问会写入 high_risk.call 审计。",
    dependencies=[Depends(require_action(ACTION_DIAGNOSTICS_READ))],
    responses={
        401: {"description": "缺少或无效的 Bearer Token"},
        403: {"description": "缺少 diagnostics.read 权限（PERMISSION_DENIED）"},
        429: {"description": "触发限流（RATE_LIMITED）"},
    },
)
async def v1_summary(request: Request) -> dict[str, object]:
    audit = request.app.state.services.try_get("audit_service")
    principal = getattr(request.state, "principal", None)
    if isinstance(audit, AuditService) and principal is not None:
        await audit.record(
            AUDIT_HIGH_RISK_CALL,
            actor_id=principal.client_id,
            client_id=principal.client_id,
            session_id=principal.session_id,
            resource="diagnostics",
            details={"endpoint": "/api/v1/diagnostics/summary", "method": "GET"},
        )
    return await _build_summary(request)


async def _build_summary(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    lifecycle = request.app.state.lifecycle
    services = request.app.state.services
    started_at = lifecycle.manager.started_at

    database = services.try_get("database")
    migration = services.try_get("migration")
    outbox_counts: dict[str, int] = {}
    inbox_counts: dict[str, int] = {}
    database_status = "unavailable"
    revision = None

    if isinstance(database, DatabaseService) and database.is_initialized and await database.ping():
        database_status = "ready"
        outbox_counts, inbox_counts = await _event_counts(database)
        if isinstance(migration, MigrationService):
            try:
                revision = await migration.current_revision()
            except AppError:
                revision = None

    head = migration.head_revision() if isinstance(migration, MigrationService) else None
    dispatcher = services.try_get("event_dispatcher")
    backups = services.try_get("backup")

    return {
        "application": {
            "name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment.value,
            "state": lifecycle.state.value,
            "started_at": started_at.isoformat() if started_at else None,
            "uptime_seconds": _uptime_seconds(started_at),
        },
        "database": {"status": database_status, "revision": revision},
        "migration": {
            "current": revision,
            "head": head,
            "at_head": revision == head,
        },
        "logging": {"log_file": str(_log_file(settings)), "level": settings.log_level.value},
        "events": {
            "dispatcher_running": isinstance(dispatcher, EventDispatcher) and dispatcher.running,
            "outbox": outbox_counts,
            "inbox": inbox_counts,
            "backlog": outbox_counts.get("pending", 0) + outbox_counts.get("failed", 0),
        },
        "backup": await _backup_summary(backups),
        "bridge": await _bridge_summary(services),
        "recent_errors": [error.to_dict() for error in recent_errors()],
    }


def _ensure_authorized(request: Request) -> None:
    settings = request.app.state.settings
    if settings.environment is not Environment.production:
        return
    token = request.headers.get(DIAGNOSTICS_TOKEN_HEADER)
    expected = _diagnostics_token()
    if not token or expected is None or not compare_digest(token, expected):
        raise PermissionDenied(
            "诊断接口需要有效令牌",
            details={"header": DIAGNOSTICS_TOKEN_HEADER},
        )


def _diagnostics_token() -> str | None:
    try:
        return KeyringSecretStore().get(DIAGNOSTICS_TOKEN_SECRET)
    except Exception:  # noqa: BLE001 - 凭证库不可用时按未授权处理
        return None


async def _event_counts(
    database: DatabaseService,
) -> tuple[dict[str, int], dict[str, int]]:
    try:
        async with database.session() as session:
            outbox = await OutboxRepository().counts(session)
            inbox = await InboxRepository().counts(session)
    except AppError as exc:
        logger.log(
            logging.WARNING,
            "diagnostics_event_counts_failed",
            extra={
                "component": "diagnostics",
                "event": "diagnostics_event_counts_failed",
                "error_code": exc.code,
            },
        )
        return {}, {}
    return outbox, inbox


async def _bridge_summary(services: Any) -> dict[str, int]:
    metrics = services.try_get("bridge_metrics")
    summary = (
        metrics.snapshot()
        if isinstance(metrics, BridgeMetrics)
        else {
            "connections": 0,
            "recovery_success": 0,
            "recovery_failed": 0,
            "fencing_rejections": 0,
        }
    )
    summary.update({"sessions_active": 0, "leases_active": 0, "events_pending_ack": 0})
    try:
        editor_sessions = services.try_get("editor_session_service")
        if isinstance(editor_sessions, EditorSessionService):
            summary["sessions_active"] = await editor_sessions.count_connected()
        leases = services.try_get("lease_service")
        if isinstance(leases, LeaseService):
            summary["leases_active"] = await leases.count_active()
        events = services.try_get("bridge_event_service")
        if isinstance(events, BridgeEventService):
            summary["events_pending_ack"] = await events.count_unacked()
    except AppError:
        # 诊断摘要不允许因单个模块失败而整体不可用。
        pass
    return summary


async def _backup_summary(service: object) -> dict[str, object]:
    if not isinstance(service, BackupService):
        return {"available": False, "count": 0, "latest": None}
    try:
        infos = await service.list()
    except AppError:
        return {"available": False, "count": 0, "latest": None}
    return {
        "available": True,
        "count": len(infos),
        "latest": infos[0].created_at if infos else None,
    }


def _log_file(settings: Settings) -> Path:
    return Path(settings.log_dir) / LOG_FILE_NAME


def _uptime_seconds(started_at: datetime | None) -> float | None:
    if started_at is None:
        return None
    return round((datetime.now(UTC) - started_at).total_seconds(), 3)
