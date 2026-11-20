"""RBAC + ABAC + Capability 纯策略（E2-T08）。

输入只包含 Principal / Action / Resource；不访问数据库、不读 keyring。
UNKNOWN 一律 DENY：未知主体、未知动作、项目越权或资源归属不明都拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from core.security.principal import (
    ACTION_E4_APPROVAL_DECIDE,
    ACTION_E4_CHANGESET_APPROVE,
    ACTION_PROJECT_ACCESS_GRANT,
    ACTION_PROJECT_ACCESS_READ,
    ACTION_PROJECT_ACCESS_REVOKE,
    ACTIONS,
    E4_PROJECT_ACTIONS,
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_OWNER,
    ROLE_VIEWER,
    Principal,
    Resource,
)

DECISION_ALLOW = "ALLOW"
DECISION_DENY = "DENY"

REASON_UNKNOWN_PRINCIPAL = "unknown_principal"
REASON_PROJECT_DENIED = "project_denied"
REASON_ROLE_DENIED = "role_denied"
REASON_CAPABILITY_MISSING = "capability_missing"
REASON_RESOURCE_MISMATCH = "resource_mismatch"

_PROJECT_ACTIONS = frozenset(
    {
        ACTION_PROJECT_ACCESS_READ,
        ACTION_PROJECT_ACCESS_GRANT,
        ACTION_PROJECT_ACCESS_REVOKE,
    }
    | E4_PROJECT_ACTIONS
)
_PROJECT_READ_ROLES = frozenset({ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER})
_PROJECT_MANAGE_ROLES = frozenset({ROLE_OWNER})
_PROJECT_EDIT_ROLES = frozenset({ROLE_OWNER, ROLE_EDITOR})
_E4_READ_ACTIONS = frozenset(action for action in E4_PROJECT_ACTIONS if action.endswith(".read"))


@dataclass(frozen=True)
class AuthorizationDecision:
    decision: str
    reason: str | None
    policy_id: str
    checked_at: datetime

    @property
    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOW


def _allow(policy_id: str) -> AuthorizationDecision:
    return AuthorizationDecision(
        decision=DECISION_ALLOW,
        reason=None,
        policy_id=policy_id,
        checked_at=datetime.now(UTC),
    )


def _deny(reason: str, policy_id: str) -> AuthorizationDecision:
    return AuthorizationDecision(
        decision=DECISION_DENY,
        reason=reason,
        policy_id=policy_id,
        checked_at=datetime.now(UTC),
    )


def evaluate(
    principal: Principal | None,
    action: str,
    resource: Resource | None = None,
) -> AuthorizationDecision:
    """执行 Capability → RBAC → ABAC 检查。"""

    if action not in ACTIONS:
        return _deny(REASON_CAPABILITY_MISSING, "capability.unknown")
    if principal is None or not principal.client_id:
        return _deny(REASON_UNKNOWN_PRINCIPAL, "principal.unknown")

    if principal.role == ROLE_ADMIN:
        return _allow("rbac.admin")

    if action not in _PROJECT_ACTIONS:
        return _allow("rbac.client")

    if resource is None or resource.project_id is None:
        return _deny(REASON_RESOURCE_MISMATCH, "abac.resource")
    if principal.project_id != resource.project_id:
        return _deny(REASON_PROJECT_DENIED, "abac.project")
    if action == ACTION_PROJECT_ACCESS_READ:
        if principal.role in _PROJECT_READ_ROLES:
            return _allow("abac.project.read")
        return _deny(REASON_ROLE_DENIED, "rbac.project.read")
    if action == ACTION_E4_APPROVAL_DECIDE:
        if principal.role in _PROJECT_MANAGE_ROLES:
            return _allow("abac.approval.decide")
        return _deny(REASON_ROLE_DENIED, "rbac.approval.decide")
    if action in _E4_READ_ACTIONS:
        if principal.role in _PROJECT_READ_ROLES:
            return _allow("abac.e4.read")
        return _deny(REASON_ROLE_DENIED, "rbac.e4.read")
    if action == ACTION_E4_CHANGESET_APPROVE:
        if principal.role in _PROJECT_EDIT_ROLES:
            return _allow("abac.changeset.approve")
        return _deny(REASON_ROLE_DENIED, "rbac.changeset.approve")
    if principal.role in _PROJECT_EDIT_ROLES:
        if action.startswith("project."):
            if principal.role in _PROJECT_MANAGE_ROLES:
                return _allow("abac.project.manage")
            return _deny(REASON_ROLE_DENIED, "rbac.project.manage")
        return _allow("abac.e4.manage")
    if principal.role in _PROJECT_MANAGE_ROLES:
        return _allow("abac.project.manage")
    return _deny(REASON_ROLE_DENIED, "rbac.project.manage")
