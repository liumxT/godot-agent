"""API 路由、版本与错误输出测试（E2-T01-IT / E2-T02）。"""

from __future__ import annotations

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.router import API_PREFIX, RouteSpec, build_api_router, route_specs, validate_specs
from app.api.version import API_VERSION
from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import StartupError
from shared.contracts import protocol_version, validate_instance

DB_URL = "sqlite+aiosqlite:///:memory:"
SYSTEM_SCHEMA = "api/system.schema.json"
ERROR_SCHEMA = "errors/error.schema.json"


@pytest.fixture()
def app():
    settings = load_settings(_env_file=None, database_url=DB_URL, environment="test")
    return create_app(settings)


@pytest.fixture()
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _spec(
    path: str, name: str, *, summary: str | None = "摘要", tags: tuple[str, ...] = ("test",)
) -> RouteSpec:
    return RouteSpec(
        group="test",
        path=path,
        name=name,
        methods=frozenset({"GET"}),
        summary=summary,
        tags=tags,
        operation_id=f"v1_test_{name}_get",
    )


async def test_system_info_serves_normal_request(client) -> None:
    response = await client.get("/api/v1/system/info")

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == API_VERSION
    assert body["protocol_version"] == protocol_version()
    assert body["environment"] == "test"
    assert validate_instance(body, SYSTEM_SCHEMA) == []
    assert response.headers["X-Request-ID"].startswith("req-")


async def test_system_status_requires_authentication(client) -> None:
    response = await client.get("/api/v1/system/status")

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "AUTH_REQUIRED"
    assert validate_instance(error, ERROR_SCHEMA) == []


async def test_unknown_route_uses_unified_error(client) -> None:
    response = await client.get("/api/v1/not-exists")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["correlation_id"] == response.headers["X-Request-ID"]
    assert validate_instance(error, ERROR_SCHEMA) == []


async def test_wrong_method_uses_unified_error(client) -> None:
    response = await client.post("/api/v1/system/info")

    assert response.status_code == 405
    error = response.json()["error"]
    assert error["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in response.headers["allow"]
    assert validate_instance(error, ERROR_SCHEMA) == []


async def test_invalid_parameters_use_unified_error(app) -> None:
    @app.get("/_test/validation", summary="测试参数校验", tags=["test"])
    async def _validate(limit: int) -> dict[str, int]:
        return {"limit": limit}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/_test/validation")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert error["details"]["errors"][0]["loc"] == ["query", "limit"]
    assert validate_instance(error, ERROR_SCHEMA) == []


def test_route_registration_covers_expected_paths() -> None:
    build_api_router()
    registered = {(spec.path, tuple(sorted(spec.methods))) for spec in route_specs()}

    assert ("/api/v1/system/info", ("GET",)) in registered
    assert ("/api/v1/system/status", ("GET",)) in registered
    assert ("/api/v1/health", ("GET",)) in registered
    assert ("/api/v1/health/live", ("GET",)) in registered
    assert ("/api/v1/health/ready", ("GET",)) in registered


def test_route_names_and_operation_ids_are_unique() -> None:
    specs = route_specs()

    assert len({spec.name for spec in specs}) == len(specs)
    assert len({spec.operation_id for spec in specs}) == len(specs)


def test_all_v1_routes_use_version_prefix() -> None:
    specs = route_specs()

    assert specs
    assert all(spec.path.startswith(API_PREFIX) for spec in specs)


def test_route_metadata_is_present() -> None:
    for spec in route_specs():
        assert spec.summary, spec.path
        assert spec.tags, spec.path


_PUBLIC_V1_PATHS = {
    "/api/v1/health",
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/api/v1/system/info",
    "/api/v1/auth/challenge",
    "/api/v1/auth/verify",
    "/api/v1/clients",
    # 管理界面只返回不含数据的静态外壳，凭证由用户在页面内输入。
    "/api/v1/manage",
}


def _has_authentication_dependency(route: APIRoute) -> bool:
    return any(
        getattr(dependency.call, "__name__", "") == "require_authenticated"
        for dependency in route.dependant.dependencies
    )


def _iter_routes(routes, prefix: str = "") -> list[tuple[str, APIRoute]]:
    found: list[tuple[str, APIRoute]] = []
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            found.extend(_iter_routes(original.routes, prefix + getattr(original, "prefix", "")))
        elif isinstance(route, APIRoute):
            found.append((prefix + route.path, route))
    return found


def test_protected_v1_routes_mount_authentication(app) -> None:
    protected = [
        (path, route)
        for path, route in _iter_routes(app.routes)
        if path.startswith(API_PREFIX) and path not in _PUBLIC_V1_PATHS
    ]

    assert protected
    for path, route in protected:
        assert _has_authentication_dependency(route), f"缺少认证依赖: {path}"


def test_api_version_is_independent_from_protocol_version() -> None:
    assert API_VERSION == "v1"
    assert protocol_version() == "1.0"
    assert API_VERSION != protocol_version()


def test_validate_specs_rejects_missing_metadata() -> None:
    with pytest.raises(StartupError) as exc_info:
        validate_specs([_spec("/api/v1/broken", "broken", summary=None, tags=())])

    errors = exc_info.value.details["errors"]
    assert any("summary" in item for item in errors)
    assert any("tags" in item for item in errors)


def test_validate_specs_rejects_duplicates() -> None:
    spec = _spec("/api/v1/dup", "dup")

    with pytest.raises(StartupError) as exc_info:
        validate_specs([spec, spec])

    errors = exc_info.value.details["errors"]
    assert any("重复" in item for item in errors)
    assert any("operationId" in item for item in errors)


def test_health_alias_and_v1_share_semantics(tmp_path) -> None:
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'routing.db').as_posix()}",
        environment="test",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        root = client.get("/health")
        versioned = client.get("/api/v1/health")

        assert root.status_code == 200
        assert versioned.status_code == 200
        assert versioned.json()["status"] == root.json()["status"]
        assert client.get("/api/v1/health/live").json() == {"status": "alive"}


async def test_api_responses_match_contract(client) -> None:
    response = await client.get("/api/v1/system/info")
    assert response.status_code == 200
    assert validate_instance(response.json(), SYSTEM_SCHEMA) == []


def test_openapi_document_is_complete(app) -> None:
    document = app.openapi()
    paths = document["paths"]

    for path in (
        "/api/v1/system/info",
        "/api/v1/system/status",
        "/api/v1/diagnostics/summary",
        "/api/v1/health",
    ):
        assert path in paths

    operation_ids = [
        operation["operationId"]
        for item in paths.values()
        for operation in item.values()
        if "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))

    for path, item in paths.items():
        if not path.startswith(API_PREFIX):
            continue
        for operation in item.values():
            assert operation.get("summary"), path
            assert operation.get("tags"), path
            assert operation.get("responses"), path


def test_openapi_declares_bearer_security(app) -> None:
    document = app.openapi()
    schemes = document["components"]["securitySchemes"]

    assert schemes["bearerAuth"]["scheme"] == "bearer"
    assert document["paths"]["/api/v1/system/status"]["get"]["security"] == [{"bearerAuth": []}]
    assert document["paths"]["/api/v1/diagnostics/summary"]["get"]["security"] == [
        {"bearerAuth": []}
    ]
    assert "security" not in document["paths"]["/api/v1/system/info"]["get"]
    assert "security" not in document["paths"]["/api/v1/health"]["get"]
