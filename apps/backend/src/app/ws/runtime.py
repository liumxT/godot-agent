"""Runtime WebSocket 端点（E3-T16）。

独立接口、独立认证、独立实例登记：Runtime 不创建 Editor Session，也不持有
Lease，只能上报自身状态。认证复用 E2 一次性挑战，Access Token 不返回给 Runtime。
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.bridge import AuthResponsePayload, RuntimeHelloPayload, RuntimeReportPayload
from app.ws.protocol import (
    CLOSE_AUTH_FAILED,
    CLOSE_SERVER_ERROR,
    ProtocolViolation,
    build_control,
    build_error_payload,
    build_error_response,
    build_success_response,
    decode_text,
    validate_control,
)
from bootstrap.service_registry import ServiceRegistry
from config.settings import Settings
from core.errors import AppError, InfrastructureError, RuntimeUnavailable
from core.logging import get_logger, log_event
from core.security.tokens import isoformat, utcnow
from modules.audit.models import (
    AUDIT_RUNTIME_ENDED,
    AUDIT_RUNTIME_REGISTERED,
    AUDIT_RUNTIME_REJECTED,
)
from modules.audit.service import AuditService
from modules.client.service import AuthService
from modules.editor_session.service import EditorSessionService
from modules.project.service import ProjectService
from modules.runtime.models import RUNTIME_RUNNING
from modules.runtime.service import RuntimeService

router = APIRouter()

_logger = get_logger("backend.runtime")


@router.websocket("/api/v1/ws/runtime")
async def runtime_socket(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    services: ServiceRegistry = websocket.app.state.services
    if not settings.bridge_enabled:
        await websocket.close(CLOSE_SERVER_ERROR, "bridge disabled")
        return

    await websocket.accept()
    runtime_instance_id: str | None = None
    correlation_id: str | None = None
    try:
        hello_frame = await _receive_control(websocket, settings)
        correlation_id = hello_frame.get("correlation_id")
        if hello_frame["message_type"] != "HELLO":
            raise ProtocolViolation("INVALID_REQUEST", "first frame must be HELLO")
        hello = _parse(RuntimeHelloPayload, hello_frame.get("payload"))

        auth_service = _require(services, "auth_service", AuthService)
        project_service = _require(services, "project_service", ProjectService)
        editor_sessions = _require(services, "editor_session_service", EditorSessionService)
        runtime_service = _require(services, "runtime_service", RuntimeService)

        challenge = await auth_service.create_challenge(hello.client_id)
        await _send(
            websocket,
            build_control(
                "AUTH_CHALLENGE",
                {
                    "challenge_id": challenge.challenge_id,
                    "challenge": challenge.challenge,
                    "expires_at": isoformat(challenge.expires_at),
                },
                correlation_id=correlation_id,
            ),
            settings,
        )
        auth_frame = await _receive_control(websocket, settings)
        if auth_frame["message_type"] != "AUTH_RESPONSE":
            raise ProtocolViolation("INVALID_REQUEST", "expected AUTH_RESPONSE")
        auth_payload = _parse(AuthResponsePayload, auth_frame.get("payload"))
        await auth_service.verify_challenge(
            challenge_id=auth_payload.challenge_id,
            client_id=hello.client_id,
            proof=auth_payload.proof,
        )

        project = await project_service.find_by_fingerprint(hello.project_fingerprint)
        if project is None:
            raise RuntimeUnavailable("项目尚未被 Editor 登记")
        editor_session_id = await editor_sessions.unique_connected_session(project.project_id)
        view = await runtime_service.register(
            runtime_instance_id=hello.runtime_instance_id,
            project_id=project.project_id,
            client_id=hello.client_id,
            process_id=hello.process_id,
            started_at=hello.started_at,
            godot_version=hello.godot_version,
            build_mode=hello.build_mode,
            editor_session_id=editor_session_id,
        )
        runtime_instance_id = view.runtime_instance_id
        await _send(
            websocket,
            build_control(
                "RUNTIME_REGISTERED",
                {
                    "runtime_instance_id": view.runtime_instance_id,
                    "project_id": view.project_id,
                    "editor_session_id": view.editor_session_id,
                    "status": view.status,
                    "heartbeat_interval_seconds": settings.bridge_runtime_heartbeat_seconds,
                },
                session_id=view.editor_session_id,
                project_id=view.project_id,
                correlation_id=correlation_id,
            ),
            settings,
        )
        await _audit(
            services,
            AUDIT_RUNTIME_REGISTERED,
            client_id=hello.client_id,
            session_id=view.editor_session_id,
            resource=f"runtime:{view.runtime_instance_id}",
            details={"project_id": view.project_id},
        )
        log_event(_logger, logging.INFO, "runtime_registered", component="runtime")

        await _serve_runtime(
            websocket,
            settings,
            runtime_service,
            runtime_instance_id=view.runtime_instance_id,
        )
        await _safe_close(websocket, 1000, "runtime stopped")
    except ProtocolViolation as exc:
        await _send_error_or_ignore(websocket, exc, correlation_id, settings)
        await _safe_close(websocket, exc.close_code, exc.code)
    except WebSocketDisconnect:
        pass
    except AppError as exc:
        await _audit(
            services,
            AUDIT_RUNTIME_REJECTED,
            session_id=runtime_instance_id,
            resource="runtime",
            decision="DENY",
            reason=exc.code.lower(),
        )
        await _send_error_or_ignore(
            websocket,
            ProtocolViolation(exc.code, str(exc), CLOSE_AUTH_FAILED),
            correlation_id,
            settings,
        )
        await _safe_close(websocket, CLOSE_AUTH_FAILED, exc.code)
    except Exception:  # 未知异常统一 1011，避免泄漏内部细节
        _logger.exception(
            "runtime_server_error",
            extra={
                "component": "runtime",
                "event": "runtime_server_error",
                "error_code": "INFRASTRUCTURE_ERROR",
            },
        )
        await _safe_close(websocket, CLOSE_SERVER_ERROR, "internal error")
    finally:
        if runtime_instance_id is not None:
            try:
                await _require(services, "runtime_service", RuntimeService).mark_ended(
                    runtime_instance_id
                )
                await _audit(
                    services,
                    AUDIT_RUNTIME_ENDED,
                    session_id=runtime_instance_id,
                    resource=f"runtime:{runtime_instance_id}",
                )
            except Exception:  # noqa: BLE001 - 清理失败只记录
                log_event(
                    _logger,
                    logging.WARNING,
                    "runtime_disconnect_cleanup_failed",
                    component="runtime",
                    error_code="INFRASTRUCTURE_ERROR",
                )


async def _serve_runtime(
    websocket: WebSocket,
    settings: Settings,
    runtime_service: RuntimeService,
    *,
    runtime_instance_id: str,
) -> None:
    while True:
        frame = await _receive_raw(websocket, settings, timeout=None)
        if isinstance(frame.get("message_type"), str):
            if frame.get("message_type") == "ERROR":
                continue
            raise ProtocolViolation("INVALID_REQUEST", "control frame not allowed")
        action = frame.get("action")
        if action != "bridge.runtime.report":
            await _send(
                websocket,
                build_error_response(
                    frame,
                    "PERMISSION_DENIED",
                    "Runtime 只允许 bridge.runtime.report",
                    retryable=False,
                ),
                settings,
            )
            continue
        try:
            report = _parse(RuntimeReportPayload, frame.get("payload"))
        except ProtocolViolation as exc:
            await _send(
                websocket,
                build_error_response(frame, exc.code, exc.message, retryable=False),
                settings,
            )
            continue
        if report.runtime_instance_id != runtime_instance_id:
            await _send(
                websocket,
                build_error_response(
                    frame,
                    "PERMISSION_DENIED",
                    "Runtime 实例不匹配",
                    retryable=False,
                ),
                settings,
            )
            continue
        try:
            view = await runtime_service.report(
                runtime_instance_id=runtime_instance_id,
                status=report.status,
            )
        except AppError as exc:
            await _send(
                websocket,
                build_error_response(frame, exc.code, exc.message, retryable=exc.retryable),
                settings,
            )
            continue
        await _send(
            websocket,
            build_success_response(
                frame,
                {
                    "runtime_instance_id": view.runtime_instance_id,
                    "status": view.status,
                    "server_time": isoformat(utcnow()),
                },
            ),
            settings,
        )
        if report.status != RUNTIME_RUNNING:
            return


def _require(services: ServiceRegistry, name: str, expected: type) -> object:
    service = services.try_get(name)
    if not isinstance(service, expected):
        raise InfrastructureError(f"服务未注册: {name}")
    return service


async def _audit(
    services: ServiceRegistry,
    action: str,
    *,
    client_id: str | None = None,
    session_id: str | None = None,
    resource: str = "runtime",
    decision: str = "ALLOW",
    reason: str | None = None,
    details: dict | None = None,
) -> None:
    audit = services.try_get("audit_service")
    if not isinstance(audit, AuditService):
        return
    try:
        await audit.record(
            action=action,
            decision=decision,
            client_id=client_id,
            session_id=session_id,
            resource=resource,
            reason=reason,
            details=details or {},
        )
    except Exception:  # noqa: BLE001 - 审计失败不覆盖业务结果
        log_event(
            _logger,
            logging.WARNING,
            "runtime_audit_failed",
            component="runtime",
            error_code="INFRASTRUCTURE_ERROR",
        )


async def _receive_control(websocket: WebSocket, settings: Settings) -> dict:
    return validate_control(
        await _receive_raw(websocket, settings, timeout=settings.bridge_handshake_timeout_seconds)
    )


async def _receive_raw(websocket: WebSocket, settings: Settings, *, timeout: float | None) -> dict:
    try:
        if timeout is None:
            raw = await websocket.receive_text()
        else:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
    except TimeoutError as exc:
        raise ProtocolViolation("REQUEST_TIMEOUT", "handshake timeout", close_code=4408) from exc
    return decode_text(raw, max_bytes=settings.bridge_ws_max_message_bytes)


async def _send(websocket: WebSocket, frame: dict, settings: Settings) -> None:
    text = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > settings.bridge_ws_max_message_bytes:
        raise ProtocolViolation("REQUEST_TOO_LARGE", "outbound frame too large", 4409)
    await websocket.send_text(text)


async def _send_error_or_ignore(
    websocket: WebSocket,
    exc: ProtocolViolation,
    correlation_id: str | None,
    settings: Settings,
) -> None:
    try:
        await _send(
            websocket,
            build_control(
                "ERROR",
                build_error_payload(exc.code, exc.message, correlation_id=correlation_id),
                correlation_id=correlation_id,
            ),
            settings,
        )
    except Exception:  # noqa: S110, BLE001 - 连接已断开时无需再报错
        pass


async def _safe_close(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code, reason)
    except Exception:  # noqa: S110, BLE001 - 已关闭时忽略
        pass


def _parse(model, payload: object):
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ProtocolViolation(
            "INVALID_REQUEST", f"invalid payload: {exc.errors()[0]['msg']}"
        ) from exc
