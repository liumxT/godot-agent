"""产品数据库迁移与升级（E12-T07）。

规则：

- 所有迁移必须先备份；
- 不可逆迁移必须显式标记并给出回滚策略；
- 中断恢复根据 ``PRODUCT_MIGRATION_RUNS`` 中记录的步骤继续；
- 失败时不自动重试，进入 FAILED / RECOVERY_REQUIRED。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from core.errors import ValidationFailed
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.product.models import (
    MIGRATION_BACKED_UP,
    MIGRATION_COMPLETED,
    MIGRATION_EXECUTING,
    MIGRATION_FAILED,
    MIGRATION_FORWARD_ONLY,
    MIGRATION_PLANNED,
    MIGRATION_RECOVERY_REQUIRED,
    MIGRATION_TYPES,
    ProductInstallationModel,
    ProductMigrationModel,
    ProductMigrationRunModel,
)
from modules.product.repository import ProductMigrationRepository, ProductMigrationRunRepository
from modules.product.versioning import COMPONENT_INDEX

MigrationRunner = Callable[[], Awaitable[Any]]


def _now() -> datetime:
    return datetime.now(UTC)


def _run_dict(record: ProductMigrationRunModel) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "migration_id": record.migration_id,
        "status": record.status,
        "backup_path": record.backup_path,
        "current_step": record.current_step,
        "error_detail": record.error_detail,
        "verification_detail": record.verification_detail,
        "created_at": record.created_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


class ProductMigrationService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        backup_provider: Any | None = None,
        runner: MigrationRunner | None = None,
    ) -> None:
        self._database = database
        self._backup = backup_provider
        self._runner = runner

    @property
    def target_schema_version(self) -> str:
        return COMPONENT_INDEX["database_schema"].version

    async def plan(self, *, current_schema_version: str) -> dict[str, Any]:
        target = self.target_schema_version
        if not current_schema_version.isdigit() or not target.isdigit():
            raise ValidationFailed(
                "Schema 版本必须为数字串",
                details={"current": current_schema_version, "target": target},
            )
        if int(current_schema_version) > int(target):
            return {
                "status": "DOWNGRADE_BLOCKED",
                "current_schema_version": current_schema_version,
                "target_schema_version": target,
                "reason": "数据库 Schema 高于当前产品支持版本，禁止自动降级",
            }
        if current_schema_version == target:
            return {
                "status": "ALREADY_AT_TARGET",
                "current_schema_version": current_schema_version,
                "target_schema_version": target,
                "migrations": [],
            }

        now = _now()
        async with self._database.session() as session, transaction(session):
            repository = ProductMigrationRepository(session)
            migration = await repository.get_by_versions(current_schema_version, target)
            if migration is None:
                migration = ProductMigrationModel(
                    migration_id=f"pmig_{uuid.uuid4().hex[:16]}",
                    from_schema_version=current_schema_version,
                    to_schema_version=target,
                    migration_type=MIGRATION_FORWARD_ONLY,
                    precondition="Backend 停止写入并完成数据库备份",
                    backup_requirement=1,
                    rollback_strategy="从升级前备份恢复数据库；插件与配置回滚到已保存版本",
                    verification_query="SELECT COUNT(*) FROM product_installations",
                    created_at=now,
                )
                await repository.add(migration)
            runs = await ProductMigrationRunRepository(session).list_by_migration(
                migration.migration_id
            )
            await session.flush()
            return {
                "status": "MIGRATION_REQUIRED",
                "migration_id": migration.migration_id,
                "from_schema_version": migration.from_schema_version,
                "to_schema_version": migration.to_schema_version,
                "migration_type": migration.migration_type,
                "backup_requirement": bool(migration.backup_requirement),
                "rollback_strategy": migration.rollback_strategy,
                "runs": [_run_dict(item) for item in runs],
            }

    async def prepare(self, migration_id: str) -> dict[str, Any]:
        now = _now()
        async with self._database.session() as session, transaction(session):
            migration = await ProductMigrationRepository(session).get(migration_id)
            if migration is None:
                raise ValidationFailed("迁移定义不存在", details={"migration_id": migration_id})
            if migration.migration_type not in MIGRATION_TYPES:
                raise ValidationFailed("未知的迁移类型", details={})
            run = ProductMigrationRunModel(
                run_id=f"prun_{uuid.uuid4().hex[:16]}",
                migration_id=migration.migration_id,
                status=MIGRATION_PLANNED,
                backup_path="",
                current_step="planned",
                error_detail="",
                verification_detail="",
                created_at=now,
                updated_at=now,
            )
            await ProductMigrationRunRepository(session).add(run)
            await session.flush()
            return _run_dict(run)

    async def execute(self, run_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise ValidationFailed("数据库迁移必须由用户确认后执行")
        if self._backup is None:
            raise ValidationFailed("数据库迁移必须配置备份服务")

        async with self._database.session() as session:
            run = await ProductMigrationRunRepository(session).get(run_id)
            if run is None:
                raise ValidationFailed("迁移执行记录不存在", details={"run_id": run_id})
            if run.status == MIGRATION_COMPLETED:
                return {**_run_dict(run), "already_applied": True}
            migration = await ProductMigrationRepository(session).get(run.migration_id)
            if migration is None:
                raise ValidationFailed("迁移定义不存在", details={})

        backup = await self._backup.create(reason=f"product-migration-{run_id}")
        backup_path = str(getattr(backup, "path", backup))

        now = _now()
        async with self._database.session() as session, transaction(session):
            run = await ProductMigrationRunRepository(session).get(run_id)
            run.backup_path = backup_path
            run.status = MIGRATION_BACKED_UP
            run.current_step = "backup"
            run.updated_at = now
            await session.flush()

        async with self._database.session() as session, transaction(session):
            run = await ProductMigrationRunRepository(session).get(run_id)
            run.status = MIGRATION_EXECUTING
            run.current_step = "execute"
            run.updated_at = _now()
            await session.flush()

        try:
            if self._runner is not None:
                await self._runner()
            verification = await self._verify()
        except Exception as exc:  # noqa: BLE001 - 迁移失败必须保留备份并进入恢复流程
            async with self._database.session() as session, transaction(session):
                run = await ProductMigrationRunRepository(session).get(run_id)
                run.status = MIGRATION_RECOVERY_REQUIRED
                run.current_step = "failed"
                run.error_detail = str(exc)
                run.updated_at = _now()
                await session.flush()
                return _run_dict(run)

        async with self._database.session() as session, transaction(session):
            run = await ProductMigrationRunRepository(session).get(run_id)
            run.status = MIGRATION_COMPLETED
            run.current_step = "completed"
            run.verification_detail = verification
            run.updated_at = _now()
            run.completed_at = _now()
            await session.flush()
            return _run_dict(run)

    async def mark_failed(self, run_id: str, detail: str) -> dict[str, Any]:
        async with self._database.session() as session, transaction(session):
            run = await ProductMigrationRunRepository(session).get(run_id)
            if run is None:
                raise ValidationFailed("迁移执行记录不存在", details={"run_id": run_id})
            run.status = MIGRATION_FAILED
            run.current_step = "failed"
            run.error_detail = detail
            run.updated_at = _now()
            await session.flush()
            return _run_dict(run)

    async def status(self) -> dict[str, Any]:
        async with self._database.session() as session:
            runs = await ProductMigrationRunRepository(session).list_unfinished()
            return {
                "target_schema_version": self.target_schema_version,
                "unfinished_runs": [_run_dict(item) for item in runs],
            }

    async def _verify(self) -> str:
        async with self._database.session() as session:
            count = await session.scalar(select(func.count()).select_from(ProductInstallationModel))
            return f"product_installations={int(count or 0)}"
