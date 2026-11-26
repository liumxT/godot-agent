"""Build & Release 服务（E10-T02 / T03 / T04）。

职责边界：

- 本服务拥有 Build Configuration / Export Preset / Build Environment 状态；
- 不修改 Project / ChangeSet / Approval / Verification 状态，只保存引用；
- 已用于构建的配置保留不可变快照，修改配置产生新版本；
- 配置中禁止出现明文 Secret；
- 未登记或无导出能力的平台不得显示为可用。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import (
    BuildConfigurationInvalid,
    BuildEnvironmentNotReady,
    ExportPresetInvalid,
    NotFoundError,
    ValidationFailed,
)
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.build_release.models import (
    BUILD_MODE_DEBUG,
    BUILD_MODE_RELEASE,
    BUILD_MODES,
    CAPABILITY_SUPPORTED,
    DESKTOP_PLATFORMS,
    ENV_BLOCKED,
    ENV_READY,
    ENV_READY_WITH_WARNINGS,
    ENVIRONMENT_STATUSES,
    PLATFORM_LINUX,
    PLATFORM_MACOS,
    PLATFORM_WINDOWS,
    BuildConfigurationModel,
    BuildConfigurationVersionModel,
    BuildEnvironmentModel,
    ExportPresetModel,
    PlatformCapabilityModel,
)
from modules.build_release.repository import (
    BuildConfigurationRepository,
    BuildConfigurationVersionRepository,
    BuildEnvironmentRepository,
    ExportPresetRepository,
    PlatformCapabilityRepository,
)

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r'(?i)"(?:password|passwd|secret|api[_-]?key|access[_-]?token)"\s*:\s*"[^"]+"'),
    re.compile(r"(?i)\bpassword\s*[=:]\s*\S+"),
    re.compile(r"(?i)\bsecret\s*[=:]\s*\S+"),
    re.compile(r"(?i)\bapi[_-]?key\s*[=:]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
_ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")

DEFAULT_PLATFORM_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "platform_id": PLATFORM_WINDOWS,
        "platform_name": "Windows Desktop",
        "supported_architectures": ["x86_64", "arm64"],
        "supported_package_formats": ["zip", "folder", "exe"],
        "required_export_templates": ["windows_release"],
        "capability_status": CAPABILITY_SUPPORTED,
    },
    {
        "platform_id": PLATFORM_MACOS,
        "platform_name": "macOS Desktop",
        "supported_architectures": ["x86_64", "arm64"],
        "supported_package_formats": ["zip", "folder", "app"],
        "required_export_templates": ["macos"],
        "capability_status": CAPABILITY_SUPPORTED,
    },
    {
        "platform_id": PLATFORM_LINUX,
        "platform_name": "Linux Desktop",
        "supported_architectures": ["x86_64", "arm64"],
        "supported_package_formats": ["zip", "folder", "binary"],
        "required_export_templates": ["linux"],
        "capability_status": CAPABILITY_SUPPORTED,
    },
)


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _detect_secret(text: str) -> str | None:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


@dataclass(frozen=True, slots=True)
class BuildConfigurationView:
    configuration_id: str
    project_id: str
    name: str
    current_version: int
    target_platform: str
    architecture: str
    created_by: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BuildConfigurationVersionView:
    version_id: str
    configuration_id: str
    project_id: str
    version: int
    godot_version_constraint: str
    target_platform: str
    architecture: str
    renderer: str
    export_preset_name: str
    build_mode: str
    feature_tags: tuple[str, ...]
    output_format: str
    env_allowlist: tuple[str, ...]
    build_timeout_seconds: int
    resource_budget: dict[str, Any]
    packaging_policy: dict[str, Any]
    verification_policy: dict[str, Any]
    config_hash: str
    created_by: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ExportPresetView:
    preset_id: str
    project_id: str
    preset_name: str
    platform: str
    export_mode: str
    export_path: str
    features: tuple[str, ...]
    resource_filters: dict[str, Any]
    template_required: str
    template_available: bool
    status: str
    validation_errors: tuple[str, ...]
    config_hash: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BuildEnvironmentView:
    environment_id: str
    project_id: str | None
    os_name: str
    os_version: str
    cpu_architecture: str
    godot_version: str
    godot_executable_path: str
    godot_executable_hash: str
    export_template_version: str
    toolchain_versions: dict[str, Any]
    sdk_versions: dict[str, Any]
    renderer: str
    build_executor_version: str
    environment_fingerprint: str
    status: str
    diagnostics: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PlatformCapabilityView:
    capability_id: str
    platform_id: str
    platform_name: str
    supported_architectures: tuple[str, ...]
    supported_godot_versions: tuple[str, ...]
    required_export_templates: tuple[str, ...]
    required_sdks: tuple[str, ...]
    required_signing_tools: tuple[str, ...]
    supported_package_formats: tuple[str, ...]
    capability_status: str
    notes: str
    export_enabled: bool


@dataclass(frozen=True, slots=True)
class ConfigurationValidationView:
    ready: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _config_view(entity: BuildConfigurationModel) -> BuildConfigurationView:
    return BuildConfigurationView(
        configuration_id=entity.configuration_id,
        project_id=entity.project_id,
        name=entity.name,
        current_version=entity.current_version,
        target_platform=entity.target_platform,
        architecture=entity.architecture,
        created_by=entity.created_by,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _config_version_view(
    entity: BuildConfigurationVersionModel,
) -> BuildConfigurationVersionView:
    return BuildConfigurationVersionView(
        version_id=entity.version_id,
        configuration_id=entity.configuration_id,
        project_id=entity.project_id,
        version=entity.version,
        godot_version_constraint=entity.godot_version_constraint,
        target_platform=entity.target_platform,
        architecture=entity.architecture,
        renderer=entity.renderer,
        export_preset_name=entity.export_preset_name,
        build_mode=entity.build_mode,
        feature_tags=tuple(_load(entity.feature_tags_json, [])),
        output_format=entity.output_format,
        env_allowlist=tuple(_load(entity.env_allowlist_json, [])),
        build_timeout_seconds=entity.build_timeout_seconds,
        resource_budget=_load(entity.resource_budget_json, {}),
        packaging_policy=_load(entity.packaging_policy_json, {}),
        verification_policy=_load(entity.verification_policy_json, {}),
        config_hash=entity.config_hash,
        created_by=entity.created_by,
        created_at=entity.created_at,
    )


def _preset_view(entity: ExportPresetModel) -> ExportPresetView:
    return ExportPresetView(
        preset_id=entity.preset_id,
        project_id=entity.project_id,
        preset_name=entity.preset_name,
        platform=entity.platform,
        export_mode=entity.export_mode,
        export_path=entity.export_path,
        features=tuple(_load(entity.features_json, [])),
        resource_filters=_load(entity.resource_filters_json, {}),
        template_required=entity.template_required,
        template_available=bool(entity.template_available),
        status=entity.status,
        validation_errors=tuple(_load(entity.validation_errors_json, [])),
        config_hash=entity.config_hash,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _environment_view(entity: BuildEnvironmentModel) -> BuildEnvironmentView:
    return BuildEnvironmentView(
        environment_id=entity.environment_id,
        project_id=entity.project_id,
        os_name=entity.os_name,
        os_version=entity.os_version,
        cpu_architecture=entity.cpu_architecture,
        godot_version=entity.godot_version,
        godot_executable_path=entity.godot_executable_path,
        godot_executable_hash=entity.godot_executable_hash,
        export_template_version=entity.export_template_version,
        toolchain_versions=_load(entity.toolchain_versions_json, {}),
        sdk_versions=_load(entity.sdk_versions_json, {}),
        renderer=entity.renderer,
        build_executor_version=entity.build_executor_version,
        environment_fingerprint=entity.environment_fingerprint,
        status=entity.status,
        diagnostics=_load(entity.diagnostics_json, {}),
        created_at=entity.created_at,
    )


def _capability_view(entity: PlatformCapabilityModel) -> PlatformCapabilityView:
    from modules.build_release.models import EXPORT_ENABLED_CAPABILITY_STATUSES

    return PlatformCapabilityView(
        capability_id=entity.capability_id,
        platform_id=entity.platform_id,
        platform_name=entity.platform_name,
        supported_architectures=tuple(_load(entity.supported_architectures_json, [])),
        supported_godot_versions=tuple(_load(entity.supported_godot_versions_json, [])),
        required_export_templates=tuple(_load(entity.required_export_templates_json, [])),
        required_sdks=tuple(_load(entity.required_sdks_json, [])),
        required_signing_tools=tuple(_load(entity.required_signing_tools_json, [])),
        supported_package_formats=tuple(_load(entity.supported_package_formats_json, [])),
        capability_status=entity.capability_status,
        notes=entity.notes,
        export_enabled=entity.capability_status in EXPORT_ENABLED_CAPABILITY_STATUSES,
    )


class BuildReleaseService:
    """构建配置、Export Preset 与构建环境的唯一入口（Batch A）。"""

    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    # ---- Build Configuration（T02） ----

    async def create_configuration(
        self,
        *,
        project_id: str,
        name: str,
        target_platform: str,
        architecture: str,
        created_by: str | None = None,
        godot_version_constraint: str = "",
        renderer: str = "",
        export_preset_name: str = "",
        build_mode: str = BUILD_MODE_RELEASE,
        feature_tags: list[str] | None = None,
        output_format: str = "",
        env_allowlist: list[str] | None = None,
        build_timeout_seconds: int = 1800,
        resource_budget: dict[str, Any] | None = None,
        packaging_policy: dict[str, Any] | None = None,
        verification_policy: dict[str, Any] | None = None,
    ) -> BuildConfigurationView:
        payload = self._normalize_config(
            target_platform=target_platform,
            architecture=architecture,
            godot_version_constraint=godot_version_constraint,
            renderer=renderer,
            export_preset_name=export_preset_name,
            build_mode=build_mode,
            feature_tags=feature_tags,
            output_format=output_format,
            env_allowlist=env_allowlist,
            build_timeout_seconds=build_timeout_seconds,
            resource_budget=resource_budget,
            packaging_policy=packaging_policy,
            verification_policy=verification_policy,
        )
        if not project_id:
            raise ValidationFailed("project_id 不能为空")
        if not name or not name.strip():
            raise ValidationFailed("构建配置名称不能为空")
        now = utcnow()
        configuration_id = _new_id("bcfg")
        version_id = _new_id("bcfv")
        config_hash = _hash_payload(payload)
        async with self._database.session() as session, transaction(session):
            repo = BuildConfigurationRepository(session)
            if await repo.get_by_name(project_id, name) is not None:
                raise BuildConfigurationInvalid("同名构建配置已存在", details={"name": name})
            entity = BuildConfigurationModel(
                configuration_id=configuration_id,
                project_id=project_id,
                name=name,
                current_version=1,
                target_platform=payload["target_platform"],
                architecture=payload["architecture"],
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            await repo.add(entity)
            await BuildConfigurationVersionRepository(session).add(
                self._version_entity(
                    version_id=version_id,
                    configuration_id=configuration_id,
                    project_id=project_id,
                    version=1,
                    payload=payload,
                    config_hash=config_hash,
                    created_by=created_by,
                    now=now,
                )
            )
        return _config_view(entity)

    async def update_configuration(
        self,
        configuration_id: str,
        *,
        created_by: str | None = None,
        **changes: Any,
    ) -> BuildConfigurationView:
        async with self._database.session() as session, transaction(session):
            repo = BuildConfigurationRepository(session)
            entity = await repo.get(configuration_id)
            if entity is None:
                raise NotFoundError(
                    "构建配置不存在", details={"configuration_id": configuration_id}
                )
            current = await BuildConfigurationVersionRepository(session).get_version(
                configuration_id, entity.current_version
            )
            assert current is not None
            merged = self._merge_payload(current, changes)
            payload = self._normalize_config(**merged)
            new_version = entity.current_version + 1
            now = utcnow()
            config_hash = _hash_payload(payload)
            if config_hash == current.config_hash:
                raise BuildConfigurationInvalid(
                    "配置内容未变化，无需生成新版本",
                    details={"configuration_id": configuration_id},
                )
            await BuildConfigurationVersionRepository(session).add(
                self._version_entity(
                    version_id=_new_id("bcfv"),
                    configuration_id=configuration_id,
                    project_id=entity.project_id,
                    version=new_version,
                    payload=payload,
                    config_hash=config_hash,
                    created_by=created_by,
                    now=now,
                )
            )
            entity.current_version = new_version
            entity.target_platform = payload["target_platform"]
            entity.architecture = payload["architecture"]
            entity.updated_at = now
            await session.flush()
        return _config_view(entity)

    async def get_configuration(self, configuration_id: str) -> BuildConfigurationView:
        async with self._database.session() as session:
            entity = await BuildConfigurationRepository(session).get(configuration_id)
        if entity is None:
            raise NotFoundError("构建配置不存在", details={"configuration_id": configuration_id})
        return _config_view(entity)

    async def get_configuration_version(
        self, configuration_id: str, version: int | None = None
    ) -> BuildConfigurationVersionView:
        async with self._database.session() as session:
            config = await BuildConfigurationRepository(session).get(configuration_id)
            if config is None:
                raise NotFoundError(
                    "构建配置不存在", details={"configuration_id": configuration_id}
                )
            version_repo = BuildConfigurationVersionRepository(session)
            target = version if version is not None else config.current_version
            entity = await version_repo.get_version(configuration_id, target)
        if entity is None:
            raise NotFoundError(
                "构建配置版本不存在",
                details={"configuration_id": configuration_id, "version": version},
            )
        return _config_version_view(entity)

    async def list_configurations(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await BuildConfigurationRepository(session).list_page(
                project_id=project_id, limit=limit, offset=offset
            )
        return {
            "items": [_config_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def validate_configuration(
        self, configuration_id: str, *, version: int | None = None
    ) -> ConfigurationValidationView:
        view = await self.get_configuration_version(configuration_id, version)
        problems: list[str] = []
        warnings: list[str] = []
        async with self._database.session() as session:
            preset = None
            if view.export_preset_name:
                preset = await ExportPresetRepository(session).get_by_name(
                    view.project_id, view.export_preset_name
                )
            capability = await PlatformCapabilityRepository(session).get_by_platform(
                view.target_platform
            )

        if preset is None:
            problems.append(f"Export Preset 不存在: {view.export_preset_name or '(未指定)'}")
        else:
            if preset.platform != view.target_platform:
                problems.append(
                    f"Export Preset 平台不匹配: {preset.platform} != {view.target_platform}"
                )
            if not preset.template_available:
                problems.append(f"导出模板不可用: {preset.template_required}")
        if capability is None:
            problems.append(f"平台能力未登记: {view.target_platform}")
        else:
            from modules.build_release.models import (
                EXPORT_ENABLED_CAPABILITY_STATUSES,
            )

            if capability.capability_status not in EXPORT_ENABLED_CAPABILITY_STATUSES:
                problems.append(
                    f"平台不支持导出: {view.target_platform} ({capability.capability_status})"
                )
            architectures = tuple(_load(capability.supported_architectures_json, []))
            if architectures and view.architecture not in architectures:
                problems.append(f"架构不受支持: {view.architecture} 可选 {sorted(architectures)}")
        if view.build_mode == BUILD_MODE_DEBUG:
            warnings.append("调试模式构建，不可作为正式发布候选")
        return ConfigurationValidationView(ready=not problems, problems=problems, warnings=warnings)

    # ---- Export Preset（T03） ----

    async def register_export_preset(
        self,
        *,
        project_id: str,
        preset_name: str,
        platform: str,
        export_path: str = "",
        export_mode: str = BUILD_MODE_RELEASE,
        features: list[str] | None = None,
        resource_filters: dict[str, Any] | None = None,
        template_required: str = "",
        template_available: bool = False,
        raw: dict[str, Any] | None = None,
    ) -> ExportPresetView:
        if not project_id:
            raise ValidationFailed("project_id 不能为空")
        if not preset_name or not preset_name.strip():
            raise ValidationFailed("Export Preset 名称不能为空")
        if platform not in DESKTOP_PLATFORMS:
            raise ExportPresetInvalid("未知导出平台", details={"platform": platform})
        raw_json = _dump(raw or {})
        if _detect_secret(raw_json):
            raise ExportPresetInvalid("Export Preset 包含疑似明文 Secret，禁止写入普通配置")
        now = utcnow()
        features_list = list(features or [])
        filters = dict(resource_filters or {})
        errors: list[str] = []
        if not template_available:
            errors.append(f"导出模板未安装: {template_required or platform}")
        config_hash = _hash_payload(
            {
                "preset_name": preset_name,
                "platform": platform,
                "export_mode": export_mode,
                "export_path": export_path,
                "features": features_list,
                "resource_filters": filters,
            }
        )
        async with self._database.session() as session, transaction(session):
            repo = ExportPresetRepository(session)
            existing = await repo.get_by_name(project_id, preset_name)
            if existing is not None:
                if existing.config_hash != config_hash:
                    raise ExportPresetInvalid(
                        "Export Preset 已变化，请通过 ChangeSet 审批后再导入",
                        details={"preset_name": preset_name},
                    )
                return _preset_view(existing)
            entity = ExportPresetModel(
                preset_id=_new_id("bpre"),
                project_id=project_id,
                preset_name=preset_name,
                platform=platform,
                export_mode=export_mode,
                export_path=export_path,
                features_json=_dump(features_list),
                resource_filters_json=_dump(filters),
                template_required=template_required,
                template_available=bool(template_available),
                status="VALID" if not errors else "INVALID",
                validation_errors_json=_dump(errors),
                raw_json=raw_json,
                config_hash=config_hash,
                created_at=now,
                updated_at=now,
            )
            await repo.add(entity)
        return _preset_view(entity)

    async def list_export_presets(
        self, project_id: str, *, platform: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await ExportPresetRepository(session).list_page(
                project_id=project_id, platform=platform, limit=limit, offset=offset
            )
        return {
            "items": [_preset_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def get_export_preset(self, preset_id: str) -> ExportPresetView:
        async with self._database.session() as session:
            entity = await ExportPresetRepository(session).get(preset_id)
        if entity is None:
            raise NotFoundError("Export Preset 不存在", details={"preset_id": preset_id})
        return _preset_view(entity)

    async def get_export_preset_by_name(
        self, project_id: str, preset_name: str
    ) -> ExportPresetView:
        async with self._database.session() as session:
            entity = await ExportPresetRepository(session).get_by_name(project_id, preset_name)
        if entity is None:
            raise ExportPresetInvalid("Export Preset 不存在", details={"preset_name": preset_name})
        return _preset_view(entity)

    # ---- Build Environment（T04） ----

    async def register_environment(
        self,
        *,
        project_id: str | None,
        os_name: str,
        os_version: str,
        cpu_architecture: str,
        godot_version: str,
        godot_executable_path: str = "",
        godot_executable_hash: str = "",
        export_template_version: str = "",
        toolchain_versions: dict[str, Any] | None = None,
        sdk_versions: dict[str, Any] | None = None,
        renderer: str = "",
        build_executor_version: str = "",
        target_platform: str | None = None,
        required_platforms: list[str] | None = None,
    ) -> BuildEnvironmentView:
        if not os_name:
            raise ValidationFailed("os_name 不能为空")
        if not godot_version:
            raise ValidationFailed("godot_version 不能为空")
        if _detect_secret(godot_executable_path):
            raise ValidationFailed("路径包含疑似敏感信息")
        toolchains = dict(toolchain_versions or {})
        sdks = dict(sdk_versions or {})
        fingerprint = _hash_payload(
            {
                "os_name": os_name,
                "os_version": os_version,
                "cpu_architecture": cpu_architecture,
                "godot_version": godot_version,
                "godot_executable_hash": godot_executable_hash,
                "export_template_version": export_template_version,
                "toolchain_versions": toolchains,
                "sdk_versions": sdks,
                "renderer": renderer,
                "build_executor_version": build_executor_version,
            }
        )
        status, diagnostics = self._evaluate_environment(
            godot_version=godot_version,
            export_template_version=export_template_version,
            toolchain_versions=toolchains,
            sdk_versions=sdks,
            target_platform=target_platform,
            required_platforms=required_platforms,
        )
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            repo = BuildEnvironmentRepository(session)
            existing = await repo.get_by_fingerprint(project_id, fingerprint)
            if existing is not None:
                return _environment_view(existing)
            entity = BuildEnvironmentModel(
                environment_id=_new_id("benv"),
                project_id=project_id,
                os_name=os_name,
                os_version=os_version,
                cpu_architecture=cpu_architecture,
                godot_version=godot_version,
                godot_executable_path=godot_executable_path,
                godot_executable_hash=godot_executable_hash,
                export_template_version=export_template_version,
                toolchain_versions_json=_dump(toolchains),
                sdk_versions_json=_dump(sdks),
                renderer=renderer,
                build_executor_version=build_executor_version,
                environment_fingerprint=fingerprint,
                status=status,
                diagnostics_json=_dump(diagnostics),
                created_at=now,
            )
            await repo.add(entity)
        return _environment_view(entity)

    async def get_environment(self, environment_id: str) -> BuildEnvironmentView:
        async with self._database.session() as session:
            entity = await BuildEnvironmentRepository(session).get(environment_id)
        if entity is None:
            raise NotFoundError("构建环境不存在", details={"environment_id": environment_id})
        return _environment_view(entity)

    async def list_environments(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in ENVIRONMENT_STATUSES:
            raise ValidationFailed("未知环境状态", details={"status": status})
        async with self._database.session() as session:
            page = await BuildEnvironmentRepository(session).list_page(
                project_id=project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_environment_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def require_ready_environment(self, environment_id: str) -> BuildEnvironmentView:
        """构建前环境门禁：BLOCKED / UNKNOWN 不得启动构建。"""

        view = await self.get_environment(environment_id)
        if view.status not in {ENV_READY, ENV_READY_WITH_WARNINGS}:
            raise BuildEnvironmentNotReady(
                "构建环境未就绪",
                details={"environment_id": environment_id, "status": view.status},
            )
        return view

    # ---- Platform Capability（T07 基础） ----

    async def ensure_platform_capabilities(self) -> None:
        now = utcnow()
        payload = [("bcap", capability, now) for capability in DEFAULT_PLATFORM_CAPABILITIES]
        async with self._database.session() as session, transaction(session):
            repo = PlatformCapabilityRepository(session)
            for _, capability, created_at in payload:
                existing = await repo.get_by_platform(capability["platform_id"])
                if existing is not None:
                    continue
                await repo.add(
                    PlatformCapabilityModel(
                        capability_id=_new_id("bcap"),
                        platform_id=capability["platform_id"],
                        platform_name=capability["platform_name"],
                        supported_architectures_json=_dump(
                            capability.get("supported_architectures", [])
                        ),
                        supported_godot_versions_json=_dump(
                            capability.get("supported_godot_versions", [])
                        ),
                        required_export_templates_json=_dump(
                            capability.get("required_export_templates", [])
                        ),
                        required_sdks_json=_dump(capability.get("required_sdks", [])),
                        required_signing_tools_json=_dump(
                            capability.get("required_signing_tools", [])
                        ),
                        supported_package_formats_json=_dump(
                            capability.get("supported_package_formats", [])
                        ),
                        capability_status=capability["capability_status"],
                        notes=capability.get("notes", ""),
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )

    async def list_platform_capabilities(self) -> list[PlatformCapabilityView]:
        async with self._database.session() as session:
            rows = await PlatformCapabilityRepository(session).list_all()
        return [_capability_view(row) for row in rows]

    # ---- 内部辅助 ----

    def _normalize_config(
        self,
        *,
        target_platform: str,
        architecture: str,
        godot_version_constraint: str = "",
        renderer: str = "",
        export_preset_name: str = "",
        build_mode: str = BUILD_MODE_RELEASE,
        feature_tags: list[str] | None = None,
        output_format: str = "",
        env_allowlist: list[str] | None = None,
        build_timeout_seconds: int = 1800,
        resource_budget: dict[str, Any] | None = None,
        packaging_policy: dict[str, Any] | None = None,
        verification_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if target_platform not in DESKTOP_PLATFORMS:
            raise BuildConfigurationInvalid(
                "首期仅支持桌面平台",
                details={"target_platform": target_platform, "allowed": list(DESKTOP_PLATFORMS)},
            )
        if not architecture:
            raise BuildConfigurationInvalid("architecture 不能为空")
        if build_mode not in BUILD_MODES:
            raise BuildConfigurationInvalid("未知构建模式", details={"build_mode": build_mode})
        if not 1 <= int(build_timeout_seconds) <= 7200:
            raise BuildConfigurationInvalid(
                "构建超时必须在 1–7200 秒之间",
                details={"build_timeout_seconds": build_timeout_seconds},
            )
        allowlist = list(env_allowlist or [])
        for entry in allowlist:
            if not _ENV_NAME_PATTERN.match(entry):
                raise BuildConfigurationInvalid("环境变量白名单格式非法", details={"entry": entry})
        tags = list(feature_tags or [])
        budget = dict(resource_budget or {})
        packaging = dict(packaging_policy or {})
        verification = dict(verification_policy or {})
        payload = {
            "godot_version_constraint": godot_version_constraint,
            "target_platform": target_platform,
            "architecture": architecture,
            "renderer": renderer,
            "export_preset_name": export_preset_name,
            "build_mode": build_mode,
            "feature_tags": tags,
            "output_format": output_format,
            "env_allowlist": allowlist,
            "build_timeout_seconds": int(build_timeout_seconds),
            "resource_budget": budget,
            "packaging_policy": packaging,
            "verification_policy": verification,
        }
        secret_hit = _detect_secret(_dump(payload))
        if secret_hit:
            raise BuildConfigurationInvalid(
                "构建配置包含疑似明文 Secret", details={"pattern": secret_hit}
            )
        return payload

    def _merge_payload(
        self, current: BuildConfigurationVersionModel, changes: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "godot_version_constraint": changes.get(
                "godot_version_constraint", current.godot_version_constraint
            ),
            "target_platform": changes.get("target_platform", current.target_platform),
            "architecture": changes.get("architecture", current.architecture),
            "renderer": changes.get("renderer", current.renderer),
            "export_preset_name": changes.get("export_preset_name", current.export_preset_name),
            "build_mode": changes.get("build_mode", current.build_mode),
            "feature_tags": changes.get("feature_tags", _load(current.feature_tags_json, [])),
            "output_format": changes.get("output_format", current.output_format),
            "env_allowlist": changes.get("env_allowlist", _load(current.env_allowlist_json, [])),
            "build_timeout_seconds": changes.get(
                "build_timeout_seconds", current.build_timeout_seconds
            ),
            "resource_budget": changes.get(
                "resource_budget", _load(current.resource_budget_json, {})
            ),
            "packaging_policy": changes.get(
                "packaging_policy", _load(current.packaging_policy_json, {})
            ),
            "verification_policy": changes.get(
                "verification_policy", _load(current.verification_policy_json, {})
            ),
        }

    def _version_entity(
        self,
        *,
        version_id: str,
        configuration_id: str,
        project_id: str,
        version: int,
        payload: dict[str, Any],
        config_hash: str,
        created_by: str | None,
        now: datetime,
    ) -> BuildConfigurationVersionModel:
        return BuildConfigurationVersionModel(
            version_id=version_id,
            configuration_id=configuration_id,
            project_id=project_id,
            version=version,
            godot_version_constraint=payload["godot_version_constraint"],
            target_platform=payload["target_platform"],
            architecture=payload["architecture"],
            renderer=payload["renderer"],
            export_preset_name=payload["export_preset_name"],
            build_mode=payload["build_mode"],
            feature_tags_json=_dump(payload["feature_tags"]),
            output_format=payload["output_format"],
            env_allowlist_json=_dump(payload["env_allowlist"]),
            build_timeout_seconds=payload["build_timeout_seconds"],
            resource_budget_json=_dump(payload["resource_budget"]),
            packaging_policy_json=_dump(payload["packaging_policy"]),
            verification_policy_json=_dump(payload["verification_policy"]),
            config_hash=config_hash,
            created_by=created_by,
            created_at=now,
        )

    def _evaluate_environment(
        self,
        *,
        godot_version: str,
        export_template_version: str,
        toolchain_versions: dict[str, Any],
        sdk_versions: dict[str, Any],
        target_platform: str | None,
        required_platforms: list[str] | None,
    ) -> tuple[str, dict[str, Any]]:
        problems: list[str] = []
        warnings: list[str] = []
        if not godot_version:
            problems.append("未检测到 Godot Engine 版本")
        if not export_template_version:
            problems.append("未检测到 Export Templates 版本")
        if not toolchain_versions:
            warnings.append("未检测到工具链版本")
        platforms = list(required_platforms or ([target_platform] if target_platform else []))
        for platform in platforms:
            if platform not in DESKTOP_PLATFORMS:
                warnings.append(f"平台未纳入首期承诺: {platform}")
            elif not sdk_versions.get(platform):
                warnings.append(f"未检测到平台 SDK: {platform}")
        if problems:
            status = ENV_BLOCKED
        elif warnings:
            status = ENV_READY_WITH_WARNINGS
        else:
            status = ENV_READY
        return status, {
            "problems": problems,
            "warnings": warnings,
            "checked_at": utcnow().isoformat(),
        }
