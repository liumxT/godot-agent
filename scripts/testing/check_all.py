#!/usr/bin/env python3
"""E0 自动化工程检查（E0-T09）。

按固定顺序执行：仓库结构 → 敏感文件 → 代码格式 → 静态检查 →
契约 Schema → Backend 测试 → Godot 插件检查 → Godot Bridge 测试，并生成 Markdown 报告。

用法（在 Backend 虚拟环境中运行）：

    cd apps/backend
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\testing\\check_all.py

可通过环境变量 ``GODOT_BIN`` 指定 Godot 可执行文件；未指定时尝试 PATH
中的 ``godot``，仍找不到则 Godot 检查记为 SKIP。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
GODOT_PROJECT = ROOT / "apps" / "godot-plugin"
PYTEST = [sys.executable, "-m", "pytest"]
RUFF = [sys.executable, "-m", "ruff"]

REQUIRED_PATHS = (
    "apps/backend/src",
    "apps/backend/tests",
    "apps/backend/migrations",
    "apps/backend/alembic.ini",
    "apps/backend/pyproject.toml",
    "apps/godot-plugin/addons/godot_ai_agent/plugin.cfg",
    "packages/contracts/schemas/manifest.json",
    "docs/06-decisions",
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    ".gitignore",
    ".editorconfig",
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".godot",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "data",
    "logs",
    "artifacts",
    "build",
    "dist",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".db", ".sqlite", ".sqlite3")
SENSITIVE_CONTENT = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)
ALLOWED_ENV_FILES = {".env.example"}


@dataclass
class StageResult:
    name: str
    status: str
    detail: str
    duration_ms: int


def _run(command: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def _iter_files() -> list[Path]:
    """优先使用 git 跟踪文件；git 不可用时退回目录遍历。"""

    git = shutil.which("git")
    if git:
        code, output = _run([git, "ls-files", "-z"], ROOT)
        if code == 0 and output:
            return [ROOT / name for name in output.split("\0") if name]

    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        # 无 git 时无法区分本地 .env 与已提交 .env，交给有 git 的环境严格检查
        if path.name.startswith(".env"):
            continue
        files.append(path)
    return files


def stage_structure() -> str:
    missing = [item for item in REQUIRED_PATHS if not (ROOT / item).exists()]
    if missing:
        raise AssertionError("缺少必需路径: " + ", ".join(missing))
    return f"{len(REQUIRED_PATHS)} 个必需路径齐全"


def stage_sensitive_files() -> str:
    problems: list[str] = []
    for path in _iter_files():
        relative = path.relative_to(ROOT).as_posix()
        name = path.name
        if name.startswith(".env") and name not in ALLOWED_ENV_FILES:
            problems.append(f"环境文件: {relative}")
            continue
        if name.endswith(SENSITIVE_SUFFIXES) or relative.startswith("secrets/"):
            problems.append(f"敏感文件: {relative}")
            continue
        if path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SENSITIVE_CONTENT:
            if pattern.search(text):
                problems.append(f"疑似凭证: {relative} ({pattern.pattern})")
                break
    if problems:
        raise AssertionError("; ".join(problems))
    return f"已扫描 {len(_iter_files())} 个文件，未发现敏感文件或凭证"


def stage_format() -> str:
    code, output = _run([*RUFF, "format", "--check", "src", "tests", "migrations"], BACKEND)
    if code != 0:
        raise AssertionError(output)
    return "ruff format --check 通过"


def stage_lint() -> str:
    code, output = _run([*RUFF, "check", "src", "tests", "migrations"], BACKEND)
    if code != 0:
        raise AssertionError(output)
    return "ruff check 通过"


def stage_contracts() -> str:
    code, output = _run([*PYTEST, "tests/contract", "-q"], BACKEND)
    if code != 0:
        raise AssertionError(output[-2000:])
    return output.splitlines()[-1] if output else "契约样例通过"


def stage_backend_tests() -> str:
    code, output = _run([*PYTEST, "-q", "--ignore=tests/contract"], BACKEND, timeout=1800)
    if code != 0:
        raise AssertionError(output[-2000:])
    return output.splitlines()[-1] if output else "Backend 测试通过"


def _godot_binary() -> str | None:
    configured = os.environ.get("GODOT_BIN")
    if configured and Path(configured).exists():
        return configured
    return shutil.which("godot") or shutil.which("godot4")


def stage_godot() -> str:
    binary = _godot_binary()
    if binary is None:
        return "SKIP: 未找到 Godot，可设置 GODOT_BIN"
    code, output = _run(
        [binary, "--headless", "--path", str(GODOT_PROJECT), "--editor", "--quit"],
        ROOT,
    )
    if code != 0:
        raise AssertionError(output[-2000:])
    # 等待上一个编辑器实例释放项目缓存与编辑器设置文件。
    time.sleep(1.5)
    code, output = _run(
        [
            binary,
            "--headless",
            "--path",
            str(GODOT_PROJECT),
            "--editor",
            "--quit-after",
            "600",
            "--",
            "--contract-test",
        ],
        ROOT,
    )
    if code != 0:
        raise AssertionError(output[-2000:])
    return "插件加载与契约探针通过"


def stage_godot_bridge() -> str:
    binary = _godot_binary()
    if binary is None:
        return "SKIP: 未找到 Godot，可设置 GODOT_BIN"
    # Godot 编辑器退出后仍可能在保存项目缓存，紧接着启动会读到旧锁并异常退出。
    # 前序阶段会留下导入/设置写盘线程，启动扫描被拖慢时 1200 帧可能不足以跑完测试，
    # 因此给测试运行器留出更大的帧数上限；测试完成会主动 quit，不影响正常耗时。
    time.sleep(3.0)
    code, output = _run(
        [
            binary,
            "--headless",
            "--path",
            str(GODOT_PROJECT),
            "--editor",
            "--quit-after",
            "6000",
            "--",
            "--e3-test",
        ],
        ROOT,
    )
    if code != 0:
        raise AssertionError(output[-2000:])
    summary = next(
        (line for line in reversed(output.splitlines()) if line.startswith("godot tests:")),
        "Godot E3 测试通过",
    )
    return summary


STAGES: tuple[tuple[str, Callable[[], str]], ...] = (
    ("仓库结构", stage_structure),
    ("敏感文件", stage_sensitive_files),
    ("代码格式", stage_format),
    ("静态检查", stage_lint),
    ("Contracts Schema", stage_contracts),
    ("Backend 测试", stage_backend_tests),
    ("Godot Plugin", stage_godot),
    ("Godot Bridge Tests", stage_godot_bridge),
)


def _write_report(results: list[StageResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# E0 CI 检查报告",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总计: {len(results)} 项，失败 {sum(r.status == 'FAIL' for r in results)} 项",
        "",
        "| 阶段 | 结果 | 耗时(ms) | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        detail = result.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {result.name} | {result.status} | {result.duration_ms} | {detail} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="E0 自动化工程检查")
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts" / "ci-report.md")
    args = parser.parse_args()

    results: list[StageResult] = []
    for name, stage in STAGES:
        started = time.perf_counter()
        print(f"[RUN ] {name}", flush=True)
        try:
            detail = stage()
        except Exception as exc:  # 检查本身失败必须继续收集其余结果
            status, detail = "FAIL", str(exc)
        else:
            status = "SKIP" if detail.startswith("SKIP") else "PASS"
        duration = int((time.perf_counter() - started) * 1000)
        results.append(StageResult(name, status, detail, duration))
        print(f"[{status}] {name} ({duration}ms) {detail if status != 'PASS' else ''}".rstrip(), flush=True)

    _write_report(results, args.report)
    print(f"\n报告: {args.report}")
    return 1 if any(result.status == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
