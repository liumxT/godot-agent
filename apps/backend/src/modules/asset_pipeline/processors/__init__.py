"""资产处理处理器注册表（E8-T09）。

只注册本阶段真正实现且经过测试的处理器；未注册的处理器 ID 在流水线提交阶段
直接拒绝，避免出现“声明支持但实际不可用”的假能力。
"""

from __future__ import annotations

from modules.asset_pipeline.processing_types import ProcessingProcessorRegistry
from modules.asset_pipeline.processors.audio import audio_processors
from modules.asset_pipeline.processors.image import image_processors
from modules.asset_pipeline.processors.model3d import model3d_processors


def default_processing_registry() -> ProcessingProcessorRegistry:
    registry = ProcessingProcessorRegistry()
    for processor in (*image_processors(), *audio_processors(), *model3d_processors()):
        registry.register(processor)
    return registry


__all__ = ["default_processing_registry"]
