"""Editor WebSocket 端点（E3-T06 / T07 / T08）。

握手顺序：HELLO → AUTH_CHALLENGE → AUTH_RESPONSE → SESSION_CREATED。
认证复用 E2 一次性挑战；``gda_`` Access Token 只在服务端内部产生，不返回插件。
本端点只做编排，持久化全部交给 modules 下的 Service。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.bridge import AuthResponsePayload, HelloPayload, StateReportPayload
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
from core.errors import (
    AppError,
    InfrastructureError,
    SessionInvalid,
    SessionSuspended,
    ValidationFailed,
)
from core.logging import get_logger, log_event
from core.security.tokens import isoformat, utcnow
from modules.audit.models import (
    AUDIT_BRIDGE_AUTH_FAILED,
    AUDIT_BRIDGE_CONNECTED,
    AUDIT_BRIDGE_DISCONNECTED,
    AUDIT_BRIDGE_PROJECT_BOUND,
    AUDIT_BRIDGE_PROJECT_SWITCHED,
    AUDIT_BRIDGE_RECOVERED,
    AUDIT_BRIDGE_RECOVERY_FAILED,
)
from modules.audit.service import AuditService
from modules.bridge_event.service import BridgeEventService
from modules.bridge_metrics import BridgeMetrics
from modules.client.service import AuthService
from modules.editor_command.hub import EditorCommandHub
from modules.editor_session.models import BINDING_CONNECTED
from modules.editor_session.service import EditorSessionService, normalize_editor_instance_id
from modules.lease.service import LeaseService, format_lease
from modules.project.service import ProjectService
from modules.session.service import SessionService
from modules.snapshot.service import SnapshotService

router = APIRouter()

_logger = get_logger("backend.bridge")


@router.websocket("/api/v1/ws/editor")
async def editor_socket(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    services: ServiceRegistry = websocket.app.state.services

    if not settings.bridge_enabled:
        await websocket.close(CLOSE_SERVER_ERROR, "bridge disabled")
        return

    await websocket.accept()
    metrics = services.try_get("bridge_metrics")
    if isinstance(metrics, BridgeMetrics):
        metrics.connection_opened()
    binding = None
    session_id: str | None = None
    correlation_id: str | None = None
    try:
        hello_frame = await _receive_control(websocket, settings)
        correlation_id = hello_frame.get("correlation_id")
        if hello_frame["message_type"] != "HELLO":
            raise ProtocolViolation("INVALID_REQUEST", "first frame must be HELLO")
        hello = _parse(HelloPayload, hello_frame.get("payload"))

        auth_service = services.get("auth_service", AuthService)
        project_service = services.get("project_service", ProjectService)
        session_service = services.get("session_service", SessionService)
        binding_service = services.get("editor_session_service", EditorSessionService)
        lease_service = services.get("lease_service", LeaseService)

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
        # 认证结果只用于建 Session；Access Token 不返回给插件。
        project = await project_service.resolve(
            project_root=hello.project.root,
            project_name=hello.project.name,
            godot_version=hello.godot_version,
        )
        metrics = services.try_get("bridge_metrics")
        resume = hello.resume
        project_switched = False
        if resume is None:
            issued = await session_service.create(hello.client_id)
            session_id = issued.session.session_id
            session_token = issued.session_token
            session_expires_at = issued.expires_at
            binding = await binding_service.bind(
                session_id=session_id,
                editor_instance_id=hello.editor_instance_id,
                project_id=project.project_id,
                godot_version=hello.godot_version,
                plugin_version=hello.plugin_version,
            )
            lease = await lease_service.issue(
                session_id=session_id,
                project_id=project.project_id,
            )
        else:
            # 恢复流程：Session 有效则复用，项目变化走切换流程；失败不静默新建。
            try:
                resumed = await session_service.authenticate(resume.session_token)
                instance_id = normalize_editor_instance_id(hello.editor_instance_id)
                if resumed.session_id != resume.session_id:
                    raise SessionInvalid("恢复会话与当前连接不一致")
                if resumed.client_id != hello.client_id:
                    raise SessionInvalid("恢复会话与当前客户端不一致")
                existing = await binding_service.get(resumed.session_id)
                if existing is None or existing.editor_instance_id != instance_id:
                    raise SessionInvalid("恢复会话缺少匹配的 Editor 绑定")
                project_switched = existing.project_id != project.project_id
                await binding_service.mark_recovering(resumed.session_id)
                # 旧连接退出证明：无论是否切换项目，旧 Lease 一律撤销后重发。
                await lease_service.revoke_for_session(
                    resumed.session_id,
                    reason="project_switched" if project_switched else "reconnected",
                )
                binding = await binding_service.bind(
                    session_id=resumed.session_id,
                    editor_instance_id=hello.editor_instance_id,
                    project_id=project.project_id,
                    godot_version=hello.godot_version,
                    plugin_version=hello.plugin_version,
                )
                session_id = resumed.session_id
                session_token = resume.session_token
                session_expires_at = resumed.expires_at
                lease = await lease_service.issue(
                    session_id=session_id,
                    project_id=project.project_id,
                )
            except AppError:
                if isinstance(metrics, BridgeMetrics):
                    metrics.recovery_failed_count()
                await _audit(
                    services,
                    AUDIT_BRIDGE_RECOVERY_FAILED,
                    session_id=resume.session_id,
                    resource="bridge",
                    decision="DENY",
                    reason="recovery_failed",
                )
                raise
            else:
                if isinstance(metrics, BridgeMetrics):
                    metrics.recovery_succeeded()
                if project_switched:
                    await _audit(
                        services,
                        AUDIT_BRIDGE_PROJECT_SWITCHED,
                        session_id=session_id,
                        resource=f"project:{project.project_id}",
                        details={"project_id": project.project_id},
                    )
                else:
                    await _audit(
                        services,
                        AUDIT_BRIDGE_RECOVERED,
                        session_id=session_id,
                        resource=f"session:{session_id}",
                    )

        await _send(
            websocket,
            build_control(
                "SESSION_CREATED",
                {
                    "session_id": session_id,
                    "session_token": session_token,
                    "token_type": "Bearer",
                    "expires_at": isoformat(session_expires_at),
                    "editor_instance_id": binding.editor_instance_id,
                    "project_id": project.project_id,
                    "lease": format_lease(lease),
                    "heartbeat_interval_seconds": settings.bridge_heartbeat_interval_seconds,
                    "request_timeout_seconds": settings.bridge_request_timeout_seconds,
                },
                session_id=session_id,
                project_id=project.project_id,
                correlation_id=correlation_id,
            ),
            settings,
        )
        await _audit(
            services,
            AUDIT_BRIDGE_PROJECT_BOUND,
            client_id=hello.client_id,
            session_id=session_id,
            resource=f"project:{project.project_id}",
            details={
                "project_root": project.project_root,
                "editor_instance_id": binding.editor_instance_id,
            },
        )
        await _audit(
            services,
            AUDIT_BRIDGE_CONNECTED,
            client_id=hello.client_id,
            session_id=session_id,
            resource=f"session:{session_id}",
        )
        log_event(
            _logger,
            logging.INFO,
            "bridge_connected",
            component="bridge",
        )

        command_hub = services.try_get("editor_command_hub")
        connection = None
        if isinstance(command_hub, EditorCommandHub):

            async def _command_sender(frame: dict) -> None:
                await _send(websocket, frame, settings)

            connection = command_hub.open(
                session_id=session_id,
                project_id=project.project_id,
                sender=_command_sender,
            )
        try:
            await _serve(
                websocket,
                settings,
                services,
                session_id=session_id,
                project_id=project.project_id,
                session_token=session_token,
                lease_id=lease.lease_id,
            )
        finally:
            if isinstance(command_hub, EditorCommandHub) and connection is not None:
                command_hub.close(connection)
    except ProtocolViolation as exc:
        await _send_error_or_ignore(websocket, exc, correlation_id, settings)
        await _safe_close(websocket, exc.close_code, exc.code)
    except WebSocketDisconnect:
        pass
    except AppError as exc:
        await _audit(
            services,
            AUDIT_BRIDGE_AUTH_FAILED,
            session_id=session_id,
            resource="bridge",
            decision="DENY",
            reason=exc.code.lower(),
        )
        violation = ProtocolViolation(exc.code, str(exc), CLOSE_AUTH_FAILED)
        await _send_error_or_ignore(websocket, violation, correlation_id, settings)
        await _safe_close(websocket, CLOSE_AUTH_FAILED, exc.code)
    except Exception:  # 未知异常统一 1011，避免泄漏内部细节
        _logger.exception(
            "bridge_server_error",
            extra={
                "component": "bridge",
                "event": "bridge_server_error",
                "error_code": "INFRASTRUCTURE_ERROR",
            },
        )
        await _safe_close(websocket, CLOSE_SERVER_ERROR, "internal error")
    finally:
        if isinstance(metrics, BridgeMetrics):
            metrics.connection_closed()
        if binding is not None and session_id is not None:
            try:
                await services.get(
                    "editor_session_service", EditorSessionService
                ).mark_disconnected(session_id)
                await _audit(
                    services,
                    AUDIT_BRIDGE_DISCONNECTED,
                    session_id=session_id,
                    resource=f"session:{session_id}",
                )
            except Exception:  # noqa: BLE001 - 清理失败只记录，不覆盖原始错误
                log_event(
                    _logger,
                    logging.WARNING,
                    "bridge_disconnect_cleanup_failed",
                    component="bridge",
                    error_code="INFRASTRUCTURE_ERROR",
                )


@dataclass
class _BridgeState:
    """单连接内的轻量状态；不跨连接共享。"""

    last_heartbeat_sequence: int | None = None

    def observe_heartbeat(self, sequence: int) -> bool:
        """记录心跳 sequence；跳号返回 True（需要补齐），重复/回退返回 False。"""

        previous = self.last_heartbeat_sequence
        if sequence <= 0:
            return False
        if previous is not None and sequence <= previous:
            return False
        self.last_heartbeat_sequence = sequence
        return previous is not None and sequence > previous + 1


async def _serve(
    websocket: WebSocket,
    settings: Settings,
    services: ServiceRegistry,
    *,
    session_id: str,
    project_id: str,
    session_token: str,
    lease_id: str,
) -> None:
    """握手完成后的业务帧循环。

    业务失败返回 response.error 并保持连接；协议级错误才关闭连接。
    """

    state = _BridgeState()
    while True:
        frame = await _receive_raw(websocket, settings, timeout=None)
        message_type = frame.get("message_type")
        if isinstance(message_type, str):
            if message_type == "ERROR":
                continue
            raise ProtocolViolation("INVALID_REQUEST", "control frame not allowed after handshake")
        if "success" in frame and not isinstance(frame.get("action"), str):
            hub = services.try_get("editor_command_hub")
            if not isinstance(hub, EditorCommandHub):
                raise ProtocolViolation("UNKNOWN_MESSAGE_TYPE", "unexpected response frame")
            if not hub.resolve(session_id, frame):
                raise ProtocolViolation("INVALID_REQUEST", "response has unknown request_id")
            continue
        action = frame.get("action")
        if not isinstance(action, str):
            raise ProtocolViolation("UNKNOWN_MESSAGE_TYPE", "unrecognized frame")
        try:
            data = await _dispatch_action(
                action,
                frame.get("payload"),
                services,
                settings,
                state=state,
                session_id=session_id,
                project_id=project_id,
                session_token=session_token,
                lease_id=lease_id,
            )
        except AppError as exc:
            if exc.code == "FENCING_TOKEN_STALE":
                metrics = services.try_get("bridge_metrics")
                if isinstance(metrics, BridgeMetrics):
                    metrics.fencing_rejected()
            await _send(
                websocket,
                build_error_response(
                    frame,
                    exc.code,
                    exc.message,
                    retryable=exc.retryable,
                ),
                settings,
            )
            continue
        except ProtocolViolation as exc:
            await _send(
                websocket,
                build_error_response(frame, exc.code, exc.message, retryable=False),
                settings,
            )
            continue
        await _send(websocket, build_success_response(frame, data), settings)


async def _dispatch_action(
    action: str,
    payload: object,
    services: ServiceRegistry,
    settings: Settings,
    *,
    state: _BridgeState,
    session_id: str,
    project_id: str,
    session_token: str,
    lease_id: str,
) -> dict:
    if action == "session.heartbeat":
        return await _handle_heartbeat(
            payload,
            services,
            settings,
            state=state,
            session_id=session_id,
            session_token=session_token,
            lease_id=lease_id,
        )
    if action == "bridge.events.publish":
        return await _handle_events_publish(
            payload,
            services,
            session_id=session_id,
            project_id=project_id,
        )
    if action == "bridge.events.ack":
        return await _handle_events_ack(payload, services, session_id=session_id)
    if action == "bridge.events.since":
        return await _handle_events_since(payload, services, session_id=session_id)
    if action == "editor.snapshot":
        return await _handle_snapshot(
            payload,
            services,
            session_id=session_id,
            project_id=project_id,
        )
    if action == "editor.state.report":
        return _handle_state_report(payload)
    if action == "editor.command.execute":
        raise ProtocolViolation(
            "NOT_IMPLEMENTED", "editor.command.execute is backend-to-plugin only"
        )
    raise ProtocolViolation("UNKNOWN_MESSAGE_TYPE", f"action is not registered: {action}")


async def _handle_heartbeat(
    payload: object,
    services: ServiceRegistry,
    settings: Settings,
    *,
    state: _BridgeState,
    session_id: str,
    session_token: str,
    lease_id: str,
) -> dict:
    binding_service = _require(services, "editor_session_service", EditorSessionService)
    session_service = _require(services, "session_service", SessionService)
    lease_service = _require(services, "lease_service", LeaseService)

    binding = await binding_service.get(session_id)
    if binding is None or binding.binding_status != BINDING_CONNECTED:
        raise SessionSuspended("Editor 绑定未处于 CONNECTED")
    session = await session_service.renew(session_token)
    lease = await lease_service.renew(lease_id)
    await binding_service.touch(session_id)

    sequence = _int_field(payload, "sequence", default=0, minimum=0)
    return {
        "server_time": isoformat(utcnow()),
        "session_status": session.status,
        "lease": format_lease(lease),
        "next_interval_seconds": settings.bridge_heartbeat_interval_seconds,
        "resync_required": state.observe_heartbeat(sequence),
    }


async def _handle_events_publish(
    payload: object,
    services: ServiceRegistry,
    *,
    session_id: str,
    project_id: str,
) -> dict:
    event_service = _require(services, "bridge_event_service", BridgeEventService)
    events = _payload_dict(payload).get("events")
    if not isinstance(events, list):
        raise ValidationFailed("events 必须是数组")
    result = await event_service.publish(
        session_id=session_id,
        project_id=project_id,
        events=events,
    )
    return {
        "accepted": result.accepted,
        "latest_sequence": result.latest_sequence,
        "persisted": result.persisted,
    }


async def _handle_events_ack(
    payload: object,
    services: ServiceRegistry,
    *,
    session_id: str,
) -> dict:
    event_service = _require(services, "bridge_event_service", BridgeEventService)
    body = _payload_dict(payload)
    raw_ids = body.get("event_ids", [])
    if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
        raise ValidationFailed("event_ids 必须是字符串数组")
    last_sequence: int | None = None
    if body.get("last_sequence") is not None:
        last_sequence = _int_field(body, "last_sequence", default=0, minimum=0)
    acked = await event_service.ack(
        session_id=session_id,
        event_ids=raw_ids,
        last_sequence=last_sequence,
    )
    return {"acked": acked}


async def _handle_events_since(
    payload: object,
    services: ServiceRegistry,
    *,
    session_id: str,
) -> dict:
    event_service = _require(services, "bridge_event_service", BridgeEventService)
    body = _payload_dict(payload)
    after_sequence = _int_field(body, "after_sequence", default=0, minimum=0)
    limit = _int_field(body, "limit", default=200, minimum=1)
    result = await event_service.since(
        session_id=session_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return {
        "events": result.events,
        "latest_sequence": result.latest_sequence,
        "snapshot_required": result.snapshot_required,
    }


async def _handle_snapshot(
    payload: object,
    services: ServiceRegistry,
    *,
    session_id: str,
    project_id: str,
) -> dict:
    lease_service = _require(services, "lease_service", LeaseService)
    snapshot_service = _require(services, "snapshot_service", SnapshotService)
    body = _payload_dict(payload)
    await lease_service.validate(session_id=session_id, project_id=project_id)
    if body:
        view = await snapshot_service.store(body, session_id=session_id, project_id=project_id)
    else:
        view = await snapshot_service.latest(session_id)
    return {"kind": "snapshot", "snapshot": view.payload}


def _handle_state_report(payload: object) -> dict:
    """E3-T15：被动接收编辑器状态增量，只做契约校验，不落库。"""

    report = _parse(StateReportPayload, _payload_dict(payload))
    return {
        "accepted": True,
        "changed": list(report.changed),
        "server_time": isoformat(utcnow()),
    }


def _require(services: ServiceRegistry, name: str, expected: type) -> object:
    service = services.try_get(name)
    if not isinstance(service, expected):
        raise InfrastructureError(f"服务未注册: {name}")
    return service


def _payload_dict(payload: object) -> dict:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValidationFailed("payload 必须是对象")
    return payload


def _int_field(payload: object, name: str, *, default: int, minimum: int) -> int:
    body = _payload_dict(payload)
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationFailed(f"{name} 必须是 >= {minimum} 的整数")
    return value


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


async def _audit(services: ServiceRegistry, action: str, **fields) -> None:
    audit = services.try_get("audit_service")
    if isinstance(audit, AuditService):
        await audit.record(action, **fields)
