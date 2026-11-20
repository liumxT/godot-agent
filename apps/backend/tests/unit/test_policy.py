"""授权策略单元测试（E2-T08-UT）。"""

from __future__ import annotations

from core.security.policy import (
    DECISION_ALLOW,
    DECISION_DENY,
    REASON_CAPABILITY_MISSING,
    REASON_PROJECT_DENIED,
    REASON_RESOURCE_MISMATCH,
    REASON_ROLE_DENIED,
    REASON_UNKNOWN_PRINCIPAL,
    evaluate,
)
from core.security.principal import (
    ACTION_DIAGNOSTICS_READ,
    ACTION_E4_APPROVAL_DECIDE,
    ACTION_E4_APPROVAL_READ,
    ACTION_E4_CHANGESET_APPROVE,
    ACTION_E4_CHANGESET_MANAGE,
    ACTION_E4_PROJECT_MANAGE,
    ACTION_E4_TASK_MANAGE,
    ACTION_E4_TASK_READ,
    ACTION_PROJECT_ACCESS_GRANT,
    ACTION_PROJECT_ACCESS_READ,
    ACTION_SESSION_CREATE,
    Principal,
    Resource,
)

PROJECT = Resource(kind="project", project_id="proj_alpha")


def _principal(role: str, *, project_id: str | None = None) -> Principal:
    return Principal(
        client_id="cli_ab2cd3ef4g5h",
        client_type="admin" if role == "admin" else "godot_editor",
        session_id="ses_ab2cd3ef4g5h",
        role=role,
        project_id=project_id,
    )


def test_unknown_action_is_denied() -> None:
    decision = evaluate(_principal("admin"), "project.delete_all")

    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_CAPABILITY_MISSING


def test_unknown_principal_is_denied() -> None:
    decision = evaluate(None, ACTION_SESSION_CREATE)

    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_UNKNOWN_PRINCIPAL


def test_admin_is_allowed_globally() -> None:
    decision = evaluate(_principal("admin"), ACTION_PROJECT_ACCESS_GRANT, PROJECT)

    assert decision.decision == DECISION_ALLOW
    assert decision.policy_id == "rbac.admin"


def test_client_level_actions_are_allowed_for_authenticated_clients() -> None:
    assert evaluate(_principal("client"), ACTION_SESSION_CREATE).decision == DECISION_ALLOW
    assert evaluate(_principal("client"), ACTION_DIAGNOSTICS_READ).decision == DECISION_ALLOW


def test_project_action_without_resource_is_denied() -> None:
    decision = evaluate(_principal("owner"), ACTION_PROJECT_ACCESS_READ)

    assert decision.reason == REASON_RESOURCE_MISMATCH


def test_project_scope_mismatch_is_denied() -> None:
    decision = evaluate(
        _principal("owner", project_id="proj_beta"), ACTION_PROJECT_ACCESS_READ, PROJECT
    )

    assert decision.reason == REASON_PROJECT_DENIED


def test_viewer_can_read_but_not_manage() -> None:
    read = evaluate(
        _principal("viewer", project_id="proj_alpha"), ACTION_PROJECT_ACCESS_READ, PROJECT
    )
    grant = evaluate(
        _principal("viewer", project_id="proj_alpha"), ACTION_PROJECT_ACCESS_GRANT, PROJECT
    )

    assert read.decision == DECISION_ALLOW
    assert grant.reason == REASON_ROLE_DENIED


def test_editor_cannot_revoke_access() -> None:
    decision = evaluate(
        _principal("editor", project_id="proj_alpha"), ACTION_PROJECT_ACCESS_GRANT, PROJECT
    )

    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_ROLE_DENIED


def test_owner_can_manage_project() -> None:
    decision = evaluate(
        _principal("owner", project_id="proj_alpha"), ACTION_PROJECT_ACCESS_GRANT, PROJECT
    )

    assert decision.decision == DECISION_ALLOW
    assert decision.policy_id == "abac.project.manage"


def test_e4_viewer_reads_but_cannot_manage() -> None:
    viewer = _principal("viewer", project_id="proj_alpha")

    assert evaluate(viewer, ACTION_E4_TASK_READ, PROJECT).decision == DECISION_ALLOW
    assert evaluate(viewer, ACTION_E4_APPROVAL_READ, PROJECT).decision == DECISION_ALLOW
    assert evaluate(viewer, ACTION_E4_TASK_MANAGE, PROJECT).reason == REASON_ROLE_DENIED
    assert evaluate(viewer, ACTION_E4_CHANGESET_MANAGE, PROJECT).reason == REASON_ROLE_DENIED


def test_e4_editor_manages_but_cannot_decide_approval() -> None:
    editor = _principal("editor", project_id="proj_alpha")

    assert evaluate(editor, ACTION_E4_TASK_MANAGE, PROJECT).decision == DECISION_ALLOW
    assert evaluate(editor, ACTION_E4_CHANGESET_APPROVE, PROJECT).decision == DECISION_ALLOW
    assert evaluate(editor, ACTION_E4_APPROVAL_DECIDE, PROJECT).reason == REASON_ROLE_DENIED
    assert evaluate(editor, ACTION_E4_PROJECT_MANAGE, PROJECT).reason == REASON_ROLE_DENIED


def test_e4_owner_can_decide_approval_and_manage_project() -> None:
    owner = _principal("owner", project_id="proj_alpha")

    assert evaluate(owner, ACTION_E4_APPROVAL_DECIDE, PROJECT).decision == DECISION_ALLOW
    assert evaluate(owner, ACTION_E4_PROJECT_MANAGE, PROJECT).decision == DECISION_ALLOW
