"""统一错误定义与 HTTP 错误输出。

所有对外错误使用同一结构：

    {"error": {"code": "...", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """应用异常基类。子类通过类属性声明错误码与 HTTP 状态。"""

    code: str = "internal_error"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class ConfigError(AppError):
    """配置缺失或非法。启动阶段必须显式失败。"""

    code = "config_error"
    status_code = 500


class StartupError(AppError):
    """启动装配失败。"""

    code = "startup_error"
    status_code = 500


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理，避免不同接口返回不同错误结构。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        from core.logging import get_logger

        get_logger("backend.error").exception(
            "unhandled_exception",
            extra={"route": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content=error_payload("internal_error", "服务器内部错误"),
        )
