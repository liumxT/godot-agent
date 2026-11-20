"""启动步骤注册（E1-T01 / T03 / T04）。

顺序对齐设计文档：配置 → 日志 → 错误处理 → 数据库 → 迁移。
迁移失败会阻断启动（E1-FI-004），由 ``LifecycleManager`` 统一回滚。
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select

from bootstrap.service_registry import ServiceRegistry
from config.service import ConfigService
from config.settings import Environment, Settings
from core.errors import validate_error_registry
from core.events.bus import EventBus
from core.events.registry import EventRegistry
from core.lifecycle.manager import LifecycleManager
from core.logging import configure_logging, flush_logging, get_logger, log_event
from infrastructure.database.backup import BackupService
from infrastructure.database.manager import MigrationService
from infrastructure.database.service import DatabaseService
from infrastructure.events.dispatcher import EventDispatcher
from infrastructure.secrets.store import KeyringSecretStore, MemorySecretStore
from infrastructure.security.bootstrap import BootstrapTokenStore
from infrastructure.security.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter
from modules.access.service import ProjectAccessService
from modules.approval.repository import ApprovalRepository
from modules.approval.service import ApprovalService
from modules.audit.service import AuditService
from modules.bridge_event.service import BridgeEventService
from modules.bridge_metrics import BridgeMetrics
from modules.changeset.repository import ChangeSetRepository
from modules.changeset.service import ChangeSetService
from modules.client.service import AuthCleanupTask, AuthService, ClientService
from modules.context.service import ContextAssemblyService
from modules.editor_session.models import EditorSessionModel
from modules.editor_session.service import EditorSessionService
from modules.lease.service import LeaseService
from modules.model_gateway.configuration import ProviderConfigurationService
from modules.model_gateway.gateway import ModelGatewayService
from modules.model_gateway.providers.registry import default_adapter_registry
from modules.model_gateway.registry import ModelRegistryService
from modules.model_gateway.routing import ModelRoutingService
from modules.project.service import ProjectService
from modules.project_registry.service import (
    ProjectConfigurationService,
    ProjectLifecycleService,
    ProjectRegistryService,
)
from modules.prompt.service import PromptService
from modules.requirement.service import RequirementService
from modules.runtime.service import RuntimeService
from modules.session.service import SessionService
from modules.snapshot.service import SnapshotService
from modules.task.repository import TaskRepository
from modules.task.service import (
    AttemptService,
    CheckpointService,
    DependencyService,
    TaskService,
)
from modules.tool.approval import ToolApprovalGate
from modules.tool.permissions import ToolPermissionEngine
from modules.tool.registry import ToolRegistryService
from modules.workflow.repository import WorkflowInstanceRepository
from modules.workflow.service import (
    WorkflowDefinitionService,
    WorkflowInstanceService,
    WorkflowNodeService,
    WorkflowPhaseService,
    WorkflowRecoveryService,
    WorkflowScheduler,
)

STARTUP_STEP_TIMEOUT = 5.0
DATABASE_STARTUP_TIMEOUT = 10.0
MIGRATION_STARTUP_TIMEOUT = 60.0
EVENT_STARTUP_TIMEOUT = 5.0
AUTH_STARTUP_TIMEOUT = 10.0


def file_log_dir(settings: Settings) -> Path | None:
    """测试环境默认不写日志文件，避免污染工作目录与并行用例。"""

    if settings.environment is Environment.test:
        return None
    return Path(settings.log_dir)


_TASK_UNFINISHED = (
    "QUEUED",
    "RUNNING",
    "PAUSING",
    "PAUSED",
    "RESUMING",
    "WAITING_APPROVAL",
    "WAITING_USER",
    "BLOCKED",
    "REVIEW_PENDING",
)
_WORKFLOW_UNFINISHED = frozenset(
    {
        "READY",
        "RUNNING",
        "PAUSING",
        "PAUSED",
        "RESUMING",
        "WAITING_APPROVAL",
        "WAITING_USER",
        "BLOCKED",
    }
)
_CHANGESET_UNFINISHED = frozenset(
    {"DRAFT", "VALIDATING", "READY_FOR_APPROVAL", "APPROVED", "APPLYING"}
)


def _project_blockers(database: DatabaseService):
    """归档前汇总未完成操作；只读查询，不修改其他模块状态。"""

    async def blockers(project_id: str) -> dict[str, int]:
        async with database.session() as session:
            task_repository = TaskRepository(session)
            running_tasks = 0
            for status in _TASK_UNFINISHED:
                running_tasks += await task_repository.count_by_status(project_id, status)
            workflows = await WorkflowInstanceRepository(session).list_page_by_project(
                project_id, limit=200, offset=0
            )
            running_workflows = sum(
                1 for item in workflows.items if item.status in _WORKFLOW_UNFINISHED
            )
            approvals = await ApprovalRepository(session).list_page(
                project_id=project_id, status="PENDING", limit=1, offset=0
            )
            changesets = await ChangeSetRepository(session).list_page(
                project_id=project_id, status=None, limit=200, offset=0
            )
            open_changesets = sum(
                1 for item in changesets.items if item.status in _CHANGESET_UNFINISHED
            )
            active_editor_sessions = (
                await session.scalar(
                    select(func.count())
                    .select_from(EditorSessionModel)
                    .where(
                        EditorSessionModel.project_id == project_id,
                        EditorSessionModel.binding_status.in_(("CONNECTED", "RECOVERING")),
                    )
                )
                or 0
            )
        return {
            "running_tasks": running_tasks,
            "running_workflows": running_workflows,
            "pending_approvals": approvals.total,
            "open_changesets": open_changesets,
            "active_editor_sessions": active_editor_sessions,
        }

    return blockers


def apply_logging(settings: Settings) -> None:
    configure_logging(
        settings.log_level.value,
        log_dir=file_log_dir(settings),
    )


def register_startup_steps(
    manager: LifecycleManager, *, settings: Settings, services: ServiceRegistry
) -> None:
    logger = get_logger("backend.lifecycle")

    def _init_config() -> None:
        service = ConfigService(settings, on_hot_reload=apply_logging)
        services.register("config", service)
        service.log_loaded("startup")

    def _init_logging() -> None:
        apply_logging(settings)
        log_event(logger, logging.INFO, "logging_ready", component="logging")

    async def _init_database() -> None:
        service = DatabaseService(settings)
        await service.initialize()
        services.register("database", service)

    async def _dispose_database() -> None:
        service = services.try_get("database")
        if isinstance(service, DatabaseService):
            await service.dispose()

    async def _run_migrations() -> None:
        database = services.get("database", DatabaseService)
        migration = MigrationService(settings, database=database)
        await migration.run()
        services.register("migration", migration)

    async def _init_auth() -> None:
        database = services.get("database", DatabaseService)
        is_test = settings.environment is Environment.test
        secret_store = MemorySecretStore() if is_test else KeyringSecretStore()
        bootstrap = BootstrapTokenStore(
            settings.data_dir,
            filename=settings.bootstrap_token_file,
            persist=not is_test,
        )
        bootstrap.ensure()
        limiter = SlidingWindowRateLimiter(settings.rate_limit_auth_per_minute)
        audit_service = AuditService(database, fail_closed=settings.audit_fail_closed)
        client_service = ClientService(database, secret_store, audit=audit_service)
        auth_service = AuthService(
            database,
            secret_store,
            challenge_ttl_seconds=settings.auth_challenge_ttl_seconds,
            access_token_ttl_seconds=settings.access_token_ttl_seconds,
            token_retention_days=settings.token_retention_days,
            limiter=limiter,
            audit=audit_service,
        )
        cleanup = AuthCleanupTask(
            auth_service, interval_seconds=settings.auth_cleanup_interval_seconds
        )
        session_service = SessionService(
            database,
            ttl_seconds=settings.session_ttl_seconds,
            max_ttl_seconds=settings.session_max_ttl_seconds,
            retention_days=settings.session_retention_days,
            audit=audit_service,
        )
        access_service = ProjectAccessService(
            database,
            ttl_seconds=settings.project_access_ttl_seconds,
            audit=audit_service,
        )
        rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_default_per_minute)
        concurrency_limiter = ConcurrencyLimiter(settings.rate_limit_max_concurrency)
        project_service = ProjectService(database)
        editor_session_service = EditorSessionService(database)
        lease_service = LeaseService(
            database,
            ttl_seconds=settings.bridge_lease_ttl_seconds,
            audit=audit_service,
        )
        bridge_event_service = BridgeEventService(
            database,
            retention_days=settings.bridge_event_retention_days,
        )
        snapshot_service = SnapshotService(
            database,
            ttl_seconds=settings.bridge_snapshot_ttl_seconds,
            keep_per_session=settings.bridge_snapshot_keep_per_session,
        )
        runtime_service = RuntimeService(database)
        project_registry_service = ProjectRegistryService(database, identity=project_service)
        project_configuration_service = ProjectConfigurationService(database)
        task_service = TaskService(database)
        task_attempt_service = AttemptService(database)
        task_dependency_service = DependencyService(database)
        task_checkpoint_service = CheckpointService(database)
        workflow_definition_service = WorkflowDefinitionService(database)
        workflow_instance_service = WorkflowInstanceService(database, tasks=task_service)
        workflow_node_service = WorkflowNodeService(
            database, tasks=task_service, instances=workflow_instance_service
        )
        workflow_phase_service = WorkflowPhaseService(
            database,
            nodes=workflow_node_service,
            instances=workflow_instance_service,
            tasks=task_service,
        )
        workflow_scheduler = WorkflowScheduler(
            database,
            nodes=workflow_node_service,
            instances=workflow_instance_service,
        )
        workflow_recovery_service = WorkflowRecoveryService(database, tasks=task_service)
        requirement_service = RequirementService(database)
        approval_service = ApprovalService(database)
        changeset_service = ChangeSetService(database, approvals=approval_service)
        adapter_registry = default_adapter_registry()
        provider_configuration_service = ProviderConfigurationService(
            database,
            secret_store,
            adapters=adapter_registry,
            default_timeout_seconds=settings.model_gateway_default_timeout_seconds,
        )
        model_registry_service = ModelRegistryService(database)
        model_routing_service = ModelRoutingService(model_registry_service)
        model_gateway_service = ModelGatewayService(
            database,
            secret_store,
            model_registry_service,
            adapters=adapter_registry,
            max_request_bytes=settings.model_gateway_max_request_bytes,
            max_retries=settings.model_gateway_max_retries,
            retry_backoff_seconds=settings.model_gateway_retry_backoff_seconds,
            default_timeout_seconds=settings.model_gateway_default_timeout_seconds,
        )
        project_lifecycle_service = ProjectLifecycleService(
            database,
            blockers=_project_blockers(database),
        )
        prompt_service = PromptService(database)
        context_assembly_service = ContextAssemblyService(
            database,
            projects=project_registry_service,
            configurations=project_configuration_service,
            tasks=task_service,
            attempts=task_attempt_service,
            workflows=workflow_instance_service,
        )
        tool_registry_service = ToolRegistryService(database)
        tool_approval_gate = ToolApprovalGate(approval_service)
        tool_permission_engine = ToolPermissionEngine(
            access=access_service,
            tasks=task_service,
            tools=tool_registry_service,
            approvals=tool_approval_gate,
        )
        try:
            await auth_service.purge_expired()
            await session_service.expire_stale()
            await access_service.expire_stale()
            await lease_service.expire_stale()
            await bridge_event_service.prune()
            await snapshot_service.prune_expired()
            await runtime_service.expire_stale(
                timeout_seconds=settings.bridge_runtime_timeout_seconds
            )
        except Exception:  # noqa: BLE001 - 清理失败不阻断启动
            log_event(
                logger,
                logging.WARNING,
                "auth_cleanup_failed",
                component="auth",
                error_code="INFRASTRUCTURE_ERROR",
            )
        try:
            await workflow_recovery_service.recover()
        except Exception:  # noqa: BLE001 - 恢复失败不阻断启动，但需留痕
            log_event(
                logger,
                logging.ERROR,
                "workflow_recovery_failed",
                component="workflow",
                error_code="INFRASTRUCTURE_ERROR",
            )
        await cleanup.start()

        services.register("secret_store", secret_store)
        services.register("bootstrap_token", bootstrap)
        services.register("audit_service", audit_service)
        services.register("auth_rate_limiter", limiter)
        services.register("client_service", client_service)
        services.register("auth_service", auth_service)
        services.register("auth_cleanup", cleanup)
        services.register("session_service", session_service)
        services.register("project_service", project_service)
        services.register("editor_session_service", editor_session_service)
        services.register("lease_service", lease_service)
        services.register("bridge_event_service", bridge_event_service)
        services.register("snapshot_service", snapshot_service)
        services.register("runtime_service", runtime_service)
        services.register("project_registry_service", project_registry_service)
        services.register("project_configuration_service", project_configuration_service)
        services.register("project_lifecycle_service", project_lifecycle_service)
        services.register("task_service", task_service)
        services.register("task_attempt_service", task_attempt_service)
        services.register("task_dependency_service", task_dependency_service)
        services.register("task_checkpoint_service", task_checkpoint_service)
        services.register("workflow_definition_service", workflow_definition_service)
        services.register("workflow_instance_service", workflow_instance_service)
        services.register("workflow_node_service", workflow_node_service)
        services.register("workflow_phase_service", workflow_phase_service)
        services.register("workflow_scheduler", workflow_scheduler)
        services.register("workflow_recovery_service", workflow_recovery_service)
        services.register("requirement_service", requirement_service)
        services.register("approval_service", approval_service)
        services.register("changeset_service", changeset_service)
        services.register("provider_configuration_service", provider_configuration_service)
        services.register("model_registry_service", model_registry_service)
        services.register("model_routing_service", model_routing_service)
        services.register("model_gateway_service", model_gateway_service)
        services.register("prompt_service", prompt_service)
        services.register("context_assembly_service", context_assembly_service)
        services.register("tool_registry_service", tool_registry_service)
        services.register("tool_approval_gate", tool_approval_gate)
        services.register("tool_permission_engine", tool_permission_engine)
        services.register("project_access_service", access_service)
        services.register("bridge_metrics", BridgeMetrics())
        services.register("rate_limiter", rate_limiter)
        services.register("concurrency_limiter", concurrency_limiter)
        log_event(logger, logging.INFO, "auth_ready", component="auth")

    async def _stop_auth() -> None:
        cleanup = services.try_get("auth_cleanup")
        if isinstance(cleanup, AuthCleanupTask):
            await cleanup.stop()

    async def _init_events() -> None:
        database = services.get("database", DatabaseService)
        registry = EventRegistry()
        bus = EventBus(registry)
        dispatcher = EventDispatcher(
            database,
            registry,
            poll_interval=settings.event_poll_interval_ms / 1000,
            batch_size=settings.event_batch_size,
            max_retries=settings.event_max_retries,
        )
        services.register("event_registry", registry)
        services.register("event_bus", bus)
        services.register("event_dispatcher", dispatcher)
        await dispatcher.start()

    async def _stop_events() -> None:
        dispatcher = services.try_get("event_dispatcher")
        if isinstance(dispatcher, EventDispatcher):
            await dispatcher.stop()

    def _init_backup() -> None:
        backup = BackupService(
            settings,
            database=services.get("database", DatabaseService),
            dispatcher=services.try_get("event_dispatcher"),
        )
        services.register("backup", backup)

    manager.register_startup_step("config", _init_config, timeout=STARTUP_STEP_TIMEOUT)
    manager.register_startup_step(
        "logging",
        _init_logging,
        rollback=flush_logging,
        timeout=STARTUP_STEP_TIMEOUT,
    )
    manager.register_startup_step("errors", validate_error_registry, timeout=1.0)
    manager.register_startup_step(
        "database",
        _init_database,
        rollback=_dispose_database,
        timeout=DATABASE_STARTUP_TIMEOUT,
    )
    manager.register_startup_step(
        "migration",
        _run_migrations,
        timeout=MIGRATION_STARTUP_TIMEOUT,
    )
    manager.register_startup_step(
        "auth",
        _init_auth,
        rollback=_stop_auth,
        timeout=AUTH_STARTUP_TIMEOUT,
    )
    manager.register_startup_step(
        "events",
        _init_events,
        rollback=_stop_events,
        timeout=EVENT_STARTUP_TIMEOUT,
    )
    manager.register_startup_step("backup", _init_backup, timeout=STARTUP_STEP_TIMEOUT)
