"""资产生产统一生成契约（E8-T05 / T06 / T07 / T08）。

Asset Pipeline 不直接访问任何 AI 厂商：图像、音频与 3D 生成都通过本模块的
适配器契约进入 Model Gateway，由 Gateway 统一完成 Provider / 模型解析、
连接配置装载、能力校验与错误标准化。

约束：

- 适配器能力必须显式声明，``UNKNOWN`` 不能视为支持；
- 图像与音频适配器与具体厂商协议解耦，只暴露统一的提交 / 查询 / 取消接口；
- 生成结果返回原始字节与结构化元数据，暂存由 Asset Pipeline 负责；
- 已发送但结果未知的请求必须保留 ``UNKNOWN``，禁止静默重提交。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from core.errors import (
    AssetGenerationInvalid,
    AssetGenerationUnknown,
    ProviderConfigurationInvalid,
    ProviderNotConfigured,
)
from modules.model_gateway.models import (
    CAPABILITY_AUDIO_OUTPUT,
    CAPABILITY_IMAGE_OUTPUT,
    CAPABILITY_MODEL_3D_OUTPUT,
    CAPABILITY_SUPPORTED,
    CAPABILITY_UNKNOWN,
)
from modules.model_gateway.providers.base import ProviderCallFailure
from modules.model_gateway.providers.errors import ProviderErrorCategory

ASSET_KIND_IMAGE = "IMAGE"
ASSET_KIND_AUDIO = "AUDIO"
ASSET_KIND_MODEL_3D = "MODEL_3D"
ASSET_KINDS = frozenset({ASSET_KIND_IMAGE, ASSET_KIND_AUDIO, ASSET_KIND_MODEL_3D})

REQUIRED_CAPABILITIES: dict[str, str] = {
    ASSET_KIND_IMAGE: CAPABILITY_IMAGE_OUTPUT,
    ASSET_KIND_AUDIO: CAPABILITY_AUDIO_OUTPUT,
    ASSET_KIND_MODEL_3D: CAPABILITY_MODEL_3D_OUTPUT,
}

ASSET_JOB_SUCCEEDED = "SUCCEEDED"
ASSET_JOB_RUNNING = "RUNNING"
ASSET_JOB_FAILED = "FAILED"
ASSET_JOB_UNKNOWN = "UNKNOWN"
ASSET_JOB_STATUSES = frozenset(
    {ASSET_JOB_SUCCEEDED, ASSET_JOB_RUNNING, ASSET_JOB_FAILED, ASSET_JOB_UNKNOWN}
)

_UNRESOLVED_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.NETWORK_ERROR,
        ProviderErrorCategory.UNKNOWN_RESULT,
    }
)


def validate_asset_kind(kind: str) -> str:
    if kind not in ASSET_KINDS:
        raise AssetGenerationInvalid(
            "资产类型不支持 AI 生成", details={"kind": kind, "allowed": sorted(ASSET_KINDS)}
        )
    return kind


@dataclass(frozen=True, slots=True)
class AssetAdapterCapabilities:
    """适配器自报能力；能力未知时必须拒绝生成。"""

    kind: str
    formats: frozenset[str]
    max_output_count: int = 1
    supports_async: bool = False
    supports_cancel: bool = False
    capability_status: str = CAPABILITY_SUPPORTED

    def __post_init__(self) -> None:
        validate_asset_kind(self.kind)
        if not self.formats:
            raise ProviderConfigurationInvalid(
                "资产生成适配器必须声明支持格式", details={"kind": self.kind}
            )
        if self.max_output_count < 1:
            raise ProviderConfigurationInvalid(
                "资产生成适配器输出数量非法", details={"kind": self.kind}
            )

    def supports_format(self, value: str) -> bool:
        return value.strip().lower() in self.formats


@dataclass(frozen=True, slots=True)
class AssetGenerationRequest:
    """统一的资产生成请求；具体参数由适配器解释并校验。"""

    project_id: str
    asset_id: str
    kind: str
    prompt: str
    model_key: str
    provider_id: str
    model_id: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    output_count: int = 1
    timeout_seconds: float | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        validate_asset_kind(self.kind)
        if not self.prompt.strip():
            raise AssetGenerationInvalid("资产生成提示词不能为空")
        if not self.model_key.strip():
            raise AssetGenerationInvalid("资产生成缺少模型键")
        if not isinstance(self.output_count, int) or isinstance(self.output_count, bool):
            raise AssetGenerationInvalid("输出数量必须是整数")
        if self.output_count < 1:
            raise AssetGenerationInvalid("输出数量必须大于 0")
        if not isinstance(self.parameters, Mapping):
            raise AssetGenerationInvalid("生成参数必须是对象")

    def parameter(self, key: str, default: Any = None) -> Any:
        return self.parameters.get(key, default)

    def format(self, default: str) -> str:
        value = self.parameter("format", default)
        return str(value).strip().lower() or default


@dataclass(frozen=True, slots=True)
class AssetGenerationOutput:
    """适配器归一化后的原始产物。"""

    data: bytes
    format: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise AssetGenerationInvalid("生成产物不能为空")
        if not self.format.strip():
            raise AssetGenerationInvalid("生成产物缺少格式")
        if not isinstance(self.metadata, Mapping):
            raise AssetGenerationInvalid("生成产物元数据必须是对象")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True, slots=True)
class AssetGenerationResult:
    status: str
    provider_job_id: str | None = None
    outputs: tuple[AssetGenerationOutput, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.status not in ASSET_JOB_STATUSES:
            raise AssetGenerationInvalid("生成结果状态非法", details={"status": self.status})
        if self.status == ASSET_JOB_SUCCEEDED and not self.outputs:
            raise AssetGenerationInvalid("生成成功的任务必须包含产物")
        if self.status in (ASSET_JOB_FAILED, ASSET_JOB_UNKNOWN) and not self.error_code:
            raise AssetGenerationInvalid(
                "失败或未知的生成结果必须提供错误码", details={"status": self.status}
            )


@dataclass(frozen=True, slots=True)
class ResolvedAssetProvider:
    """Gateway 解析后的资产 Provider；业务侧不得自行构造。"""

    adapter: AssetGenerationAdapter
    kind: str
    provider_id: str
    model_id: str
    model_key: str
    required_capability: str
    timeout_seconds: float


class AssetGenerationAdapter(Protocol):
    """图像 / 音频 / 3D 适配器的稳定接口。"""

    def get_capabilities(self) -> AssetAdapterCapabilities: ...

    def validate_configuration(self) -> None: ...

    def validate_request(self, request: AssetGenerationRequest) -> None: ...

    def estimate_cost(self, request: AssetGenerationRequest) -> Decimal | None: ...

    async def submit_generation(self, request: AssetGenerationRequest) -> AssetGenerationResult: ...

    async def query_generation(
        self, request: AssetGenerationRequest, provider_job_id: str
    ) -> AssetGenerationResult: ...

    async def cancel_generation(
        self, request: AssetGenerationRequest, provider_job_id: str
    ) -> AssetGenerationResult: ...


class BaseAssetGenerationAdapter:
    """通用实现：配置校验、能力校验与结果归一化辅助。"""

    kind: str = ""
    provider_types: frozenset[str] = frozenset()
    formats: frozenset[str] = frozenset()
    max_output_count: int = 1
    supports_async: bool = False
    supports_cancel: bool = False
    capability_status: str = CAPABILITY_SUPPORTED
    requires_api_key: bool = True
    allowed_schemes: frozenset[str] = frozenset({"https"})
    default_format: str = ""

    def __init__(
        self,
        *,
        endpoint: str,
        api_version: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int = 60,
        transport=None,
    ) -> None:
        if not self.kind:
            raise ProviderConfigurationInvalid("资产生成适配器缺少 kind 声明")
        self._endpoint = endpoint.strip()
        self._api_version = api_version
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    def get_capabilities(self) -> AssetAdapterCapabilities:
        return AssetAdapterCapabilities(
            kind=self.kind,
            formats=self.formats,
            max_output_count=self.max_output_count,
            supports_async=self.supports_async,
            supports_cancel=self.supports_cancel,
            capability_status=self.capability_status,
        )

    def validate_configuration(self) -> None:
        if not self._endpoint:
            raise ProviderConfigurationInvalid(
                "资产生成 Provider endpoint 不能为空", details={"kind": self.kind}
            )
        scheme = self._endpoint.split("://", 1)[0].lower() if "://" in self._endpoint else ""
        if scheme not in self.allowed_schemes:
            raise ProviderConfigurationInvalid(
                "资产生成 Provider endpoint 非法",
                details={"kind": self.kind, "allowed_schemes": sorted(self.allowed_schemes)},
            )
        if self._timeout_seconds < 1:
            raise ProviderConfigurationInvalid(
                "资产生成 timeout 必须大于等于 1 秒", details={"kind": self.kind}
            )
        if self.requires_api_key and not self._api_key:
            raise ProviderNotConfigured(
                "资产生成 Provider 缺少 API Key", details={"kind": self.kind}
            )

    def validate_request(self, request: AssetGenerationRequest) -> None:
        capabilities = self.get_capabilities()
        if capabilities.kind != request.kind:
            raise AssetGenerationInvalid(
                "适配器与资产类型不匹配",
                details={"adapter_kind": capabilities.kind, "request_kind": request.kind},
            )
        if capabilities.capability_status != CAPABILITY_SUPPORTED:
            raise AssetGenerationInvalid(
                "资产生成能力未验证，不能作为可用 Provider",
                details={
                    "kind": capabilities.kind,
                    "capability_status": capabilities.capability_status,
                },
            )
        if request.output_count > capabilities.max_output_count:
            raise AssetGenerationInvalid(
                "输出数量超过适配器能力",
                details={
                    "requested": request.output_count,
                    "max_output_count": capabilities.max_output_count,
                },
            )
        value = request.parameter("format", self.default_format)
        if value is not None:
            candidate = str(value).strip().lower()
            if candidate and not capabilities.supports_format(candidate):
                raise AssetGenerationInvalid(
                    "适配器不支持该输出格式",
                    details={"format": candidate, "supported": sorted(capabilities.formats)},
                )

    def estimate_cost(self, request: AssetGenerationRequest) -> Decimal | None:
        return None

    async def submit_generation(self, request: AssetGenerationRequest) -> AssetGenerationResult:
        raise NotImplementedError("资产生成适配器未实现提交")

    async def query_generation(
        self, request: AssetGenerationRequest, provider_job_id: str
    ) -> AssetGenerationResult:
        raise AssetGenerationInvalid("该资产生成适配器不支持异步查询", details={"kind": self.kind})

    async def cancel_generation(
        self, request: AssetGenerationRequest, provider_job_id: str
    ) -> AssetGenerationResult:
        raise AssetGenerationInvalid("该资产生成适配器不支持取消", details={"kind": self.kind})

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers

    def _client(self):
        import httpx

        return httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
        )

    def _failure_from_exception(self, error: Exception) -> ProviderCallFailure:
        import httpx

        if isinstance(error, httpx.ConnectError):
            category, sent = ProviderErrorCategory.NETWORK_ERROR, False
        elif isinstance(error, httpx.ConnectTimeout):
            category, sent = ProviderErrorCategory.TIMEOUT, False
        elif isinstance(error, httpx.TimeoutException):
            category, sent = ProviderErrorCategory.TIMEOUT, True
        elif isinstance(error, httpx.HTTPError):
            category, sent = ProviderErrorCategory.NETWORK_ERROR, True
        else:
            category, sent = ProviderErrorCategory.UNKNOWN_RESULT, True
        return ProviderCallFailure(
            _error_info(category, str(error) or type(error).__name__), sent=sent
        )

    def _failure_from_response(self, response) -> ProviderCallFailure:
        category = _category_for_status(response.status_code)
        message: str | None = None
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, Mapping):
            error = data.get("error")
            if isinstance(error, Mapping) and isinstance(error.get("message"), str):
                message = error["message"]
            elif isinstance(error, str):
                message = error
        return ProviderCallFailure(
            _error_info(
                category,
                message or f"Provider 返回 HTTP {response.status_code}",
                http_status=response.status_code,
            ),
            sent=True,
        )


def _error_info(
    category: ProviderErrorCategory,
    message: str,
    *,
    http_status: int | None = None,
):
    from modules.model_gateway.providers.errors import ProviderErrorInfo

    return ProviderErrorInfo(
        category=category,
        message=message,
        retryable=category.value
        in {"RATE_LIMIT", "PROVIDER_UNAVAILABLE", "NETWORK_ERROR", "TIMEOUT"},
        http_status=http_status,
    )


def _category_for_status(status_code: int) -> ProviderErrorCategory:
    if status_code in (401, 403):
        return ProviderErrorCategory.AUTH_ERROR
    if status_code == 429:
        return ProviderErrorCategory.RATE_LIMIT
    if status_code >= 500:
        return ProviderErrorCategory.PROVIDER_UNAVAILABLE
    return ProviderErrorCategory.INVALID_REQUEST


def is_unresolved_failure(failure: ProviderCallFailure) -> bool:
    """请求可能已被 Provider 接收但结果未知。"""

    return failure.sent and failure.info.category in _UNRESOLVED_CATEGORIES


def unknown_from_failure(failure: ProviderCallFailure, *, kind: str) -> AssetGenerationUnknown:
    return AssetGenerationUnknown(
        "资产生成结果未知，禁止直接重试",
        details={
            "kind": kind,
            "category": failure.info.category.value,
            "message": failure.info.message,
        },
    )


def assert_unverified_capability(status: str | None, *, kind: str) -> None:
    if status == CAPABILITY_SUPPORTED:
        return
    raise AssetGenerationInvalid(
        "Provider 能力未经确认，不能视为满足生成要求",
        details={
            "kind": kind,
            "capability_status": status or CAPABILITY_UNKNOWN,
        },
    )


class AssetAdapterRegistry:
    """按资产类型与 provider_type 创建适配器。"""

    def __init__(self) -> None:
        self._factories: dict[tuple[str, str], Any] = {}

    def register(self, kind: str, provider_type: str, factory) -> None:
        validate_asset_kind(kind)
        if not provider_type.strip():
            raise ProviderConfigurationInvalid("资产生成 provider_type 不能为空")
        key = (kind, provider_type)
        if key in self._factories:
            raise ProviderConfigurationInvalid(
                "资产生成适配器重复注册",
                details={"kind": kind, "provider_type": provider_type},
            )
        self._factories[key] = factory

    def supports(self, kind: str, provider_type: str) -> bool:
        return (kind, provider_type) in self._factories

    def types(self, kind: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                provider_type
                for current_kind, provider_type in self._factories
                if current_kind == kind
            )
        )

    def create(
        self,
        kind: str,
        provider_type: str,
        *,
        endpoint: str,
        api_version: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
        transport=None,
    ) -> AssetGenerationAdapter:
        factory = self._factories.get((kind, provider_type))
        if factory is None:
            raise ProviderConfigurationInvalid(
                "未注册该类资产的生成适配器",
                details={"kind": kind, "provider_type": provider_type},
            )
        kwargs: dict[str, Any] = {
            "endpoint": endpoint,
            "api_version": api_version,
            "api_key": api_key,
        }
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        if transport is not None:
            kwargs["transport"] = transport
        return factory(**kwargs)
