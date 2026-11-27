"""兼容性矩阵与环境诊断（E12-T09 / T18）。

规则：

- 兼容性声明必须有真实测试依据；未验证环境标记 UNKNOWN，绝不自动当作 PASS；
- 不支持的环境阻止不安全操作，并给出具体原因；
- 插件版本独立演进，兼容判断依据协议主版本与数据库 Schema。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from modules.product.versioning import (
    COMPATIBILITY_MATRIX_VERSION,
    COMPONENT_INDEX,
    PRODUCT_VERSION,
)

PASS = "PASS"
WARNING = "WARNING"
FAILED = "FAILED"
UNSUPPORTED = "UNSUPPORTED"
UNKNOWN = "UNKNOWN"
LEVELS = frozenset({PASS, WARNING, FAILED, UNSUPPORTED, UNKNOWN})
_SEVERITY = {PASS: 0, UNKNOWN: 1, WARNING: 2, UNSUPPORTED: 3, FAILED: 4}

VERIFIED = "VERIFIED"
PARTIAL = "PARTIAL"
UNVERIFIED = "UNVERIFIED"
_NOT_VERIFIED_BY_CI = "未在 CI 或真实环境验证"


@dataclass(frozen=True, slots=True)
class EnvironmentCheck:
    key: str
    status: str
    detail: str
    recovery: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "status": self.status,
            "detail": self.detail,
            "recovery": self.recovery,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentReport:
    matrix_version: str
    overall: str
    checks: tuple[EnvironmentCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "matrix_version": self.matrix_version,
            "overall": self.overall,
            "checks": [item.to_dict() for item in self.checks],
        }


MATRIX: dict[str, Any] = {
    "matrix_version": COMPATIBILITY_MATRIX_VERSION,
    "product_version": PRODUCT_VERSION,
    "components": {
        "backend": COMPONENT_INDEX["backend"].version,
        "godot_plugin": COMPONENT_INDEX["godot_plugin"].version,
    },
    "godot": {
        "4.5": VERIFIED,
        "4.4": PARTIAL,
    },
    "operating_systems": {
        "windows": {"x86_64": VERIFIED, "arm64": UNVERIFIED},
        "linux": {"x86_64": PARTIAL, "arm64": UNVERIFIED},
        "macos": {"arm64": UNVERIFIED, "x86_64": UNVERIFIED},
    },
    "python": {"3.14": VERIFIED},
    "credential_store": {"keyring": VERIFIED, "none": PARTIAL},
    "notes": "仅 VERIFIED / PARTIAL 可声明支持；UNVERIFIED 一律返回 UNKNOWN",
}


def matrix() -> dict[str, Any]:
    return MATRIX


def _platform_check(environment: Mapping[str, Any]) -> EnvironmentCheck:
    os_name = str(environment.get("os") or "").lower()
    arch = str(environment.get("architecture") or "").lower()
    if not os_name or not arch:
        return EnvironmentCheck(
            "platform",
            UNKNOWN,
            "未提供操作系统或 CPU 架构",
            "在首次运行向导中重新检测系统环境",
        )
    architectures = MATRIX["operating_systems"].get(os_name)
    if architectures is None:
        return EnvironmentCheck(
            "platform", UNSUPPORTED, f"不支持的操作系统: {os_name}", "使用 Windows x64 版本"
        )
    level = architectures.get(arch)
    if level is None:
        return EnvironmentCheck(
            "platform",
            UNSUPPORTED,
            f"{os_name} / {arch} 未列入支持范围",
            "使用受支持的架构或等待后续版本",
        )
    if level == VERIFIED:
        return EnvironmentCheck("platform", PASS, f"{os_name} / {arch} 已验证")
    if level == PARTIAL:
        return EnvironmentCheck(
            "platform",
            WARNING,
            f"{os_name} / {arch} 仅部分验证",
            "在正式项目使用前执行一次完整安装与导出验证",
        )
    return EnvironmentCheck(
        "platform",
        UNKNOWN,
        f"{os_name} / {arch} {_NOT_VERIFIED_BY_CI}",
        "保持备份，并在升级前验证安装与插件连接",
    )


def _godot_check(environment: Mapping[str, Any]) -> EnvironmentCheck:
    raw = str(environment.get("godot_version") or "").strip()
    if not raw:
        return EnvironmentCheck(
            "godot", UNKNOWN, "未检测到 Godot 版本", "安装 Godot 4.5.x 并在向导中设置路径"
        )
    match = re.match(r"^(\d+)\.(\d+)", raw)
    if not match:
        return EnvironmentCheck(
            "godot", UNKNOWN, f"无法解析 Godot 版本: {raw}", "重新检测 Godot 可执行文件"
        )
    major, minor = int(match.group(1)), int(match.group(2))
    key = f"{major}.{minor}"
    level = MATRIX["godot"].get(key)
    if level == VERIFIED:
        return EnvironmentCheck("godot", PASS, f"Godot {raw} 已验证")
    if level == PARTIAL:
        return EnvironmentCheck(
            "godot",
            WARNING,
            f"Godot {raw} 仅部分验证",
            "升级到 Godot 4.5.x 以获得完整验证覆盖",
        )
    if major < 4:
        return EnvironmentCheck(
            "godot", UNSUPPORTED, f"Godot {raw} 低于最低支持版本", "升级到 Godot 4.5.x"
        )
    return EnvironmentCheck(
        "godot",
        UNKNOWN,
        f"Godot {raw} 未经验证",
        "使用 Godot 4.5.x，或在项目中保留可回滚备份",
    )


def _credential_check(environment: Mapping[str, Any]) -> EnvironmentCheck:
    value = environment.get("credential_store")
    if value is None:
        return EnvironmentCheck(
            "credential_store",
            UNKNOWN,
            "未检测系统凭证库",
            "在设置中心运行“凭证库检测”",
        )
    if value is True or str(value).lower() in {"keyring", "true", "1"}:
        return EnvironmentCheck("credential_store", PASS, "系统凭证库可用")
    return EnvironmentCheck(
        "credential_store",
        WARNING,
        "系统凭证库不可用，将使用受限的会话内存凭证",
        "安装系统凭证库后端，或仅在受控环境使用临时凭证",
    )


def _disk_check(environment: Mapping[str, Any]) -> EnvironmentCheck:
    value = environment.get("disk_free_gb")
    if value is None:
        return EnvironmentCheck("disk", UNKNOWN, "未检测磁盘空间", "运行环境诊断")
    free = float(value)
    if free < 1:
        return EnvironmentCheck("disk", FAILED, f"磁盘剩余 {free:.1f} GB", "清理磁盘后重试")
    if free < 5:
        return EnvironmentCheck("disk", WARNING, f"磁盘剩余 {free:.1f} GB", "建议保留至少 5 GB")
    return EnvironmentCheck("disk", PASS, f"磁盘剩余 {free:.1f} GB")


def _python_check(environment: Mapping[str, Any]) -> EnvironmentCheck:
    raw = str(environment.get("python_version") or "").strip()
    if not raw:
        return EnvironmentCheck("python", UNKNOWN, "未检测 Python 运行时", "运行环境诊断")
    match = re.match(r"^(\d+)\.(\d+)", raw)
    level = MATRIX["python"].get(f"{match.group(1)}.{match.group(2)}") if match else None
    if level == VERIFIED:
        return EnvironmentCheck("python", PASS, f"Python {raw} 已验证")
    return EnvironmentCheck(
        "python",
        UNKNOWN,
        f"Python {raw} 未经验证",
        "使用 Python 3.14 运行时，或改用打包后的 Backend",
    )


def _boolean_check(
    environment: Mapping[str, Any],
    key: str,
    *,
    pass_detail: str,
    fail_detail: str,
    fail_status: str = FAILED,
    recovery: str = "",
) -> EnvironmentCheck:
    value = environment.get(key)
    if value is None:
        return EnvironmentCheck(key, UNKNOWN, f"未检测 {key}", recovery)
    if bool(value):
        return EnvironmentCheck(key, PASS, pass_detail)
    return EnvironmentCheck(key, fail_status, fail_detail, recovery)


def check_component_compatibility(
    *,
    plugin_version: str | None = None,
    backend_version: str | None = None,
    protocol_version: str | None = None,
    database_schema: str | None = None,
) -> list[EnvironmentCheck]:
    """插件/后端/协议/Schema 兼容性；缺失信息一律 UNKNOWN。"""

    checks: list[EnvironmentCheck] = []
    supported_schema = COMPONENT_INDEX["database_schema"].version

    if not backend_version:
        checks.append(
            EnvironmentCheck("backend", UNKNOWN, "未提供 Backend 版本", "升级到正式版本后重试")
        )
    else:
        checks.append(EnvironmentCheck("backend", PASS, f"Backend {backend_version}"))

    if not plugin_version:
        checks.append(
            EnvironmentCheck("plugin", UNKNOWN, "未检测 Godot Plugin", "在项目中安装插件")
        )
    elif not protocol_version:
        checks.append(
            EnvironmentCheck(
                "plugin",
                UNKNOWN,
                f"Plugin {plugin_version} 未上报协议版本",
                "重新连接 Editor 以同步协议版本",
            )
        )
    else:
        checks.append(EnvironmentCheck("plugin", PASS, f"Plugin {plugin_version}"))

    if not protocol_version:
        checks.append(
            EnvironmentCheck(
                "protocol",
                UNKNOWN,
                "未提供协议版本",
                "重新启动 Backend 与 Godot Editor",
            )
        )
    elif protocol_version.split(".")[0] != "1":
        checks.append(
            EnvironmentCheck(
                "protocol",
                FAILED,
                f"协议版本 {protocol_version} 与 Backend 不兼容",
                "安装与 Backend 匹配的 Godot Plugin",
            )
        )
    else:
        checks.append(EnvironmentCheck("protocol", PASS, f"协议 {protocol_version}"))

    if not database_schema:
        checks.append(
            EnvironmentCheck("database_schema", UNKNOWN, "未读取数据库 Schema 版本", "启动 Backend")
        )
    elif database_schema == supported_schema:
        checks.append(EnvironmentCheck("database_schema", PASS, f"Schema {database_schema}"))
    elif not database_schema.isdigit() or not supported_schema.isdigit():
        checks.append(
            EnvironmentCheck(
                "database_schema",
                UNKNOWN,
                f"无法解析数据库 Schema 版本: {database_schema}",
                "运行产品诊断并重新读取 Schema",
            )
        )
    elif int(database_schema) > int(supported_schema):
        checks.append(
            EnvironmentCheck(
                "database_schema",
                FAILED,
                f"数据库 Schema {database_schema} 高于当前产品支持版本 {supported_schema}",
                "安装更新的产品版本，禁止降级覆盖数据库",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "database_schema",
                WARNING,
                f"数据库 Schema {database_schema} 需要迁移到 {supported_schema}",
                "执行产品升级与迁移流程",
            )
        )

    return checks


def check_environment(environment: Mapping[str, Any]) -> EnvironmentReport:
    checks: list[EnvironmentCheck] = [_platform_check(environment), _godot_check(environment)]
    checks.extend(
        check_component_compatibility(
            plugin_version=environment.get("plugin_version"),
            backend_version=environment.get("backend_version"),
            protocol_version=environment.get("protocol_version"),
            database_schema=environment.get("database_schema"),
        )
    )
    checks.extend(
        [
            _credential_check(environment),
            _disk_check(environment),
            _python_check(environment),
            _boolean_check(
                environment,
                "network",
                pass_detail="网络连接可用",
                fail_detail="网络不可用，模型与外部服务将受限",
                fail_status=WARNING,
                recovery="检查代理与网络设置；纯本地功能仍可使用",
            ),
            _boolean_check(
                environment,
                "port_available",
                pass_detail="Backend 端口可用",
                fail_detail="Backend 端口被占用",
                recovery="关闭占用端口的进程，或在设置中更换端口",
            ),
        ]
    )
    overall = _overall(checks)
    return EnvironmentReport(
        matrix_version=COMPATIBILITY_MATRIX_VERSION,
        overall=overall,
        checks=tuple(checks),
    )


def _overall(checks: list[EnvironmentCheck]) -> str:
    severity = max((_SEVERITY.get(item.status, _SEVERITY[UNKNOWN]) for item in checks), default=0)
    for level in (FAILED, UNSUPPORTED, WARNING, UNKNOWN):
        if _SEVERITY[level] == severity:
            return level
    return PASS
