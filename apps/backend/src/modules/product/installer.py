"""安装器、首次运行与 Plugin 安装（E12-T02 / T03 / T08）。

安装器只负责产品组件与记录，不修改用户项目内容。Plugin 安装计划必须先
展示变更清单；用户修改过的文件不得静默覆盖。
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.compatibility import PASS, UNKNOWN, WARNING
from modules.product.models import (
    INSTALL_COMPLETED,
    INSTALL_INSTALLING,
    INSTALL_PARTIAL,
    INSTALL_RECOVERY_REQUIRED,
    INSTALL_ROLLED_BACK,
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_PENDING,
    STEP_RUNNING,
    ProductInstallationModel,
    ProductInstallationStepModel,
)
from modules.product.repository import InstallationRepository, InstallationStepRepository
from modules.product.versioning import COMPONENT_INDEX, PRODUCT_VERSION

VERIFICATION_KEYS = (
    "backend_startable",
    "api_reachable",
    "database_read_write",
    "migration_complete",
    "plugin_files_complete",
    "protocol_compatible",
    "websocket_connected",
    "session_lease",
    "log_dir_writable",
    "secret_store_available",
)

INSTALL_STEPS = (
    "precheck",
    "create_directories",
    "copy_backend",
    "install_plugin",
    "initialize_database",
    "write_configuration",
    "verify",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _is_within(child: str, parent: str) -> bool:
    try:
        return Path(child).resolve().is_relative_to(Path(parent).resolve())
    except OSError, ValueError:
        return False


def _check(key: str, status: str, detail: str, recovery: str = "") -> dict[str, str]:
    return {"key": key, "status": status, "detail": detail, "recovery": recovery}


def _installation_dict(record: ProductInstallationModel) -> dict[str, Any]:
    return {
        "installation_id": record.installation_id,
        "product_version": record.product_version,
        "status": record.status,
        "install_dir": record.install_dir,
        "data_dir": record.data_dir,
        "config_dir": record.config_dir,
        "log_dir": record.log_dir,
        "database_path": record.database_path,
        "components": json.loads(record.components_json),
        "last_step": record.last_step,
        "error_detail": record.error_detail,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


class InstallationService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    # ------------------------------------------------------------------ preflight
    def preflight(
        self,
        *,
        install_dir: str,
        data_dir: str,
        components: Iterable[str],
        disk_free_gb: float | None = None,
        writable: bool | None = None,
    ) -> dict[str, Any]:
        selected = list(components)
        checks: list[dict[str, str]] = []

        if not install_dir or not data_dir:
            checks.append(
                _check("directories", "FAILED", "必须提供安装目录与用户数据目录", "重新选择目录")
            )
        elif _is_within(data_dir, install_dir) or _is_within(install_dir, data_dir):
            checks.append(
                _check(
                    "directory_separation",
                    "FAILED",
                    "用户数据目录与安装目录必须相互独立",
                    "将用户数据放到 LocalAppData / XDG 数据目录",
                )
            )
        else:
            checks.append(_check("directory_separation", PASS, "安装目录与用户数据目录已隔离"))

        if not selected:
            checks.append(_check("components", "FAILED", "至少选择一个产品组件", "选择 Backend"))
        else:
            unknown = [item for item in selected if item not in COMPONENT_INDEX]
            duplicated = sorted({item for item in selected if selected.count(item) > 1})
            missing_required = [
                item
                for item, component in COMPONENT_INDEX.items()
                if component.required and item not in selected
            ]
            if unknown:
                checks.append(
                    _check(
                        "components", "FAILED", f"未知组件: {', '.join(unknown)}", "重新选择组件"
                    )
                )
            elif duplicated:
                checks.append(
                    _check(
                        "components", "FAILED", f"组件重复: {', '.join(duplicated)}", "移除重复项"
                    )
                )
            elif missing_required:
                checks.append(
                    _check(
                        "components",
                        "FAILED",
                        f"缺少必需组件: {', '.join(missing_required)}",
                        "勾选必需组件",
                    )
                )
            else:
                checks.append(_check("components", PASS, "组件选择有效"))

        if writable is None:
            checks.append(_check("permissions", UNKNOWN, "未检测目录写权限", "运行安装前检查"))
        elif writable:
            checks.append(_check("permissions", PASS, "安装目录可写"))
        else:
            checks.append(
                _check("permissions", "FAILED", "安装目录不可写", "以有权限的账户运行安装器")
            )

        if disk_free_gb is None:
            checks.append(_check("disk", UNKNOWN, "未检测磁盘空间", "运行安装前检查"))
        elif disk_free_gb < 2:
            checks.append(_check("disk", "FAILED", f"磁盘剩余 {disk_free_gb:.1f} GB", "清理磁盘"))
        elif disk_free_gb < 5:
            checks.append(
                _check("disk", WARNING, f"磁盘剩余 {disk_free_gb:.1f} GB", "建议保留 5 GB")
            )
        else:
            checks.append(_check("disk", PASS, f"磁盘剩余 {disk_free_gb:.1f} GB"))

        critical = {"directories", "directory_separation", "components", "permissions", "disk"}
        can_install = all(
            item["status"] in {PASS, WARNING} for item in checks if item["key"] in critical
        )
        return {"can_install": can_install, "checks": checks}

    # ---------------------------------------------------------------- lifecycle
    async def start(
        self,
        *,
        install_dir: str,
        data_dir: str,
        config_dir: str,
        log_dir: str,
        database_path: str,
        components: Iterable[str],
        disk_free_gb: float | None = None,
        writable: bool | None = None,
    ) -> dict[str, Any]:
        preflight = self.preflight(
            install_dir=install_dir,
            data_dir=data_dir,
            components=components,
            disk_free_gb=disk_free_gb,
            writable=writable,
        )
        if not preflight["can_install"]:
            raise ValidationFailed("安装前检查未通过", details={"checks": preflight["checks"]})

        now = _now()
        async with self._database.session() as session, transaction(session):
            installation = ProductInstallationModel(
                installation_id=_new_id("inst"),
                product_version=PRODUCT_VERSION,
                status=INSTALL_INSTALLING,
                install_dir=install_dir,
                data_dir=data_dir,
                config_dir=config_dir,
                log_dir=log_dir,
                database_path=database_path,
                components_json=json.dumps(list(components)),
                last_step="precheck",
                error_detail="",
                created_at=now,
                updated_at=now,
            )
            await InstallationRepository(session).add(installation)
            steps = InstallationStepRepository(session)
            await steps.add(
                ProductInstallationStepModel(
                    step_id=_new_id("step"),
                    installation_id=installation.installation_id,
                    step_name="precheck",
                    status=STEP_COMPLETED,
                    detail=json.dumps(preflight["checks"]),
                    files_json="[]",
                    created_at=now,
                    updated_at=now,
                )
            )
            for step in INSTALL_STEPS[1:]:
                await steps.add(
                    ProductInstallationStepModel(
                        step_id=_new_id("step"),
                        installation_id=installation.installation_id,
                        step_name=step,
                        status=STEP_PENDING,
                        detail="",
                        files_json="[]",
                        created_at=now,
                        updated_at=now,
                    )
                )
            await session.flush()
            return _installation_dict(installation)

    async def get(self, installation_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            installation = await InstallationRepository(session).get(installation_id)
            if installation is None:
                raise ValidationFailed(
                    "安装记录不存在", details={"installation_id": installation_id}
                )
            return _installation_dict(installation)

    async def latest(self) -> dict[str, Any] | None:
        async with self._database.session() as session:
            installation = await InstallationRepository(session).get_latest()
            return _installation_dict(installation) if installation else None

    async def record_step(
        self,
        installation_id: str,
        *,
        step_name: str,
        status: str,
        detail: str = "",
        files: Iterable[str] = (),
    ) -> dict[str, Any]:
        if status not in {STEP_PENDING, STEP_RUNNING, STEP_COMPLETED, STEP_FAILED}:
            raise ValidationFailed("未知的安装步骤状态", details={"status": status})
        now = _now()
        async with self._database.session() as session, transaction(session):
            installation = await InstallationRepository(session).get(installation_id)
            if installation is None:
                raise ValidationFailed(
                    "安装记录不存在", details={"installation_id": installation_id}
                )
            step = await InstallationStepRepository(session).get_by_name(installation_id, step_name)
            if step is None:
                raise ValidationFailed("安装步骤不存在", details={"step_name": step_name})
            step.status = status
            step.detail = detail
            step.files_json = json.dumps(list(files))
            step.updated_at = now
            if status == STEP_COMPLETED:
                installation.last_step = step_name
                installation.updated_at = now
            await session.flush()
            return {
                "installation_id": installation_id,
                "step_name": step.step_name,
                "status": step.status,
            }

    async def verify(self, installation_id: str, verification: Mapping[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        for key in VERIFICATION_KEYS:
            value = verification.get(key)
            if value is None:
                checks.append(_check(key, UNKNOWN, "未提供验证结果", "重新运行安装后检查"))
            elif value is True or str(value).lower() in {"true", "pass", "1"}:
                checks.append(_check(key, PASS, "通过"))
            else:
                checks.append(_check(key, "FAILED", "检查未通过", "查看安装日志并执行恢复"))

        statuses = {item["status"] for item in checks}
        if "FAILED" in statuses:
            status, error = INSTALL_RECOVERY_REQUIRED, "安装后检查失败，可执行回滚或恢复"
        elif UNKNOWN in statuses:
            status, error = INSTALL_PARTIAL, "部分检查缺少结果，不能视为安装完成"
        else:
            status, error = INSTALL_COMPLETED, ""

        now = _now()
        async with self._database.session() as session, transaction(session):
            installation = await InstallationRepository(session).get(installation_id)
            if installation is None:
                raise ValidationFailed(
                    "安装记录不存在", details={"installation_id": installation_id}
                )
            installation.status = status
            installation.error_detail = error
            installation.last_step = "verify"
            installation.updated_at = now
            installation.completed_at = now if status == INSTALL_COMPLETED else None
            step = await InstallationStepRepository(session).get_by_name(installation_id, "verify")
            if step is not None:
                step.status = STEP_COMPLETED if status == INSTALL_COMPLETED else STEP_FAILED
                step.detail = json.dumps(checks)
                step.updated_at = now
            await session.flush()
        return {"installation_id": installation_id, "status": status, "checks": checks}

    async def rollback(self, installation_id: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            installation = await InstallationRepository(session).get(installation_id)
            if installation is None:
                raise ValidationFailed(
                    "安装记录不存在", details={"installation_id": installation_id}
                )
            if installation.status == INSTALL_ROLLED_BACK:
                return {
                    "installation_id": installation_id,
                    "status": INSTALL_ROLLED_BACK,
                    "already_rolled_back": True,
                }
            installation.status = INSTALL_ROLLED_BACK
            installation.error_detail = "安装回滚不会删除用户数据"
            installation.updated_at = _now()
            await session.flush()
            return {
                "installation_id": installation_id,
                "status": INSTALL_ROLLED_BACK,
                "preserved": [installation.data_dir, installation.database_path],
                "removed_project_files": [],
            }

    async def uninstall(
        self, installation_id: str, *, remove_user_data: bool = False
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            installation = await InstallationRepository(session).get(installation_id)
            if installation is None:
                raise ValidationFailed(
                    "安装记录不存在", details={"installation_id": installation_id}
                )
            preserved = (
                [] if remove_user_data else [installation.data_dir, installation.database_path]
            )
            return {
                "installation_id": installation_id,
                "remove_install_files": True,
                "remove_user_data": remove_user_data,
                "preserved": preserved,
                "preserved_project_files": "用户 Godot 项目目录永远不会被产品卸载删除",
                "requires_confirmation": True,
                "project_files_touched": False,
            }

    # ------------------------------------------------------------ plugin install
    def plugin_install_plan(
        self,
        *,
        project_dir: str,
        plugin_version: str,
        existing_version: str | None = None,
        modified_files: Iterable[str] = (),
        source: str = "zip",
    ) -> dict[str, Any]:
        if not project_dir:
            raise ValidationFailed("必须提供 Godot 项目目录")
        if source not in {"zip", "installer", "project"}:
            raise ValidationFailed("未知的 Plugin 安装来源", details={"source": source})
        conflicts = sorted({str(item) for item in modified_files})
        if existing_version == plugin_version and not conflicts:
            action = "SKIP"
            reason = "已安装相同版本"
        elif existing_version is None:
            action = "INSTALL"
            reason = "首次安装"
        elif conflicts:
            action = "CONFLICT"
            reason = "检测到用户修改过的 Plugin 文件，禁止静默覆盖"
        else:
            action = "UPGRADE"
            reason = f"从 {existing_version} 升级到 {plugin_version}"
        return {
            "project_dir": str(Path(project_dir)),
            "plugin_version": plugin_version,
            "existing_version": existing_version,
            "action": action,
            "reason": reason,
            "conflicts": conflicts,
            "requires_confirmation": action in {"INSTALL", "UPGRADE", "CONFLICT"},
            "overwrite_user_modified": False,
            "backup": ["addons/godot_ai_agent"],
            "change_manifest": [
                {"path": "addons/godot_ai_agent", "operation": action.lower()},
            ],
        }

    def apply_plugin_install(
        self,
        plan: Mapping[str, Any],
        *,
        confirmed: bool,
        overwrite_user_modified: bool = False,
    ) -> dict[str, Any]:
        if plan.get("action") == "SKIP":
            return {"applied": False, "reason": "无需安装"}
        if plan.get("requires_confirmation") and not confirmed:
            raise ValidationFailed("Plugin 安装需要用户确认")
        if plan.get("action") == "CONFLICT" and not overwrite_user_modified:
            raise ValidationFailed(
                "检测到用户修改过的 Plugin 文件，拒绝覆盖",
                details={"conflicts": plan.get("conflicts", [])},
            )
        return {
            "applied": True,
            "project_dir": plan.get("project_dir"),
            "backup": plan.get("backup", []),
            "overwrote_user_modified": bool(
                plan.get("action") == "CONFLICT" and overwrite_user_modified
            ),
        }

    # --------------------------------------------------------------- first run
    def first_run_wizard(self, context: Mapping[str, Any]) -> dict[str, Any]:
        def _step(key: str, status: str, detail: str) -> dict[str, str]:
            return {"key": key, "status": status, "detail": detail}

        steps = [
            _step("welcome", "READY", "欢迎使用 Godot AI Agent Platform"),
            _step("runtime_mode", "READY", "支持 Development Assistant 与 Autonomous 模式"),
            _step(
                "backend_status",
                PASS if context.get("backend_running") else UNKNOWN,
                "Backend 运行中" if context.get("backend_running") else "Backend 尚未启动",
            ),
            _step(
                "data_directory",
                PASS if context.get("data_dir") else UNKNOWN,
                "用户数据目录已设置" if context.get("data_dir") else "需要选择用户数据目录",
            ),
            _step(
                "security",
                PASS if context.get("credential_store") else WARNING,
                "系统凭证库可用"
                if context.get("credential_store")
                else "凭证库不可用，使用受限模式",
            ),
            _step(
                "provider",
                PASS if context.get("provider_configured") else STEP_PENDING,
                "模型 Provider 已配置"
                if context.get("provider_configured")
                else "待配置模型 Provider",
            ),
            _step(
                "model_policy",
                PASS if context.get("model_configured") else STEP_PENDING,
                "默认模型策略已设置" if context.get("model_configured") else "待设置默认模型",
            ),
            _step(
                "budget",
                PASS if context.get("budget_configured") else WARNING,
                "预算已设置"
                if context.get("budget_configured")
                else "未设置预算，将使用保守默认值",
            ),
            _step(
                "godot_detection",
                PASS if context.get("godot_version") else UNKNOWN,
                f"检测到 Godot {context.get('godot_version')}"
                if context.get("godot_version")
                else "未检测到 Godot",
            ),
            _step(
                "plugin_connection",
                PASS if context.get("plugin_connected") else STEP_PENDING,
                "Plugin 已连接" if context.get("plugin_connected") else "等待 Plugin 连接",
            ),
            _step(
                "project_selection",
                PASS if context.get("project_path") else STEP_PENDING,
                f"项目: {context.get('project_path')}"
                if context.get("project_path")
                else "待选择 Godot 项目",
            ),
        ]
        complete = all(item["status"] in {PASS, "READY"} for item in steps)
        steps.append(
            _step(
                "integrity_diagnostics",
                PASS if complete else STEP_PENDING,
                "完整性诊断通过" if complete else "尚有步骤未完成",
            )
        )
        return {"steps": steps, "complete": complete, "total": len(steps)}

    @staticmethod
    def default_paths(data_root: str) -> dict[str, str]:
        root = Path(data_root)
        return {
            "data_dir": str(root),
            "config_dir": str(root / "config"),
            "log_dir": str(root / "logs"),
            "database_path": str(root / "data" / "godot_ai_agent.db"),
            "cache_dir": str(root / "cache"),
            "backup_dir": str(root / "backups"),
        }

    @staticmethod
    def platform_data_root(
        *, os_name: str | None = None, env: Mapping[str, str] | None = None
    ) -> str:
        values = dict(os.environ if env is None else env)
        system = (os_name or os.name).lower()
        if system.startswith("win"):
            base = values.get("LOCALAPPDATA") or values.get("APPDATA") or str(Path.home())
            return str(Path(base) / "GodotAIAgent")
        if system == "darwin":
            return str(Path.home() / "Library" / "Application Support" / "GodotAIAgent")
        base = values.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return str(Path(base) / "godot-ai-agent")
