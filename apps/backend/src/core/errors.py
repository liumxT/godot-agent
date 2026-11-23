"""统一错误定义与 HTTP 错误输出（E0-T08）。

对外错误统一结构（见 packages/contracts/errors/error.schema.json）：

    {"error": {"code": "...", "message": "...", "details": {...},
               "retryable": false, "correlation_id": "..."}}

错误码必须是大写蛇形（``^[A-Z][A-Z0-9_]{2,63}$``），且优先使用
``packages/contracts/errors/error-codes.json`` 中登记的错误码。
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.logging import context_values, get_logger

_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")

# HTTP 层错误码映射：保证 404/405/422 等框架错误与业务错误输出同一结构。
_HTTP_ERROR_CODES: dict[int, str] = {
    400: "INVALID_REQUEST",
    401: "UNAUTHORIZED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_FAILED",
    503: "DEPENDENCY_UNAVAILABLE",
    504: "TIMEOUT",
}


class AppError(Exception):
    """应用异常基类。子类通过类属性声明错误码、HTTP 状态与可重试性。"""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers
        if code is not None:
            if not _CODE_PATTERN.match(code):
                raise ValueError(f"错误码必须为大写蛇形: {code}")
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable


class ConfigError(AppError):
    """配置缺失或非法。启动阶段必须显式失败。"""

    code = "CONFIG_ERROR"
    status_code = 500


class StartupError(AppError):
    """启动装配失败。"""

    code = "STARTUP_ERROR"
    status_code = 500


class LifecycleStateError(AppError):
    """生命周期状态非法或状态迁移不被允许。"""

    code = "LIFECYCLE_STATE_ERROR"
    status_code = 500


class ValidationFailed(AppError):
    """输入未通过校验。"""

    code = "INVALID_REQUEST"
    status_code = 400


class AuthenticationError(AppError):
    """缺少或无效的认证凭证。"""

    code = "UNAUTHORIZED"
    status_code = 401


class AuthRequired(AppError):
    """缺少 Bearer 或 Bootstrap Token。"""

    code = "AUTH_REQUIRED"
    status_code = 401


class AuthInvalid(AppError):
    """客户端或凭证无效。"""

    code = "AUTH_INVALID"
    status_code = 401


class AuthChallengeInvalid(AppError):
    """挑战过期、重复使用或 proof 错误。"""

    code = "AUTH_CHALLENGE_INVALID"
    status_code = 401


class TokenInvalid(AppError):
    """Access Token 无法识别。"""

    code = "TOKEN_INVALID"
    status_code = 401


class TokenExpired(AppError):
    """Access Token 已过期。"""

    code = "TOKEN_EXPIRED"
    status_code = 401


class TokenRevoked(AppError):
    """Access Token 已被撤销或轮换。"""

    code = "TOKEN_REVOKED"
    status_code = 401


class ClientExists(AppError):
    """客户端 ID 已存在。"""

    code = "CLIENT_EXISTS"
    status_code = 409


class SessionInvalid(AppError):
    """Session 无法识别或状态非法。"""

    code = "SESSION_INVALID"
    status_code = 401


class SessionExpired(AppError):
    """Session 已过期。"""

    code = "SESSION_EXPIRED"
    status_code = 401


class SessionRevoked(AppError):
    """Session 已被撤销。"""

    code = "SESSION_REVOKED"
    status_code = 401


class SessionSuspended(AppError):
    """E3：Editor 绑定处于 RECOVERING，受保护操作暂停。"""

    code = "SESSION_SUSPENDED"
    status_code = 409
    retryable = True


class LeaseExpired(AppError):
    """E3：租约不存在或已过期。"""

    code = "LEASE_EXPIRED"
    status_code = 409
    retryable = True


class LeaseRevoked(AppError):
    """E3：租约被撤销。"""

    code = "LEASE_REVOKED"
    status_code = 409


class FencingTokenStale(AppError):
    """E3：携带的 Fencing Token 不是项目最新值。"""

    code = "FENCING_TOKEN_STALE"
    status_code = 409


class SnapshotUnavailable(AppError):
    """E3：没有可用于恢复的有效快照，需要重新采集。"""

    code = "SNAPSHOT_UNAVAILABLE"
    status_code = 404
    retryable = True


class RuntimeUnavailable(AppError):
    """E3：Runtime 身份不可用或未登记项目。"""

    code = "RUNTIME_UNAVAILABLE"
    status_code = 503
    retryable = True


class EventSequenceGap(AppError):
    """E3：事件 sequence 出现不可补齐的断档。"""

    code = "EVENT_SEQUENCE_GAP"
    status_code = 409
    retryable = True


class ProjectAccessDenied(AppError):
    """当前 Session 没有该项目的有效访问。"""

    code = "PROJECT_ACCESS_DENIED"
    status_code = 403


class InvalidStateTransition(AppError):
    """E4：业务对象状态机不允许该迁移。"""

    code = "INVALID_STATE_TRANSITION"
    status_code = 409


class VersionConflict(AppError):
    """E4：乐观锁版本冲突，需要重新读取后重试。"""

    code = "VERSION_CONFLICT"
    status_code = 409
    retryable = True


class DependencyCycle(AppError):
    """E4：任务依赖存在循环。"""

    code = "DEPENDENCY_CYCLE"
    status_code = 409


class ApprovalExpired(AppError):
    """E4：审批已过期，不能继续使用。"""

    code = "APPROVAL_EXPIRED"
    status_code = 409


class ApprovalHashMismatch(AppError):
    """E4：审批绑定的目标哈希与当前内容不一致，必须重新审批。"""

    code = "APPROVAL_HASH_MISMATCH"
    status_code = 409


class ProviderConfigurationInvalid(AppError):
    """E5：Provider 连接配置不完整或非法。"""

    code = "PROVIDER_CONFIGURATION_INVALID"
    status_code = 422


class ProviderNotConfigured(AppError):
    """E5：Provider 缺少可用配置或凭证。"""

    code = "PROVIDER_NOT_CONFIGURED"
    status_code = 409


class ModelUnavailable(AppError):
    """E5：用户指定的模型不可用，必须显式返回原因与替代项。"""

    code = "MODEL_UNAVAILABLE"
    status_code = 409


class ModelCapabilityUnsupported(AppError):
    """E5：模型未验证具备所需能力。"""

    code = "MODEL_CAPABILITY_UNSUPPORTED"
    status_code = 409


class ModelAlreadyRegistered(AppError):
    """E5：同一 Provider 下的模型键已登记。"""

    code = "MODEL_ALREADY_REGISTERED"
    status_code = 409


class ModelCallFailed(AppError):
    """E5：Provider 调用失败；``details`` 中给出分类与请求 ID。"""

    code = "MODEL_CALL_FAILED"
    status_code = 502


class ModelRequestUnknown(AppError):
    """E5：请求已发送但结果未知，不能按失败直接重试。"""

    code = "MODEL_REQUEST_UNKNOWN"
    status_code = 409


class PromptVariableInvalid(AppError):
    """E5：Prompt 变量缺少、类型不符或占位符未声明。"""

    code = "PROMPT_VARIABLE_INVALID"
    status_code = 400


class ContextSourceMissing(AppError):
    """E5：Context 装配所需来源不存在，或固定 Context 引用缺失。"""

    code = "CONTEXT_SOURCE_MISSING"
    status_code = 409


class ToolAlreadyRegistered(AppError):
    """E5：同一工具名称的版本已存在。"""

    code = "TOOL_ALREADY_REGISTERED"
    status_code = 409


class ToolSchemaInvalid(AppError):
    """E5：工具输入或输出 Schema 不是合法 JSON Schema。"""

    code = "TOOL_SCHEMA_INVALID"
    status_code = 400


class ToolInputInvalid(AppError):
    """E5：工具输入未通过 Schema 校验。"""

    code = "TOOL_INPUT_INVALID"
    status_code = 400


class ToolOutputInvalid(AppError):
    """E5：工具输出未通过 Schema 校验。"""

    code = "TOOL_OUTPUT_INVALID"
    status_code = 502


class ToolAdapterMissing(AppError):
    """E5：没有可执行该工具的 Adapter。"""

    code = "TOOL_ADAPTER_MISSING"
    status_code = 502


class ResourceLockConflict(AppError):
    """E5：目标资源已被其他持有者锁定，或锁类型不兼容。"""

    code = "RESOURCE_LOCK_CONFLICT"
    status_code = 409


class ResourceLockExpired(AppError):
    """E5：资源锁已过期或已释放，必须重新获取。"""

    code = "RESOURCE_LOCK_EXPIRED"
    status_code = 409


class EditorNotConnected(AppError):
    """E5：目标 Editor Session 没有活动的桥接连接。"""

    code = "EDITOR_NOT_CONNECTED"
    status_code = 409
    retryable = True


class EditorCommandTimeout(AppError):
    """E5：编辑器命令已发送但未在期限内返回结果。"""

    code = "EDITOR_COMMAND_TIMEOUT"
    status_code = 504


class RequestTooLarge(AppError):
    """请求体超过大小限制。"""

    code = "REQUEST_TOO_LARGE"
    status_code = 413


class RequestTimeout(AppError):
    """请求处理超过时限。"""

    code = "REQUEST_TIMEOUT"
    status_code = 504
    retryable = True


class RateLimited(AppError):
    """触发限流，应退避后重试。"""

    code = "RATE_LIMITED"
    status_code = 429
    retryable = True


class AuditFailed(AppError):
    """审计写入失败，敏感操作按 fail-closed 拒绝。"""

    code = "AUDIT_FAILED"
    status_code = 503
    retryable = True


class PermissionDenied(AppError):
    """已认证但无权执行该操作。"""

    code = "PERMISSION_DENIED"
    status_code = 403


class NotFoundError(AppError):
    """目标资源不存在。"""

    code = "NOT_FOUND"
    status_code = 404


class OperationTimeout(AppError):
    """操作超时，可按策略重试。"""

    code = "TIMEOUT"
    status_code = 504
    retryable = True


class ShutdownTimeout(OperationTimeout):
    """关闭超时；仅在本地生命周期流程中使用。"""

    code = "SHUTDOWN_TIMEOUT"


class DatabaseError(AppError):
    """数据库不可用或数据完整性错误。"""

    code = "DATABASE_UNAVAILABLE"
    status_code = 503
    retryable = True


class InfrastructureError(AppError):
    """基础设施层失败（文件、事件、凭证库等）。"""

    code = "INFRASTRUCTURE_ERROR"
    status_code = 500


class MigrationError(AppError):
    """数据库迁移失败。"""

    code = "MIGRATION_FAILED"
    status_code = 500


class BackupError(AppError):
    """备份或恢复失败。"""

    code = "BACKUP_FAILED"
    status_code = 500


def iter_error_types() -> list[type[AppError]]:
    """返回 AppError 及其全部子类，用于错误码登记检查。"""

    found: list[type[AppError]] = [AppError]
    pending = list(AppError.__subclasses__())
    while pending:
        current = pending.pop()
        found.append(current)
        pending.extend(current.__subclasses__())
    return found


def validate_error_registry() -> None:
    """启动时校验异常类声明，避免非法错误码进入运行期。"""

    problems: list[str] = []
    for error_type in iter_error_types():
        code = error_type.code
        if not _CODE_PATTERN.match(code):
            problems.append(f"{error_type.__name__}: {code}")
    if problems:
        raise StartupError(
            "错误码登记非法",
            details={"errors": problems, "pattern": _CODE_PATTERN.pattern},
        )


def error_payload(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    *,
    retryable: bool = False,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    resolved_id = correlation_id or context_values().get("correlation_id") or uuid4().hex
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "retryable": retryable,
            "correlation_id": resolved_id,
        }
    }


def install_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理，避免不同接口返回不同错误结构。"""

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status_code = exc.status_code
        code = _HTTP_ERROR_CODES.get(status_code, "INVALID_REQUEST")
        get_logger("backend.error").log(
            logging.WARNING if status_code < 500 else logging.ERROR,
            "http_error",
            extra={
                "component": "errors",
                "event": "http_error",
                "route": request.url.path,
                "error_code": code,
            },
        )
        return JSONResponse(
            status_code=status_code,
            content=error_payload(
                code,
                str(exc.detail),
                correlation_id=getattr(request.state, "correlation_id", None),
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "type": error.get("type", ""),
                "msg": error.get("msg", ""),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "VALIDATION_FAILED",
                "请求参数校验失败",
                {"errors": errors},
                correlation_id=getattr(request.state, "correlation_id", None),
            ),
        )

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        get_logger("backend.error").log(
            level,
            "app_error",
            extra={
                "component": "errors",
                "event": "app_error",
                "route": request.url.path,
                "error_code": exc.code,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                exc.code,
                exc.message,
                exc.details,
                retryable=exc.retryable,
                correlation_id=getattr(request.state, "correlation_id", None),
            ),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        get_logger("backend.error").exception(
            "unhandled_exception",
            extra={
                "component": "errors",
                "event": "unhandled_exception",
                "route": request.url.path,
                "error_code": "INTERNAL_ERROR",
            },
        )
        return JSONResponse(
            status_code=500,
            content=error_payload(
                "INTERNAL_ERROR",
                "服务器内部错误",
                correlation_id=getattr(request.state, "correlation_id", None),
            ),
        )
