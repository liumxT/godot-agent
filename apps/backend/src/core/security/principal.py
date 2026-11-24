"""安全模型：Principal、Action 与 Resource（E2-T08）。

本模块不依赖数据库与基础设施，只描述授权决策的输入。
"""

from __future__ import annotations

from dataclasses import dataclass

ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ROLE_CLIENT = "client"

ACTION_SYSTEM_READ = "system.read"
ACTION_CLIENT_REGISTER = "client.register"
ACTION_CLIENT_READ = "client.read"
ACTION_SESSION_CREATE = "session.create"
ACTION_SESSION_READ = "session.read"
ACTION_SESSION_REVOKE = "session.revoke"
ACTION_PROJECT_ACCESS_READ = "project.access.read"
ACTION_PROJECT_ACCESS_GRANT = "project.access.grant"
ACTION_PROJECT_ACCESS_REVOKE = "project.access.revoke"
ACTION_DIAGNOSTICS_READ = "diagnostics.read"
ACTION_BRIDGE_READ = "bridge.read"
ACTION_BRIDGE_WRITE = "bridge.write"
ACTION_E4_PROJECT_READ = "project.read"
ACTION_E4_PROJECT_MANAGE = "project.manage"
ACTION_E4_TASK_READ = "task.read"
ACTION_E4_TASK_MANAGE = "task.manage"
ACTION_E4_WORKFLOW_READ = "workflow.read"
ACTION_E4_WORKFLOW_MANAGE = "workflow.manage"
ACTION_E4_CHANGESET_READ = "changeset.read"
ACTION_E4_CHANGESET_MANAGE = "changeset.manage"
ACTION_E4_CHANGESET_APPROVE = "changeset.approve"
ACTION_E4_APPROVAL_READ = "approval.read"
ACTION_E4_APPROVAL_DECIDE = "approval.decide"
ACTION_E5_TOOL_READ = "tool.read"
ACTION_E5_TOOL_MANAGE = "tool.manage"
ACTION_E5_MODEL_READ = "model.read"
ACTION_E5_MODEL_MANAGE = "model.manage"
ACTION_E6_AGENT_READ = "agent.read"
ACTION_E6_AGENT_MANAGE = "agent.manage"
ACTION_E7_MULTI_AGENT_READ = "multi_agent.read"
ACTION_E7_MULTI_AGENT_MANAGE = "multi_agent.manage"
ACTION_E8_ASSET_READ = "asset.read"
ACTION_E8_ASSET_CREATE = "asset.create"
ACTION_E8_ASSET_UPDATE = "asset.update_metadata"
ACTION_E8_ASSET_GENERATE = "asset.generate"
ACTION_E8_ASSET_PROCESS = "asset.process"
ACTION_E8_ASSET_REVIEW_QUALITY = "asset.review.quality"
ACTION_E8_ASSET_REVIEW_LICENSE = "asset.review.license"
ACTION_E8_ASSET_APPROVE = "asset.approve"
ACTION_E8_ASSET_IMPORT = "asset.import"
ACTION_E8_ASSET_DELIVER = "asset.deliver"
ACTION_E8_ASSET_ROLLBACK = "asset.rollback"
ACTION_E8_ASSET_ARCHIVE = "asset.archive"
ACTION_E9_VERIFICATION_READ = "verification.read"
ACTION_E9_VERIFICATION_CREATE = "verification.create"
ACTION_E9_VERIFICATION_RUN = "verification.run"
ACTION_E9_VERIFICATION_REVIEW = "verification.review"
ACTION_E9_VERIFICATION_WAIVE = "verification.waive"
ACTION_E9_DEFECT_READ = "defect.read"
ACTION_E9_DEFECT_CREATE = "defect.create"
ACTION_E9_DEFECT_MANAGE = "defect.manage"
ACTION_E9_QUALITY_GATE_READ = "quality_gate.read"
ACTION_E9_QUALITY_GATE_EVALUATE = "quality_gate.evaluate"
ACTION_E9_PHASE_REVIEW_READ = "phase_review.read"
ACTION_E9_PHASE_REVIEW_SUBMIT = "phase_review.submit"
ACTION_E9_PHASE_REVIEW_DECIDE = "phase_review.decide"

E9_PROJECT_ACTIONS = frozenset(
    {
        ACTION_E9_VERIFICATION_READ,
        ACTION_E9_VERIFICATION_CREATE,
        ACTION_E9_VERIFICATION_RUN,
        ACTION_E9_VERIFICATION_REVIEW,
        ACTION_E9_VERIFICATION_WAIVE,
        ACTION_E9_DEFECT_READ,
        ACTION_E9_DEFECT_CREATE,
        ACTION_E9_DEFECT_MANAGE,
        ACTION_E9_QUALITY_GATE_READ,
        ACTION_E9_QUALITY_GATE_EVALUATE,
        ACTION_E9_PHASE_REVIEW_READ,
        ACTION_E9_PHASE_REVIEW_SUBMIT,
        ACTION_E9_PHASE_REVIEW_DECIDE,
    }
)

E8_PROJECT_ACTIONS = frozenset(
    {
        ACTION_E8_ASSET_READ,
        ACTION_E8_ASSET_CREATE,
        ACTION_E8_ASSET_UPDATE,
        ACTION_E8_ASSET_GENERATE,
        ACTION_E8_ASSET_PROCESS,
        ACTION_E8_ASSET_REVIEW_QUALITY,
        ACTION_E8_ASSET_REVIEW_LICENSE,
        ACTION_E8_ASSET_APPROVE,
        ACTION_E8_ASSET_IMPORT,
        ACTION_E8_ASSET_DELIVER,
        ACTION_E8_ASSET_ROLLBACK,
        ACTION_E8_ASSET_ARCHIVE,
    }
)

E4_PROJECT_ACTIONS = frozenset(
    {
        ACTION_E4_PROJECT_READ,
        ACTION_E4_PROJECT_MANAGE,
        ACTION_E4_TASK_READ,
        ACTION_E4_TASK_MANAGE,
        ACTION_E4_WORKFLOW_READ,
        ACTION_E4_WORKFLOW_MANAGE,
        ACTION_E4_CHANGESET_READ,
        ACTION_E4_CHANGESET_MANAGE,
        ACTION_E4_CHANGESET_APPROVE,
        ACTION_E4_APPROVAL_READ,
        ACTION_E4_APPROVAL_DECIDE,
    }
)

E5_PROJECT_ACTIONS = frozenset(
    {
        ACTION_E5_TOOL_READ,
        ACTION_E5_TOOL_MANAGE,
        ACTION_E5_MODEL_READ,
        ACTION_E5_MODEL_MANAGE,
    }
)

E6_PROJECT_ACTIONS = frozenset(
    {
        ACTION_E6_AGENT_READ,
        ACTION_E6_AGENT_MANAGE,
    }
)

E7_PROJECT_ACTIONS = frozenset(
    {
        ACTION_E7_MULTI_AGENT_READ,
        ACTION_E7_MULTI_AGENT_MANAGE,
    }
)

ACTIONS = frozenset(
    {
        ACTION_SYSTEM_READ,
        ACTION_CLIENT_REGISTER,
        ACTION_CLIENT_READ,
        ACTION_SESSION_CREATE,
        ACTION_SESSION_READ,
        ACTION_SESSION_REVOKE,
        ACTION_PROJECT_ACCESS_READ,
        ACTION_PROJECT_ACCESS_GRANT,
        ACTION_PROJECT_ACCESS_REVOKE,
        ACTION_DIAGNOSTICS_READ,
        ACTION_BRIDGE_READ,
        ACTION_BRIDGE_WRITE,
    }
    | E4_PROJECT_ACTIONS
    | E5_PROJECT_ACTIONS
    | E6_PROJECT_ACTIONS
    | E7_PROJECT_ACTIONS
    | E8_PROJECT_ACTIONS
    | E9_PROJECT_ACTIONS
)


@dataclass(frozen=True)
class Principal:
    """已认证主体。``role`` 为 admin 时全局生效，其余角色只作用于 project_id。"""

    client_id: str
    client_type: str
    session_id: str | None = None
    role: str = ROLE_CLIENT
    project_id: str | None = None


@dataclass(frozen=True)
class Resource:
    kind: str
    project_id: str | None = None
