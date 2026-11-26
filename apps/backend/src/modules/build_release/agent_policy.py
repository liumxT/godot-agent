"""Build & Release Agent 策略（E10-T19）。

冻结规则：

- Agent 只能通过 Orchestrator / Tool System 调用受控构建与发布操作；
- Agent 不得任意执行 Shell、读取签名私钥、修改 Artifact、绕过或自行批准发布、
  把 UNKNOWN 标记为成功、直接调用未授权外部发布 API；
- 发布审批与发布执行只能由用户触发。
"""

from __future__ import annotations

from core.errors import PermissionDenied, ValidationFailed

__all__ = [
    "AGENT_ACTIONS",
    "AGENT_ALLOWED_ACTIONS",
    "AGENT_FORBIDDEN_ACTIONS",
    "AGENT_ROLES",
    "AGENT_ROLE_ALLOWED_ACTIONS",
    "agent_policy",
    "ensure_agent_action_allowed",
]

AGENT_ACTION_READ_BUILD = "READ_BUILD"
AGENT_ACTION_CREATE_BUILD = "CREATE_BUILD"
AGENT_ACTION_START_BUILD = "START_BUILD"
AGENT_ACTION_CANCEL_BUILD = "CANCEL_BUILD"
AGENT_ACTION_READ_ARTIFACT = "READ_ARTIFACT"
AGENT_ACTION_CREATE_PACKAGE = "CREATE_PACKAGE"
AGENT_ACTION_REQUEST_SMOKE_TEST = "REQUEST_SMOKE_TEST"
AGENT_ACTION_CREATE_CANDIDATE = "CREATE_CANDIDATE"
AGENT_ACTION_REQUEST_APPROVAL = "REQUEST_APPROVAL"
AGENT_ACTION_READ_RELEASE = "READ_RELEASE"
AGENT_ACTION_PREPARE_RELEASE = "PREPARE_RELEASE"

AGENT_ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        AGENT_ACTION_READ_BUILD,
        AGENT_ACTION_CREATE_BUILD,
        AGENT_ACTION_START_BUILD,
        AGENT_ACTION_CANCEL_BUILD,
        AGENT_ACTION_READ_ARTIFACT,
        AGENT_ACTION_CREATE_PACKAGE,
        AGENT_ACTION_REQUEST_SMOKE_TEST,
        AGENT_ACTION_CREATE_CANDIDATE,
        AGENT_ACTION_REQUEST_APPROVAL,
        AGENT_ACTION_READ_RELEASE,
        AGENT_ACTION_PREPARE_RELEASE,
    }
)

AGENT_FORBIDDEN_ACTION_SHELL_EXEC = "SHELL_EXEC"
AGENT_FORBIDDEN_ACTION_ACCESS_SIGNING_SECRET = "ACCESS_SIGNING_SECRET"
AGENT_FORBIDDEN_ACTION_MODIFY_ARTIFACT = "MODIFY_ARTIFACT"
AGENT_FORBIDDEN_ACTION_BYPASS_APPROVAL = "BYPASS_APPROVAL"
AGENT_FORBIDDEN_ACTION_SELF_APPROVE = "SELF_APPROVE"
AGENT_FORBIDDEN_ACTION_MARK_UNKNOWN_SUCCESS = "MARK_UNKNOWN_SUCCESS"
AGENT_FORBIDDEN_ACTION_CALL_UNAUTHORIZED_PUBLISH_API = "CALL_UNAUTHORIZED_PUBLISH_API"

AGENT_FORBIDDEN_ACTIONS: frozenset[str] = frozenset(
    {
        AGENT_FORBIDDEN_ACTION_SHELL_EXEC,
        AGENT_FORBIDDEN_ACTION_ACCESS_SIGNING_SECRET,
        AGENT_FORBIDDEN_ACTION_MODIFY_ARTIFACT,
        AGENT_FORBIDDEN_ACTION_BYPASS_APPROVAL,
        AGENT_FORBIDDEN_ACTION_SELF_APPROVE,
        AGENT_FORBIDDEN_ACTION_MARK_UNKNOWN_SUCCESS,
        AGENT_FORBIDDEN_ACTION_CALL_UNAUTHORIZED_PUBLISH_API,
    }
)

AGENT_ACTIONS: frozenset[str] = AGENT_ALLOWED_ACTIONS | AGENT_FORBIDDEN_ACTIONS

ROLE_BUILD_RELEASE_ENGINEER = "build_release_engineer"
ROLE_PROJECT_PLANNING_DELIVERY_AGENT = "project_planning_delivery_agent"
ROLE_QA_ENGINEER = "qa_engineer"
ROLE_TEST_AUTOMATION_ENGINEER = "test_automation_engineer"
ROLE_GODOT_INTEGRATION_SPECIALIST = "godot_integration_specialist"

AGENT_ROLE_ALLOWED_ACTIONS: dict[str, frozenset[str]] = {
    ROLE_BUILD_RELEASE_ENGINEER: frozenset(
        {
            AGENT_ACTION_READ_BUILD,
            AGENT_ACTION_CREATE_BUILD,
            AGENT_ACTION_START_BUILD,
            AGENT_ACTION_CANCEL_BUILD,
            AGENT_ACTION_READ_ARTIFACT,
            AGENT_ACTION_CREATE_PACKAGE,
            AGENT_ACTION_REQUEST_SMOKE_TEST,
            AGENT_ACTION_CREATE_CANDIDATE,
            AGENT_ACTION_REQUEST_APPROVAL,
            AGENT_ACTION_READ_RELEASE,
            AGENT_ACTION_PREPARE_RELEASE,
        }
    ),
    ROLE_PROJECT_PLANNING_DELIVERY_AGENT: frozenset(
        {AGENT_ACTION_READ_BUILD, AGENT_ACTION_READ_ARTIFACT, AGENT_ACTION_READ_RELEASE}
    ),
    ROLE_QA_ENGINEER: frozenset(
        {
            AGENT_ACTION_READ_BUILD,
            AGENT_ACTION_READ_ARTIFACT,
            AGENT_ACTION_REQUEST_SMOKE_TEST,
            AGENT_ACTION_CREATE_CANDIDATE,
            AGENT_ACTION_REQUEST_APPROVAL,
            AGENT_ACTION_READ_RELEASE,
        }
    ),
    ROLE_TEST_AUTOMATION_ENGINEER: frozenset(
        {
            AGENT_ACTION_READ_BUILD,
            AGENT_ACTION_READ_ARTIFACT,
            AGENT_ACTION_REQUEST_SMOKE_TEST,
            AGENT_ACTION_READ_RELEASE,
        }
    ),
    ROLE_GODOT_INTEGRATION_SPECIALIST: frozenset(
        {
            AGENT_ACTION_READ_BUILD,
            AGENT_ACTION_CREATE_BUILD,
            AGENT_ACTION_START_BUILD,
            AGENT_ACTION_READ_ARTIFACT,
            AGENT_ACTION_READ_RELEASE,
        }
    ),
}

AGENT_ROLES: frozenset[str] = frozenset(AGENT_ROLE_ALLOWED_ACTIONS)


def ensure_agent_action_allowed(agent_role: str, action: str) -> None:
    """校验 Agent 角色是否可执行该构建/发布操作。"""

    if action in AGENT_FORBIDDEN_ACTIONS:
        raise PermissionDenied(
            "Agent 无权执行该构建或发布操作",
            details={"role": agent_role, "action": action, "reason": "forbidden_by_policy"},
        )
    if action not in AGENT_ALLOWED_ACTIONS:
        raise ValidationFailed(
            "未知构建发布操作",
            details={"action": action, "allowed": sorted(AGENT_ALLOWED_ACTIONS)},
        )
    if agent_role not in AGENT_ROLE_ALLOWED_ACTIONS:
        raise ValidationFailed(
            "未知 Agent 角色",
            details={"role": agent_role, "allowed": sorted(AGENT_ROLES)},
        )
    if action not in AGENT_ROLE_ALLOWED_ACTIONS[agent_role]:
        raise PermissionDenied(
            "当前 Agent 角色无权执行该操作",
            details={"role": agent_role, "action": action},
        )


def agent_policy() -> dict[str, object]:
    return {
        "allowed_actions": sorted(AGENT_ALLOWED_ACTIONS),
        "forbidden_actions": sorted(AGENT_FORBIDDEN_ACTIONS),
        "roles": {role: sorted(actions) for role, actions in AGENT_ROLE_ALLOWED_ACTIONS.items()},
        "approval_requires_user": True,
        "unknown_cannot_be_marked_success": True,
    }
