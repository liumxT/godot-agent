"""打包产物冒烟检查（E0-T02 / E10 使用）。

验证内容：
1. ``--migrate`` 能在打包产物内找到 migrations 并建表。
2. 进程能启动并通过 ``GET /health``。
3. 记录产物体积与冷启动耗时。

用法：
    python scripts/release/smoke_packaged_backend.py <exe 路径> [端口]
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HEALTH_TIMEOUT = 30.0


def _env(workdir: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GODOT_AI_DATABASE_URL": f"sqlite+aiosqlite:///{(workdir / 'backend.db').as_posix()}",
            "GODOT_AI_HOST": "127.0.0.1",
            "GODOT_AI_PORT": str(port),
            "GODOT_AI_LOG_DIR": str(workdir / "logs"),
            "GODOT_AI_ENVIRONMENT": "production",
        }
    )
    return env


def _directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def _migrate(exe: Path, workdir: Path, port: int) -> dict[str, object]:
    completed = subprocess.run(
        [str(exe), "--migrate"],
        cwd=workdir,
        env=_env(workdir, port),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = completed.stdout.strip()
    print("[migrate stdout]", output)
    if completed.returncode != 0:
        print("[migrate stderr]", completed.stderr.strip())
        raise SystemExit(f"migrate failed: exit={completed.returncode}")

    result = json.loads(output.splitlines()[-1])
    connection = sqlite3.connect(workdir / "backend.db")
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    missing = {"alembic_version", "runtime_metadata"} - tables
    if missing:
        raise SystemExit(f"missing tables: {sorted(missing)}")
    return result


def _stop(process: subprocess.Popen[str]) -> None:
    """onefile 模式下引导进程会派生子进程，必须整棵进程树一起结束。"""

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _health(exe: Path, workdir: Path, port: int) -> tuple[int, dict[str, object]]:
    process = subprocess.Popen(
        [str(exe)],
        cwd=workdir,
        env=_env(workdir, port),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/health"
    started = time.perf_counter()
    try:
        deadline = started + HEALTH_TIMEOUT
        while time.perf_counter() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise SystemExit(f"process exited early: {process.returncode}\n{output}")
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") != "ok":
                    raise SystemExit(f"unexpected health payload: {payload}")
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return elapsed_ms, payload
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.2)
        raise SystemExit("health check timed out")
    finally:
        _stop(process)


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: smoke_packaged_backend.py <exe> [port]")

    exe = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8799
    if not exe.is_file():
        raise SystemExit(f"executable not found: {exe}")

    with tempfile.TemporaryDirectory(prefix="godot-ai-smoke-") as tmp:
        workdir = Path(tmp)
        migration = _migrate(exe, workdir, port)
        elapsed_ms, payload = _health(exe, workdir, port)

    # PyInstaller 6 的 onedir 产物在 exe 同级有 _internal 目录
    onedir = (exe.parent / "_internal").is_dir()
    size = _directory_size(exe.parent) if onedir else exe.stat().st_size
    summary = {
        "executable": str(exe),
        "mode": "onedir" if onedir else "onefile",
        "migration": migration,
        "health_ok": payload,
        "startup_ms": elapsed_ms,
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 1),
    }
    print("[smoke]", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
