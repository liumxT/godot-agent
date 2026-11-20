"""审计事件实体（E2-T11）。

审计记录只追加；``details`` 是脱敏后的 JSON 文本，不允许存放 Secret/Token。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

DECISION_ALLOW = "ALLOW"
DECISION_DENY = "DENY"

AUDIT_CLIENT_REGISTERED = "client.registered"
AUDIT_AUTH_SUCCEEDED = "auth.succeeded"
AUDIT_AUTH_FAILED = "auth.failed"
AUDIT_SESSION_CREATED = "session.created"
AUDIT_SESSION_REVOKED = "session.revoked"
AUDIT_ACCESS_GRANTED = "access.granted"
AUDIT_ACCESS_REVOKED = "access.revoked"
AUDIT_AUTHORIZATION_DENIED = "authorization.denied"
AUDIT_HIGH_RISK_CALL = "high_risk.call"
AUDIT_CONFIG_CHANGED = "config.changed"
AUDIT_BRIDGE_CONNECTED = "bridge.connected"
AUDIT_BRIDGE_DISCONNECTED = "bridge.disconnected"
AUDIT_BRIDGE_AUTH_FAILED = "bridge.auth_failed"
AUDIT_BRIDGE_PROJECT_BOUND = "bridge.project_bound"
AUDIT_BRIDGE_PROJECT_SWITCHED = "bridge.project_switched"
AUDIT_BRIDGE_RECOVERED = "bridge.recovered"
AUDIT_BRIDGE_RECOVERY_FAILED = "bridge.recovery_failed"
AUDIT_RUNTIME_REGISTERED = "runtime.registered"
AUDIT_RUNTIME_ENDED = "runtime.ended"
AUDIT_RUNTIME_REJECTED = "runtime.rejected"
AUDIT_LEASE_ISSUED = "lease.issued"
AUDIT_LEASE_RENEWED = "lease.renewed"
AUDIT_LEASE_EXPIRED = "lease.expired"
AUDIT_LEASE_REVOKED = "lease.revoked"
AUDIT_LEASE_REJECTED = "lease.rejected"

AUDIT_ACTIONS = frozenset(
    {
        AUDIT_CLIENT_REGISTERED,
        AUDIT_AUTH_SUCCEEDED,
        AUDIT_AUTH_FAILED,
        AUDIT_SESSION_CREATED,
        AUDIT_SESSION_REVOKED,
        AUDIT_ACCESS_GRANTED,
        AUDIT_ACCESS_REVOKED,
        AUDIT_AUTHORIZATION_DENIED,
        AUDIT_HIGH_RISK_CALL,
        AUDIT_CONFIG_CHANGED,
        AUDIT_BRIDGE_CONNECTED,
        AUDIT_BRIDGE_DISCONNECTED,
        AUDIT_BRIDGE_AUTH_FAILED,
        AUDIT_BRIDGE_PROJECT_BOUND,
        AUDIT_BRIDGE_PROJECT_SWITCHED,
        AUDIT_BRIDGE_RECOVERED,
        AUDIT_BRIDGE_RECOVERY_FAILED,
        AUDIT_RUNTIME_REGISTERED,
        AUDIT_RUNTIME_ENDED,
        AUDIT_RUNTIME_REJECTED,
        AUDIT_LEASE_ISSUED,
        AUDIT_LEASE_RENEWED,
        AUDIT_LEASE_EXPIRED,
        AUDIT_LEASE_REVOKED,
        AUDIT_LEASE_REJECTED,
    }
)


class AuditEventModel(Base):
    __tablename__ = "e2_audit_events"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_e2_audit_events_timestamp", "timestamp"),
        Index("ix_e2_audit_events_client_timestamp", "client_id", "timestamp"),
        Index("ix_e2_audit_events_action", "action"),
    )
