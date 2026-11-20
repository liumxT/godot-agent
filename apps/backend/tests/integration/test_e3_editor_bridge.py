"""Editor Bridge 握手与认证集成测试（E3-T06 / T07 / T08）。

真实 uvicorn + 真实 WebSocket 客户端，覆盖：
HELLO → AUTH_CHALLENGE → AUTH_RESPONSE → SESSION_CREATED、错误 proof、
非法首帧、超大帧、握手超时、项目校验与未登记 action。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from bootstrap.application import create_app
from config.settings import load_settings
from modules.client.service import ClientService
from shared.contracts import validate_instance

SESSION_CREATED_SCHEMA = "bridge/session-created.schema.json"
ERROR_SCHEMA = "errors/error.schema.json"
RECEIVE_TIMEOUT = 5.0


def _settings(tmp_path: Path, **overrides):
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'bridge.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
        **overrides,
    )


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "demo_project"
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="Demo"\n', encoding="utf-8"
    )
    return root


@asynccontextmanager
async def _running_server(tmp_path: Path, **overrides):
    app = create_app(_settings(tmp_path, **overrides))
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(300):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started, "uvicorn 未能启动"
    port = int(server.servers[0].sockets[0].getsockname()[1])
    try:
        yield app, port
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 15)


async def _connect(port: int) -> ClientConnection:
    return await connect(f"ws://127.0.0.1:{port}/api/v1/ws/editor", open_timeout=5)


async def _register(app) -> dict:
    registered = await app.state.services.get("client_service", ClientService).register(
        client_type="godot_editor", client_name="Editor"
    )
    return {
        "client_id": registered.client_id,
        "client_secret": registered.client_secret,
    }


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _control(message_type: str, payload: dict, **overrides) -> dict:
    frame = {
        "protocol_version": "1.0",
        "message_id": f"ctl_{uuid4().hex[:8]}",
        "message_type": message_type,
        "timestamp": _timestamp(),
        "session_id": None,
        "project_id": None,
        "correlation_id": "corr-e3",
        "payload": payload,
    }
    frame.update(overrides)
    return frame


def _hello(client_id: str, project_root: Path, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "editor_instance_id": "edi_0123456789ab",
        "plugin_version": "0.1.0",
        "godot_version": "4.5.1",
        "project": {
            "root": str(project_root),
            "name": "Demo",
            "godot_version": "4.5.1",
        },
    }
    payload.update(overrides)
    return _control("HELLO", payload)


def _proof(secret: str, challenge_id: str, challenge: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{challenge_id}.{challenge}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _recv(ws: ClientConnection) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=RECEIVE_TIMEOUT))


async def _auth_response(ws: ClientConnection, client_secret: str) -> dict:
    challenge = await _recv(ws)
    assert challenge["message_type"] == "AUTH_CHALLENGE"
    challenge_id = challenge["payload"]["challenge_id"]
    proof = _proof(client_secret, challenge_id, challenge["payload"]["challenge"])
    await ws.send(
        json.dumps(
            _control(
                "AUTH_RESPONSE",
                {"challenge_id": challenge_id, "proof": proof},
                correlation_id=challenge["correlation_id"],
            )
        )
    )
    return challenge


async def _handshake(ws: ClientConnection, client_id: str, secret: str, project_root: Path) -> dict:
    await ws.send(json.dumps(_hello(client_id, project_root)))
    await _auth_response(ws, secret)
    created = await _recv(ws)
    assert created["message_type"] == "SESSION_CREATED", created
    return created


async def _expect_close(ws: ClientConnection) -> int:
    with pytest.raises(ConnectionClosed) as caught:
        while True:
            await ws.recv()
    closed = caught.value
    if closed.rcvd is not None:
        return int(closed.rcvd.code)
    return int(closed.code)


async def test_handshake_returns_session_and_lease(tmp_path, project_root) -> None:
    """T06-IT-001 / T07-IT-001 / T08-IT-001：认证成功返回完整会话。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            created = await _handshake(
                ws, registered["client_id"], registered["client_secret"], project_root
            )

        payload = created["payload"]
        assert validate_instance(payload, SESSION_CREATED_SCHEMA) == []
        assert payload["session_token"].startswith("gds_")
        assert payload["session_id"].startswith("ses_")
        assert payload["project_id"].startswith("prj_")
        assert payload["editor_instance_id"] == "edi_0123456789ab"
        assert payload["lease"]["status"] == "ACTIVE"
        assert payload["lease"]["fencing_token"] == 1
        assert created["session_id"] == payload["session_id"]


async def test_wrong_proof_is_rejected_with_auth_close_code(tmp_path, project_root) -> None:
    """T06-UT-001：错误 proof 必须认证失败并关闭 4401。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            await ws.send(json.dumps(_hello(registered["client_id"], project_root)))
            challenge = await _recv(ws)
            await ws.send(
                json.dumps(
                    _control(
                        "AUTH_RESPONSE",
                        {
                            "challenge_id": challenge["payload"]["challenge_id"],
                            "proof": "invalid-proof",
                        },
                    )
                )
            )
            error = await _recv(ws)
            assert error["message_type"] == "ERROR"
            assert error["payload"]["code"] == "AUTH_CHALLENGE_INVALID"
            assert validate_instance(error["payload"], ERROR_SCHEMA) == []
            assert await _expect_close(ws) == 4401


async def test_first_frame_must_be_hello(tmp_path, project_root) -> None:
    """T06-UT-002：未认证连接只允许 HELLO。"""

    async with _running_server(tmp_path) as (_app, port), await _connect(port) as ws:
        await ws.send(json.dumps(_control("AUTH_RESPONSE", {"challenge_id": "x", "proof": "y"})))
        error = await _recv(ws)
        assert error["payload"]["code"] == "INVALID_REQUEST"
        assert await _expect_close(ws) == 4401


async def test_unknown_control_type_is_rejected(tmp_path, project_root) -> None:
    """T06-UT-003：未知控制类型返回 UNKNOWN_MESSAGE_TYPE。"""

    async with _running_server(tmp_path) as (_app, port), await _connect(port) as ws:
        frame = _control("HELLO", {})
        frame["message_type"] = "PING"
        await ws.send(json.dumps(frame))
        error = await _recv(ws)
        assert error["payload"]["code"] == "UNKNOWN_MESSAGE_TYPE"
        assert await _expect_close(ws) == 4401


async def test_oversized_frame_closes_with_4409(tmp_path, project_root) -> None:
    """T06-UT-004：超过 256 KiB 的帧必须拒绝并以 4409 关闭。"""

    async with _running_server(tmp_path) as (_app, port), await _connect(port) as ws:
        await ws.send("x" * (262144 + 1))
        error = await _recv(ws)
        assert error["payload"]["code"] == "REQUEST_TOO_LARGE"
        assert await _expect_close(ws) == 4409


async def test_handshake_timeout_closes_with_4408(tmp_path) -> None:
    """T06-UT-005：握手超时以 4408 关闭。"""

    async with (
        _running_server(tmp_path, bridge_handshake_timeout_seconds=0.2) as (_app, port),
        await _connect(port) as ws,
    ):
        error = await _recv(ws)
        assert error["payload"]["code"] == "REQUEST_TIMEOUT"
        assert await _expect_close(ws) == 4408


async def test_invalid_project_root_is_rejected(tmp_path) -> None:
    """T06-IT-002：项目根目录不存在时不得创建 Session。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        missing = tmp_path / "does_not_exist"
        async with await _connect(port) as ws:
            await ws.send(json.dumps(_hello(registered["client_id"], missing)))
            await _auth_response(ws, registered["client_secret"])
            error = await _recv(ws)
            assert error["payload"]["code"] == "INVALID_REQUEST"
            assert await _expect_close(ws) == 4401


async def test_unknown_action_after_handshake_returns_error_response(
    tmp_path, project_root
) -> None:
    """握手后未登记 action 返回 response 错误但不关闭连接。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            await _handshake(ws, registered["client_id"], registered["client_secret"], project_root)
            await ws.send(
                json.dumps(
                    {
                        "protocol_version": "1.0",
                        "request_id": "req_000000000001",
                        "timestamp": _timestamp(),
                        "action": "editor.unknown",
                        "payload": {},
                    }
                )
            )
            response = await _recv(ws)
            assert response["success"] is False
            assert response["request_id"] == "req_000000000001"
            assert response["error"]["code"] == "UNKNOWN_MESSAGE_TYPE"


async def test_session_created_has_exact_fields(tmp_path, project_root) -> None:
    """T07-UT-003：SESSION_CREATED 字段集合固定，无额外字段。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            created = await _handshake(
                ws, registered["client_id"], registered["client_secret"], project_root
            )
        assert set(created["payload"]) == {
            "session_id",
            "session_token",
            "token_type",
            "expires_at",
            "editor_instance_id",
            "project_id",
            "lease",
            "heartbeat_interval_seconds",
            "request_timeout_seconds",
        }


def _request_frame(request_id: str, action: str, payload: dict) -> dict:
    return {
        "protocol_version": "1.0",
        "request_id": request_id,
        "timestamp": _timestamp(),
        "session_id": None,
        "project_id": None,
        "correlation_id": "corr-e3",
        "action": action,
        "payload": payload,
    }


async def _request(ws: ClientConnection, action: str, payload: dict) -> dict:
    await ws.send(json.dumps(_request_frame(f"req_{uuid4().hex[:12]}", action, payload)))
    return await _recv(ws)


def _bridge_event(event_id: str, event_type: str = "project.opened") -> dict:
    return {
        "protocol_version": "1.0",
        "event_id": event_id,
        "event_type": event_type,
        "timestamp": _timestamp(),
        "source": "plugin",
        "payload": {"value": 1},
    }


def _snapshot_payload(created: dict, version: int = 1) -> dict:
    return {
        "snapshot_id": f"snp_{version:012x}",
        "session_id": created["payload"]["session_id"],
        "project_id": created["payload"]["project_id"],
        "editor_instance_id": created["payload"]["editor_instance_id"],
        "snapshot_version": version,
        "last_event_sequence": 0,
        "created_at": _timestamp(),
        "editor_status": "READY",
        "project_status": "READY",
        "active_scene": "res://scenes/main.tscn",
        "current_selection": ["res://scenes/main.tscn"],
        "unsaved_resources": [],
        "run_status": "STOPPED",
        "import_status": "IDLE",
        "truncated": False,
    }


async def test_heartbeat_updates_session_and_reports_gap(tmp_path, project_root) -> None:
    """T09-IT-001：心跳续期 Session/租约，并识别 sequence 跳号。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            created = await _handshake(
                ws, registered["client_id"], registered["client_secret"], project_root
            )

            first = await _request(
                ws,
                "session.heartbeat",
                {"sequence": 1, "client_time": _timestamp(), "run_status": "STOPPED"},
            )
            assert first["success"] is True, first
            data = first["data"]
            assert data["session_status"] == "ACTIVE"
            assert data["lease"]["status"] == "ACTIVE"
            assert data["lease"]["fencing_token"] == created["payload"]["lease"]["fencing_token"]
            assert data["next_interval_seconds"] == created["payload"]["heartbeat_interval_seconds"]
            assert data["resync_required"] is False

            gap = await _request(ws, "session.heartbeat", {"sequence": 3})
            assert gap["success"] is True
            assert gap["data"]["resync_required"] is True

            duplicate = await _request(ws, "session.heartbeat", {"sequence": 3})
            assert duplicate["data"]["resync_required"] is False


async def test_publish_events_returns_monotonic_sequence(tmp_path, project_root) -> None:
    """T10-IT-001：上行事件返回单调 sequence，重复 event_id 幂等。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            await _handshake(ws, registered["client_id"], registered["client_secret"], project_root)

            published = await _request(
                ws,
                "bridge.events.publish",
                {"events": [_bridge_event("evt_it00000001"), _bridge_event("evt_it00000002")]},
            )
            assert published["success"] is True, published
            assert published["data"]["accepted"] == ["evt_it00000001", "evt_it00000002"]
            assert published["data"]["persisted"] == 2
            assert published["data"]["latest_sequence"] == 2

            repeated = await _request(
                ws,
                "bridge.events.publish",
                {"events": [_bridge_event("evt_it00000001")]},
            )
            assert repeated["data"]["persisted"] == 0
            assert repeated["data"]["latest_sequence"] == 2

            acked = await _request(ws, "bridge.events.ack", {"event_ids": [], "last_sequence": 2})
            assert acked["success"] is True
            since = await _request(ws, "bridge.events.since", {"after_sequence": 0})
            assert since["success"] is True
            assert since["data"]["events"] == []
            assert since["data"]["snapshot_required"] is False


async def test_snapshot_store_then_fetch_latest(tmp_path, project_root) -> None:
    """T11-IT-001：editor.snapshot 存储后可取回最新快照。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            created = await _handshake(
                ws, registered["client_id"], registered["client_secret"], project_root
            )

            stored = await _request(ws, "editor.snapshot", _snapshot_payload(created))
            assert stored["success"] is True, stored
            assert stored["data"]["kind"] == "snapshot"
            assert stored["data"]["snapshot"]["snapshot_id"] == "snp_000000000001"

            fetched = await _request(ws, "editor.snapshot", {})
            assert fetched["success"] is True
            assert fetched["data"]["snapshot"]["snapshot_id"] == "snp_000000000001"

        async with await _connect(port) as second:
            await _handshake(
                second, registered["client_id"], registered["client_secret"], project_root
            )
            missing = await _request(second, "editor.snapshot", {})
            assert missing["success"] is False
            assert missing["error"]["code"] == "SNAPSHOT_UNAVAILABLE"
            assert missing["error"]["retryable"] is True


def _session_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _resume_handshake(
    ws: ClientConnection,
    client_id: str,
    secret: str,
    project_root: Path,
    session_id: str,
    session_token: str,
    *,
    editor_instance_id: str = "edi_0123456789ab",
) -> dict:
    await ws.send(
        json.dumps(
            _hello(
                client_id,
                project_root,
                editor_instance_id=editor_instance_id,
                resume={"session_id": session_id, "session_token": session_token},
            )
        )
    )
    await _auth_response(ws, secret)
    return await _recv(ws)


async def test_reconnect_with_resume_reuses_session_and_rotates_lease(
    tmp_path, project_root
) -> None:
    """T12-IT-001：断线重连复用 Session，旧租约撤销并重新颁发。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            first = (
                await _handshake(
                    ws, registered["client_id"], registered["client_secret"], project_root
                )
            )["payload"]

        async with await _connect(port) as ws:
            created = await _resume_handshake(
                ws,
                registered["client_id"],
                registered["client_secret"],
                project_root,
                first["session_id"],
                first["session_token"],
            )
            assert created["message_type"] == "SESSION_CREATED", created
            payload = created["payload"]
            assert payload["session_id"] == first["session_id"]
            assert payload["lease"]["lease_id"] != first["lease"]["lease_id"]
            assert payload["lease"]["fencing_token"] == 2

            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
                # 绑定状态在响应发送后异步落库；用低频轮询避免触发接口限流。
                for _ in range(40):
                    response = await http.get(
                        "/api/v1/bridge/status",
                        headers=_session_headers(payload["session_token"]),
                    )
                    if response.json().get("binding", {}).get("binding_status") == "CONNECTED":
                        break
                    await asyncio.sleep(0.5)
            assert response.status_code == 200, response.text
            status = response.json()
            assert status["session_id"] == first["session_id"]
            assert status["binding"]["binding_status"] == "CONNECTED"
            assert status["lease"]["lease_id"] == payload["lease"]["lease_id"]
            assert status["project"]["project_id"] == payload["project_id"]


async def test_project_switch_on_resume(tmp_path, project_root) -> None:
    """T14-IT-001：项目路径变化后恢复时切换绑定并重新签发租约。"""

    other_root = tmp_path / "other_project"
    other_root.mkdir()
    (other_root / "project.godot").write_text('config/name="Other"\n', encoding="utf-8")

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            first = (
                await _handshake(
                    ws, registered["client_id"], registered["client_secret"], project_root
                )
            )["payload"]

        async with await _connect(port) as ws:
            created = await _resume_handshake(
                ws,
                registered["client_id"],
                registered["client_secret"],
                other_root,
                first["session_id"],
                first["session_token"],
            )
            payload = created["payload"]
            assert payload["session_id"] == first["session_id"]
            assert payload["project_id"] != first["project_id"]
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
                response = await http.get(
                    "/api/v1/bridge/status",
                    headers=_session_headers(payload["session_token"]),
                )
            status = response.json()
            assert status["project"]["project_id"] == payload["project_id"]
            assert status["project"]["project_root"].endswith("other_project")


async def test_invalid_resume_token_is_rejected(tmp_path, project_root) -> None:
    """T12-UT-005：无效恢复凭证必须认证失败，不静默新建 Session。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as ws:
            await ws.send(
                json.dumps(
                    _hello(
                        registered["client_id"],
                        project_root,
                        resume={
                            "session_id": "ses_000000000000",
                            "session_token": "gds_" + "A" * 43,
                        },
                    )
                )
            )
            await _auth_response(ws, registered["client_secret"])
            error = await _recv(ws)
            assert error["message_type"] == "ERROR"
            assert error["payload"]["code"] == "SESSION_INVALID"
            assert await _expect_close(ws) == 4401


async def test_two_editors_are_isolated_and_listed_per_project(tmp_path, project_root) -> None:
    """T13-IT-001：同一项目的多 Editor 会话独立，跨项目查询被拒绝。"""

    async with _running_server(tmp_path) as (app, port):
        registered = await _register(app)
        async with await _connect(port) as first, await _connect(port) as second:
            one = (
                await _handshake(
                    first,
                    registered["client_id"],
                    registered["client_secret"],
                    project_root,
                )
            )["payload"]
            await second.send(
                json.dumps(
                    _hello(
                        registered["client_id"],
                        project_root,
                        editor_instance_id="edi_ffffffffffff",
                    )
                )
            )
            await _auth_response(second, registered["client_secret"])
            two = (await _recv(second))["payload"]
            assert one["session_id"] != two["session_id"]
            assert one["editor_instance_id"] != two["editor_instance_id"]

            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
                own = await http.get(
                    "/api/v1/bridge/sessions",
                    headers=_session_headers(two["session_token"]),
                )
                denied = await http.get(
                    "/api/v1/bridge/sessions",
                    params={"project_id": "prj_otherproject"},
                    headers=_session_headers(two["session_token"]),
                )
            assert own.status_code == 200, own.text
            projects = own.json()["projects"]
            assert len(projects) == 1
            assert projects[0]["project_id"] == two["project_id"]
            assert projects[0]["session_count"] == 2
            assert denied.status_code == 403
