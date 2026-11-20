"""Runtime 通道服务与 WebSocket 集成测试（E3-T16 / T18-IT-012）。"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ValidationFailed
from core.security.tokens import compute_proof
from modules.client.service import ClientService
from modules.project.service import ProjectService
from modules.runtime.models import RUNTIME_ENDED, RUNTIME_RUNNING, RUNTIME_STOPPED
from modules.runtime.service import RuntimeService

RECEIVE_TIMEOUT = 5.0


def _settings(tmp_path: Path, **overrides):
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
        **overrides,
    )


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "runtime_project"
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="Runtime"\n', encoding="utf-8"
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


@asynccontextmanager
async def _running_app(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    async with app.state.lifecycle.lifespan(app):
        yield app


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
        "correlation_id": "corr-runtime",
        "payload": payload,
    }
    frame.update(overrides)
    return frame


def _runtime_hello(client_id: str, fingerprint: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "runtime_instance_id": "rti_0123456789ab",
        "project_root": "res://",
        "project_fingerprint": fingerprint,
        "process_id": 4321,
        "started_at": _timestamp(),
        "godot_version": "4.5.1",
        "build_mode": "debug",
        "status": "RUNNING",
    }
    payload.update(overrides)
    return _control("HELLO", payload)


def _report(runtime_instance_id: str, status: str) -> dict:
    return {
        "protocol_version": "1.0",
        "request_id": f"req_{uuid4().hex[:12]}",
        "timestamp": _timestamp(),
        "session_id": None,
        "project_id": None,
        "correlation_id": "corr-runtime",
        "action": "bridge.runtime.report",
        "payload": {
            "runtime_instance_id": runtime_instance_id,
            "status": status,
            "timestamp": _timestamp(),
        },
    }


async def _connect(port: int) -> ClientConnection:
    return await connect(f"ws://127.0.0.1:{port}/api/v1/ws/runtime", open_timeout=5)


async def _recv(ws: ClientConnection) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=RECEIVE_TIMEOUT))


async def _authenticate(ws: ClientConnection, secret: str) -> dict:
    challenge = await _recv(ws)
    challenge_id = challenge["payload"]["challenge_id"]
    proof = compute_proof(secret, challenge_id, challenge["payload"]["challenge"])
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


async def _expect_close(ws: ClientConnection) -> int:
    with pytest.raises(ConnectionClosed) as caught:
        while True:
            await ws.recv()
    closed = caught.value
    if closed.rcvd is not None:
        return int(closed.rcvd.code)
    return int(closed.code)


async def _register_client(app, client_type: str = "godot_editor") -> dict:
    registered = await app.state.services.get("client_service", ClientService).register(
        client_type=client_type, client_name="RuntimeHost"
    )
    return {"client_id": registered.client_id, "secret": registered.client_secret}


async def _project(app, root: Path) -> dict:
    view = await app.state.services.get("project_service", ProjectService).resolve(
        project_root=str(root), project_name="Runtime", godot_version="4.5.1"
    )
    return {"project_id": view.project_id, "fingerprint": view.project_fingerprint}


async def test_runtime_registers_and_reports_stopped(tmp_path, project_root) -> None:
    """T16-IT-001：Runtime 独立认证、登记、上报并正常结束。"""

    async with _running_server(tmp_path) as (app, port):
        client = await _register_client(app)
        project = await _project(app, project_root)
        async with await _connect(port) as ws:
            await ws.send(json.dumps(_runtime_hello(client["client_id"], project["fingerprint"])))
            await _authenticate(ws, client["secret"])
            registered = await _recv(ws)
            assert registered["message_type"] == "RUNTIME_REGISTERED"
            assert registered["payload"]["project_id"] == project["project_id"]
            assert registered["payload"]["status"] == RUNTIME_RUNNING

            await ws.send(json.dumps(_report("rti_0123456789ab", "RUNNING")))
            running = await _recv(ws)
            assert running["success"] is True
            assert running["data"]["status"] == RUNTIME_RUNNING

            await ws.send(json.dumps(_report("rti_0123456789ab", "STOPPED")))
            stopped = await _recv(ws)
            assert stopped["success"] is True
            assert stopped["data"]["status"] == RUNTIME_STOPPED
            assert await _expect_close(ws) == 1000

        runtime_service = app.state.services.get("runtime_service", RuntimeService)
        runtime_service_instances = await runtime_service.list_by_project(project["project_id"])
        assert len(runtime_service_instances) == 1
        assert runtime_service_instances[0].status == RUNTIME_STOPPED


async def test_runtime_cannot_call_editor_actions(tmp_path, project_root) -> None:
    """T16-IT-002：Runtime 通道不继承 Editor 权限。"""

    async with _running_server(tmp_path) as (app, port):
        client = await _register_client(app)
        project = await _project(app, project_root)
        async with await _connect(port) as ws:
            await ws.send(json.dumps(_runtime_hello(client["client_id"], project["fingerprint"])))
            await _authenticate(ws, client["secret"])
            await _recv(ws)

            frame = _report("rti_0123456789ab", "RUNNING")
            frame["action"] = "editor.snapshot"
            frame["payload"] = {}
            await ws.send(json.dumps(frame))
            denied = await _recv(ws)
            assert denied["success"] is False
            assert denied["error"]["code"] == "PERMISSION_DENIED"


async def test_runtime_rejects_unregistered_project(tmp_path, project_root) -> None:
    """T16-IT-003：未登记项目指纹返回 RUNTIME_UNAVAILABLE。"""

    async with _running_server(tmp_path) as (app, port):
        client = await _register_client(app)
        async with await _connect(port) as ws:
            await ws.send(json.dumps(_runtime_hello(client["client_id"], "0" * 64)))
            await _authenticate(ws, client["secret"])
            error = await _recv(ws)
            assert error["message_type"] == "ERROR"
            assert error["payload"]["code"] == "RUNTIME_UNAVAILABLE"
            assert await _expect_close(ws) == 4401


async def test_runtime_service_is_idempotent_and_rejects_cross_project(tmp_path) -> None:
    """T16-UT-001：重复注册幂等；同 ID 跨项目拒绝。"""

    first_root = tmp_path / "first"
    first_root.mkdir()
    (first_root / "project.godot").write_text('config/name="A"\n', encoding="utf-8")
    second_root = tmp_path / "second"
    second_root.mkdir()
    (second_root / "project.godot").write_text('config/name="B"\n', encoding="utf-8")

    async with _running_app(tmp_path) as app:
        database = app.state.services.get("database")
        project_service = app.state.services.get("project_service", ProjectService)
        first = await project_service.resolve(project_root=str(first_root))
        second = await project_service.resolve(project_root=str(second_root))
        now = datetime.now(UTC)
        service = RuntimeService(database, clock=lambda: now)

        once = await service.register(
            runtime_instance_id="rti_aaaaaaaaaaaa",
            project_id=first.project_id,
            client_id=None,
            process_id=100,
            started_at=now,
            godot_version="4.5.1",
        )
        twice = await service.register(
            runtime_instance_id="rti_aaaaaaaaaaaa",
            project_id=first.project_id,
            client_id=None,
            process_id=101,
            started_at=now,
            godot_version="4.5.1",
        )
        assert once.runtime_instance_id == twice.runtime_instance_id
        assert twice.process_id == 101
        assert await service.count_active() == 1

        with pytest.raises(ValidationFailed):
            await service.register(
                runtime_instance_id="rti_aaaaaaaaaaaa",
                project_id=second.project_id,
                client_id=None,
                process_id=102,
                started_at=now,
            )


async def test_runtime_expires_stale_instances(tmp_path) -> None:
    """T16-UT-002：心跳超时的实例统一收尾为 ENDED。"""

    root = tmp_path / "stale"
    root.mkdir()
    (root / "project.godot").write_text('config/name="Stale"\n', encoding="utf-8")

    async with _running_app(tmp_path) as app:
        database = app.state.services.get("database")
        project = await app.state.services.get("project_service", ProjectService).resolve(
            project_root=str(root)
        )
        clock = {"now": datetime.now(UTC)}
        service = RuntimeService(database, clock=lambda: clock["now"])
        await service.register(
            runtime_instance_id="rti_bbbbbbbbbbbb",
            project_id=project.project_id,
            client_id=None,
            process_id=200,
            started_at=clock["now"],
        )
        assert await service.count_active() == 1

        clock["now"] += timedelta(seconds=60)
        assert await service.expire_stale(timeout_seconds=20) == 1
        instances = await service.list_by_project(project.project_id)
        assert instances[0].status == RUNTIME_ENDED
        assert instances[0].ended_at is not None
