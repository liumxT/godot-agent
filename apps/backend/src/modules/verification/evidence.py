"""证据有效性与完整性检查（E9-T13）。

证据必须可追溯到真实来源；文件型证据要校验路径与 Hash。缺少运行环境、
项目版本等上下文的证据视为不可追溯，不能用于质量判定。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

REQUIRED_CONTEXT_BY_TYPE: dict[str, tuple[str, ...]] = {
    "SCREENSHOT": ("project_revision", "runtime_instance_id"),
    "VIDEO": ("project_revision", "runtime_instance_id"),
    "RUNTIME_TRACE": ("project_revision", "runtime_instance_id"),
    "PERFORMANCE_SAMPLE": ("project_revision",),
    "DIFF": ("project_revision",),
}


def evidence_context_problems(
    evidence_type: str, metadata: dict[str, Any]
) -> tuple[str, ...]:
    problems: list[str] = []
    for key in REQUIRED_CONTEXT_BY_TYPE.get(evidence_type, ()):
        if not metadata.get(key):
            problems.append(f"证据缺少上下文: {key}")
    return tuple(problems)


def file_reference_path(reference: str) -> Path | None:
    if not reference.startswith("file://"):
        return None
    raw = reference[len("file://") :]
    # Windows 的 file:///d:/x 去掉前导斜杠，避免出现 /d:/x
    if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        raw = raw[1:]
    return Path(raw)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file_reference(reference: str, expected_hash: str) -> tuple[str, ...]:
    """校验文件型证据是否存在且 Hash 一致。"""

    path = file_reference_path(reference)
    if path is None:
        return ()
    if not path.is_file():
        return (f"证据文件不存在: {reference}",)
    try:
        actual = file_sha256(path)
    except OSError as exc:
        return (f"证据文件无法读取: {exc}",)
    if actual != expected_hash:
        return (f"证据 Hash 不一致: {reference}",)
    return ()
