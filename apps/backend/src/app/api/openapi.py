"""OpenAPI 安全方案（E2-T12）。

为受 Bearer 保护的路由声明 ``bearerAuth``，公开路由不声明 ``security``，
使 OpenAPI 文档与运行时的认证依赖保持一致。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/health/live",
        "/health/ready",
        "/api/v1/health",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/system/info",
        "/api/v1/auth/challenge",
        "/api/v1/auth/verify",
        "/api/v1/clients",
        "/diagnostics/summary",
    }
)

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def install_openapi_security(app: FastAPI) -> None:
    """替换 ``app.openapi``：注入 Bearer 方案并标注受保护操作。"""

    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema is not None:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        components.setdefault("securitySchemes", {})["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "description": "Access Token（gda_）或 Session Token（gds_）",
        }

        for path, item in schema.get("paths", {}).items():
            if path in PUBLIC_PATHS:
                continue
            for method, operation in item.items():
                if method in _HTTP_METHODS:
                    operation.setdefault("security", [{"bearerAuth": []}])

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
