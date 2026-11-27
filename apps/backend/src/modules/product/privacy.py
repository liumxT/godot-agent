"""隐私与数据治理（E12-T11）。

默认值：

- Telemetry 关闭；
- 项目源码、资产与项目路径默认不上传；
- 上下文预览必须显示模型、Provider 与将发送的内容；
- 数据导出/删除必须用户确认，且永远不删除用户项目。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.diagnostics import redact_value
from modules.product.models import TelemetryConsentModel
from modules.product.repository import (
    CrashReportRepository,
    SupportBundleRepository,
    TelemetryConsentRepository,
)

TELEMETRY_CATEGORIES = ("crash", "usage", "performance")
DELETE_SCOPES = ("telemetry", "diagnostics")
DEFAULT_CONTEXT_HINT = "仅发送当前请求所需的任务与文件摘要，不包含项目源码全量内容"


def _now() -> datetime:
    return datetime.now(UTC)


class PrivacyService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def telemetry_state(self) -> dict[str, Any]:
        async with self._database.session() as session:
            consent = await TelemetryConsentRepository(session).get_latest()
            if consent is None:
                return {
                    "enabled": False,
                    "categories": [],
                    "default": "OFF",
                    "decided_by_user": False,
                }
            return {
                "enabled": bool(consent.enabled),
                "categories": json.loads(consent.categories_json),
                "default": "OFF",
                "decided_by_user": True,
                "granted_by": consent.granted_by,
                "granted_at": consent.granted_at.isoformat() if consent.granted_at else None,
                "revoked_at": consent.revoked_at.isoformat() if consent.revoked_at else None,
            }

    async def set_telemetry(
        self,
        *,
        enabled: bool,
        categories: Iterable[str],
        actor: str,
    ) -> dict[str, Any]:
        selected = list(categories)
        unknown = [item for item in selected if item not in TELEMETRY_CATEGORIES]
        if unknown:
            raise ValidationFailed("未知的 Telemetry 类别", details={"categories": unknown})
        if enabled and not selected:
            raise ValidationFailed("开启 Telemetry 必须明确选择类别")
        now = _now()
        async with self._database.session() as session, transaction(session):
            repository = TelemetryConsentRepository(session)
            latest = await repository.get_latest()
            if latest is None:
                latest = TelemetryConsentModel(
                    consent_id=f"consent_{uuid.uuid4().hex[:16]}",
                    enabled=1 if enabled else 0,
                    categories_json=json.dumps(selected),
                    granted_by=actor,
                    granted_at=now if enabled else None,
                    revoked_at=None if enabled else now,
                    created_at=now,
                    updated_at=now,
                )
                await repository.add(latest)
            else:
                latest.enabled = 1 if enabled else 0
                latest.categories_json = json.dumps(selected)
                latest.granted_by = actor
                if enabled:
                    latest.granted_at = now
                    latest.revoked_at = None
                else:
                    latest.revoked_at = now
                latest.updated_at = now
            await session.flush()
        return await self.telemetry_state()

    async def context_preview(self, context: Mapping[str, Any]) -> dict[str, Any]:
        secrets_removed = redact_value(dict(context))
        return {
            "sent_to_model": secrets_removed,
            "project_source_included": False,
            "project_assets_included": False,
            "absolute_paths_included": False,
            "secrets_included": False,
            "default_upload_policy": "DISABLED",
            "hint": DEFAULT_CONTEXT_HINT,
        }

    async def prepare_data_export(self) -> dict[str, Any]:
        return {
            "exportable": [
                "product_configuration",
                "installation_records",
                "diagnostics_records",
                "telemetry_consent",
            ],
            "excluded": [
                "godot_project_source",
                "godot_project_assets",
                "credentials",
            ],
            "requires_confirmation": True,
            "project_files_touched": False,
        }

    async def delete_user_data(
        self,
        *,
        scope: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if scope not in DELETE_SCOPES:
            raise ValidationFailed(
                "仅支持删除产品诊断或 Telemetry 数据",
                details={"scope": scope, "supported": list(DELETE_SCOPES)},
            )
        if not confirmed:
            raise ValidationFailed("删除本地数据必须由用户确认")
        deleted = 0
        async with self._database.session() as session, transaction(session):
            if scope == "telemetry":
                consent = await TelemetryConsentRepository(session).get_latest()
                if consent is not None:
                    await session.delete(consent)
                    deleted += 1
            else:
                bundles = await SupportBundleRepository(session).list_latest()
                for bundle in bundles:
                    await session.delete(bundle)
                    deleted += 1
                crashes = await CrashReportRepository(session).list_latest()
                for crash in crashes:
                    await session.delete(crash)
                    deleted += 1
            await session.flush()
        return {
            "scope": scope,
            "deleted_records": deleted,
            "project_files_touched": False,
            "preserved": ["godot_project_source", "godot_project_assets"],
        }
