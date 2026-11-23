"""Model 接口（E5-T30）：模型目录、Provider 配置与用量/费用汇总。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.api.deps import authorize_project_action, enforce_rate_limit, require_authenticated
from app.schemas.access import PROJECT_ID_PATTERN
from core.security.principal import ACTION_E5_MODEL_MANAGE, ACTION_E5_MODEL_READ
from core.security.tokens import isoformat
from modules.model_gateway.configuration import (
    ProviderConfigurationService,
    ProviderConfigurationView,
)
from modules.model_gateway.gateway import ModelGatewayService
from modules.model_gateway.registry import ModelRegistryService, ModelView, ProviderView

router = APIRouter(
    tags=["models"],
    dependencies=[Depends(require_authenticated), Depends(enforce_rate_limit)],
)

_ERRORS = {
    401: {"description": "认证失败"},
    403: {"description": "无项目访问或权限不足（PROJECT_ACCESS_DENIED / PERMISSION_DENIED）"},
    404: {"description": "模型或 Provider 不存在（NOT_FOUND）"},
    422: {"description": "请求参数校验失败（VALIDATION_FAILED）"},
    429: {"description": "触发限流（RATE_LIMITED）"},
}


class ProviderCreateRequest(BaseModel):
    project_id: str = Field(..., pattern=PROJECT_ID_PATTERN)
    name: str = Field(..., min_length=1, max_length=128)
    provider_type: str = Field(..., min_length=1, max_length=32)
    endpoint: str = Field(..., min_length=1, max_length=512)
    api_version: str | None = Field(default=None, max_length=64)
    credential_ref: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=512)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    enabled: bool = True


def _registry(request: Request) -> ModelRegistryService:
    return request.app.state.services.get("model_registry_service", ModelRegistryService)


def _configuration(request: Request) -> ProviderConfigurationService:
    return request.app.state.services.get(
        "provider_configuration_service", ProviderConfigurationService
    )


def _gateway(request: Request) -> ModelGatewayService:
    return request.app.state.services.get("model_gateway_service", ModelGatewayService)


def _format_capability(capability) -> dict[str, Any]:
    return {
        "capability": capability.capability,
        "support_status": capability.support_status,
        "max_input": capability.max_input,
        "max_output": capability.max_output,
        "evidence_source": capability.evidence_source,
        "api_version": capability.api_version,
        "verified_at": isoformat(capability.verified_at) if capability.verified_at else None,
    }


def _format_model(model: ModelView) -> dict[str, Any]:
    price = model.price
    return {
        "model_id": model.model_id,
        "provider_id": model.provider_id,
        "model_key": model.model_key,
        "display_name": model.display_name,
        "context_window": model.context_window,
        "max_output_tokens": model.max_output_tokens,
        "status": model.status,
        "source": model.source,
        "last_verified_at": isoformat(model.last_verified_at) if model.last_verified_at else None,
        "price": (
            {
                "input_price": str(price.input_price),
                "output_price": str(price.output_price),
                "currency": price.currency,
                "effective_at": isoformat(price.effective_at),
            }
            if price is not None
            else None
        ),
        "capabilities": [_format_capability(item) for item in model.capabilities],
    }


def _format_provider(provider: ProviderView) -> dict[str, Any]:
    return {
        "provider_id": provider.provider_id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "status": provider.status,
        "configuration_ref": provider.configuration_ref,
        "created_at": isoformat(provider.created_at),
        "updated_at": isoformat(provider.updated_at),
    }


def _format_configuration(
    configuration: ProviderConfigurationView | None,
) -> dict[str, Any] | None:
    if configuration is None:
        return None
    return {
        "configuration_id": configuration.configuration_id,
        "provider_id": configuration.provider_id,
        "endpoint": configuration.endpoint,
        "api_version": configuration.api_version,
        "credential_ref": configuration.credential_ref,
        "timeout_seconds": configuration.timeout_seconds,
        "enabled": configuration.enabled,
        "configuration_version": configuration.configuration_version,
        "updated_by": configuration.updated_by,
        "updated_at": isoformat(configuration.updated_at),
    }


@router.get(
    "/models",
    summary="列出模型",
    description="列出已登记模型及其能力与价格，可按 Provider 过滤。",
    responses=_ERRORS,
)
async def list_models(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
    provider_id: str | None = Query(default=None),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_MODEL_READ)
    models = await _registry(request).list_models(provider_id=provider_id)
    return {"items": [_format_model(model) for model in models]}


@router.get(
    "/models/{model_id}",
    summary="查询模型",
    description="返回模型元数据、当前价格与能力状态。",
    responses=_ERRORS,
)
async def get_model(
    model_id: str,
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_MODEL_READ)
    return _format_model(await _registry(request).get_model(model_id))


@router.get(
    "/models/{model_id}/capabilities",
    summary="查询模型能力",
    description="返回模型各项能力状态；UNKNOWN 不视为支持。",
    responses=_ERRORS,
)
async def get_model_capabilities(
    model_id: str,
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_MODEL_READ)
    model = await _registry(request).get_model(model_id)
    return {
        "model_id": model.model_id,
        "capabilities": [_format_capability(item) for item in model.capabilities],
    }


@router.get(
    "/providers",
    summary="列出 Provider",
    description="列出 Provider 与其最新连接配置。",
    responses=_ERRORS,
)
async def list_providers(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_MODEL_READ)
    providers = await _registry(request).list_providers()
    items: list[dict[str, Any]] = []
    for provider in providers:
        configuration = await _configuration(request).get(provider.provider_id)
        entry = _format_provider(provider)
        entry["configuration"] = _format_configuration(configuration)
        items.append(entry)
    return {"items": items}


@router.post(
    "/providers",
    summary="注册 Provider",
    description="登记 Provider 并保存连接配置；API Key 走 Secrets，不落库明文。",
    responses=_ERRORS,
)
async def create_provider(payload: ProviderCreateRequest, request: Request) -> dict:
    await authorize_project_action(request, payload.project_id, ACTION_E5_MODEL_MANAGE)
    provider = await _registry(request).register_provider(
        name=payload.name, provider_type=payload.provider_type
    )
    configuration = await _configuration(request).save(
        provider.provider_id,
        endpoint=payload.endpoint,
        api_version=payload.api_version,
        credential_ref=payload.credential_ref,
        api_key=payload.api_key,
        timeout_seconds=payload.timeout_seconds,
        enabled=payload.enabled,
        actor_id=request.state.principal.client_id,
    )
    entry = _format_provider(provider)
    entry["configuration"] = _format_configuration(configuration)
    return entry


@router.post(
    "/providers/{provider_id}/test",
    summary="测试 Provider 连接",
    description="校验当前配置是否可用，不发起生成请求。",
    responses=_ERRORS,
)
async def test_provider(
    provider_id: str,
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_MODEL_MANAGE)
    health = await _configuration(request).test_connection(provider_id)
    return {
        "provider_id": provider_id,
        "provider_type": health.provider_type,
        "status": health.status,
        "detail": health.detail,
    }


@router.get(
    "/model-usage",
    summary="查询模型用量",
    description="按项目汇总 Token 使用量，并给出按模型的明细。",
    responses=_ERRORS,
)
async def get_model_usage(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_MODEL_READ)
    summary = await _gateway(request).usage_summary(project_id)
    return {
        "project_id": project_id,
        "input_tokens": summary.input_tokens,
        "output_tokens": summary.output_tokens,
        "total_tokens": summary.total_tokens,
        "by_model": [
            {
                "model_id": item.model_id,
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "total_tokens": item.total_tokens,
            }
            for item in summary.by_model
        ],
    }


@router.get(
    "/model-cost",
    summary="查询模型费用",
    description="按项目汇总模型调用费用，并返回涉及的币种。",
    responses=_ERRORS,
)
async def get_model_cost(
    request: Request,
    project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
) -> dict:
    await authorize_project_action(request, project_id, ACTION_E5_MODEL_READ)
    summary = await _gateway(request).cost_summary(project_id)
    return {
        "project_id": project_id,
        "input_cost": str(summary.input_cost),
        "output_cost": str(summary.output_cost),
        "total_cost": str(summary.total_cost),
        "currencies": list(summary.currencies),
    }
