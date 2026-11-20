"""健康状态聚合（E1-T12）。

区分 Liveness / Readiness / Dependency Health；检查只读，不触发写入。
状态取值：HEALTHY / DEGRADED / UNHEALTHY / STARTING / STOPPING。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from core.errors import AppError
from core.lifecycle.states import LifecycleState
from infrastructure.database import health as database_health
from infrastructure.database.backup import BackupService
from infrastructure.database.manager import MigrationService
from infrastructure.database.service import DatabaseService
from infrastructure.events.dispatcher import EventDispatcher

if TYPE_CHECKING:
    from bootstrap.lifecycle import Lifecycle
    from bootstrap.service_registry import ServiceRegistry


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    STARTING = "STARTING"
    STOPPING = "STOPPING"


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    status: HealthStatus
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: HealthStatus
    checks: tuple[HealthCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "checks": [check.to_dict() for check in self.checks],
        }


async def collect_health(lifecycle: Lifecycle, services: ServiceRegistry) -> HealthReport:
    """聚合应用状态与关键依赖；任一依赖不可用即整体降级或不可用。"""

    state = lifecycle.state
    application = _application_check(state)
    checks: list[HealthCheck] = [application]

    database = services.try_get("database")
    if isinstance(database, DatabaseService):
        db_state = await database_health.check(database)
        if not db_state.available:
            checks.append(HealthCheck("database", HealthStatus.UNHEALTHY, "unavailable"))
        elif db_state.integrity != "ok":
            checks.append(
                HealthCheck("database", HealthStatus.UNHEALTHY, f"integrity:{db_state.integrity}")
            )
        else:
            checks.append(HealthCheck("database", HealthStatus.HEALTHY, "reachable"))
    else:
        checks.append(HealthCheck("database", HealthStatus.DEGRADED, "not_initialized"))

    migration = services.try_get("migration")
    if isinstance(migration, MigrationService):
        try:
            await migration.verify_at_head()
        except AppError as exc:
            checks.append(HealthCheck("migration", HealthStatus.UNHEALTHY, exc.code))
        else:
            checks.append(HealthCheck("migration", HealthStatus.HEALTHY, "at_head"))
    else:
        checks.append(HealthCheck("migration", HealthStatus.DEGRADED, "not_initialized"))

    checks.append(_presence_check(services, "config"))
    checks.append(_logging_check())
    checks.append(_events_check(services, database))
    checks.append(_presence_check(services, "backup", service_type=BackupService))

    if application.status in (HealthStatus.STARTING, HealthStatus.STOPPING):
        return HealthReport(application.status, tuple(checks))

    statuses = {check.status for check in checks}
    if HealthStatus.UNHEALTHY in statuses:
        overall = HealthStatus.UNHEALTHY
    elif HealthStatus.DEGRADED in statuses:
        overall = HealthStatus.DEGRADED
    else:
        overall = HealthStatus.HEALTHY
    return HealthReport(overall, tuple(checks))


def readiness(report: HealthReport) -> tuple[bool, str]:
    """Readiness 判定：RUNNING 且数据库、迁移均健康。"""

    required = {"database", "migration"}
    for check in report.checks:
        if check.name in required and check.status is not HealthStatus.HEALTHY:
            return False, check.name
    if report.status is not HealthStatus.HEALTHY:
        return False, "application"
    return True, ""


def _application_check(state: LifecycleState) -> HealthCheck:
    if state is LifecycleState.RUNNING:
        return HealthCheck("application", HealthStatus.HEALTHY, state.value)
    if state in (LifecycleState.CREATED, LifecycleState.INITIALIZING, LifecycleState.STARTING):
        return HealthCheck("application", HealthStatus.STARTING, state.value)
    if state is LifecycleState.STOPPING:
        return HealthCheck("application", HealthStatus.STOPPING, state.value)
    return HealthCheck("application", HealthStatus.UNHEALTHY, state.value)


def _presence_check(
    services: ServiceRegistry,
    name: str,
    *,
    service_type: type | None = None,
) -> HealthCheck:
    service = services.try_get(name)
    if service is None or (service_type is not None and not isinstance(service, service_type)):
        return HealthCheck(name, HealthStatus.DEGRADED, "not_registered")
    return HealthCheck(name, HealthStatus.HEALTHY, "registered")


def _logging_check() -> HealthCheck:
    handlers = logging.getLogger().handlers
    if handlers:
        return HealthCheck("logging", HealthStatus.HEALTHY, f"{len(handlers)}_handlers")
    return HealthCheck("logging", HealthStatus.DEGRADED, "no_handlers")


def _events_check(services: ServiceRegistry, database: object) -> HealthCheck:
    dispatcher = services.try_get("event_dispatcher")
    if not isinstance(dispatcher, EventDispatcher):
        return HealthCheck("events", HealthStatus.DEGRADED, "not_registered")
    if dispatcher.running:
        return HealthCheck("events", HealthStatus.HEALTHY, "running")
    if isinstance(database, DatabaseService) and database.is_ephemeral:
        return HealthCheck("events", HealthStatus.HEALTHY, "embedded")
    return HealthCheck("events", HealthStatus.DEGRADED, "not_running")
