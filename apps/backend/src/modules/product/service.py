"""产品聚合服务（E12-T01 / T12）。

只读取产品域与自身公开能力，不复制其他模块业务状态。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text

from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.diagnostics import DiagnosticsService
from modules.product.licensing import LicenseService
from modules.product.models import (
    INSTALL_COMPLETED,
    ProductAuditModel,
    ProductInstallationModel,
)
from modules.product.repository import (
    ProductMigrationRunRepository,
    RecoveryOperationRepository,
    UpdateOperationRepository,
)
from modules.product.versioning import (
    COMPATIBILITY_MATRIX_VERSION,
    GAME_ARTIFACT_VERSION_DOMAIN,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    PRODUCT_VERSION_DOMAIN,
    component_manifest,
    contract_manifest,
)

CAPABILITIES = (
    ("development_assistant", "Development Assistant"),
    ("autonomous_development", "Autonomous Game Development"),
    ("multi_agent", "Multi-Agent Orchestration"),
    ("asset_pipeline", "Asset Pipeline"),
    ("verification", "Verification & QA"),
    ("build_release", "Game Build & Release"),
    ("product_recovery", "Product Recovery"),
    ("diagnostics", "Diagnostics & Support Bundle"),
)


def _now() -> datetime:
    return datetime.now(UTC)


class ProductService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        license_service: LicenseService,
        diagnostics: DiagnosticsService,
    ) -> None:
        self._database = database
        self._license = license_service
        self._diagnostics = diagnostics

    async def info(self) -> dict[str, Any]:
        return {
            "product_name": PRODUCT_NAME,
            "product_version": PRODUCT_VERSION,
            "version_domain": PRODUCT_VERSION_DOMAIN,
            "game_artifact_version_domain": GAME_ARTIFACT_VERSION_DOMAIN,
            "version_domains_isolated": True,
            "compatibility_matrix_version": COMPATIBILITY_MATRIX_VERSION,
            "components": component_manifest()["components"],
            "contracts": contract_manifest(),
            "build": {
                "channel": os.environ.get("GODOT_AI_PRODUCT_CHANNEL", "DEV"),
                "source_revision": os.environ.get("GIT_COMMIT", "unknown"),
                "python_version": ".".join(str(item) for item in sys.version_info[:3]),
                "platform": sys.platform,
            },
        }

    async def capabilities(self) -> dict[str, Any]:
        evaluation = await self._license.evaluate()
        features = set(evaluation.get("features", []))
        return {
            "modes": ["development_assistant", "autonomous_development"],
            "licenses": {
                "status": evaluation["status"],
                "valid": evaluation["valid"],
                "mode": evaluation["mode"],
            },
            "capabilities": [
                {"key": key, "name": name, "available": key in features or key == "diagnostics"}
                for key, name in CAPABILITIES
            ],
        }

    async def health(self) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        checks.append(await self._database_check())
        checks.append(await self._schema_check())
        checks.append(await self._installation_check())
        checks.append(await self._license_check())
        checks.append(await self._pending_operations_check())

        statuses = {item["status"] for item in checks}
        if "FAILED" in statuses:
            overall = "FAILED"
        elif "WARNING" in statuses:
            overall = "WARNING"
        elif "UNKNOWN" in statuses:
            overall = "UNKNOWN"
        else:
            overall = "PASS"
        return {
            "product_version": PRODUCT_VERSION,
            "overall": overall,
            "checks": checks,
            "checked_at": _now().isoformat(),
        }

    async def _database_check(self) -> dict[str, str]:
        try:
            async with self._database.session() as session:
                await session.scalar(select(func.count()).select_from(ProductInstallationModel))
            return {"key": "database", "status": "PASS", "detail": "产品数据库可读"}
        except Exception as exc:  # noqa: BLE001 - 健康检查必须返回 FAILED
            return {"key": "database", "status": "FAILED", "detail": str(exc)}

    async def _schema_check(self) -> dict[str, str]:
        try:
            async with self._database.session() as session:
                version = await session.scalar(text("SELECT version_num FROM alembic_version"))
            if version is None:
                return {"key": "schema", "status": "UNKNOWN", "detail": "未读取到迁移版本"}
            return {"key": "schema", "status": "PASS", "detail": f"Schema {version}"}
        except Exception as exc:  # noqa: BLE001 - 无法读取 Schema 时返回 UNKNOWN
            return {"key": "schema", "status": "UNKNOWN", "detail": str(exc)}

    async def _installation_check(self) -> dict[str, str]:
        async with self._database.session() as session:
            installation = await session.scalar(
                select(ProductInstallationModel).order_by(
                    ProductInstallationModel.created_at.desc()
                )
            )
        if installation is None:
            return {"key": "installation", "status": "WARNING", "detail": "尚未执行产品安装"}
        if installation.status == INSTALL_COMPLETED:
            return {
                "key": "installation",
                "status": "PASS",
                "detail": f"安装已完成（{installation.product_version}）",
            }
        return {
            "key": "installation",
            "status": "WARNING",
            "detail": f"安装状态: {installation.status}",
        }

    async def _license_check(self) -> dict[str, str]:
        evaluation = await self._license.evaluate()
        if evaluation["valid"]:
            return {"key": "license", "status": "PASS", "detail": f"授权 {evaluation['status']}"}
        if evaluation["status"] == "UNKNOWN":
            return {"key": "license", "status": "WARNING", "detail": evaluation["message"]}
        return {"key": "license", "status": "WARNING", "detail": evaluation["message"]}

    async def _pending_operations_check(self) -> dict[str, str]:
        async with self._database.session() as session:
            updates = await UpdateOperationRepository(session).list_unfinished()
            migrations = await ProductMigrationRunRepository(session).list_unfinished()
            recoveries = await RecoveryOperationRepository(session).list_unfinished()
        pending = len(updates) + len(migrations) + len(recoveries)
        if pending == 0:
            return {"key": "operations", "status": "PASS", "detail": "无未完成升级或恢复操作"}
        return {
            "key": "operations",
            "status": "WARNING",
            "detail": f"存在 {pending} 个未完成操作，需检查恢复状态",
        }

    async def audit(
        self,
        *,
        action: str,
        actor_id: str,
        outcome: str,
        target: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        async with self._database.session() as session, transaction(session):
            session.add(
                ProductAuditModel(
                    audit_id=f"aud_{os.urandom(8).hex()}",
                    action=action,
                    actor_id=actor_id,
                    outcome=outcome,
                    target=target,
                    detail_json=json.dumps(detail or {}, ensure_ascii=False),
                    created_at=_now(),
                )
            )
            await session.flush()

    async def diagnostics_snapshot(self) -> dict[str, Any]:
        """支持包使用的只读快照。"""

        info = await self.info()
        health = await self.health()
        error_catalog = await self._diagnostics.errors()
        audits = await self._diagnostics.recent_audits(20)
        return {
            "product": {
                "name": info["product_name"],
                "version": info["product_version"],
                "components": info["components"],
            },
            "environment": {
                "python_version": info["build"]["python_version"],
                "platform": info["build"]["platform"],
                "channel": info["build"]["channel"],
            },
            "health": health,
            "recent_errors": [item for item in error_catalog if item["category"] != "unknown"][:10],
            "recent_audits": audits,
        }

    async def error_catalog(self) -> list[dict[str, str]]:
        return await self._diagnostics.errors()
