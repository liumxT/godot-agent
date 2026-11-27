"""产品恢复与长期运行异常处理（E12-T08 / T16）。

规则：

- 恢复前必须执行状态检查并生成计划；
- UNKNOWN 状态不得直接重试，必须人工核实；
- 用户项目目录、用户源码与资产永远不会被恢复流程删除。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.models import (
    RECOVERY_COMPLETED,
    RECOVERY_CONFIRMED,
    RECOVERY_EXECUTING,
    RECOVERY_FAILED,
    RECOVERY_INSPECTED,
    RECOVERY_MANUAL,
    RECOVERY_PLANNED,
    RECOVERY_VERIFYING,
    ProductInstallationModel,
    RecoveryOperationModel,
    RecoveryPointModel,
)
from modules.product.repository import (
    InstallationRepository,
    ProductMigrationRunRepository,
    RecoveryOperationRepository,
    RecoveryPointRepository,
    UpdateOperationRepository,
)

POINT_KINDS = frozenset({"DATABASE", "PLUGIN", "CONFIGURATION", "FULL"})
EXTERNAL_AREAS = ("tasks", "agents", "tools", "changesets", "locks", "outbox", "inbox")

StateProbe = Callable[[], Awaitable[Mapping[str, Any]]]


def _now() -> datetime:
    return datetime.now(UTC)


def _operation_dict(record: RecoveryOperationModel) -> dict[str, Any]:
    return {
        "operation_id": record.operation_id,
        "recovery_point_id": record.recovery_point_id,
        "status": record.status,
        "current_step": record.current_step,
        "inspection": json.loads(record.inspection_json),
        "plan": json.loads(record.plan_json),
        "confirmed": bool(record.confirmed),
        "error_detail": record.error_detail,
        "created_at": record.created_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


class RecoveryService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        backup_provider: Any | None = None,
        state_probe: StateProbe | None = None,
    ) -> None:
        self._database = database
        self._backup = backup_provider
        self._probe = state_probe

    async def create_point(
        self,
        *,
        kind: str,
        path: str,
        integrity_hash: str,
        description: str,
        product_version: str,
    ) -> dict[str, Any]:
        if kind not in POINT_KINDS:
            raise ValidationFailed("未知的恢复点类型", details={"kind": kind})
        if not path:
            raise ValidationFailed("恢复点必须包含路径")
        async with self._database.session() as session, transaction(session):
            record = RecoveryPointModel(
                recovery_point_id=f"rp_{uuid.uuid4().hex[:16]}",
                kind=kind,
                product_version=product_version,
                path=path,
                integrity_hash=integrity_hash,
                status="AVAILABLE",
                description=description,
                created_at=_now(),
            )
            await RecoveryPointRepository(session).add(record)
            await session.flush()
            return {
                "recovery_point_id": record.recovery_point_id,
                "kind": record.kind,
                "path": record.path,
                "integrity_hash": record.integrity_hash,
                "status": record.status,
            }

    async def list_points(self) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            rows = await RecoveryPointRepository(session).list_latest()
            return [
                {
                    "recovery_point_id": row.recovery_point_id,
                    "kind": row.kind,
                    "product_version": row.product_version,
                    "path": row.path,
                    "integrity_hash": row.integrity_hash,
                    "status": row.status,
                    "description": row.description,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    async def inspect(self, recovery_point_id: str | None = None) -> dict[str, Any]:
        async with self._database.session() as session:
            point = None
            if recovery_point_id:
                point = await RecoveryPointRepository(session).get(recovery_point_id)
                if point is None:
                    raise ValidationFailed(
                        "恢复点不存在", details={"recovery_point_id": recovery_point_id}
                    )
            installation = await InstallationRepository(session).get_latest()
            updates = await UpdateOperationRepository(session).list_unfinished()
            migrations = await ProductMigrationRunRepository(session).list_unfinished()
            inspection = {
                "installation": (
                    {
                        "status": installation.status,
                        "last_step": installation.last_step,
                        "product_version": installation.product_version,
                    }
                    if installation
                    else {"status": "UNKNOWN"}
                ),
                "unfinished_updates": [
                    {"operation_id": item.operation_id, "status": item.status} for item in updates
                ],
                "unfinished_migrations": [
                    {"run_id": item.run_id, "status": item.status} for item in migrations
                ],
                "recovery_point": (
                    {
                        "recovery_point_id": point.recovery_point_id,
                        "kind": point.kind,
                        "path": point.path,
                    }
                    if point
                    else None
                ),
                "external": {},
            }

        external: dict[str, Any] = {}
        if self._probe is not None:
            try:
                external = dict(await self._probe())
            except Exception as exc:  # noqa: BLE001 - 探针异常必须降级为 UNKNOWN
                external = {"probe": {"status": "UNKNOWN", "detail": str(exc)}}
        for area in EXTERNAL_AREAS:
            external.setdefault(area, {"status": "UNKNOWN", "detail": "未提供状态探针"})
        inspection["external"] = external

        operation = RecoveryOperationModel(
            operation_id=f"rec_{uuid.uuid4().hex[:16]}",
            recovery_point_id=recovery_point_id or "",
            status=RECOVERY_INSPECTED,
            current_step="inspection",
            inspection_json=json.dumps(inspection, ensure_ascii=False),
            plan_json="{}",
            confirmed=0,
            error_detail="",
            created_at=_now(),
            updated_at=_now(),
        )
        async with self._database.session() as session, transaction(session):
            await RecoveryOperationRepository(session).add(operation)
            await session.flush()
            return {
                **inspection,
                "operation_id": operation.operation_id,
                "status": operation.status,
            }

    async def plan(self, operation_id: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            repository = RecoveryOperationRepository(session)
            operation = await repository.get(operation_id)
            if operation is None:
                raise ValidationFailed("恢复操作不存在", details={"operation_id": operation_id})
            inspection = json.loads(operation.inspection_json)
            actions: list[dict[str, Any]] = []
            manual = False
            external = inspection.get("external", {})
            for area, value in external.items():
                status = value.get("status") if isinstance(value, Mapping) else "UNKNOWN"
                if status == "UNKNOWN":
                    manual = True
                    actions.append(
                        {
                            "area": area,
                            "action": "manual_verification",
                            "reason": "外部状态未知，必须人工核实",
                        }
                    )
            if inspection.get("unfinished_migrations"):
                actions.append({"area": "database", "action": "restore_database_from_backup"})
            if inspection.get("unfinished_updates"):
                actions.append({"area": "update", "action": "rollback_product_components"})
            if not actions:
                actions.append({"area": "system", "action": "verify_only"})
            plan = {
                "actions": actions,
                "requires_manual_verification": manual,
                "delete_user_project": False,
                "preserve_user_data": True,
            }
            operation.plan_json = json.dumps(plan, ensure_ascii=False)
            operation.status = RECOVERY_MANUAL if manual else RECOVERY_PLANNED
            operation.current_step = "plan"
            operation.updated_at = _now()
            await session.flush()
            return _operation_dict(operation)

    async def execute(
        self,
        operation_id: str,
        *,
        confirmed: bool = False,
        manual_verification_done: bool = False,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValidationFailed("恢复操作必须由用户确认")
        async with self._database.session() as session:
            operation = await RecoveryOperationRepository(session).get(operation_id)
            if operation is None:
                raise ValidationFailed("恢复操作不存在", details={"operation_id": operation_id})
            inspection = json.loads(operation.inspection_json)
            plan = json.loads(operation.plan_json or "{}")
            if plan.get("requires_manual_verification") and not manual_verification_done:
                raise ValidationFailed(
                    "存在 UNKNOWN 状态，必须先完成人工核实",
                    details={"actions": plan.get("actions", [])},
                )
            point = None
            if operation.recovery_point_id:
                point = await RecoveryPointRepository(session).get(operation.recovery_point_id)

        now = _now()
        async with self._database.session() as session, transaction(session):
            operation = await RecoveryOperationRepository(session).get(operation_id)
            operation.confirmed = 1
            operation.status = RECOVERY_CONFIRMED
            operation.current_step = "confirmed"
            operation.updated_at = now
            await session.flush()

        async with self._database.session() as session, transaction(session):
            operation = await RecoveryOperationRepository(session).get(operation_id)
            operation.status = RECOVERY_EXECUTING
            operation.current_step = "execute"
            operation.updated_at = _now()
            await session.flush()

        try:
            if point is not None and point.kind in {"DATABASE", "FULL"}:
                if self._backup is None:
                    raise ValidationFailed("恢复数据库需要配置备份服务")
                await self._backup.restore(point.path)
        except Exception as exc:  # noqa: BLE001 - 恢复失败必须记录并保留用户数据
            async with self._database.session() as session, transaction(session):
                operation = await RecoveryOperationRepository(session).get(operation_id)
                operation.status = RECOVERY_FAILED
                operation.current_step = "failed"
                operation.error_detail = str(exc)
                operation.updated_at = _now()
                await session.flush()
                return _operation_dict(operation)

        async with self._database.session() as session, transaction(session):
            operation = await RecoveryOperationRepository(session).get(operation_id)
            operation.status = RECOVERY_VERIFYING
            operation.current_step = "verify"
            operation.updated_at = _now()
            await session.flush()

        verification = await self._verify_after_recovery()
        async with self._database.session() as session, transaction(session):
            operation = await RecoveryOperationRepository(session).get(operation_id)
            operation.status = RECOVERY_COMPLETED if verification["ok"] else RECOVERY_FAILED
            operation.current_step = "completed" if verification["ok"] else "verify_failed"
            if not verification["ok"]:
                operation.error_detail = verification["detail"]
            operation.updated_at = _now()
            operation.completed_at = _now()
            await session.flush()
            result = _operation_dict(operation)
            result["verification"] = verification
            result["preserved_user_data"] = True
            result["deleted_user_project"] = False
            result["inspection_summary"] = inspection
            return result

    async def _verify_after_recovery(self) -> dict[str, Any]:
        try:
            async with self._database.session() as session:
                count = await session.scalar(
                    select(func.count()).select_from(ProductInstallationModel)
                )
            return {"ok": True, "detail": f"installations={int(count or 0)}"}
        except Exception as exc:  # noqa: BLE001 - 验证失败返回 FAILED 而非抛出
            return {"ok": False, "detail": str(exc)}
