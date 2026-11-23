"""资产内部存储布局（E8-T01 / T02）。

数据库只保存元数据、Hash 与相对路径；资产文件保存在：

    {data_dir}/assets/projects/{project_id}/{area}/...

``source / generated / processed / previews / manifests / temporary`` 与 Godot
项目目录完全隔离。本模块负责路径规范化、越界防护、文件名冲突处理与原子写入。
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4

from core.errors import AssetPathInvalid, AssetStorageError
from modules.asset_pipeline.models import STORAGE_AREAS

_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)

DEFAULT_MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_CONFLICT_SUFFIX = 999


def validate_project_id(project_id: str) -> str:
    if not _PROJECT_ID_PATTERN.match(project_id or ""):
        raise AssetPathInvalid("项目 ID 不合法", details={"project_id": project_id})
    return project_id


def normalize_relative_path(relative_path: str) -> str:
    """规范化内部相对路径，拒绝绝对路径、穿越与平台保留名。"""

    if not relative_path or not relative_path.strip():
        raise AssetPathInvalid("资产路径不能为空")
    candidate = relative_path.replace("\\", "/").strip()
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise AssetPathInvalid("资产路径必须是相对路径", details={"path": relative_path})

    segments = candidate.split("/")
    normalized: list[str] = []
    for segment in segments:
        if segment in ("", "."):
            raise AssetPathInvalid("资产路径包含空段或当前目录", details={"path": relative_path})
        if segment == "..":
            raise AssetPathInvalid("资产路径不能包含 ..", details={"path": relative_path})
        if segment != segment.strip():
            raise AssetPathInvalid("资产路径段不能包含首尾空白", details={"path": relative_path})
        if not _SEGMENT_PATTERN.match(segment):
            raise AssetPathInvalid(
                "资产路径段包含非法字符", details={"path": relative_path, "segment": segment}
            )
        stem = segment.split(".")[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise AssetPathInvalid("资产路径使用系统保留名", details={"segment": segment})
        normalized.append(segment)
    return "/".join(normalized)


class AssetStorage:
    """资产内部暂存区。所有公开方法都只接受项目 ID、区域与相对路径。"""

    def __init__(self, root: Path, *, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self._root = Path(root)
        self._max_file_bytes = max_file_bytes

    @property
    def root(self) -> Path:
        return self._root

    def project_dir(self, project_id: str) -> Path:
        return self._root / "projects" / validate_project_id(project_id)

    def area_dir(self, project_id: str, area: str) -> Path:
        if area not in STORAGE_AREAS:
            raise AssetPathInvalid("未知资产存储区域", details={"area": area})
        return self.project_dir(project_id) / area

    def ensure_layout(self, project_id: str) -> None:
        for area in STORAGE_AREAS:
            self.area_dir(project_id, area).mkdir(parents=True, exist_ok=True)

    def resolve(self, project_id: str, area: str, relative_path: str) -> Path:
        normalized = normalize_relative_path(relative_path)
        base = self.area_dir(project_id, area).resolve()
        target = (base / normalized).resolve()
        if not target.is_relative_to(base):
            raise AssetPathInvalid(
                "资产路径越界", details={"path": relative_path, "area": area}
            )
        return target

    def allocate(
        self, project_id: str, area: str, filename: str, *, create: bool = False
    ) -> tuple[str, Path]:
        """返回未被占用的相对路径；文件名冲突时追加 ``_001`` 等后缀。"""

        normalized = normalize_relative_path(filename)
        if "/" in normalized:
            raise AssetPathInvalid(
                "allocate 只接受文件名", details={"filename": filename}
            )
        stem, suffix = os.path.splitext(normalized)
        candidates = [normalized]
        candidates.extend(f"{stem}_{index:03d}{suffix}" for index in range(1, MAX_CONFLICT_SUFFIX + 1))
        for candidate in candidates:
            target = self.resolve(project_id, area, candidate)
            if not target.exists():
                if create:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch(exist_ok=False)
                return candidate, target
        raise AssetStorageError("无法分配资产文件名", details={"filename": filename})

    def write_bytes(
        self,
        project_id: str,
        area: str,
        relative_path: str,
        data: bytes,
        *,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """原子写入：同目录临时文件 + ``os.replace``。"""

        if len(data) > self._max_file_bytes:
            raise AssetStorageError(
                "资产文件超过大小限制",
                details={"size": len(data), "limit": self._max_file_bytes},
            )
        target = self.resolve(project_id, area, relative_path)
        if target.exists() and not overwrite:
            raise AssetPathInvalid(
                "资产文件已存在，禁止静默覆盖", details={"path": relative_path}
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise AssetStorageError(
                "资产文件写入失败", details={"path": relative_path, "reason": str(exc)}
            ) from exc
        return {
            "relative_path": normalize_relative_path(relative_path),
            "content_hash": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }

    def read_bytes(self, project_id: str, area: str, relative_path: str) -> bytes:
        target = self.resolve(project_id, area, relative_path)
        if not target.is_file():
            raise AssetStorageError(
                "资产文件不存在", details={"path": relative_path, "area": area}
            )
        try:
            return target.read_bytes()
        except OSError as exc:
            raise AssetStorageError(
                "资产文件读取失败", details={"path": relative_path, "reason": str(exc)}
            ) from exc

    def hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with Path(path).open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise AssetStorageError(
                "资产文件读取失败", details={"path": str(path), "reason": str(exc)}
            ) from exc
        return digest.hexdigest()
