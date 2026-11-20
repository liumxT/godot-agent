"""E4 Project / Task / Workflow / ChangeSet / Approval 集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    ApprovalExpired,
    ApprovalHashMismatch,
    DependencyCycle,
    InvalidStateTransition,
    ValidationFailed,
    VersionConflict,
)
from modules.approval.models import APPROVAL_TYPE_CHANGESET_APPLY, TARGET_CHANGESET_HASH
from modules.approval.service import ApprovalService
from modules.changeset.service import ChangeSetService
from modules.project_registry.service import (
    ProjectConfigurationService,
    ProjectLifecycleService,
    ProjectRegistryService,
)
from modules.task.models import TASK_BLOCKED, TASK_RUNNING
from modules.task.service import AttemptService, DependencyService, TaskService
from modules.workflow.service import (
    WorkflowDefinitionService,
    WorkflowInstanceService,
    WorkflowNodeService,
    WorkflowPhaseService,
    WorkflowRecoveryService,
    WorkflowScheduler,
)


@asynccontextmanager
async def _running(tmp_path: Path, name: str = "e4.db"):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / name).as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "demo_project"
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="Demo"\n', encoding="utf-8"
    )
    return root


async def _project_id(app, project_root: Path) -> str:
    view = await app.state.services.get(
        "project_registry_service", ProjectRegistryService
    ).register(project_root=str(project_root), name="Demo", created_by="cli_test")
    return view.project_id


async def _running_task(app, project_id: str) -> str:
    tasks = app.state.services.get("task_service", TaskService)
    task = await tasks.create(project_id=project_id, title="Build level", created_by="cli_test")
    await tasks.transition(task.task_id, "QUEUED")
    await tasks.transition(task.task_id, "RUNNING")
    return task.task_id


async def test_task_attempt_and_event_sequence(tmp_path: Path, project_root: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project_id(app, project_root)
        tasks = app.state.services.get("task_service", TaskService)
        attempts = app.state.services.get("task_attempt_service", AttemptService)

        task = await tasks.create(project_id=project_id, title="Build level", created_by="cli")
        assert task.status == "READY"

        running = await tasks.transition(task.task_id, "QUEUED")
        assert running.status == "QUEUED"
        running = await tasks.transition(task.task_id, "RUNNING")
        assert running.status == "RUNNING"

        attempt = await attempts.create(task.task_id, agent_instance_id="agt_1")
        assert attempt.attempt_number == 1
        await attempts.start(attempt.attempt_id)
        finished = await attempts.finish(attempt.attempt_id, "SUCCEEDED", summary="done")
        assert finished.status == "SUCCEEDED"

        events = await tasks.list_events(task.task_id)
        sequences = [item.sequence for item in events["items"]]
        assert sequences == sorted(sequences)
        event_types = {item.event_type for item in events["items"]}
        assert {"TASK_CREATED", "TASK_READY", "TASK_STARTED", "ATTEMPT_CREATED"} <= event_types


async def test_dependencies_block_and_cycle_detection(tmp_path: Path, project_root: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project_id(app, project_root)
        tasks = app.state.services.get("task_service", TaskService)
        dependencies = app.state.services.get("task_dependency_service", DependencyService)

        first = await tasks.create(project_id=project_id, title="First")
        second = await tasks.create(project_id=project_id, title="Second")
        await dependencies.create(first.task_id, second.task_id)

        with pytest.raises(DependencyCycle):
            await dependencies.create(second.task_id, first.task_id)

        await tasks.transition(second.task_id, "QUEUED")
        with pytest.raises(InvalidStateTransition):
            await tasks.transition(second.task_id, TASK_RUNNING)

        await tasks.transition(first.task_id, "QUEUED")
        await tasks.transition(first.task_id, "RUNNING")
        await tasks.transition(first.task_id, "REVIEW_PENDING")
        await tasks.transition(first.task_id, "COMPLETED")

        unblocked = await dependencies.on_task_completed(first.task_id, tasks=tasks)
        assert second.task_id in unblocked or not await dependencies.is_blocked(second.task_id)
        await tasks.transition(second.task_id, "RUNNING")


async def test_workflow_completion_requires_phase_acceptance(
    tmp_path: Path, project_root: Path
) -> None:
    async with _running(tmp_path) as app:
        services = app.state.services
        project_id = await _project_id(app, project_root)
        task_id = await _running_task(app, project_id)
        tasks = services.get("task_service", TaskService)
        definitions = services.get("workflow_definition_service", WorkflowDefinitionService)
        instances = services.get("workflow_instance_service", WorkflowInstanceService)
        nodes = services.get("workflow_node_service", WorkflowNodeService)
        phases = services.get("workflow_phase_service", WorkflowPhaseService)
        scheduler = services.get("workflow_scheduler", WorkflowScheduler)

        definition = await definitions.create(
            name="Basic flow",
            category="GAME_DEVELOPMENT",
            document={
                "nodes": [
                    {"node_key": "analyze", "node_type": "AI_EXECUTION", "phase_key": "p1"},
                    {
                        "node_key": "implement",
                        "node_type": "TOOL_OPERATION",
                        "dependency_keys": ["analyze"],
                        "phase_key": "p1",
                    },
                ],
                "phases": [{"phase_key": "p1", "name": "Phase 1"}],
            },
        )
        instance = await instances.create(
            project_id=project_id,
            task_id=task_id,
            definition_id=definition.definition_id,
        )

        tick = await scheduler.tick(instance.instance_id)
        assert tick["started"]["node_key"] == "analyze"

        await nodes.complete_node(instance.instance_id, "analyze")
        await nodes.advance(instance.instance_id)
        await nodes.start_node(instance.instance_id, "implement")
        await nodes.complete_node(instance.instance_id, "implement", output_ref="res://out")

        phase_rows = await phases.list_phases(instance.instance_id)
        assert phase_rows[0].status == "REVIEW_PENDING"
        await phases.submit_review(
            instance.instance_id, "p1", summary="phase done", deliverables=["res://out"]
        )
        await phases.accept_phase(instance.instance_id, "p1", actor_id="cli_user")

        completed = await instances.get(instance.instance_id)
        assert completed.status == "COMPLETED"
        task = await tasks.get(task_id)
        assert task.status == "REVIEW_PENDING"

        accepted = await tasks.accept(task_id, actor_id="cli_user")
        assert accepted.status == "COMPLETED"


async def test_changeset_approval_and_apply(tmp_path: Path, project_root: Path) -> None:
    async with _running(tmp_path) as app:
        services = app.state.services
        project_id = await _project_id(app, project_root)
        changesets = services.get("changeset_service", ChangeSetService)
        approvals = services.get("approval_service", ApprovalService)

        changeset = await changesets.create(
            project_id=project_id,
            title="Add scene",
            items=[
                {
                    "resource_path": "scenes/main.tscn",
                    "operation_type": "CREATE",
                    "new_content_hash": "a" * 64,
                    "risk_level": "LOW",
                }
            ],
        )
        assert changeset.status == "DRAFT"

        validation = await changesets.validate(changeset.changeset_id)
        assert validation["status"] == "VALID"

        approval = await changesets.submit_for_approval(changeset.changeset_id, requested_by="cli")
        approved = await changesets.approve(
            changeset.changeset_id, approval.approval_id, actor_id="cli_owner"
        )
        assert approved.status == "APPROVED"

        applying = await changesets.start_apply(
            changeset.changeset_id, approval.approval_id, actor_id="cli_owner"
        )
        assert applying.status == "APPLYING"
        applied = await changesets.finish_apply(changeset.changeset_id)
        assert applied.status == "APPLIED"
        assert (await changesets.verify_hash(changeset.changeset_id))["valid"] is True

        mismatch = await approvals.create(
            project_id=project_id,
            target_type=TARGET_CHANGESET_HASH,
            target_id=changeset.changeset_id,
            target_hash="f" * 64,
            approval_type=APPROVAL_TYPE_CHANGESET_APPLY,
        )
        with pytest.raises(ApprovalHashMismatch):
            await approvals.approve(
                mismatch.approval_id,
                actor_id="cli_owner",
                current_target_hash="0" * 64,
            )


async def test_approval_expiry_is_persisted(tmp_path: Path, project_root: Path) -> None:
    async with _running(tmp_path) as app:
        project_id = await _project_id(app, project_root)
        approvals = app.state.services.get("approval_service", ApprovalService)
        approval = await approvals.create(
            project_id=project_id,
            target_type=TARGET_CHANGESET_HASH,
            target_id="chs_missing",
            target_hash="a" * 64,
            approval_type=APPROVAL_TYPE_CHANGESET_APPLY,
            ttl_seconds=-1,
        )
        with pytest.raises(ApprovalExpired):
            await approvals.approve(approval.approval_id, actor_id="cli_owner")

        reloaded = await approvals.get(approval.approval_id)
        assert reloaded.status == "EXPIRED"


async def test_project_registry_configuration_and_lifecycle(
    tmp_path: Path, project_root: Path
) -> None:
    async with _running(tmp_path) as app:
        services = app.state.services
        registry = services.get("project_registry_service", ProjectRegistryService)
        configuration = services.get("project_configuration_service", ProjectConfigurationService)
        lifecycle = services.get("project_lifecycle_service", ProjectLifecycleService)
        tasks = services.get("task_service", TaskService)

        project = await registry.register(
            project_root=str(project_root), name="Lifecycle", created_by="cli_test"
        )
        assert project.status == "ACTIVE"
        assert (await registry.verify_identity(project.project_id)).project_id == project.project_id

        config = await configuration.get(project.project_id)
        assert config.values
        updated = await configuration.update(
            project.project_id,
            {"default_language": "zh-CN"},
            expected_version=config.version,
        )
        assert updated.version == config.version + 1
        with pytest.raises(VersionConflict):
            await configuration.update(
                project.project_id, {"default_language": "en"}, expected_version=config.version
            )

        with pytest.raises(InvalidStateTransition):
            await lifecycle.transition(project.project_id, "INITIALIZING")

        assert (await lifecycle.suspend(project.project_id)).status == "SUSPENDED"
        assert (await lifecycle.resume(project.project_id)).status == "ACTIVE"
        assert (await lifecycle.close(project.project_id)).status == "CLOSED"
        assert (await lifecycle.reactivate(project.project_id)).status == "ACTIVE"

        await tasks.create(project_id=project.project_id, title="Running work", created_by="cli")
        running = (await tasks.list(project.project_id))["items"][0]
        await tasks.transition(running.task_id, "QUEUED")
        await tasks.transition(running.task_id, "RUNNING")

        with pytest.raises(InvalidStateTransition) as blocked:
            await lifecycle.archive(project.project_id)
        blockers = blocked.value.details["blockers"]
        assert blockers["running_tasks"] >= 1

        archived = await lifecycle.archive(project.project_id, force=True)
        assert archived.status == "ARCHIVED"


async def test_approval_cannot_be_reused_across_changesets(
    tmp_path: Path, project_root: Path
) -> None:
    async with _running(tmp_path) as app:
        services = app.state.services
        project_id = await _project_id(app, project_root)
        changesets = services.get("changeset_service", ChangeSetService)
        approvals = services.get("approval_service", ApprovalService)

        def item(path: str) -> dict:
            return {
                "resource_path": path,
                "operation_type": "CREATE",
                "new_content_hash": "a" * 64,
                "risk_level": "LOW",
            }

        first = await changesets.create(project_id=project_id, title="One", items=[item("a.gd")])
        second = await changesets.create(project_id=project_id, title="Two", items=[item("b.gd")])
        await changesets.validate(first.changeset_id)
        await changesets.validate(second.changeset_id)

        foreign = await changesets.submit_for_approval(second.changeset_id, requested_by="cli")
        with pytest.raises(ValidationFailed):
            await changesets.approve(first.changeset_id, foreign.approval_id, actor_id="cli_owner")
        # 越权尝试不能消耗他人审批。
        assert (await approvals.get(foreign.approval_id)).status == "PENDING"

        own = await changesets.submit_for_approval(first.changeset_id, requested_by="cli")
        approved = await changesets.approve(
            first.changeset_id, own.approval_id, actor_id="cli_owner"
        )
        assert approved.status == "APPROVED"
        assert (
            await changesets.approve(first.changeset_id, own.approval_id, actor_id="cli_owner")
        ).status == "APPROVED"

        # 审批后内容变化：旧审批保留，但哈希绑定使新内容无法复用该审批。
        other = await changesets.create(project_id=project_id, title="Bind", items=[item("d.gd")])
        await changesets.validate(other.changeset_id)
        bound = await changesets.submit_for_approval(other.changeset_id, requested_by="cli")
        replaced = await changesets.replace_manifest(other.changeset_id, [item("e.gd")])
        assert replaced.status == "DRAFT"
        await changesets.validate(other.changeset_id)
        with pytest.raises(ApprovalHashMismatch):
            await changesets.approve(other.changeset_id, bound.approval_id, actor_id="cli_owner")
        assert (await approvals.get(bound.approval_id)).status == "PENDING"


async def test_workflow_instance_pins_definition_version(
    tmp_path: Path, project_root: Path
) -> None:
    async with _running(tmp_path) as app:
        services = app.state.services
        project_id = await _project_id(app, project_root)
        task_id = await _running_task(app, project_id)
        definitions = services.get("workflow_definition_service", WorkflowDefinitionService)
        instances = services.get("workflow_instance_service", WorkflowInstanceService)

        definition = await definitions.create(
            name="Pinned",
            category="GAME_DEVELOPMENT",
            document={
                "nodes": [{"node_key": "analyze", "node_type": "AI_EXECUTION"}],
                "phases": [{"phase_key": "p1", "name": "Phase 1"}],
            },
        )
        instance = await instances.create(
            project_id=project_id,
            task_id=task_id,
            definition_id=definition.definition_id,
        )
        assert instance.definition_version == 1

        await definitions.add_version(
            definition.definition_id,
            {
                "nodes": [{"node_key": "other", "node_type": "AI_EXECUTION"}],
                "phases": [{"phase_key": "p1", "name": "Phase 1"}],
            },
        )
        pinned = await instances.get(instance.instance_id)
        assert pinned.definition_version == 1


async def test_recovery_marks_unknown_attempt_and_blocked_task(
    tmp_path: Path, project_root: Path
) -> None:
    async with _running(tmp_path, name="recovery.db") as app:
        project_id = await _project_id(app, project_root)
        task_id = await _running_task(app, project_id)
        attempts = app.state.services.get("task_attempt_service", AttemptService)
        tasks = app.state.services.get("task_service", TaskService)
        recovery = app.state.services.get("workflow_recovery_service", WorkflowRecoveryService)

        attempt = await attempts.create(task_id)
        await attempts.start(attempt.attempt_id)

        report = await recovery.recover()
        assert report["recovered_attempts"] >= 1
        recovered = await attempts.get(attempt.attempt_id)
        assert recovered.status == "UNKNOWN"
        task = await tasks.get(task_id)
        assert task.status == TASK_BLOCKED
