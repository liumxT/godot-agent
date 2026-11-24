"""3D 资产适配器基础（E8-T08）。

本阶段只建立 3D 生成接口、能力声明与结构化检查能力，不承诺商业级 3D 生成：

- 统一提交 / 查询接口；
- GLB / glTF / OBJ 结构解析：几何体、材质、UV、骨骼、动画；
- 空几何体、无法解析的产物直接拒绝；
- 是否支持 FBX 等格式必须由适配器能力显式声明，未知即不支持。
"""

from __future__ import annotations

import base64
import binascii
import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.errors import AssetGenerationInvalid
from modules.model_gateway.asset_generation import (
    ASSET_JOB_SUCCEEDED,
    ASSET_KIND_MODEL_3D,
    AssetGenerationOutput,
    AssetGenerationRequest,
    AssetGenerationResult,
    BaseAssetGenerationAdapter,
)
from modules.model_gateway.models import PROVIDER_TYPE_LOCAL
from modules.model_gateway.providers.base import ProviderCallFailure
from modules.model_gateway.providers.errors import (
    ProviderErrorCategory,
    ProviderErrorInfo,
)

_3D_FORMATS = frozenset({"glb", "gltf", "obj"})
_TRIANGLES = 4


@dataclass(frozen=True, slots=True)
class GeometryReport:
    format: str
    mesh_count: int
    triangle_count: int
    material_count: int
    texture_count: int
    has_uv: bool
    skin_count: int
    animation_count: int
    empty: bool

    def to_mapping(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "mesh_count": self.mesh_count,
            "triangle_count": self.triangle_count,
            "material_count": self.material_count,
            "texture_count": self.texture_count,
            "has_uv": self.has_uv,
            "skin_count": self.skin_count,
            "animation_count": self.animation_count,
            "empty": self.empty,
        }


@dataclass(frozen=True, slots=True)
class MaterialReport:
    material_count: int
    named_materials: tuple[str, ...]
    has_textures: bool

    def to_mapping(self) -> dict[str, Any]:
        return {
            "material_count": self.material_count,
            "named_materials": list(self.named_materials),
            "has_textures": self.has_textures,
        }


class LocalModel3DAdapter(BaseAssetGenerationAdapter):
    """本地 3D 生成服务协议（POST ``/3d/generations``）。"""

    kind = ASSET_KIND_MODEL_3D
    provider_types = frozenset({PROVIDER_TYPE_LOCAL})
    formats = _3D_FORMATS
    max_output_count = 1
    supports_async = False
    supports_cancel = False
    requires_api_key = False
    allowed_schemes = frozenset({"http", "https"})
    default_format = "glb"

    def validate_request(self, request: AssetGenerationRequest) -> None:
        super().validate_request(request)
        budget = request.parameter("polygon_budget")
        if budget is not None:
            try:
                parsed = int(budget)
            except (TypeError, ValueError) as error:
                raise _invalid("polygon_budget", "必须是正整数") from error
            if parsed <= 0:
                raise _invalid("polygon_budget", "必须是正整数")

    async def submit_generation(self, request: AssetGenerationRequest) -> AssetGenerationResult:
        self.validate_configuration()
        output_format = request.format(self.default_format)
        payload = {
            "model": request.model_key,
            "prompt": request.prompt,
            "format": output_format,
            "polygon_budget": request.parameter("polygon_budget"),
        }
        try:
            async with self._client() as client:
                response = await client.post(
                    self.endpoint.rstrip("/") + "/3d/generations",
                    headers=self._headers(),
                    json=payload,
                )
                if response.status_code >= 400:
                    raise self._failure_from_response(response)
                data, job_id = _extract_payload(response, output_format)
        except ProviderCallFailure:
            raise
        except Exception as error:
            raise self._failure_from_exception(error) from error
        try:
            geometry = inspect_geometry(data, output_format)
            materials = inspect_materials(data, output_format)
        except AssetGenerationInvalid as error:
            raise ProviderCallFailure(
                ProviderErrorInfo(
                    category=ProviderErrorCategory.CONTENT_REJECTED,
                    message=error.message,
                    retryable=False,
                ),
                sent=True,
            ) from error
        if geometry.empty:
            raise ProviderCallFailure(
                ProviderErrorInfo(
                    category=ProviderErrorCategory.CONTENT_REJECTED,
                    message="3D 产物几何体为空",
                    retryable=False,
                ),
                sent=True,
            )
        budget = request.parameter("polygon_budget")
        if budget is not None and geometry.triangle_count > int(budget):
            raise ProviderCallFailure(
                ProviderErrorInfo(
                    category=ProviderErrorCategory.CONTENT_REJECTED,
                    message="3D 产物三角形数量超过预算",
                    retryable=False,
                ),
                sent=True,
            )
        output = AssetGenerationOutput(
            data=data,
            format=output_format,
            metadata={
                "geometry": geometry.to_mapping(),
                "materials": materials.to_mapping(),
            },
        )
        return AssetGenerationResult(
            status=ASSET_JOB_SUCCEEDED,
            provider_job_id=job_id,
            outputs=(output,),
        )


def _extract_payload(response, output_format: str) -> tuple[bytes, str]:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise _invalid("response", "3D Provider 响应必须是对象")
        job_id = payload.get("provider_job_id")
        encoded = payload.get("data_base64")
        if not isinstance(encoded, str) or not encoded:
            raise _invalid("response", "3D Provider 缺少 data_base64")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise _invalid("response", "3D Base64 解码失败") from error
        return data, str(job_id) if job_id else "model3d_sync"
    return response.content, response.headers.get("x-request-id") or "model3d_sync"


def inspect_geometry(data: bytes, output_format: str) -> GeometryReport:
    fmt = output_format.strip().lower()
    if fmt == "glb":
        document = _parse_glb(data)
        return _gltf_geometry(document, "glb")
    if fmt == "gltf":
        return _gltf_geometry(_load_json(data), "gltf")
    if fmt == "obj":
        return _obj_geometry(data)
    raise AssetGenerationInvalid("不支持的 3D 格式", details={"format": fmt})


def inspect_materials(data: bytes, output_format: str) -> MaterialReport:
    fmt = output_format.strip().lower()
    if fmt == "glb":
        document = _parse_glb(data)
        return _gltf_materials(document)
    if fmt == "gltf":
        return _gltf_materials(_load_json(data))
    if fmt == "obj":
        names: list[str] = []
        for line in data.decode("utf-8", errors="replace").splitlines():
            if line.startswith("usemtl "):
                name = line[7:].strip()
                if name and name not in names:
                    names.append(name)
        return MaterialReport(len(names), tuple(names), False)
    raise AssetGenerationInvalid("不支持的 3D 格式", details={"format": fmt})


def _load_json(data: bytes) -> Mapping[str, Any]:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssetGenerationInvalid("glTF 文档无法解析") from error
    if not isinstance(document, Mapping):
        raise AssetGenerationInvalid("glTF 文档必须是对象")
    return document


def _parse_glb(data: bytes) -> Mapping[str, Any]:
    if len(data) < 20 or not data.startswith(b"glTF"):
        raise AssetGenerationInvalid("GLB 魔数或长度非法")
    version, declared_length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise AssetGenerationInvalid("仅支持 glTF 2.0", details={"version": version})
    if declared_length > len(data):
        raise AssetGenerationInvalid("GLB 声明长度超出文件大小")
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:
        raise AssetGenerationInvalid("GLB 首个 chunk 必须是 JSON")
    end = 20 + chunk_length
    if end > len(data):
        raise AssetGenerationInvalid("GLB JSON chunk 截断")
    return _load_json(data[20:end].rstrip(b"\x00 "))


def _gltf_geometry(document: Mapping[str, Any], fmt: str) -> GeometryReport:
    meshes = _list(document.get("meshes"))
    accessors = _list(document.get("accessors"))
    triangles = 0
    has_uv = False
    for mesh in meshes:
        for primitive in _list(mesh.get("primitives")) if isinstance(mesh, Mapping) else []:
            if not isinstance(primitive, Mapping):
                continue
            attributes = primitive.get("attributes")
            if isinstance(attributes, Mapping) and "TEXCOORD_0" in attributes:
                has_uv = True
            mode = primitive.get("mode", _TRIANGLES)
            if mode != _TRIANGLES:
                continue
            count = _accessor_count(primitive.get("indices"), accessors)
            if count is None and isinstance(attributes, Mapping):
                count = _accessor_count(attributes.get("POSITION"), accessors)
            if count:
                triangles += count // 3
    return GeometryReport(
        format=fmt,
        mesh_count=len(meshes),
        triangle_count=triangles,
        material_count=len(_list(document.get("materials"))),
        texture_count=len(_list(document.get("textures"))),
        has_uv=has_uv,
        skin_count=len(_list(document.get("skins"))),
        animation_count=len(_list(document.get("animations"))),
        empty=not meshes or triangles <= 0,
    )


def _gltf_materials(document: Mapping[str, Any]) -> MaterialReport:
    materials = _list(document.get("materials"))
    names: list[str] = []
    for material in materials:
        if isinstance(material, Mapping):
            name = material.get("name")
            if isinstance(name, str) and name and name not in names:
                names.append(name)
    return MaterialReport(
        material_count=len(materials),
        named_materials=tuple(names),
        has_textures=bool(_list(document.get("textures"))),
    )


def _obj_geometry(data: bytes) -> GeometryReport:
    vertices = 0
    triangles = 0
    uv_count = 0
    material_names: list[str] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("v "):
            vertices += 1
        elif stripped.startswith("f "):
            triangles += max(len(stripped.split()) - 3, 1)
        elif stripped.startswith("vt "):
            uv_count += 1
        elif stripped.startswith("usemtl "):
            name = stripped[7:].strip()
            if name and name not in material_names:
                material_names.append(name)
    return GeometryReport(
        format="obj",
        mesh_count=1 if vertices else 0,
        triangle_count=triangles,
        material_count=len(material_names),
        texture_count=0,
        has_uv=uv_count > 0,
        skin_count=0,
        animation_count=0,
        empty=vertices == 0 or triangles == 0,
    )


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _accessor_count(reference: Any, accessors: list[Any]) -> int | None:
    if not isinstance(reference, int) or not 0 <= reference < len(accessors):
        return None
    accessor = accessors[reference]
    if not isinstance(accessor, Mapping):
        return None
    count = accessor.get("count")
    return count if isinstance(count, int) and count > 0 else None


def _invalid(name: str, reason: str):
    return AssetGenerationInvalid("3D 生成参数非法", details={"parameter": name, "reason": reason})
