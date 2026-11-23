"""API 路由注册与版本前缀（E2-T02）。

所有 E2 接口挂在 ``/api/v1`` 下；``/health*`` 保留一份根路径兼容别名。
``build_api_router()`` 在装配时校验路由元数据：缺失 ``summary`` / ``tags``、
重复注册或使用非法方法都会直接导致启动失败。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fastapi import APIRouter
from fastapi.routing import APIRoute

from app.api.agents import router as agents_router
from app.api.approvals import router as approvals_router
from app.api.auth import protected_router as auth_protected_router
from app.api.auth import router as auth_router
from app.api.bridge import router as bridge_router
from app.api.changesets import router as changesets_router
from app.api.clients import router as clients_router
from app.api.diagnostics import v1_router as diagnostics_router
from app.api.health import router as health_router
from app.api.management_ui import router as management_ui_router
from app.api.models import router as models_router
from app.api.multi_agent import router as multi_agent_router
from app.api.projects import router as projects_router
from app.api.projects_v1 import router as projects_v1_router
from app.api.sessions import router as sessions_router
from app.api.system import router as system_router
from app.api.system import status_router as system_status_router
from app.api.tasks import router as tasks_router
from app.api.tools import router as tools_router
from app.api.version import API_PREFIX, API_VERSION
from app.api.workflows import router as workflows_router
from core.errors import StartupError

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

ROUTERS: tuple[tuple[str, APIRouter], ...] = (
    ("health", health_router),
    ("system", system_router),
    ("system", system_status_router),
    ("system", diagnostics_router),
    ("auth", auth_router),
    ("auth", auth_protected_router),
    ("clients", clients_router),
    ("sessions", sessions_router),
    ("projects", projects_router),
    ("projects", projects_v1_router),
    ("tasks", tasks_router),
    ("workflows", workflows_router),
    ("changesets", changesets_router),
    ("approvals", approvals_router),
    ("tools", tools_router),
    ("models", models_router),
    ("agents", agents_router),
    ("multi-agent", multi_agent_router),
    ("manage", management_ui_router),
    ("bridge", bridge_router),
)


@dataclass(frozen=True, slots=True)
class RouteSpec:
    """路由注册的规范化描述，用于校验与测试。"""

    group: str
    path: str
    name: str
    methods: frozenset[str]
    summary: str | None
    tags: tuple[str, ...]
    operation_id: str


def build_api_router() -> APIRouter:
    """汇总 ``/api/v1`` 子路由并校验元数据。"""

    router = APIRouter(prefix=API_PREFIX)
    for group, child in ROUTERS:
        router.include_router(
            child,
            generate_unique_id_function=_operation_id_factory(group),
        )
    validate_specs(route_specs())
    return router


def route_specs() -> tuple[RouteSpec, ...]:
    """展开已登记子路由；不依赖 FastAPI 的惰性 include 展开时机。"""

    specs: list[RouteSpec] = []
    for group, child in ROUTERS:
        specs.extend(_router_specs(group, child))
    return tuple(specs)


def validate_specs(specs: Sequence[RouteSpec]) -> None:
    """校验路由注册规则；不合法时抛出 ``StartupError``。"""

    problems: list[str] = []
    seen: set[tuple[str, frozenset[str]]] = set()
    names: set[str] = set()
    operations: set[str] = set()

    for spec in specs:
        key = (spec.path, spec.methods)
        if key in seen:
            problems.append(f"路由重复注册: {sorted(spec.methods)} {spec.path}")
        seen.add(key)

        if spec.name in names:
            problems.append(f"路由名重复: {spec.name}")
        names.add(spec.name)

        if spec.operation_id in operations:
            problems.append(f"operationId 重复: {spec.operation_id}")
        operations.add(spec.operation_id)

        if not spec.path.startswith(API_PREFIX):
            problems.append(f"路由未使用 {API_PREFIX} 前缀: {spec.path}")
        if not spec.methods or not spec.methods <= _ALLOWED_METHODS:
            problems.append(f"请求方法非法: {sorted(spec.methods)} {spec.path}")
        if not spec.summary:
            problems.append(f"缺少 summary: {spec.path}")
        if not spec.tags:
            problems.append(f"缺少 tags: {spec.path}")

    if problems:
        raise StartupError("API 路由注册非法", details={"errors": problems})


def _router_specs(group: str, router: APIRouter) -> list[RouteSpec]:
    generate = _operation_id_factory(group)
    specs: list[RouteSpec] = []
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        specs.append(
            RouteSpec(
                group=group,
                path=API_PREFIX + route.path,
                name=route.name,
                methods=frozenset(route.methods or ()),
                summary=route.summary,
                tags=tuple(route.tags or ()),
                operation_id=generate(route),
            )
        )
    return specs


def _operation_id_factory(group: str) -> Callable[[APIRoute], str]:
    """生成带版本与分组前缀的 operationId，避免根路径别名与 v1 重名。"""

    def _generate(route: APIRoute) -> str:
        methods = "_".join(sorted(route.methods or ())).lower()
        return f"{API_VERSION}_{group}_{route.name}_{methods}"

    return _generate
