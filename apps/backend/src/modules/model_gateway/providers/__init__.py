"""模型 Provider 适配层（E5-T02 / T03）。

外部 Provider 只通过本层接入；业务模块不得直接依赖厂商 SDK 或响应结构。
"""

from modules.model_gateway.providers.registry import AdapterRegistry, default_adapter_registry

__all__ = ["AdapterRegistry", "default_adapter_registry"]
