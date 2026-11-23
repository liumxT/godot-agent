"""3D 资产处理处理器（E8-T09）。

本阶段只提供可验证的检查型处理器：

- ``model3d.mesh_inspection``：解析 GLB / glTF / OBJ 并输出几何报告；
- ``model3d.material_inspection``：输出材质与贴图报告。

格式转换、贴图提取、几何优化与贴图压缩不在本阶段实现，处理器不注册即表示
不支持；流水线会在提交阶段明确报错，绝不伪造处理能力。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.errors import AssetGenerationInvalid, AssetProcessingInvalid
from modules.asset_pipeline.processing_types import (
    ProcessingArtifact,
    ProcessingContext,
    ProcessingPayload,
)
from modules.model_gateway.asset_adapters.model3d import (
    inspect_geometry,
    inspect_materials,
)

PROCESSOR_VERSION = "1.0"


def _single(payload: ProcessingPayload) -> ProcessingArtifact:
    if len(payload.artifacts) != 1:
        raise AssetProcessingInvalid(
            "该处理器要求单一 3D 输入", details={"artifacts": len(payload.artifacts)}
        )
    return payload.artifacts[0]


def _replace(artifact: ProcessingArtifact, key: str, report: Mapping[str, Any]):
    metadata = dict(artifact.metadata)
    metadata[key] = dict(report)
    return ProcessingArtifact(
        data=artifact.data,
        format=artifact.format,
        filename_hint=artifact.filename_hint,
        metadata=metadata,
    )


class MeshInspectionProcessor:
    processor_id = "model3d.mesh_inspection"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        if not isinstance(parameters, Mapping):
            raise AssetProcessingInvalid("处理参数必须是对象")

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        try:
            report = inspect_geometry(artifact.data, artifact.format)
        except AssetGenerationInvalid as error:
            raise AssetProcessingInvalid(
                "3D 几何无法解析", details={"format": artifact.format}
            ) from error
        context.check_deadline()
        return ProcessingPayload((_replace(artifact, "geometry", report.to_mapping()),))


class MaterialInspectionProcessor:
    processor_id = "model3d.material_inspection"
    version = PROCESSOR_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        if not isinstance(parameters, Mapping):
            raise AssetProcessingInvalid("处理参数必须是对象")

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload:
        self.validate(parameters)
        artifact = _single(payload)
        try:
            report = inspect_materials(artifact.data, artifact.format)
        except AssetGenerationInvalid as error:
            raise AssetProcessingInvalid(
                "3D 材质无法解析", details={"format": artifact.format}
            ) from error
        context.check_deadline()
        return ProcessingPayload((_replace(artifact, "materials", report.to_mapping()),))


def model3d_processors() -> tuple[Any, ...]:
    """默认 3D 处理器集合（仅检查型能力）。"""

    return (
        MeshInspectionProcessor(),
        MaterialInspectionProcessor(),
    )
