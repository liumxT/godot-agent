"""验证发现与报告（E9-T06）。

所有静态/结构/资源校验都输出同一种可持久化报告：

- ``Finding`` 描述具体问题（文件、行号、严重级别、稳定 code）；
- ``AnalysisReport`` 汇总扫描文件数、错误/警告与附加信息；
- ``content_hash`` 用于证据追溯，相同输入必须产生相同哈希。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: str
    message: str
    file: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "file": self.file,
            "line": self.line,
        }


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    kind: str
    files_scanned: int
    findings: tuple[Finding, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity == SEVERITY_ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity == SEVERITY_WARNING)

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "files_scanned": self.files_scanned,
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [item.to_dict() for item in self.findings],
            "details": self.details,
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def failure_reason(self, limit: int = 3) -> str | None:
        messages = [f"{item.code}: {item.message}" for item in self.errors[:limit]]
        if not messages:
            return None
        return "；".join(messages)


def error(code: str, message: str, file: str, line: int | None = None) -> Finding:
    return Finding(code=code, severity=SEVERITY_ERROR, message=message, file=file, line=line)


def warning(code: str, message: str, file: str, line: int | None = None) -> Finding:
    return Finding(code=code, severity=SEVERITY_WARNING, message=message, file=file, line=line)
