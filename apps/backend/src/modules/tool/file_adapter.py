"""文件系统工具 Adapter（E5-T29）。

所有路径都必须落在已登记项目根目录内；``..``、绝对路径、符号链接逃逸、
隐藏路径与敏感文件一律拒绝。写入后必须重新读取校验，并通知 Editor 刷新；
不能仅凭"写入返回成功"就认为资源可用，也不能伪造 Godot UID。
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from modules.editor_command.hub import EDITOR_COMMAND_ACTION, EditorCommandHub
from modules.project_registry.service import ProjectRegistryService
from modules.tool.adapters import AdapterResult, ToolDispatchContext, VerificationCheck
from modules.tool.models import EXECUTION_FAILED, EXECUTION_SUCCEEDED
from modules.tool.registry import ToolView

MAX_TEXT_BYTES = 1024 * 1024
MAX_SEARCH_FILES = 2000
EDITOR_REFRESH_TIMEOUT = 10.0
IMPORT_SUFFIXES = frozenset({".gd", ".gdshader", ".tscn", ".tres", ".import"})
SENSITIVE_NAMES = frozenset(
    {"project.godot", "export_presets.cfg", "credentials.cfg", "client_secret.txt"}
)
SENSITIVE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".keystore"})

FILE_PATH_DENIED = "FILE_PATH_DENIED"
FILE_NOT_FOUND = "FILE_NOT_FOUND"
FILE_ALREADY_EXISTS = "FILE_ALREADY_EXISTS"
FILE_BINARY_NOT_SUPPORTED = "FILE_BINARY_NOT_SUPPORTED"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
FILE_PATCH_MISMATCH = "FILE_PATCH_MISMATCH"
FILE_OPERATION_FAILED = "FILE_OPERATION_FAILED"

__all__ = ["FileToolAdapter", "PathViolation"]


class PathViolation(Exception):
    """路径不在项目范围内或命中禁止规则。"""


class _PathGuard:
    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self, raw: str) -> Path:
        text = (raw or "").strip()
        text = text.removeprefix("res://")
        if text.startswith("user://"):
            raise PathViolation("不允许访问 user:// 路径")
        if not text or text == ".":
            return self.root
        candidate = Path(text)
        if candidate.is_absolute():
            raise PathViolation("不允许使用绝对路径")
        for part in candidate.parts:
            if part == "..":
                raise PathViolation("不允许包含 .. 路径段")
            if part.startswith("."):
                raise PathViolation("不允许访问隐藏路径")
        resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PathViolation("路径逃逸出项目根目录") from exc
        if resolved.name.lower() in SENSITIVE_NAMES:
            raise PathViolation("敏感文件不允许访问")
        if resolved.suffix.lower() in SENSITIVE_SUFFIXES:
            raise PathViolation("敏感文件类型不允许访问")
        return resolved

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


class FileToolAdapter:
    name = "file_system"

    def __init__(
        self,
        projects: ProjectRegistryService,
        *,
        hub: EditorCommandHub | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._projects = projects
        self._hub = hub
        self._clock = clock
        self._logger = get_logger("backend.tool.file")

    def supports(self, tool: ToolView) -> bool:
        return tool.category == "FILE_SYSTEM"

    async def execute(self, context: ToolDispatchContext) -> AdapterResult:
        try:
            project = await self._projects.get(context.project_id)
        except Exception as exc:  # noqa: BLE001 - 项目不可用即不能访问文件
            return _failed(FILE_PATH_DENIED, f"项目不可用: {exc}")
        guard = _PathGuard(Path(project.project_root).resolve())
        handler = _HANDLERS.get(context.tool_name)
        if handler is None:
            return _failed("TOOL_UNSUPPORTED", f"文件工具未实现: {context.tool_name}")
        try:
            return await handler(self, guard, context)
        except PathViolation as exc:
            return _failed(FILE_PATH_DENIED, str(exc))
        except UnicodeDecodeError as exc:
            return _failed(FILE_BINARY_NOT_SUPPORTED, f"文件不是 UTF-8 文本: {exc.reason}")
        except OSError as exc:
            log_event(
                self._logger,
                logging.WARNING,
                "file_tool_failed",
                component="tool",
                error_code=FILE_OPERATION_FAILED,
            )
            return _failed(FILE_OPERATION_FAILED, f"{type(exc).__name__}: {exc}"[:512])

    async def inspect(self, context: ToolDispatchContext) -> AdapterResult | None:
        """只能用可验证的客观事实判断；无法确定时返回 None 交给恢复流程。"""

        try:
            project = await self._projects.get(context.project_id)
        except Exception:  # noqa: BLE001 - 观测失败保持未知
            return None
        guard = _PathGuard(Path(project.project_root).resolve())
        try:
            if context.tool_name == "file.delete":
                target = guard.resolve(str(context.input.get("path", "")))
                passed = not target.exists()
                return AdapterResult(
                    status=EXECUTION_SUCCEEDED if passed else "UNKNOWN",
                    output={"path": guard.relative(target), "deleted": passed} if passed else None,
                    checks=(VerificationCheck("file_absent", passed, guard.relative(target)),),
                )
            if context.tool_name in ("file.move", "file.rename"):
                destination = _move_destination(guard, context)
                if destination is not None and destination.exists():
                    return AdapterResult(
                        status=EXECUTION_SUCCEEDED,
                        output={"path": guard.relative(destination), "moved": True},
                        checks=(VerificationCheck("destination_exists", True, guard.relative(destination)),),
                    )
        except PathViolation:
            return None
        return None


# --- 读操作 ---


async def _read(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    target = guard.resolve(str(context.input.get("path", "")))
    if not target.is_file():
        return _failed(FILE_NOT_FOUND, guard.relative(target))
    size = target.stat().st_size
    if size > MAX_TEXT_BYTES:
        return _failed(FILE_TOO_LARGE, f"文件超过 {MAX_TEXT_BYTES} 字节")
    content = target.read_bytes().decode("utf-8")
    digest = _sha256(target)
    return AdapterResult(
        status=EXECUTION_SUCCEEDED,
        output={
            "path": guard.relative(target),
            "content": content,
            "size": size,
            "sha256": digest,
        },
        checks=(VerificationCheck("file_readable", True, guard.relative(target)),),
        evidence_refs=(f"file:{guard.relative(target)}", f"sha256:{digest}"),
    )


async def _list(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    target = guard.resolve(str(context.input.get("path", "")))
    if not target.is_dir():
        return _failed(FILE_NOT_FOUND, guard.relative(target))
    recursive = bool(context.input.get("recursive", False))
    entries: list[dict[str, Any]] = []
    for path in sorted(target.rglob("*") if recursive else target.iterdir()):
        if _hidden_relative(guard, path):
            continue
        entries.append(
            {
                "path": guard.relative(path),
                "name": path.name,
                "is_dir": path.is_dir(),
                "size": path.stat().st_size if path.is_file() else 0,
            }
        )
        if len(entries) >= 1000:
            break
    return AdapterResult(status=EXECUTION_SUCCEEDED, output={"path": guard.relative(target), "entries": entries})


async def _search(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    base = guard.resolve(str(context.input.get("path", "")))
    pattern = str(context.input.get("pattern", ""))
    if not pattern:
        return _failed(FILE_OPERATION_FAILED, "缺少 pattern")
    limit = int(context.input.get("max_results", 100))
    regex: re.Pattern[str] | None = None
    if bool(context.input.get("regex", False)):
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return _failed(FILE_OPERATION_FAILED, f"正则表达式非法: {exc}")
    matches: list[dict[str, Any]] = []
    scanned = 0
    for path in _walk_files(guard, base):
        scanned += 1
        if scanned > MAX_SEARCH_FILES:
            break
        if path.stat().st_size > MAX_TEXT_BYTES:
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            hit = regex.search(line) if regex is not None else (pattern in line)
            if not hit:
                continue
            matches.append({"path": guard.relative(path), "line": number, "text": line[:256]})
            if len(matches) >= limit:
                return AdapterResult(
                    status=EXECUTION_SUCCEEDED,
                    output={"matches": matches, "truncated": True},
                )
    return AdapterResult(status=EXECUTION_SUCCEEDED, output={"matches": matches, "truncated": False})


async def _hash(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    target = guard.resolve(str(context.input.get("path", "")))
    if not target.is_file():
        return _failed(FILE_NOT_FOUND, guard.relative(target))
    digest = _sha256(target)
    return AdapterResult(
        status=EXECUTION_SUCCEEDED,
        output={"path": guard.relative(target), "sha256": digest},
        evidence_refs=(f"sha256:{digest}",),
    )


async def _stat(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    target = guard.resolve(str(context.input.get("path", "")))
    if not target.exists():
        return _failed(FILE_NOT_FOUND, guard.relative(target))
    stat = target.stat()
    return AdapterResult(
        status=EXECUTION_SUCCEEDED,
        output={
            "path": guard.relative(target),
            "is_file": target.is_file(),
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        },
    )


# --- 写操作 ---


async def _create(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    target = guard.resolve(str(context.input.get("path", "")))
    if target.exists():
        return _failed(FILE_ALREADY_EXISTS, guard.relative(target))
    content = _content(context)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8"))
    return await _finish_write(adapter, guard, context, target, content, created=True)


async def _write(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    target = guard.resolve(str(context.input.get("path", "")))
    content = _content(context)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8"))
    return await _finish_write(adapter, guard, context, target, content, created=False)


async def _patch(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    target = guard.resolve(str(context.input.get("path", "")))
    if not target.is_file():
        return _failed(FILE_NOT_FOUND, guard.relative(target))
    old_text = str(context.input.get("old_text", ""))
    new_text = str(context.input.get("new_text", ""))
    if not old_text:
        return _failed(FILE_OPERATION_FAILED, "old_text 不能为空")
    original = target.read_bytes().decode("utf-8")
    found = original.count(old_text)
    expected = context.input.get("expected_replacements")
    if found == 0 or (expected is not None and found != int(expected)):
        return _failed(
            FILE_PATCH_MISMATCH,
            f"匹配次数 {found} 与预期不一致",
        )
    updated = original.replace(old_text, new_text)
    target.write_bytes(updated.encode("utf-8"))
    result = await _finish_write(adapter, guard, context, target, updated, created=False)
    checks = result.checks + (VerificationCheck("replacements", True, f"替换 {found} 处"),)
    return AdapterResult(
        status=result.status,
        output={**(result.output or {}), "replacements": found},
        checks=checks,
        evidence_refs=result.evidence_refs,
    )


async def _move(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    source = guard.resolve(str(context.input.get("path", "")))
    destination = guard.resolve(str(context.input.get("destination", "")))
    if not source.exists():
        return _failed(FILE_NOT_FOUND, guard.relative(source))
    if destination.exists():
        return _failed(FILE_ALREADY_EXISTS, guard.relative(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return await _finish_write(
        adapter, guard, context, destination, None, created=True, moved_from=guard.relative(source)
    )


async def _rename(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    source = guard.resolve(str(context.input.get("path", "")))
    new_name = str(context.input.get("new_name", "")).strip()
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        return _failed(FILE_OPERATION_FAILED, "new_name 非法")
    if new_name.startswith("."):
        return _failed(FILE_PATH_DENIED, "不允许使用隐藏文件名")
    if not source.exists():
        return _failed(FILE_NOT_FOUND, guard.relative(source))
    destination = guard.resolve(str(source.parent.relative_to(guard.root) / new_name))
    if destination.exists():
        return _failed(FILE_ALREADY_EXISTS, guard.relative(destination))
    source.rename(destination)
    return await _finish_write(
        adapter, guard, context, destination, None, created=True, moved_from=guard.relative(source)
    )


async def _delete(adapter: FileToolAdapter, guard: _PathGuard, context: ToolDispatchContext) -> AdapterResult:
    target = guard.resolve(str(context.input.get("path", "")))
    if not target.is_file():
        return _failed(FILE_NOT_FOUND, guard.relative(target))
    rel = guard.relative(target)
    target.unlink()
    refresh = await _notify_editor(adapter, context, [rel])
    return AdapterResult(
        status=EXECUTION_SUCCEEDED,
        output={"path": rel, "deleted": True},
        checks=(VerificationCheck("file_absent", not target.exists(), rel), refresh),
        evidence_refs=(f"file:{rel}",),
    )


async def _finish_write(
    adapter: FileToolAdapter,
    guard: _PathGuard,
    context: ToolDispatchContext,
    target: Path,
    expected_content: str | None,
    *,
    created: bool,
    moved_from: str | None = None,
) -> AdapterResult:
    rel = guard.relative(target)
    re_read_ok = target.is_file()
    if expected_content is not None and re_read_ok:
        re_read_ok = target.read_bytes().decode("utf-8") == expected_content
    digest = _sha256(target) if target.is_file() else ""
    checks = [
        VerificationCheck("file_exists", target.is_file(), rel),
        VerificationCheck("content_verified", re_read_ok, rel),
    ]
    if target.suffix.lower() in IMPORT_SUFFIXES:
        checks.append(
            VerificationCheck("import_pending", None, "资源导入由编辑器完成，尚未确认")
        )
    refresh = await _notify_editor(adapter, context, [rel])
    checks.append(refresh)
    status = EXECUTION_SUCCEEDED if target.is_file() and re_read_ok else EXECUTION_FAILED
    output: dict[str, Any] = {
        "path": rel,
        "created": created,
        "size": target.stat().st_size if target.is_file() else 0,
        "sha256": digest,
    }
    if moved_from:
        output["moved_from"] = moved_from
    return AdapterResult(
        status=status,
        output=output,
        checks=tuple(checks),
        evidence_refs=(f"file:{rel}", f"sha256:{digest}") if digest else (f"file:{rel}",),
    )


# --- 辅助 ---


def _move_destination(guard: _PathGuard, context: ToolDispatchContext) -> Path | None:
    if context.tool_name == "file.move":
        return guard.resolve(str(context.input.get("destination", "")))
    source = guard.resolve(str(context.input.get("path", "")))
    new_name = str(context.input.get("new_name", "")).strip()
    if not new_name or "/" in new_name or "\\" in new_name:
        return None
    return guard.resolve(str(source.parent.relative_to(guard.root) / new_name))


async def _notify_editor(
    adapter: FileToolAdapter, context: ToolDispatchContext, paths: list[str]
) -> VerificationCheck:
    if adapter._hub is None or not context.session_id:
        return VerificationCheck("editor_refresh", None, "编辑器未连接")
    connection = adapter._hub.get(context.session_id)
    if connection is None:
        return VerificationCheck("editor_refresh", None, "编辑器未连接")
    try:
        response = await connection.send_command(
            EDITOR_COMMAND_ACTION,
            {
                "execution_id": context.execution_id,
                "tool_name": "godot.editor.refresh",
                "tool_version": 0,
                "arguments": {"paths": [f"res://{path}" for path in paths]},
                "resource_scope": list(context.resource_scope),
                "fencing_token": context.fencing_token,
                "phase": "EXECUTE",
            },
            timeout=min(EDITOR_REFRESH_TIMEOUT, context.timeout_seconds),
        )
    except Exception as exc:  # noqa: BLE001 - 刷新失败不阻断写入，但要记录为未确认
        return VerificationCheck("editor_refresh", None, f"{type(exc).__name__}: {exc}"[:256])
    detail = "编辑器已刷新" if response.success else "编辑器刷新失败"
    return VerificationCheck("editor_refresh", response.success, detail)


def _walk_files(guard: _PathGuard, base: Path):
    if base.is_file():
        yield base
        return
    for path in base.rglob("*"):
        if not path.is_file() or _hidden_relative(guard, path):
            continue
        yield path


def _hidden_relative(guard: _PathGuard, path: Path) -> bool:
    try:
        parts = path.relative_to(guard.root).parts
    except ValueError:
        return True
    return any(part.startswith(".") for part in parts)


def _content(context: ToolDispatchContext) -> str:
    value = context.input.get("content", "")
    return value if isinstance(value, str) else str(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _failed(code: str, message: str) -> AdapterResult:
    return AdapterResult(status=EXECUTION_FAILED, error_code=code, error_message=message[:512])


_HANDLERS = {
    "file.read": _read,
    "file.list": _list,
    "file.search": _search,
    "file.create": _create,
    "file.write": _write,
    "file.patch": _patch,
    "file.move": _move,
    "file.rename": _rename,
    "file.delete": _delete,
    "file.hash": _hash,
    "file.stat": _stat,
}
