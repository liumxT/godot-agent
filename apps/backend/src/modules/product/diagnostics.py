"""诊断、支持包与崩溃报告（E12-T12 / T17）。

规则：

- 支持包导出前必须用户确认；
- 支持包默认排除项目源码、资产、凭证、Token 与本机绝对路径；
- 错误码必须带恢复建议；
- 崩溃报告默认只保存在本地，发送必须另行授权。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.configuration import SECRET_KEY_PATTERN, SECRET_VALUE_PATTERN
from modules.product.models import CrashReportModel, ProductAuditModel, SupportBundleModel
from modules.product.repository import (
    CrashReportRepository,
    ProductAuditRepository,
    SupportBundleRepository,
)

ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/Users/|/home/|/root/|/var/|/opt/)")
MAX_TEXT = 2000

ERROR_CATALOG: dict[str, dict[str, str]] = {
    "INSTALL_PRECHECK_FAILED": {
        "category": "installation",
        "message": "安装前检查未通过",
        "recovery": "根据检查项修复目录、权限或磁盘空间后重试",
        "docs": "docs/04-operations/runbooks.md#安装失败",
    },
    "UPDATE_SIGNATURE_INVALID": {
        "category": "update",
        "message": "更新包签名无效",
        "recovery": "只使用官方渠道发布并签名的更新包；不要绕过签名校验",
        "docs": "docs/04-operations/runbooks.md#更新失败",
    },
    "UPDATE_NOT_APPROVED": {
        "category": "update",
        "message": "更新未经过用户确认",
        "recovery": "在确认更新计划后重新批准安装",
        "docs": "docs/04-operations/runbooks.md#更新失败",
    },
    "MIGRATION_BACKUP_MISSING": {
        "category": "migration",
        "message": "数据库迁移缺少备份",
        "recovery": "先创建数据库备份，再执行迁移",
        "docs": "docs/04-operations/runbooks.md#迁移失败",
    },
    "RECOVERY_UNKNOWN_STATE": {
        "category": "recovery",
        "message": "系统存在 UNKNOWN 状态",
        "recovery": "先完成状态检查与人工核实，再执行恢复",
        "docs": "docs/04-operations/runbooks.md#恢复",
    },
    "PROTOCOL_INCOMPATIBLE": {
        "category": "compatibility",
        "message": "Plugin 与 Backend 协议不兼容",
        "recovery": "安装与 Backend 版本匹配的 Plugin",
        "docs": "docs/05-product/user-guide.md#兼容性",
    },
    "SECRET_STORE_UNAVAILABLE": {
        "category": "security",
        "message": "系统凭证库不可用",
        "recovery": "安装并配置系统凭证库后端，或使用受限会话凭证",
        "docs": "docs/03-development/secrets.md",
    },
    "MODEL_UNAVAILABLE": {
        "category": "model",
        "message": "用户指定的模型不可用",
        "recovery": "在设置中选择当前 Provider 实际可用的模型；系统不会静默替换",
        "docs": "docs/05-product/user-guide.md#模型配置",
    },
    "DATABASE_CORRUPTED": {
        "category": "database",
        "message": "数据库完整性检查失败",
        "recovery": "停止 Backend，使用最近恢复点恢复数据库",
        "docs": "docs/04-operations/runbooks.md#数据库恢复",
    },
}


def _now() -> datetime:
    return datetime.now(UTC)


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if SECRET_KEY_PATTERN.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        if SECRET_VALUE_PATTERN.search(value):
            return "<redacted>"
        if ABSOLUTE_PATH.match(value):
            return "<path>"
        if len(value) > MAX_TEXT:
            return value[:MAX_TEXT] + "…<truncated>"
    return value


def error_entry(code: str) -> dict[str, str]:
    entry = ERROR_CATALOG.get(code)
    if entry is None:
        return {
            "code": code,
            "category": "unknown",
            "message": "未登记错误码",
            "recovery": "导出支持包并联系技术支持",
            "docs": "docs/04-operations/runbooks.md",
        }
    return {"code": code, **entry}


class DiagnosticsService:
    def __init__(self, database: DatabaseService, data_dir: str) -> None:
        self._database = database
        self._data_dir = data_dir

    async def errors(self) -> list[dict[str, str]]:
        return [error_entry(code) for code in sorted(ERROR_CATALOG)]

    def prepare_bundle(
        self,
        context: Mapping[str, Any],
        *,
        logs: Iterable[str] = (),
    ) -> dict[str, Any]:
        sanitized_logs = [redact_value(line) for line in logs][:500]
        summary = {
            "product": redact_value(context.get("product", {})),
            "environment": redact_value(context.get("environment", {})),
            "compatibility": redact_value(context.get("compatibility", {})),
            "installation": redact_value(context.get("installation", {})),
            "recent_errors": redact_value(context.get("recent_errors", [])),
            "logs": sanitized_logs,
            "excluded": {
                "project_source": True,
                "project_assets": True,
                "credentials": True,
                "tokens": True,
                "absolute_paths": True,
            },
        }
        return {
            "bundle": summary,
            "requires_user_confirmation": True,
            "contains_project_source": False,
            "contains_secrets": False,
        }

    async def export_bundle(
        self,
        context: Mapping[str, Any],
        *,
        created_by: str,
        confirmed: bool = False,
        logs: Iterable[str] = (),
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValidationFailed("导出支持包必须由用户确认")
        prepared = self.prepare_bundle(context, logs=logs)
        bundle_id = f"bundle_{uuid.uuid4().hex[:16]}"
        target_dir = Path(self._data_dir) / "support-bundles"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{bundle_id}.json"
        payload = json.dumps(prepared["bundle"], ensure_ascii=False, indent=2).encode()
        target.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        now = _now()
        async with self._database.session() as session, transaction(session):
            record = SupportBundleModel(
                bundle_id=bundle_id,
                status="EXPORTED",
                path=str(target),
                sha256=digest,
                summary_json=json.dumps(
                    {
                        "excluded": prepared["bundle"]["excluded"],
                        "sections": list(prepared["bundle"]),
                    }
                ),
                created_by=created_by,
                exported_at=now,
                created_at=now,
            )
            await SupportBundleRepository(session).add(record)
            await self._audit(
                session,
                action="product.support_bundle.export",
                actor_id=created_by,
                target=bundle_id,
                detail={"sha256": digest},
            )
            await session.flush()
        return {
            "bundle_id": bundle_id,
            "path": str(target),
            "sha256": digest,
            "sections": list(prepared["bundle"]),
            "contains_project_source": False,
            "contains_secrets": False,
        }

    async def list_bundles(self) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            rows = await SupportBundleRepository(session).list_latest()
            return [
                {
                    "bundle_id": row.bundle_id,
                    "status": row.status,
                    "path": row.path,
                    "sha256": row.sha256,
                    "created_by": row.created_by,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    async def report_crash(
        self,
        *,
        error_code: str,
        summary: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        sanitized = redact_value({"summary": summary, "context": context})
        crash_id = f"crash_{uuid.uuid4().hex[:16]}"
        async with self._database.session() as session, transaction(session):
            record = CrashReportModel(
                crash_id=crash_id,
                error_code=error_code,
                summary=str(redact_value(summary)),
                sanitized_json=json.dumps(sanitized, ensure_ascii=False),
                status="LOCAL_ONLY",
                created_at=_now(),
            )
            await CrashReportRepository(session).add(record)
            await session.flush()
        return {
            "crash_id": crash_id,
            "status": "LOCAL_ONLY",
            "sent": False,
            "error": error_entry(error_code),
        }

    async def recent_audits(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            rows = await ProductAuditRepository(session).list_latest(limit)
            return [
                {
                    "audit_id": row.audit_id,
                    "action": row.action,
                    "actor_id": row.actor_id,
                    "outcome": row.outcome,
                    "target": row.target,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    async def _audit(
        self,
        session: Any,
        *,
        action: str,
        actor_id: str,
        target: str,
        detail: Mapping[str, Any],
    ) -> None:
        await ProductAuditRepository(session).add(
            ProductAuditModel(
                audit_id=f"aud_{uuid.uuid4().hex[:16]}",
                action=action,
                actor_id=actor_id,
                outcome="SUCCESS",
                target=target,
                detail_json=json.dumps(redact_value(detail), ensure_ascii=False),
                created_at=_now(),
            )
        )
