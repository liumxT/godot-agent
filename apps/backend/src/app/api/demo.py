"""E11 Platformer Demo API（T01 / T02 / T20）。

契约规则：

- Demo 规格、需求、功能与验收数据由 E11 Demo Application Service 管理；
- 本 API 不修改 Task / Workflow / Agent / Approval / Verification / Build 状态；
- 验收结论只记录 ACCEPTED / ACCEPTED_WITH_NOTES / REJECTED，拒绝时必须带后续修复任务；
- 所有资源访问都先解析项目，再执行项目授权。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from app.schemas.demo_game import (
    DemoAcceptanceReviewRequest,
    DemoCriterionStatusRequest,
    DemoScenarioStatusRequest,
)
from core.security.principal import (
    ACTION_E11_DEMO_ACCEPT,
    ACTION_E11_DEMO_MANAGE,
    ACTION_E11_DEMO_READ,
)
from modules.demo_game.service import DemoGameService

router = APIRouter(
    tags=["demo"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足"},
    404: {"description": "Demo 规格、需求、验收条件或场景不存在"},
    409: {"description": "状态冲突"},
    422: {"description": "请求参数校验失败"},
    429: {"description": "触发限流"},
}


def _service(request: Request) -> DemoGameService:
    return request.app.state.services.get("demo_game_service", DemoGameService)


@router.post(
    "/demo/projects/{project_id}/spec",
    summary="初始化 Platformer Demo 规格",
    description="写入需求、机制、关卡、功能、验收条件与测试场景基线；重复调用幂等。",
    responses=_ERRORS,
)
async def demo_seed_spec(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_MANAGE)
    return await _service(request).seed_platformer(project_id)


@router.get("/demo/projects/{project_id}/spec", summary="读取 Demo 规格", responses=_ERRORS)
async def demo_get_spec(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_READ)
    return await _service(request).get_spec(project_id)


@router.post(
    "/demo/projects/{project_id}/spec/freeze",
    summary="冻结 Demo 规格基线",
    responses=_ERRORS,
)
async def demo_freeze_spec(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_MANAGE)
    return await _service(request).freeze_spec(project_id)


@router.get(
    "/demo/projects/{project_id}/requirements",
    summary="列出 Demo 需求与验收条件",
    responses=_ERRORS,
)
async def demo_list_requirements(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    priority: str | None = Query(default=None, min_length=1, max_length=8),
    system: str | None = Query(default=None, min_length=1, max_length=32),
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_READ)
    return await _service(request).list_requirements(project_id, priority=priority, system=system)


@router.get("/demo/projects/{project_id}/features", summary="列出 Demo 功能清单", responses=_ERRORS)
async def demo_list_features(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_READ)
    return await _service(request).list_features(project_id)


@router.get(
    "/demo/projects/{project_id}/mechanics", summary="列出 Demo 玩法机制", responses=_ERRORS
)
async def demo_list_mechanics(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_READ)
    return await _service(request).list_mechanics(project_id)


@router.get("/demo/projects/{project_id}/levels", summary="列出 Demo 关卡设计", responses=_ERRORS)
async def demo_list_levels(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_READ)
    return await _service(request).list_levels(project_id)


@router.get(
    "/demo/projects/{project_id}/scenarios", summary="列出 Demo 测试场景", responses=_ERRORS
)
async def demo_list_scenarios(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_READ)
    return await _service(request).list_scenarios(project_id)


@router.get(
    "/demo/projects/{project_id}/acceptance",
    summary="读取 Demo 验收状态与历史",
    responses=_ERRORS,
)
async def demo_get_acceptance(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_READ)
    return await _service(request).acceptance_summary(project_id)


@router.post(
    "/demo/projects/{project_id}/acceptance/review",
    status_code=status.HTTP_201_CREATED,
    summary="提交用户验收结论",
    description="REJECTED 必须提供 follow_up_title，用于创建后续修复任务。",
    responses=_ERRORS,
)
async def demo_review_acceptance(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: DemoAcceptanceReviewRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_ACCEPT)
    return await _service(request).review(
        project_id,
        decision=payload.decision,
        reviewer=request.state.principal.client_id,
        summary=payload.summary,
        known_issues=tuple(payload.known_issues),
        remaining_risks=tuple(payload.remaining_risks),
        follow_up_title=payload.follow_up_title,
    )


@router.post(
    "/demo/projects/{project_id}/acceptance/criteria",
    summary="更新 Demo 验收条件状态",
    responses=_ERRORS,
)
async def demo_set_criterion_status(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: DemoCriterionStatusRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_MANAGE)
    return await _service(request).set_criterion_status(
        project_id, payload.requirement_key, payload.criterion_key, payload.status
    )


@router.post(
    "/demo/projects/{project_id}/acceptance/scenarios",
    summary="更新 Demo 测试场景状态",
    responses=_ERRORS,
)
async def demo_set_scenario_status(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN),
    payload: DemoScenarioStatusRequest = ...,
    request: Request = ...,
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_MANAGE)
    return await _service(request).set_scenario_status(
        project_id, payload.scenario_key, payload.status
    )


@router.get(
    "/demo/projects/{project_id}/system-report",
    summary="读取 Demo 系统级报告",
    description="聚合 Demo 覆盖度、需求追踪、验收结论以及 Verification / Build 公开摘要。",
    responses=_ERRORS,
)
async def demo_system_report(
    project_id: str = Path(pattern=PROJECT_ID_PATTERN), request: Request = ...
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E11_DEMO_READ)
    return await _service(request).system_report(project_id)
