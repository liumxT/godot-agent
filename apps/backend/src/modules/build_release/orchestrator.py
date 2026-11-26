"""构建编排与恢复（E10-T05 / T17）。

编排器只拥有 Build / Build Attempt 状态：

- 启动构建立前必须通过配置、环境、Preset 与平台能力门禁；
- 所有实际执行都经过受控执行器；
- 退出码为 0 但无可运行产物视为失败（P05）；
- 超时或结果不明确进入 UNKNOWN，必须先核对产物再收敛（P06）；
- 重试必须创建新的 Attempt，不覆盖旧记录。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.errors import (
    BuildEnvironmentNotReady,
    BuildExecutorError,
    BuildRecoveryRequired,
    BuildStateInvalid,
    ExportPresetInvalid,
    NotFoundError,
    ValidationFailed,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.adapter import (
    EXEC_TIMEOUT,
    EXEC_UNDETERMINED,
    BuildExecutor,
    ExecutionResult,
    GodotHeadlessAdapter,
    PlatformExportAdapter,
    redact_text,
)
from modules.build_release.models import (
    ATTEMPT_FAILED,
    ATTEMPT_RUNNING,
    ATTEMPT_SUCCEEDED,
    ATTEMPT_UNKNOWN,
    BUILD_CANCELLED,
    BUILD_COLLECTING,
    BUILD_EXPORTING,
    BUILD_FAILED,
    BUILD_PREPARING,
    BUILD_QUEUED,
    BUILD_RUNNING,
    BUILD_SUCCEEDED,
    BUILD_TRANSITIONS,
    BUILD_UNKNOWN,
    BuildAttemptModel,
    BuildJobModel,
    BuildLogModel,
)
from modules.build_release.repository import (
    BuildAttemptRepository,
    BuildJobRepository,
    BuildLogRepository,
)
from modules.build_release.service import BuildReleaseService

ERROR_OUTPUT_MISSING = "BUILD_OUTPUT_MISSING"
ERROR_EXIT_NONZERO = "BUILD_EXIT_NONZERO"
ERROR_TIMEOUT = "BUILD_TIMEOUT"
ERROR_UNDETERMINED = "BUILD_UNDETERMINED"
ERROR_GATE_FAILED = "BUILD_GATE_FAILED"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def ensure_build_transition(current: str, target: str) -> None:
    if target not in BUILD_TRANSITIONS.get(current, frozenset()):
        raise BuildStateInvalid("构建状态迁移非法", details={"from": current, "to": target})


@dataclass(frozen=True, slots=True)
class BuildJobView:
    build_id: str
    project_id: str
    build_config_id: str | None
    build_config_version: int
    source_revision: str
    changeset_id: str | None
    environment_id: str | None
    status: str
    current_attempt_id: str | None
    executor_id: str | None
    error_code: str | None
    requested_by: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class BuildAttemptView:
    attempt_id: str
    build_id: str
    attempt_number: int
    status: str
    executor_id: str
    exit_code: int | None
    error_code: str | None
    output_manifest: list[dict[str, Any]]
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class BuildRecoveryView:
    build_id: str
    previous_status: str
    resolved_status: str
    has_output: bool
    reason: str


def _job_view(entity: BuildJobModel) -> BuildJobView:
    return BuildJobView(
        build_id=entity.build_id,
        project_id=entity.project_id,
        build_config_id=entity.build_config_id,
        build_config_version=entity.build_config_version,
        source_revision=entity.source_revision,
        changeset_id=entity.changeset_id,
        environment_id=entity.environment_id,
        status=entity.status,
        current_attempt_id=entity.current_attempt_id,
        executor_id=entity.executor_id,
        error_code=entity.error_code,
        requested_by=entity.requested_by,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
    )


def _attempt_view(entity: BuildAttemptModel) -> BuildAttemptView:
    return BuildAttemptView(
        attempt_id=entity.attempt_id,
        build_id=entity.build_id,
        attempt_number=entity.attempt_number,
        status=entity.status,
        executor_id=entity.executor_id,
        exit_code=entity.exit_code,
        error_code=entity.error_code,
        output_manifest=_load(entity.output_manifest_json, []),
        started_at=entity.started_at,
        finished_at=entity.finished_at,
    )


def _new_id(prefix: str) -> str:
    from uuid import uuid4

    return prefix + uuid4().hex[:12]


class BuildOrchestrator:
    """构建生命周期编排器。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        builds: BuildReleaseService,
        executor: BuildExecutor,
        godot_adapter: GodotHeadlessAdapter | None = None,
        export_adapter: PlatformExportAdapter | None = None,
        projects: Any | None = None,
    ) -> None:
        self._database = database
        self._builds = builds
        self._executor = executor
        self._godot = godot_adapter or GodotHeadlessAdapter()
        self._export = export_adapter or PlatformExportAdapter()
        self._projects = projects

    async def create_build(
        self,
        *,
        project_id: str,
        build_config_id: str,
        environment_id: str,
        source_revision: str = "",
        changeset_id: str | None = None,
        requested_by: str | None = None,
        executor_id: str = "local",
    ) -> BuildJobView:
        if not project_id:
            raise ValidationFailed("project_id 不能为空")
        config = await self._builds.get_configuration(build_config_id)
        if config.project_id != project_id:
            raise ValidationFailed(
                "构建配置不属于该项目",
                details={"build_config_id": build_config_id},
            )
        now = utcnow()
        entity = BuildJobModel(
            build_id=_new_id("bld"),
            project_id=project_id,
            build_config_id=build_config_id,
            build_config_version=config.current_version,
            source_revision=source_revision,
            changeset_id=changeset_id,
            environment_id=environment_id,
            status=BUILD_QUEUED,
            executor_id=executor_id,
            requested_by=requested_by,
            version=1,
            created_at=now,
            updated_at=now,
        )
        async with self._database.session() as session, transaction(session):
            await BuildJobRepository(session).add(entity)
        return _job_view(entity)

    async def start_build(self, build_id: str) -> BuildJobView:
        build = await self._load_build(build_id)
        if build.status == BUILD_UNKNOWN:
            raise BuildRecoveryRequired(
                "构建处于 UNKNOWN，必须先完成状态核对",
                details={"build_id": build_id},
            )
        if build.status != BUILD_QUEUED:
            raise BuildStateInvalid(
                "只有 QUEUED 状态可以启动构建",
                details={"build_id": build_id, "status": build.status},
            )
        prepared = await self._prepare(build)
        result = await self._executor.run(prepared["command"])
        return await self._record(build, prepared, result)

    async def retry_build(self, build_id: str) -> BuildJobView:
        build = await self._load_build(build_id)
        if build.status == BUILD_UNKNOWN:
            raise BuildRecoveryRequired(
                "构建处于 UNKNOWN，必须先完成状态核对再重试",
                details={"build_id": build_id},
            )
        if build.status != BUILD_FAILED:
            raise BuildStateInvalid(
                "只有 FAILED 状态可以重试", details={"build_id": build_id, "status": build.status}
            )
        async with self._database.session() as session, transaction(session):
            entity = await BuildJobRepository(session).get(build_id)
            assert entity is not None
            ensure_build_transition(entity.status, BUILD_QUEUED)
            entity.status = BUILD_QUEUED
            entity.error_code = None
            entity.finished_at = None
            entity.current_attempt_id = None
            entity.version += 1
            entity.updated_at = utcnow()
            await session.flush()
        return await self.start_build(build_id)

    async def cancel_build(self, build_id: str) -> BuildJobView:
        async with self._database.session() as session, transaction(session):
            entity = await BuildJobRepository(session).get(build_id)
            if entity is None:
                raise NotFoundError("构建不存在", details={"build_id": build_id})
            if entity.status not in {
                BUILD_QUEUED,
                BUILD_PREPARING,
                BUILD_RUNNING,
                BUILD_EXPORTING,
                BUILD_COLLECTING,
            }:
                raise BuildStateInvalid(
                    "当前状态不可取消",
                    details={"build_id": build_id, "status": entity.status},
                )
            ensure_build_transition(entity.status, BUILD_CANCELLED)
            entity.status = BUILD_CANCELLED
            entity.cancel_requested_at = utcnow()
            entity.updated_at = utcnow()
            entity.finished_at = utcnow()
            await session.flush()
        return _job_view(entity)

    async def recover_build(self, build_id: str) -> BuildRecoveryView:
        """核对 UNKNOWN 构建的实际产物，而不是直接重跑（T17 / P06）。"""

        build = await self._load_build(build_id)
        if build.status != BUILD_UNKNOWN:
            raise BuildStateInvalid(
                "只有 UNKNOWN 状态需要恢复核对",
                details={"build_id": build_id, "status": build.status},
            )
        attempt = await self._load_current_attempt(build)
        output_dir = await self._output_dir(build, attempt)
        outputs = self._export.collect_outputs(output_dir)
        has_output = bool(outputs["has_output"])
        exit_code = attempt.exit_code if attempt is not None else None

        if exit_code is not None:
            resolved = BUILD_SUCCEEDED if exit_code == 0 and has_output else BUILD_FAILED
            reason = (
                "exit=0 且存在产物"
                if resolved == BUILD_SUCCEEDED
                else f"exit={exit_code} 或产物缺失"
            )
        else:
            resolved = BUILD_SUCCEEDED if has_output else BUILD_FAILED
            reason = "无退出码，依据产物存在性收敛" if has_output else "无退出码且无产物"

        async with self._database.session() as session, transaction(session):
            entity = await BuildJobRepository(session).get(build_id)
            assert entity is not None
            ensure_build_transition(entity.status, resolved)
            entity.status = resolved
            entity.error_code = None if resolved == BUILD_SUCCEEDED else ERROR_UNDETERMINED
            entity.finished_at = utcnow()
            entity.updated_at = utcnow()
            if attempt is not None:
                stored = await BuildAttemptRepository(session).get(attempt.attempt_id)
                if stored is not None:
                    stored.status = (
                        ATTEMPT_SUCCEEDED if resolved == BUILD_SUCCEEDED else ATTEMPT_FAILED
                    )
                    stored.output_manifest_json = _dump(outputs["files"])
                    stored.finished_at = utcnow()
            await session.flush()
        return BuildRecoveryView(
            build_id=build_id,
            previous_status=BUILD_UNKNOWN,
            resolved_status=resolved,
            has_output=has_output,
            reason=reason,
        )

    async def get_build(self, build_id: str) -> BuildJobView:
        return _job_view(await self._load_build(build_id))

    async def list_builds(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await BuildJobRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_job_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def list_attempts(self, build_id: str) -> list[BuildAttemptView]:
        await self._load_build(build_id)
        async with self._database.session() as session:
            rows = await BuildAttemptRepository(session).list_for_build(build_id)
        return [_attempt_view(row) for row in rows]

    # ---- 内部实现 ----

    async def _load_build(self, build_id: str) -> BuildJobModel:
        async with self._database.session() as session:
            entity = await BuildJobRepository(session).get(build_id)
        if entity is None:
            raise NotFoundError("构建不存在", details={"build_id": build_id})
        return entity

    async def _load_current_attempt(self, build: BuildJobModel) -> BuildAttemptModel | None:
        if not build.current_attempt_id:
            return None
        async with self._database.session() as session:
            return await BuildAttemptRepository(session).get(build.current_attempt_id)

    async def _output_dir(self, build: BuildJobModel, attempt: BuildAttemptModel | None) -> Path:
        project_root = await self._project_root(build.project_id)
        number = attempt.attempt_number if attempt is not None else 1
        return project_root / "build" / "e10" / build.build_id / f"attempt-{number}"

    async def _project_root(self, project_id: str) -> Path:
        if self._projects is None:
            raise BuildExecutorError("项目路径解析服务不可用")
        try:
            view = await self._projects.get(project_id)
        except NotFoundError:
            raise BuildExecutorError(
                "项目不存在，无法定位构建目录", details={"project_id": project_id}
            ) from None
        project_root = getattr(view, "project_root", None)
        if not project_root:
            raise BuildExecutorError("项目路径缺失", details={"project_id": project_id})
        return Path(project_root)

    async def _prepare(self, build: BuildJobModel) -> dict[str, Any]:
        """执行启动前门禁与命令构造，不修改持久化状态。"""

        config = await self._builds.get_configuration_version(
            build.build_config_id or "", build.build_config_version
        )
        if build.environment_id is None:
            raise BuildEnvironmentNotReady("构建未绑定环境", details={"build_id": build.build_id})
        environment = await self._builds.require_ready_environment(build.environment_id)
        preset = await self._builds.get_export_preset_by_name(
            build.project_id, config.export_preset_name
        )
        if not preset.template_available:
            raise ExportPresetInvalid("导出模板不可用", details={"preset": preset.preset_name})
        if preset.platform != config.target_platform:
            raise ExportPresetInvalid(
                "Export Preset 平台与配置不匹配",
                details={"preset": preset.platform, "config": config.target_platform},
            )
        capabilities = await self._builds.list_platform_capabilities()
        capability = next(
            (item for item in capabilities if item.platform_id == config.target_platform), None
        )
        problems = self._export.validate(
            platform=config.target_platform,
            architecture=config.architecture,
            capability=capability,
        )
        if problems:
            raise ExportPresetInvalid("平台导出能力校验失败", details={"problems": problems})
        project_root = await self._project_root(build.project_id)

        async with self._database.session() as session:
            attempt_number = await BuildAttemptRepository(session).next_number(build.build_id)

        output_dir = project_root / "build" / "e10" / build.build_id / f"attempt-{attempt_number}"
        output_path = self._export.default_output(
            output_dir, config.target_platform, build.build_id
        )
        command = self._godot.build_command(
            project_root=project_root,
            preset_name=config.export_preset_name,
            output_path=output_path,
            build_mode=config.build_mode,
            timeout_seconds=config.build_timeout_seconds,
            env_allowlist=config.env_allowlist,
            feature_tags=config.feature_tags,
        )
        now = utcnow()
        attempt = BuildAttemptModel(
            attempt_id=_new_id("bat"),
            build_id=build.build_id,
            attempt_number=attempt_number,
            executor_id=build.executor_id or "local",
            status=ATTEMPT_RUNNING,
            command_template_id=command.template_id,
            command_json=_dump(command.display),
            environment_id=build.environment_id,
            environment_fingerprint=environment.environment_fingerprint,
            output_manifest_json="[]",
            started_at=now,
            created_at=now,
        )
        async with self._database.session() as session, transaction(session):
            stored = await BuildJobRepository(session).get(build.build_id)
            assert stored is not None
            ensure_build_transition(stored.status, BUILD_PREPARING)
            stored.status = BUILD_PREPARING
            stored.updated_at = now
            ensure_build_transition(stored.status, BUILD_RUNNING)
            stored.status = BUILD_RUNNING
            stored.started_at = stored.started_at or now
            stored.current_attempt_id = attempt.attempt_id
            stored.updated_at = now
            await BuildAttemptRepository(session).add(attempt)
            await session.flush()
        return {
            "command": command,
            "attempt": attempt,
            "output_dir": output_dir,
        }

    async def _record(
        self,
        build: BuildJobModel,
        prepared: dict[str, Any],
        result: ExecutionResult,
    ) -> BuildJobView:
        attempt: BuildAttemptModel = prepared["attempt"]
        output_dir: Path = prepared["output_dir"]
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            stored = await BuildJobRepository(session).get(build.build_id)
            assert stored is not None
            stored_attempt = await BuildAttemptRepository(session).get(attempt.attempt_id)
            assert stored_attempt is not None
            await self._write_logs(session, stored_attempt.attempt_id, result)
            stored_attempt.exit_code = result.exit_code
            stored_attempt.finished_at = result.finished_at
            stored_attempt.log_reference = f"build_attempt:{stored_attempt.attempt_id}"

            if result.status in {EXEC_TIMEOUT, EXEC_UNDETERMINED}:
                stored_attempt.status = ATTEMPT_UNKNOWN
                ensure_build_transition(stored.status, BUILD_UNKNOWN)
                stored.status = BUILD_UNKNOWN
                stored.error_code = (
                    ERROR_TIMEOUT if result.status == EXEC_TIMEOUT else ERROR_UNDETERMINED
                )
            elif result.succeeded:
                ensure_build_transition(stored.status, BUILD_EXPORTING)
                stored.status = BUILD_EXPORTING
                outputs = self._export.collect_outputs(output_dir)
                stored_attempt.output_manifest_json = _dump(outputs["files"])
                if not outputs["has_output"]:
                    ensure_build_transition(stored.status, BUILD_FAILED)
                    stored.status = BUILD_FAILED
                    stored.error_code = ERROR_OUTPUT_MISSING
                    stored_attempt.status = ATTEMPT_FAILED
                else:
                    ensure_build_transition(stored.status, BUILD_COLLECTING)
                    stored.status = BUILD_COLLECTING
                    ensure_build_transition(stored.status, BUILD_SUCCEEDED)
                    stored.status = BUILD_SUCCEEDED
                    stored.error_code = None
                    stored_attempt.status = ATTEMPT_SUCCEEDED
            else:
                ensure_build_transition(stored.status, BUILD_FAILED)
                stored.status = BUILD_FAILED
                stored.error_code = ERROR_EXIT_NONZERO
                stored_attempt.status = ATTEMPT_FAILED

            stored.finished_at = now
            stored.updated_at = now
            stored.version += 1
            await session.flush()
        return _job_view(stored)

    async def _write_logs(self, session: Any, attempt_id: str, result: ExecutionResult) -> None:
        repo = BuildLogRepository(session)
        sequence = await repo.next_sequence(attempt_id)
        now = utcnow()
        for stream, content in (("stdout", result.stdout), ("stderr", result.stderr)):
            if not content:
                continue
            await repo.add(
                BuildLogModel(
                    log_id=_new_id("blog"),
                    attempt_id=attempt_id,
                    stream=stream,
                    sequence=sequence,
                    content=redact_text(content),
                    created_at=now,
                )
            )
            sequence += 1
