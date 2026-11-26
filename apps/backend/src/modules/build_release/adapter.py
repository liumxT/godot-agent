"""受控构建执行器与 Godot Headless / 平台导出适配器（E10-T06 / T07）。

安全约束（P02）：

- 只能执行白名单可执行文件，禁止 shell 拼接；
- 工作目录必须位于项目根目录之内；
- 环境变量只透传白名单；
- 强超时限制；
- 日志统一脱敏后落库；
- 退出码为 0 且确有产物才算成功（P05）。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol

from core.errors import BuildPathInvalid, ExportPresetInvalid, ValidationFailed
from core.security.tokens import utcnow
from modules.build_release.models import (
    BUILD_MODE_DEBUG,
    CAPABILITY_SUPPORTED,
    CAPABILITY_SUPPORTED_WITH_REQUIREMENTS,
    PLATFORM_LINUX,
    PLATFORM_MACOS,
    PLATFORM_WINDOWS,
)

EXEC_SUCCEEDED = "SUCCEEDED"
EXEC_FAILED = "FAILED"
EXEC_TIMEOUT = "TIMEOUT"
EXEC_UNDETERMINED = "UNDETERMINED"

ALLOWED_EXECUTABLES = frozenset(
    {
        "godot",
        "godot4",
        "godot.exe",
        "godot4.exe",
        "godot.windows.editor.x86_64.exe",
        "godot.linuxbsd.editor.x86_64",
        "godot.macos.editor.universal",
    }
)

_REDACTIONS = (
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "sk-***"),
    (re.compile(r"(?i)(password|secret|token|api[_-]?key)(\s*[=:]\s*)\S+"), r"\1\2***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"), "Bearer ***"),
)


def redact_text(text: str, limit: int = 200_000) -> str:
    result = text[:limit]
    for pattern, replacement in _REDACTIONS:
        result = pattern.sub(replacement, result)
    return result


def ensure_within(base: Path, target: Path) -> Path:
    """目标路径必须位于 base 之内，防止路径逃逸。"""

    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if base_resolved != target_resolved and base_resolved not in target_resolved.parents:
        raise BuildPathInvalid(
            "构建路径越界", details={"base": str(base_resolved), "target": str(target_resolved)}
        )
    return target_resolved


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True, slots=True)
class BuildCommand:
    template_id: str
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    timeout_seconds: int
    display: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime

    @property
    def succeeded(self) -> bool:
        return self.status == EXEC_SUCCEEDED and self.exit_code == 0


class BuildExecutor(Protocol):
    async def run(self, command: BuildCommand) -> ExecutionResult: ...


class LocalProcessExecutor:
    """基于 asyncio 子进程的本地执行器（不使用 shell）。"""

    async def run(self, command: BuildCommand) -> ExecutionResult:
        executable = Path(command.argv[0]).name.lower()
        if executable not in ALLOWED_EXECUTABLES:
            raise ValidationFailed("可执行文件不在白名单内", details={"executable": executable})
        started_at = utcnow()
        try:
            process = await asyncio.create_subprocess_exec(
                *command.argv,
                cwd=str(command.cwd),
                env=command.env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return ExecutionResult(
                status=EXEC_UNDETERMINED,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                started_at=started_at,
                finished_at=utcnow(),
            )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=command.timeout_seconds
            )
            exit_code = process.returncode
            status = EXEC_SUCCEEDED if exit_code == 0 else EXEC_FAILED
        except TimeoutError:
            process.kill()
            await process.wait()
            return ExecutionResult(
                status=EXEC_TIMEOUT,
                exit_code=None,
                stdout="",
                stderr="构建超时，实际执行状态不明确",
                started_at=started_at,
                finished_at=utcnow(),
            )
        return ExecutionResult(
            status=status,
            exit_code=exit_code,
            stdout=redact_text(stdout.decode("utf-8", errors="replace")),
            stderr=redact_text(stderr.decode("utf-8", errors="replace")),
            started_at=started_at,
            finished_at=utcnow(),
        )


class GodotHeadlessAdapter:
    """构造受控的 Godot Headless 导出命令（T06）。"""

    def __init__(self, executable: str = "godot") -> None:
        self._executable = executable

    def build_command(
        self,
        *,
        project_root: Path,
        preset_name: str,
        output_path: Path,
        build_mode: str,
        timeout_seconds: int,
        env_allowlist: list[str] | tuple[str, ...],
        feature_tags: list[str] | tuple[str, ...] = (),
    ) -> BuildCommand:
        if not preset_name:
            raise ExportPresetInvalid("构建缺少 Export Preset 名称")
        if timeout_seconds <= 0:
            raise ValidationFailed("构建超时必须大于 0")
        resolved_output = ensure_within(project_root, output_path)
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        mode_flag = "--export-debug" if build_mode == BUILD_MODE_DEBUG else "--export-release"
        argv = [
            self._executable,
            "--headless",
            "--path",
            str(project_root.resolve()),
            mode_flag,
            preset_name,
            str(resolved_output),
        ]
        for tag in feature_tags:
            argv.extend(["--feature-tag", str(tag)])
        env = {name: os.environ[name] for name in env_allowlist if name in os.environ}
        return BuildCommand(
            template_id="godot.headless.export.v1",
            argv=tuple(argv),
            cwd=project_root.resolve(),
            env=env,
            timeout_seconds=int(timeout_seconds),
            display={
                "preset": preset_name,
                "mode": build_mode,
                "output": str(resolved_output),
            },
        )


class PlatformExportAdapter:
    """平台导出能力校验与产物检查（T07）。"""

    _EXPECTED_SUFFIX: ClassVar[dict[str, str]] = {
        PLATFORM_WINDOWS: ".exe",
        PLATFORM_LINUX: ".x86_64",
        PLATFORM_MACOS: ".zip",
    }

    def validate(
        self,
        *,
        platform: str,
        architecture: str,
        capability: Any,
    ) -> list[str]:
        problems: list[str] = []
        if capability is None:
            problems.append(f"平台能力未登记: {platform}")
            return problems
        if capability.capability_status not in {
            CAPABILITY_SUPPORTED,
            CAPABILITY_SUPPORTED_WITH_REQUIREMENTS,
        }:
            problems.append(f"平台导出能力不可用: {platform} ({capability.capability_status})")
        if architecture not in capability.supported_architectures:
            problems.append(
                f"架构不受支持: {architecture} 可选 {list(capability.supported_architectures)}"
            )
        return problems

    def default_output(self, output_dir: Path, platform: str, project_slug: str) -> Path:
        suffix = self._EXPECTED_SUFFIX.get(platform)
        if suffix is None:
            raise ExportPresetInvalid("未知平台导出格式", details={"platform": platform})
        return output_dir / f"{project_slug}{suffix}"

    def collect_outputs(self, output_dir: Path) -> dict[str, Any]:
        """收集产物清单；只有存在非空文件才算有真实可见产物（P05）。"""

        if not output_dir.exists():
            return {"files": [], "total_bytes": 0, "has_output": False}
        files: list[dict[str, Any]] = []
        total = 0
        for path in sorted(output_dir.rglob("*")):
            if not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            files.append(
                {
                    "path": path.relative_to(output_dir).as_posix(),
                    "size": size,
                    "hash": file_digest(path) if size > 0 else "",
                }
            )
        return {
            "files": files,
            "total_bytes": total,
            "has_output": any(item["size"] > 0 for item in files),
        }
