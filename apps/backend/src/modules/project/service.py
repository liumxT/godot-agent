"""项目身份解析（E3-T14 前置）。

服务端不信任客户端提交的路径：重新 ``realpath``、确认 ``project.godot``
可读并重算指纹。``project_id`` 由路径稳定推导，路径变化即视为不同项目。
"""

from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.errors import ValidationFailed
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.project.models import ProjectModel
from modules.project.repository import ProjectRepository

PROJECT_ID_PREFIX = "prj_"
PROJECT_FILE_NAME = "project.godot"
MAX_PROJECT_NAME_LENGTH = 256


@dataclass(frozen=True)
class ProjectView:
    project_id: str
    project_root: str
    project_fingerprint: str
    project_name: str
    godot_version: str | None
    created_at: datetime
    last_seen_at: datetime


def _view(entity: ProjectModel) -> ProjectView:
    return ProjectView(
        project_id=entity.project_id,
        project_root=entity.project_root,
        project_fingerprint=entity.project_fingerprint,
        project_name=entity.project_name,
        godot_version=entity.godot_version,
        created_at=ensure_utc(entity.created_at),
        last_seen_at=ensure_utc(entity.last_seen_at),
    )


def project_fingerprint(project_root: Path) -> str:
    return hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()


def project_id_for(project_root: Path) -> str:
    """``prj_`` + sha256(realpath) 的 base32 前 12 位。"""

    digest = hashlib.sha256(str(project_root).encode("utf-8")).digest()
    encoded = base64.b32encode(digest[:8]).decode("ascii").lower().rstrip("=")
    return PROJECT_ID_PREFIX + encoded[:12]


class ProjectService:
    """项目解析与临时记录；不判断访问权限，也不阻塞连接。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._clock = clock
        self._logger = get_logger("backend.bridge")

    async def resolve(
        self,
        *,
        project_root: str,
        project_name: str | None = None,
        godot_version: str | None = None,
    ) -> ProjectView:
        root = self._normalize_root(project_root)
        fingerprint = project_fingerprint(root)
        project_id = project_id_for(root)
        display_name = (project_name or root.name).strip()[:MAX_PROJECT_NAME_LENGTH]
        now = self._clock()

        async with self._database.session() as session, transaction(session):
            repository = ProjectRepository(session)
            entity = await repository.get(project_id)
            if entity is None:
                same_root = await repository.get_by_root(str(root))
                if same_root is not None:
                    raise ValidationFailed(
                        "项目根目录已被其他项目占用",
                        details={"project_id": same_root.project_id},
                    )
                entity = ProjectModel(
                    project_id=project_id,
                    project_root=str(root),
                    project_fingerprint=fingerprint,
                    project_name=display_name,
                    godot_version=godot_version,
                    created_at=now,
                    last_seen_at=now,
                )
                await repository.add(entity)
            else:
                if entity.project_fingerprint != fingerprint:
                    raise ValidationFailed(
                        "项目身份与已登记记录不一致",
                        details={"project_id": project_id},
                    )
                entity.project_name = display_name
                if godot_version:
                    entity.godot_version = godot_version
                entity.last_seen_at = now
            view = _view(entity)

        log_event(
            self._logger,
            logging.INFO,
            "bridge_project_bound",
            component="bridge",
        )
        return view

    async def get(self, project_id: str) -> ProjectView | None:
        """按 ``project_id`` 读取已登记项目；不存在时返回 ``None``。"""

        async with self._database.session() as session:
            entity = await ProjectRepository(session).get(project_id)
        return _view(entity) if entity is not None else None

    async def find_by_fingerprint(self, fingerprint: str) -> ProjectView | None:
        """Runtime 只携带 ``res://`` 根路径，用指纹匹配已登记项目。"""

        async with self._database.session() as session:
            entity = await ProjectRepository(session).get_by_fingerprint(fingerprint)
        return _view(entity) if entity is not None else None

    def _normalize_root(self, project_root: str) -> Path:
        raw = (project_root or "").strip()
        if not raw:
            raise ValidationFailed("缺少项目根目录")
        try:
            root = Path(raw).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValidationFailed("项目根目录不可访问") from exc
        if not root.is_dir():
            raise ValidationFailed("项目根目录不是目录")
        project_file = root / PROJECT_FILE_NAME
        if not project_file.is_file():
            raise ValidationFailed("项目根目录缺少 project.godot")
        try:
            project_file.read_bytes()
        except OSError as exc:
            raise ValidationFailed("project.godot 不可读") from exc
        return root
