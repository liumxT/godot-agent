"""资产生成适配器默认注册。"""

from __future__ import annotations

from modules.model_gateway.asset_adapters.audio import OpenAIAudioAdapter
from modules.model_gateway.asset_adapters.image import OpenAIImageAdapter
from modules.model_gateway.asset_adapters.model3d import LocalModel3DAdapter
from modules.model_gateway.asset_generation import AssetAdapterRegistry

__all__ = ["default_asset_adapter_registry"]


def default_asset_adapter_registry() -> AssetAdapterRegistry:
    """注册内置适配器；未注册的 Provider 类型视为不支持。"""

    registry = AssetAdapterRegistry()
    for provider_type in OpenAIImageAdapter.provider_types:
        registry.register("IMAGE", provider_type, OpenAIImageAdapter)
    for provider_type in OpenAIAudioAdapter.provider_types:
        registry.register("AUDIO", provider_type, OpenAIAudioAdapter)
    for provider_type in LocalModel3DAdapter.provider_types:
        registry.register("MODEL_3D", provider_type, LocalModel3DAdapter)
    return registry
