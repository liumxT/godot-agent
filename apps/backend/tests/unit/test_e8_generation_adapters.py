"""E8-M3 资产生成适配器单元测试。"""

from __future__ import annotations

import base64
import io
import json
import struct
import wave

import httpx
import pytest

from core.errors import AssetGenerationInvalid, ProviderConfigurationInvalid
from modules.model_gateway.asset_adapters import default_asset_adapter_registry
from modules.model_gateway.asset_adapters.audio import (
    AssetGenerationInvalidAudio,
    OpenAIAudioAdapter,
    inspect_audio,
)
from modules.model_gateway.asset_adapters.image import OpenAIImageAdapter
from modules.model_gateway.asset_adapters.model3d import (
    LocalModel3DAdapter,
    inspect_geometry,
    inspect_materials,
)
from modules.model_gateway.asset_generation import (
    ASSET_JOB_SUCCEEDED,
    ASSET_KIND_AUDIO,
    ASSET_KIND_IMAGE,
    ASSET_KIND_MODEL_3D,
    AssetAdapterCapabilities,
    AssetGenerationRequest,
)
from modules.model_gateway.models import (
    CAPABILITY_UNKNOWN,
    PROVIDER_TYPE_LOCAL,
    PROVIDER_TYPE_OPENAI,
)
from modules.model_gateway.providers.base import ProviderCallFailure


def _request(kind: str, **parameters) -> AssetGenerationRequest:
    return AssetGenerationRequest(
        project_id="proj_1",
        asset_id="ast_1",
        kind=kind,
        prompt="pixel art hero",
        model_key="image-model",
        provider_id="openai",
        model_id="model_1",
        parameters=parameters,
    )


def _image_adapter(handler=None) -> OpenAIImageAdapter:
    return OpenAIImageAdapter(
        endpoint="https://api.openai.com/v1",
        api_key="secret",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler) if handler else None,
    )


def test_default_registry_declares_only_known_adapters() -> None:
    registry = default_asset_adapter_registry()

    assert PROVIDER_TYPE_OPENAI in registry.types(ASSET_KIND_IMAGE)
    assert PROVIDER_TYPE_OPENAI in registry.types(ASSET_KIND_AUDIO)
    assert PROVIDER_TYPE_LOCAL in registry.types(ASSET_KIND_MODEL_3D)
    assert registry.supports(ASSET_KIND_MODEL_3D, PROVIDER_TYPE_LOCAL) is True

    with pytest.raises(ProviderConfigurationInvalid):
        registry.create(
            ASSET_KIND_IMAGE,
            PROVIDER_TYPE_LOCAL,
            endpoint="http://127.0.0.1",
        )
    with pytest.raises(ProviderConfigurationInvalid):
        registry.register(ASSET_KIND_IMAGE, PROVIDER_TYPE_OPENAI, OpenAIImageAdapter)


def test_image_adapter_validates_size_format_and_transparency() -> None:
    adapter = _image_adapter()
    adapter.validate_request(_request(ASSET_KIND_IMAGE, width=512, height=512, format="png"))

    with pytest.raises(AssetGenerationInvalid):
        adapter.validate_request(_request(ASSET_KIND_IMAGE, width=333, height=512))
    with pytest.raises(AssetGenerationInvalid):
        adapter.validate_request(_request(ASSET_KIND_IMAGE, format="gif"))
    with pytest.raises(AssetGenerationInvalid):
        adapter.validate_request(
            _request(ASSET_KIND_IMAGE, format="jpeg", transparent_background=True)
        )


def test_unknown_capability_is_not_treated_as_supported() -> None:
    class UnverifiedImageAdapter(OpenAIImageAdapter):
        capability_status = CAPABILITY_UNKNOWN

    adapter = UnverifiedImageAdapter(
        endpoint="https://api.openai.com/v1", api_key="secret", timeout_seconds=5
    )
    with pytest.raises(AssetGenerationInvalid):
        adapter.validate_request(_request(ASSET_KIND_IMAGE))


@pytest.mark.asyncio
async def test_image_adapter_decodes_base64_results() -> None:
    payload = base64.b64encode(b"png-bytes").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/generations")
        body = json.loads(request.content)
        assert body["response_format"] == "b64_json"
        assert body["size"] == "512x512"
        return httpx.Response(200, json={"id": "img_job_1", "data": [{"b64_json": payload}]})

    result = await _image_adapter(handler).submit_generation(
        _request(ASSET_KIND_IMAGE, width=512, height=512, format="png")
    )

    assert result.status == ASSET_JOB_SUCCEEDED
    assert result.provider_job_id == "img_job_1"
    assert result.outputs[0].data == b"png-bytes"
    assert result.outputs[0].format == "png"


@pytest.mark.asyncio
async def test_image_adapter_maps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(ProviderCallFailure):
        await _image_adapter(handler).submit_generation(_request(ASSET_KIND_IMAGE))


def _wav_bytes(samples: list[int], *, sample_rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buffer.getvalue()


def test_audio_inspector_extracts_technical_metrics() -> None:
    data = _wav_bytes([0, 1000, -1000, 32767] * 100)
    report = inspect_audio(data, "wav")

    assert report["container"] == "wav"
    assert report["sample_rate"] == 8000
    assert report["channels"] == 1
    assert report["clipping"] is True
    assert report["duration_seconds"] > 0


def test_audio_inspector_rejects_corrupted_data() -> None:
    with pytest.raises(AssetGenerationInvalidAudio):
        inspect_audio(b"not-a-wave", "wav")
    with pytest.raises(AssetGenerationInvalidAudio):
        inspect_audio(b"not-an-ogg", "ogg")


def test_audio_adapter_validates_voice_and_speed() -> None:
    adapter = OpenAIAudioAdapter(
        endpoint="https://api.openai.com/v1", api_key="secret", timeout_seconds=5
    )
    adapter.validate_request(_request(ASSET_KIND_AUDIO, format="wav", voice="alloy", speed=1.0))
    with pytest.raises(AssetGenerationInvalid):
        adapter.validate_request(_request(ASSET_KIND_AUDIO, format="wav", speed=0.1))
    with pytest.raises(AssetGenerationInvalid):
        adapter.validate_request(_request(ASSET_KIND_AUDIO, format="wav", voice=""))


def _glb_bytes(document: dict) -> bytes:
    raw = json.dumps(document).encode("utf-8")
    raw += b" " * ((4 - len(raw) % 4) % 4)
    total = 12 + 8 + len(raw)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(raw), 0x4E4F534A)
        + raw
    )


def test_model3d_inspector_reads_glb_geometry_and_materials() -> None:
    document = {
        "asset": {"version": "2.0"},
        "meshes": [
            {
                "name": "hero",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                        "indices": 2,
                        "mode": 4,
                    }
                ],
            }
        ],
        "accessors": [{"count": 3}, {"count": 3}, {"count": 6}],
        "materials": [{"name": "skin"}],
        "textures": [{}],
        "skins": [{}],
        "animations": [{}],
    }
    data = _glb_bytes(document)

    geometry = inspect_geometry(data, "glb")
    materials = inspect_materials(data, "glb")

    assert geometry.format == "glb"
    assert geometry.mesh_count == 1
    assert geometry.triangle_count == 2
    assert geometry.has_uv is True
    assert geometry.skin_count == 1
    assert geometry.animation_count == 1
    assert geometry.empty is False
    assert materials.material_count == 1
    assert materials.named_materials == ("skin",)
    assert materials.has_textures is True


def test_model3d_inspector_reads_obj_and_detects_empty_geometry() -> None:
    obj = (
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nusemtl stone\nf 1 2 3\nf 1 3 4"
    )
    geometry = inspect_geometry(obj.encode(), "obj")
    materials = inspect_materials(obj.encode(), "obj")

    assert geometry.triangle_count == 2
    assert geometry.has_uv is True
    assert geometry.empty is False
    assert materials.named_materials == ("stone",)

    empty = inspect_geometry(b"v 0 0 0\n", "obj")
    assert empty.empty is True


def test_model3d_adapter_estimates_no_cost_and_validates_budget() -> None:
    adapter = LocalModel3DAdapter(endpoint="http://127.0.0.1:9000", timeout_seconds=5)
    adapter.validate_configuration()
    adapter.validate_request(_request(ASSET_KIND_MODEL_3D, format="glb", polygon_budget=5000))
    assert adapter.estimate_cost(_request(ASSET_KIND_MODEL_3D)) is None
    with pytest.raises(AssetGenerationInvalid):
        adapter.validate_request(_request(ASSET_KIND_MODEL_3D, polygon_budget=0))


def test_capabilities_require_formats() -> None:
    with pytest.raises(ProviderConfigurationInvalid):
        AssetAdapterCapabilities(kind=ASSET_KIND_IMAGE, formats=frozenset())
