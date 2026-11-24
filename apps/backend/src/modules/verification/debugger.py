"""Debugger 错误归一化与错误门禁（E9-T10）。

设计原则：

- 日志文本只用于分类与去重，不能单独据此判定缺陷责任；
- 结构化错误必须保留来源、场景、节点、脚本、堆栈与运行环境引用；
- 同一 ``fingerprint`` 聚合为一条记录，历史记录标记为 baseline；
- 新增 Fatal / Error 未解决时阻止通过，历史问题必须显式记录而非静默忽略。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from modules.verification.models import (
    DEBUGGER_ERROR_CATEGORIES,
    DEBUGGER_SEVERITIES,
    ERROR_CATEGORY_ENGINE_CRASH,
    ERROR_CATEGORY_INFO,
    ERROR_CATEGORY_INVALID_ACCESS,
    ERROR_CATEGORY_INVALID_CALL,
    ERROR_CATEGORY_NODE_NOT_FOUND,
    ERROR_CATEGORY_NULL_REFERENCE,
    ERROR_CATEGORY_PARSER,
    ERROR_CATEGORY_PHYSICS,
    ERROR_CATEGORY_RESOURCE_LOAD,
    ERROR_CATEGORY_RUNTIME,
    ERROR_CATEGORY_SCRIPT,
    ERROR_CATEGORY_SIGNAL,
    ERROR_CATEGORY_WARNING,
    ERROR_STATUS_IGNORED,
    ERROR_STATUS_OPEN,
    ERROR_STATUS_RESOLVED,
    SEVERITY_ERROR,
    SEVERITY_FATAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)

_ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]+")
_NUMBER_PATTERN = re.compile(r"\b\d+\b")
_WHITESPACE_PATTERN = re.compile(r"\s+")

_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ERROR_CATEGORY_ENGINE_CRASH, ("crash", "segmentation fault", "access violation")),
    (ERROR_CATEGORY_PARSER, ("parse error", "parser error")),
    (ERROR_CATEGORY_INVALID_CALL, ("invalid call",)),
    (ERROR_CATEGORY_INVALID_ACCESS, ("invalid access", "invalid index", "out of bounds")),
    (ERROR_CATEGORY_NULL_REFERENCE, ("null instance", "nil instance", "null reference")),
    (ERROR_CATEGORY_RESOURCE_LOAD, ("failed to load", "can't open file", "cannot open")),
    (ERROR_CATEGORY_NODE_NOT_FOUND, ("node not found", "nodepath")),
    (ERROR_CATEGORY_SIGNAL, ("signal",)),
    (ERROR_CATEGORY_PHYSICS, ("physics", "collision shape")),
    (ERROR_CATEGORY_SCRIPT, ("script error", "script")),
)

_FATAL_CATEGORIES = frozenset({ERROR_CATEGORY_ENGINE_CRASH, ERROR_CATEGORY_PARSER})
_WARNING_CATEGORIES = frozenset({ERROR_CATEGORY_WARNING})


@dataclass(frozen=True, slots=True)
class DebuggerErrorInput:
    """来自 Debugger / Runtime 的一条结构化错误。"""

    category: str
    severity: str
    message: str
    source: str = ""
    scene: str | None = None
    node: str | None = None
    script: str | None = None
    stack_trace: str | None = None
    runtime_instance_id: str | None = None
    godot_version: str | None = None
    project_revision: str | None = None
    changeset_id: str | None = None

    def __post_init__(self) -> None:
        if self.category not in DEBUGGER_ERROR_CATEGORIES:
            raise ValueError(f"未知 Debugger 错误分类: {self.category}")
        if self.severity not in DEBUGGER_SEVERITIES:
            raise ValueError(f"未知 Debugger 严重级别: {self.severity}")
        if not self.message.strip():
            raise ValueError("Debugger 错误必须包含消息")


@dataclass(frozen=True, slots=True)
class DebuggerErrorSnapshot:
    """门禁评估所需的最小错误快照。"""

    severity: str
    category: str
    is_baseline: bool
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class DebuggerGatePolicy:
    """错误门禁策略。

    ``require_approval_for_new_error`` 为真时不直接阻止，而是要求人工批准；
    批准本身属于 Approval System，Verification 只表达门禁结论。
    """

    block_new_fatal: bool = True
    block_new_error: bool = True
    require_approval_for_new_error: bool = False
    block_new_warning: bool = False
    warn_on_new_warning: bool = True

    def __post_init__(self) -> None:
        if self.require_approval_for_new_error and self.block_new_error:
            raise ValueError("新增 Error 不能同时被阻止和要求人工批准")


@dataclass(frozen=True, slots=True)
class DebuggerGateDecision:
    allowed: bool
    blocking: bool
    requires_approval: bool
    reasons: tuple[str, ...]
    new_fatal: int
    new_error: int
    new_warning: int
    baseline_open: int
    counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "blocking": self.blocking,
            "requires_approval": self.requires_approval,
            "reasons": list(self.reasons),
            "new_fatal": self.new_fatal,
            "new_error": self.new_error,
            "new_warning": self.new_warning,
            "baseline_open": self.baseline_open,
            "counts": self.counts,
        }


def classify(message: str) -> str:
    """根据错误文本给出保守分类；未知文本归为 RUNTIME_ERROR。"""

    text = message.strip().lower()
    if text.startswith(("warning", "w:")) or "warning:" in text:
        return ERROR_CATEGORY_WARNING
    if text.startswith(("info", "i:")) or "info:" in text:
        return ERROR_CATEGORY_INFO
    for category, markers in _CATEGORY_RULES:
        if any(marker in text for marker in markers):
            return category
    return ERROR_CATEGORY_RUNTIME


def severity_for(category: str, fallback: str = SEVERITY_ERROR) -> str:
    if category in _FATAL_CATEGORIES:
        return SEVERITY_FATAL
    if category in _WARNING_CATEGORIES:
        return SEVERITY_WARNING
    return fallback


def normalize_message(message: str) -> str:
    """去掉地址与数量波动，用于稳定去重。"""

    text = _ADDRESS_PATTERN.sub("#", message.strip().lower())
    text = _NUMBER_PATTERN.sub("#", text)
    return _WHITESPACE_PATTERN.sub(" ", text)


def fingerprint_error(error: DebuggerErrorInput) -> str:
    payload = "|".join(
        (
            error.category,
            normalize_message(error.message),
            error.script or "",
            error.node or "",
            error.scene or "",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_snapshot(
    *,
    severity: str,
    category: str,
    is_baseline: bool,
    status: str,
    message: str,
) -> DebuggerErrorSnapshot:
    return DebuggerErrorSnapshot(
        severity=severity,
        category=category,
        is_baseline=is_baseline,
        status=status,
        message=message,
    )


def evaluate_gate(
    errors: Sequence[DebuggerErrorSnapshot],
    policy: DebuggerGatePolicy | None = None,
) -> DebuggerGateDecision:
    """评估错误门禁；只有未解决错误参与阻断判断。"""

    active = [item for item in errors if item.status == ERROR_STATUS_OPEN]
    resolved = [item for item in errors if item.status == ERROR_STATUS_RESOLVED]
    ignored = [item for item in errors if item.status == ERROR_STATUS_IGNORED]

    new_fatal = [
        item for item in active if not item.is_baseline and item.severity == SEVERITY_FATAL
    ]
    new_error = [
        item for item in active if not item.is_baseline and item.severity == SEVERITY_ERROR
    ]
    new_warning = [
        item for item in active if not item.is_baseline and item.severity == SEVERITY_WARNING
    ]
    baseline_open = [
        item
        for item in active
        if item.is_baseline and item.severity in {SEVERITY_FATAL, SEVERITY_ERROR}
    ]

    policy = policy or DebuggerGatePolicy()
    reasons: list[str] = []
    blocking = False
    requires_approval = False

    if new_fatal and policy.block_new_fatal:
        blocking = True
        reasons.append(f"存在 {len(new_fatal)} 条未解决的新增 Fatal 错误")
    if new_error:
        if policy.block_new_error:
            blocking = True
            reasons.append(f"存在 {len(new_error)} 条未解决的新增 Error")
        elif policy.require_approval_for_new_error:
            requires_approval = True
            reasons.append(f"存在 {len(new_error)} 条未解决的新增 Error，需要人工批准")
    if new_warning and policy.block_new_warning:
        blocking = True
        reasons.append(f"存在 {len(new_warning)} 条未解决的新增 Warning")
    elif new_warning and policy.warn_on_new_warning:
        reasons.append(f"记录 {len(new_warning)} 条新增 Warning")
    if baseline_open:
        reasons.append(f"{len(baseline_open)} 条历史 Fatal/Error 仍未解决，已记录基线")

    counts = {
        "total": len(errors),
        "open": len(active),
        "resolved": len(resolved),
        "ignored": len(ignored),
        SEVERITY_FATAL: sum(1 for item in active if item.severity == SEVERITY_FATAL),
        SEVERITY_ERROR: sum(1 for item in active if item.severity == SEVERITY_ERROR),
        SEVERITY_WARNING: sum(1 for item in active if item.severity == SEVERITY_WARNING),
        SEVERITY_INFO: sum(1 for item in active if item.severity == SEVERITY_INFO),
    }
    return DebuggerGateDecision(
        allowed=not blocking,
        blocking=blocking,
        requires_approval=requires_approval,
        reasons=tuple(reasons),
        new_fatal=len(new_fatal),
        new_error=len(new_error),
        new_warning=len(new_warning),
        baseline_open=len(baseline_open),
        counts=counts,
    )
