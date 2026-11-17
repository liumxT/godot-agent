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
from fastapi.responses import JSONResponse

from core.logging import context_values, get_logger

_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


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
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
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
