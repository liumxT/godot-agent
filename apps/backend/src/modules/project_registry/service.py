"""Project Registry / Lifecycle / Configuration（E4-T01…T05）。

状态权威：Project 状态只能由本服务修改；Task/Workflow/Approval/ChangeSet
只通过公开查询接口提供归档阻塞信息，不在此处直接改写其状态。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import InvalidStateTransition, NotFoundError, ValidationFailed, VersionConflict
from core.logging import get_logger, log_event
from core.security.tokens import ensure_utc, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.editor_session.models import EditorSessionModel
from modules.project.service import ProjectService
from modules.project_registry.models import (
    FINGERPRINT_ALGORITHM,
    MEMBER_OWNER,
    MEMBER_ROLES,
    PROJECT_ACTIVE,
    PROJECT_ARCHIVED,
    PROJECT_CLOSED,
    PROJECT_INITIALIZING,
    PROJECT_SUSPENDED,
    PROJECT_TRANSITIONS,
    PROJECT_TYPE_UNKNOWN,
    PROJECT_TYPES,
    ProjectConfigurationModel,
    ProjectConfigurationVersionModel,
    ProjectIdentityModel,
    ProjectMembershipModel,
    ProjectRecordModel,
)
from modules.project_registry.repository import (
    ProjectConfigurationRepository,
    ProjectConfigurationVersionRepository,
    ProjectIdentityRepository,
    ProjectMembershipRepository,
    ProjectRecordRepository,
)

_ID_PREFIX = "prj_"
_MAX_NAME = 256
_CONFIG_FIELDS = (
    "default_game_type",
    "default_language",
    "preferred_rendering_method",
    "target_platforms",
    "godot_version_policy",
    "default_ai_model",
    "default_agent_profile",
    "coding_conventions",
    "naming_conventions",
    "asset_policy",
    "verification_policy",
    "approval_policy",
)

BlockerCheck = Callable[[str], Awaitable[dict[str, int]]]


@dataclass(frozen=True)
class ProjectView:
    project_id: str
    name: str
    description: str | None
    project_root: str
    project_fingerprint: str
    godot_version: str | None
    project_type: str
    status: str
    configuration_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class ConfigurationView:
    project_id: str
    values: dict[str, Any]
    version: int
    updated_at: datetime


@dataclass(frozen=True)
class MembershipView:
    membership_id: str
    project_id: str
    client_id: str
    role: str
    created_at: datetime


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _project_view(entity: ProjectRecordModel) -> ProjectView:
    return ProjectView(
        project_id=entity.project_id,
        name=entity.name,
        description=entity.description,
        project_root=entity.project_root,
        project_fingerprint=entity.project_fingerprint,
        godot_version=entity.godot_version,
        project_type=entity.project_type,
        status=entity.status,
        configuration_id=entity.configuration_id,
        version=entity.version,
        created_at=ensure_utc(entity.created_at),
        updated_at=ensure_utc(entity.updated_at),
        archived_at=ensure_utc(entity.archived_at) if entity.archived_at else None,
    )


def _config_view(entity: ProjectConfigurationModel) -> ConfigurationView:
    values = {field: getattr(entity, field) for field in _CONFIG_FIELDS}
    return ConfigurationView(
        project_id=entity.project_id,
        values=values,
        version=entity.version,
        updated_at=ensure_utc(entity.updated_at),
    )


def _membership_view(entity: ProjectMembershipModel) -> MembershipView:
    return MembershipView(
        membership_id=entity.membership_id,
        project_id=entity.project_id,
        client_id=entity.client_id,
        role=entity.role,
        created_at=ensure_utc(entity.created_at),
    )


class ProjectRegistryService:
    """项目注册、查询、更新与身份复核。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        identity: ProjectService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._identity = identity
        self._clock = clock
        self._logger = get_logger("backend.project")

    async def register(
        self,
        *,
        project_root: str,
        name: str | None = None,
        description: str | None = None,
        project_type: str = PROJECT_TYPE_UNKNOWN,
        godot_version: str | None = None,
        created_by: str | None = None,
    ) -> ProjectView:
        if project_type not in PROJECT_TYPES:
            raise ValidationFailed("project_type 非法", details={"project_type": project_type})
        identity = await self._identity.resolve(
            project_root=project_root,
            project_name=name,
            godot_version=godot_version,
        )
        now = self._clock()
        display = (name or identity.project_name).strip()[:_MAX_NAME]

        async with self._database.session() as session, transaction(session):
            records = ProjectRecordRepository(session)
            entity = await records.get(identity.project_id)
            if entity is None:
                entity = ProjectRecordModel(
                    project_id=identity.project_id,
                    name=display,
                    description=description,
                    project_root=identity.project_root,
                    project_fingerprint=identity.project_fingerprint,
                    godot_version=godot_version,
                    project_type=project_type,
                    status=PROJECT_INITIALIZING,
                    configuration_id=None,
                    version=1,
                    created_at=now,
                    updated_at=now,
                    archived_at=None,
                )
                await records.add(entity)
                await ProjectIdentityRepository(session).add(
                    ProjectIdentityModel(
                        project_id=entity.project_id,
                        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
                        fingerprint_value=identity.project_fingerprint,
                        project_config_path=f"{identity.project_root}/project.godot",
                        last_verified_at=now,
                    )
                )
                await self._ensure_configuration(session, entity, created_by=created_by, now=now)
                if created_by:
                    await self._ensure_membership(
                        session, entity.project_id, created_by, MEMBER_OWNER, now
                    )
            entity.status = PROJECT_ACTIVE
            entity.updated_at = now
            await session.flush()
            view = _project_view(entity)

        log_event(self._logger, logging.INFO, "project_registered", component="project")
        return view

    async def get(self, project_id: str) -> ProjectView:
        async with self._database.session() as session:
            entity = await ProjectRecordRepository(session).get(project_id)
        if entity is None:
            raise NotFoundError("项目不存在", details={"project_id": project_id})
        return _project_view(entity)

    async def list(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await ProjectRecordRepository(session).list_page(
                status=status, limit=limit, offset=offset
            )
        return {
            "items": [_project_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        project_type: str | None = None,
        expected_version: int | None = None,
    ) -> ProjectView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ProjectRecordRepository(session).get(project_id)
            if entity is None:
                raise NotFoundError("项目不存在", details={"project_id": project_id})
            if expected_version is not None and entity.version != expected_version:
                raise VersionConflict(
                    "项目版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            if name is not None:
                entity.name = name.strip()[:_MAX_NAME] or entity.name
            if description is not None:
                entity.description = description
            if project_type is not None:
                if project_type not in PROJECT_TYPES:
                    raise ValidationFailed("project_type 非法")
                entity.project_type = project_type
            entity.version += 1
            entity.updated_at = now
            await session.flush()
            view = _project_view(entity)
        log_event(self._logger, logging.INFO, "project_updated", component="project")
        return view

    async def verify_identity(self, project_id: str) -> ProjectView:
        """重新 realpath + 重算指纹，确认项目未被移动或替换。"""

        async with self._database.session() as session:
            entity = await ProjectRecordRepository(session).get(project_id)
        if entity is None:
            raise NotFoundError("项目不存在", details={"project_id": project_id})
        resolved = await self._identity.resolve(
            project_root=entity.project_root,
            project_name=entity.name,
            godot_version=entity.godot_version,
        )
        if resolved.project_id != project_id:
            raise ValidationFailed("项目身份无法验证", details={"project_id": project_id})
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            identity = await ProjectIdentityRepository(session).get(project_id)
            if identity is not None:
                identity.last_verified_at = now
                identity.fingerprint_value = resolved.project_fingerprint
            record = await ProjectRecordRepository(session).get(project_id)
            if record is not None:
                record.updated_at = now
                await session.flush()
                return _project_view(record)
        raise NotFoundError("项目不存在", details={"project_id": project_id})

    async def resolve_from_editor_session(self, session_id: str) -> ProjectView:
        """同一项目可由多个 Editor 打开；这里只返回 Session 当前绑定的项目。"""

        async with self._database.session() as session:
            binding = await session.get(EditorSessionModel, session_id)
            if binding is None:
                raise NotFoundError("Editor Session 未绑定项目")
            entity = await ProjectRecordRepository(session).get(binding.project_id)
        if entity is None:
            raise NotFoundError("项目未注册", details={"project_id": binding.project_id})
        return _project_view(entity)

    async def add_membership(
        self, project_id: str, *, client_id: str, role: str = MEMBER_OWNER
    ) -> MembershipView:
        if role not in MEMBER_ROLES:
            raise ValidationFailed("项目成员角色非法", details={"role": role})
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await self._ensure_membership(session, project_id, client_id, role, now)
            view = _membership_view(entity)
        return view

    async def list_memberships(self, project_id: str) -> list[MembershipView]:
        async with self._database.session() as session:
            rows = await ProjectMembershipRepository(session).list_by_project(project_id)
        return [_membership_view(row) for row in rows]

    async def _ensure_configuration(
        self,
        session,
        entity: ProjectRecordModel,
        *,
        created_by: str | None,
        now: datetime,
    ) -> None:
        configuration = ProjectConfigurationModel(
            project_id=entity.project_id,
            version=1,
            updated_at=now,
        )
        await ProjectConfigurationRepository(session).add(configuration)
        version = ProjectConfigurationVersionModel(
            version_id=_new_id("pcfg_"),
            project_id=entity.project_id,
            version_no=1,
            config_json=json.dumps(
                {field: None for field in _CONFIG_FIELDS}, ensure_ascii=False, sort_keys=True
            ),
            created_by=created_by,
            created_at=now,
        )
        await ProjectConfigurationVersionRepository(session).add(version)
        entity.configuration_id = version.version_id

    async def _ensure_membership(
        self, session, project_id: str, client_id: str, role: str, now: datetime
    ) -> ProjectMembershipModel:
        repository = ProjectMembershipRepository(session)
        rows = await repository.list_by_project(project_id)
        for row in rows:
            if row.client_id == client_id:
                row.role = role
                await session.flush()
                return row
        entity = ProjectMembershipModel(
            membership_id=_new_id("pmb_"),
            project_id=project_id,
            client_id=client_id,
            role=role,
            created_at=now,
        )
        await repository.add(entity)
        return entity


class ProjectConfigurationService:
    """项目配置读取与版本化更新。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._clock = clock

    async def get(self, project_id: str) -> ConfigurationView:
        async with self._database.session() as session:
            entity = await ProjectConfigurationRepository(session).get(project_id)
        if entity is None:
            raise NotFoundError("项目配置不存在", details={"project_id": project_id})
        return _config_view(entity)

    async def update(
        self,
        project_id: str,
        changes: dict[str, Any],
        *,
        actor: str | None = None,
        expected_version: int | None = None,
    ) -> ConfigurationView:
        unknown = set(changes) - set(_CONFIG_FIELDS)
        if unknown:
            raise ValidationFailed("存在未知配置字段", details={"fields": sorted(unknown)})
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ProjectConfigurationRepository(session).get(project_id)
            if entity is None:
                raise NotFoundError("项目配置不存在", details={"project_id": project_id})
            if expected_version is not None and entity.version != expected_version:
                raise VersionConflict(
                    "配置版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            for field, value in changes.items():
                setattr(entity, field, value)
            entity.version += 1
            entity.updated_at = now
            version = ProjectConfigurationVersionModel(
                version_id=_new_id("pcfg_"),
                project_id=project_id,
                version_no=entity.version,
                config_json=json.dumps(
                    {field: getattr(entity, field) for field in _CONFIG_FIELDS},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                created_by=actor,
                created_at=now,
            )
            await ProjectConfigurationVersionRepository(session).add(version)
            record = await ProjectRecordRepository(session).get(project_id)
            if record is not None:
                record.configuration_id = version.version_id
                record.updated_at = now
            await session.flush()
            view = _config_view(entity)
        return view

    async def list_versions(self, project_id: str) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            rows = await ProjectConfigurationVersionRepository(session).list_by_project(project_id)
        return [
            {
                "version_id": row.version_id,
                "version_no": row.version_no,
                "config": json.loads(row.config_json),
                "created_by": row.created_by,
                "created_at": ensure_utc(row.created_at),
            }
            for row in rows
        ]


class ProjectLifecycleService:
    """Project 状态机；归档前通过 ``blockers`` 汇总未完成操作。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        blockers: BlockerCheck | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._database = database
        self._blockers = blockers
        self._clock = clock
        self._logger = get_logger("backend.project")

    async def activate(self, project_id: str) -> ProjectView:
        return await self.transition(project_id, PROJECT_ACTIVE)

    async def suspend(self, project_id: str) -> ProjectView:
        return await self.transition(project_id, PROJECT_SUSPENDED)

    async def resume(self, project_id: str) -> ProjectView:
        return await self.transition(project_id, PROJECT_ACTIVE)

    async def close(self, project_id: str) -> ProjectView:
        return await self.transition(project_id, PROJECT_CLOSED)

    async def reactivate(self, project_id: str) -> ProjectView:
        return await self.transition(project_id, PROJECT_ACTIVE)

    async def archive(self, project_id: str, *, force: bool = False) -> ProjectView:
        if self._blockers is not None:
            summary = await self._blockers(project_id)
            pending = {key: value for key, value in summary.items() if value}
            if pending and not force:
                raise InvalidStateTransition(
                    "项目存在未完成操作，需要先处理或显式强制归档",
                    details={"project_id": project_id, "blockers": pending},
                )
        return await self.transition(project_id, PROJECT_ARCHIVED, force=force)

    async def transition(self, project_id: str, target: str, *, force: bool = False) -> ProjectView:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            entity = await ProjectRecordRepository(session).get(project_id)
            if entity is None:
                raise NotFoundError("项目不存在", details={"project_id": project_id})
            if target != entity.status:
                allowed = PROJECT_TRANSITIONS.get(entity.status, frozenset())
                if target not in allowed:
                    raise InvalidStateTransition(
                        f"非法项目状态迁移: {entity.status} → {target}",
                        details={"project_id": project_id},
                    )
                entity.status = target
            if target == PROJECT_ARCHIVED and entity.archived_at is None:
                entity.archived_at = now
            if target == PROJECT_ACTIVE:
                entity.archived_at = None
            entity.version += 1
            entity.updated_at = now
            await session.flush()
            view = _project_view(entity)
        log_event(
            self._logger,
            logging.INFO,
            "project_lifecycle_changed",
            component="project",
        )
        return view


def format_project(view: ProjectView) -> dict[str, Any]:
    return {
        "project_id": view.project_id,
        "name": view.name,
        "description": view.description,
        "project_root": view.project_root,
        "project_fingerprint": view.project_fingerprint,
        "godot_version": view.godot_version,
        "project_type": view.project_type,
        "status": view.status,
        "configuration_id": view.configuration_id,
        "version": view.version,
        "created_at": ensure_utc(view.created_at).isoformat(),
        "updated_at": ensure_utc(view.updated_at).isoformat(),
        "archived_at": ensure_utc(view.archived_at).isoformat() if view.archived_at else None,
    }


def format_configuration(view: ConfigurationView) -> dict[str, Any]:
    return {
        "project_id": view.project_id,
        "configuration": view.values,
        "version": view.version,
        "updated_at": ensure_utc(view.updated_at).isoformat(),
    }


def format_membership(view: MembershipView) -> dict[str, Any]:
    return {
        "membership_id": view.membership_id,
        "project_id": view.project_id,
        "client_id": view.client_id,
        "role": view.role,
        "created_at": ensure_utc(view.created_at).isoformat(),
    }
