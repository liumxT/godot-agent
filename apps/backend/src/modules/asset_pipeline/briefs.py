"""Asset Brief 与技术规格（E8-T04）。

Brief 把游戏需求转化为结构化、可验证的资产规格。规格由 Agent 或用户提出，
用户可以确认或修改；已批准 Brief 的规格变更必须创建新的 Brief 版本。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import AssetBriefInvalid, NotFoundError, VersionConflict
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    ASSET_CATEGORIES,
    BRIEF_APPROVED,
    BRIEF_DRAFT,
    BRIEF_PROPOSED,
    BRIEF_SUPERSEDED,
    BRIEF_TRANSITIONS,
    AssetBriefModel,
)
from modules.asset_pipeline.repository import AssetBriefRepository

GODOT_RESOURCE_TYPES = frozenset(
    {
        "Sprite2D",
        "AnimatedSprite2D",
        "Texture2D",
        "AtlasTexture",
        "TileSet",
        "TileMapLayer",
        "AudioStream",
        "AudioStreamPlayer2D",
        "AudioStreamPlayer",
        "StandardMaterial3D",
        "MeshInstance3D",
    }
)

_IMAGE_KEYS = frozenset(
    {
        "width",
        "height",
        "aspect_ratio",
        "transparent_background",
        "alpha_required",
        "color_space",
        "format",
        "bit_depth",
        "allow_antialiasing",
        "pixel_art",
        "subject_position",
        "sprite_sheet",
        "frame_count",
        "frame_size",
        "animation_fps",
        "loop_mode",
        "atlas_padding",
        "texture_filtering",
        "godot_resource",
    }
)
_AUDIO_KEYS = frozenset(
    {
        "format",
        "sample_rate",
        "channels",
        "duration_seconds",
        "peak_db",
        "volume_range",
        "loop_start_seconds",
        "loop_end_seconds",
        "seamless_loop",
        "fade_in_out",
        "subtitles_required",
        "usage",
        "godot_resource",
    }
)
_MODEL_KEYS = frozenset(
    {
        "format",
        "scale",
        "forward_axis",
        "up_axis",
        "polygon_budget",
        "material_style",
        "godot_resource",
    }
)
_RESOURCE_KEYS = frozenset({"format", "fallback", "preload", "godot_resource"})

_IMAGE_FORMATS = frozenset({"png", "webp", "jpg", "exr"})
_AUDIO_FORMATS = frozenset({"wav", "ogg"})
_MODEL_FORMATS = frozenset({"glb", "gltf", "fbx", "obj"})
_COLOR_SPACES = frozenset({"sRGB", "Linear"})
_LOOP_MODES = frozenset({"loop", "once", "ping_pong"})
_TEXTURE_FILTERING = frozenset({"nearest", "linear"})
_USAGES = frozenset({"sfx", "music", "ambience", "voice"})
_SUBJECT_POSITIONS = frozenset({"center", "bottom_center", "custom"})
_AXES = frozenset({"X", "Y", "Z", "-X", "-Y", "-Z"})


def _invalid(message: str, **details: Any) -> AssetBriefInvalid:
    return AssetBriefInvalid(message, details=details)


def _require_int(spec: dict[str, Any], key: str, *, minimum: int, maximum: int) -> int:
    value = spec.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise _invalid("规格数值非法", key=key, value=value, minimum=minimum, maximum=maximum)
    return value


def _optional_bool(spec: dict[str, Any], key: str) -> None:
    if key in spec and not isinstance(spec[key], bool):
        raise _invalid("规格布尔值非法", key=key, value=spec[key])


def _optional_enum(spec: dict[str, Any], key: str, allowed: frozenset[str]) -> None:
    if key in spec and spec[key] not in allowed:
        raise _invalid("规格枚举非法", key=key, value=spec[key], allowed=sorted(allowed))


def _reject_unknown(spec: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise _invalid("规格包含未知字段", fields=unknown)


def _validate_godot_resource(value: Any) -> None:
    if not isinstance(value, dict):
        raise _invalid("godot_resource 必须是对象")
    resource_type = value.get("resource_type")
    if resource_type not in GODOT_RESOURCE_TYPES:
        raise _invalid(
            "Godot 资源类型不受支持",
            resource_type=resource_type,
            allowed=sorted(GODOT_RESOURCE_TYPES),
        )
    properties = value.get("properties", {})
    if not isinstance(properties, dict):
        raise _invalid("godot_resource.properties 必须是对象")


def validate_image_spec(spec: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(spec, _IMAGE_KEYS)
    _require_int(spec, "width", minimum=1, maximum=8192)
    _require_int(spec, "height", minimum=1, maximum=8192)
    _optional_enum(spec, "aspect_ratio", frozenset({"1:1", "4:3", "16:9", "3:4", "9:16"}))
    _optional_enum(spec, "color_space", _COLOR_SPACES)
    _optional_enum(spec, "format", _IMAGE_FORMATS)
    _optional_enum(spec, "loop_mode", _LOOP_MODES)
    _optional_enum(spec, "texture_filtering", _TEXTURE_FILTERING)
    _optional_enum(spec, "subject_position", _SUBJECT_POSITIONS)
    for key in ("transparent_background", "alpha_required", "allow_antialiasing", "pixel_art"):
        _optional_bool(spec, key)
    if "bit_depth" in spec and spec["bit_depth"] not in (8, 16):
        raise _invalid("位深必须是 8 或 16", value=spec["bit_depth"])
    if "frame_count" in spec:
        _require_int(spec, "frame_count", minimum=1, maximum=240)
    if "animation_fps" in spec:
        _require_int(spec, "animation_fps", minimum=1, maximum=120)
    if "atlas_padding" in spec:
        _require_int(spec, "atlas_padding", minimum=0, maximum=64)
    if "frame_size" in spec:
        size = spec["frame_size"]
        if (
            not isinstance(size, list)
            or len(size) != 2
            or not all(isinstance(item, int) and item > 0 for item in size)
        ):
            raise _invalid("frame_size 必须是 [width, height]")
    if "sprite_sheet" in spec:
        grid = spec["sprite_sheet"]
        if not isinstance(grid, dict):
            raise _invalid("sprite_sheet 必须是对象")
        for key in ("columns", "rows"):
            value = grid.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise _invalid("sprite_sheet 网格非法", key=key, value=value)
    if "godot_resource" in spec:
        _validate_godot_resource(spec["godot_resource"])
    return dict(spec)


def validate_audio_spec(spec: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(spec, _AUDIO_KEYS)
    _optional_enum(spec, "format", _AUDIO_FORMATS)
    _optional_enum(spec, "usage", _USAGES)
    if "sample_rate" in spec and spec["sample_rate"] not in (22050, 44100, 48000):
        raise _invalid("采样率非法", value=spec["sample_rate"])
    if "channels" in spec and spec["channels"] not in (1, 2):
        raise _invalid("声道数必须是 1 或 2", value=spec["channels"])
    if "duration_seconds" in spec:
        value = spec["duration_seconds"]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value <= 600:
            raise _invalid("时长非法", value=value)
    if "peak_db" in spec:
        value = spec["peak_db"]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not -60 <= value <= 0:
            raise _invalid("峰值必须位于 -60 到 0 dB", value=value)
    if "volume_range" in spec:
        value = spec["volume_range"]
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
            or value[0] > value[1]
        ):
            raise _invalid("音量范围必须是 [min, max]", value=value)
    if "loop_start_seconds" in spec and spec["loop_start_seconds"] < 0:
        raise _invalid("循环起点不能为负")
    if "loop_end_seconds" in spec and spec["loop_end_seconds"] <= spec.get(
        "loop_start_seconds", 0
    ):
        raise _invalid("循环终点必须大于起点")
    for key in ("seamless_loop", "fade_in_out", "subtitles_required"):
        _optional_bool(spec, key)
    if "godot_resource" in spec:
        _validate_godot_resource(spec["godot_resource"])
    return dict(spec)


def validate_model_spec(spec: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(spec, _MODEL_KEYS)
    _optional_enum(spec, "format", _MODEL_FORMATS)
    _optional_enum(spec, "forward_axis", _AXES)
    _optional_enum(spec, "up_axis", _AXES)
    if "scale" in spec:
        value = spec["scale"]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise _invalid("模型缩放必须为正数", value=value)
    if "polygon_budget" in spec:
        _require_int(spec, "polygon_budget", minimum=1, maximum=5_000_000)
    if "godot_resource" in spec:
        _validate_godot_resource(spec["godot_resource"])
    return dict(spec)


def validate_resource_spec(spec: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(spec, _RESOURCE_KEYS)
    _optional_bool(spec, "preload")
    if "godot_resource" in spec:
        _validate_godot_resource(spec["godot_resource"])
    return dict(spec)


def validate_technical_spec(category: str, spec: dict[str, Any] | None) -> dict[str, Any]:
    if category not in ASSET_CATEGORIES:
        raise _invalid("资产分类未知", category=category)
    if not spec:
        raise _invalid("Asset Brief 必须包含技术规格", category=category)
    if not isinstance(spec, dict):
        raise _invalid("技术规格必须是对象")
    if category == "IMAGE":
        return validate_image_spec(spec)
    if category == "AUDIO":
        return validate_audio_spec(spec)
    if category == "MODEL_3D":
        return validate_model_spec(spec)
    return validate_resource_spec(spec)


@dataclass(frozen=True, slots=True)
class AssetBriefView:
    brief_id: str
    project_id: str
    task_id: str | None
    asset_id: str | None
    title: str
    asset_category: str
    visual_direction: str
    style_reference: str
    technical_constraints: dict[str, Any]
    animation_requirements: dict[str, Any]
    delivery_requirements: dict[str, Any]
    license_requirements: dict[str, Any]
    acceptance_criteria: tuple[str, ...]
    status: str
    created_by: str | None
    version: int
    created_at: datetime
    updated_at: datetime


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _brief_view(entity: AssetBriefModel) -> AssetBriefView:
    return AssetBriefView(
        brief_id=entity.brief_id,
        project_id=entity.project_id,
        task_id=entity.task_id,
        asset_id=entity.asset_id,
        title=entity.title,
        asset_category=entity.asset_category,
        visual_direction=entity.visual_direction,
        style_reference=entity.style_reference,
        technical_constraints=_load(entity.technical_constraints_json, {}),
        animation_requirements=_load(entity.animation_requirements_json, {}),
        delivery_requirements=_load(entity.delivery_requirements_json, {}),
        license_requirements=_load(entity.license_requirements_json, {}),
        acceptance_criteria=tuple(_load(entity.acceptance_criteria_json, [])),
        status=entity.status,
        created_by=entity.created_by,
        version=entity.version,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


class AssetBriefService:
    """Asset Brief 创建、修改与状态管理。"""

    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def create(
        self,
        *,
        project_id: str,
        title: str,
        asset_category: str,
        visual_direction: str = "",
        style_reference: str = "",
        technical_constraints: dict[str, Any] | None = None,
        animation_requirements: dict[str, Any] | None = None,
        delivery_requirements: dict[str, Any] | None = None,
        license_requirements: dict[str, Any] | None = None,
        acceptance_criteria: tuple[str, ...] = (),
        task_id: str | None = None,
        asset_id: str | None = None,
        created_by: str | None = None,
    ) -> AssetBriefView:
        clean_title = title.strip()
        if not clean_title:
            raise _invalid("Brief 标题不能为空")
        technical = validate_technical_spec(asset_category, technical_constraints)
        now = utcnow()
        async with self._database.session() as session, transaction(session):
            entity = await AssetBriefRepository(session).add(
                AssetBriefModel(
                    brief_id="brf_" + uuid4().hex[:12],
                    project_id=project_id,
                    task_id=task_id,
                    asset_id=asset_id,
                    title=clean_title,
                    asset_category=asset_category,
                    visual_direction=visual_direction,
                    style_reference=style_reference,
                    technical_constraints_json=_dump(technical),
                    animation_requirements_json=_dump(animation_requirements or {}),
                    delivery_requirements_json=_dump(delivery_requirements or {}),
                    license_requirements_json=_dump(license_requirements or {}),
                    acceptance_criteria_json=_dump(list(acceptance_criteria)),
                    status=BRIEF_DRAFT,
                    created_by=created_by,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            view = _brief_view(entity)
        return view

    async def get(self, brief_id: str) -> AssetBriefView:
        async with self._database.session() as session:
            entity = await AssetBriefRepository(session).get(brief_id)
        if entity is None:
            raise NotFoundError("Asset Brief 不存在", details={"brief_id": brief_id})
        return _brief_view(entity)

    async def list(
        self, project_id: str, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            page = await AssetBriefRepository(session).list_for_project(
                project_id, status=status, limit=limit, offset=offset
            )
        return {
            "items": [_brief_view(item) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

    async def update(
        self,
        brief_id: str,
        *,
        expected_version: int | None = None,
        title: str | None = None,
        visual_direction: str | None = None,
        style_reference: str | None = None,
        technical_constraints: dict[str, Any] | None = None,
        animation_requirements: dict[str, Any] | None = None,
        delivery_requirements: dict[str, Any] | None = None,
        license_requirements: dict[str, Any] | None = None,
        acceptance_criteria: tuple[str, ...] | None = None,
    ) -> AssetBriefView:
        async with self._database.session() as session, transaction(session):
            repository = AssetBriefRepository(session)
            entity = await repository.get(brief_id)
            if entity is None:
                raise NotFoundError("Asset Brief 不存在", details={"brief_id": brief_id})
            if entity.status not in (BRIEF_DRAFT, BRIEF_PROPOSED):
                raise _invalid("已批准或已废弃的 Brief 不能修改", status=entity.status)
            if expected_version is not None and entity.version != expected_version:
                raise VersionConflict(
                    "Brief 版本已变化",
                    details={"expected": expected_version, "actual": entity.version},
                )
            if title is not None:
                clean_title = title.strip()
                if not clean_title:
                    raise _invalid("Brief 标题不能为空")
                entity.title = clean_title
            if visual_direction is not None:
                entity.visual_direction = visual_direction
            if style_reference is not None:
                entity.style_reference = style_reference
            if technical_constraints is not None:
                entity.technical_constraints_json = _dump(
                    validate_technical_spec(entity.asset_category, technical_constraints)
                )
            if animation_requirements is not None:
                entity.animation_requirements_json = _dump(animation_requirements)
            if delivery_requirements is not None:
                entity.delivery_requirements_json = _dump(delivery_requirements)
            if license_requirements is not None:
                entity.license_requirements_json = _dump(license_requirements)
            if acceptance_criteria is not None:
                entity.acceptance_criteria_json = _dump(list(acceptance_criteria))
            entity.version += 1
            entity.updated_at = utcnow()
            await session.flush()
            view = _brief_view(entity)
        return view

    async def transition(self, brief_id: str, to_status: str) -> AssetBriefView:
        async with self._database.session() as session, transaction(session):
            repository = AssetBriefRepository(session)
            entity = await repository.get(brief_id)
            if entity is None:
                raise NotFoundError("Asset Brief 不存在", details={"brief_id": brief_id})
            allowed = BRIEF_TRANSITIONS.get(entity.status, frozenset())
            if to_status not in allowed:
                raise _invalid(
                    "Brief 状态迁移不合法", **{"from": entity.status, "to": to_status}
                )
            entity.status = to_status
            entity.version += 1
            entity.updated_at = utcnow()
            await session.flush()
            view = _brief_view(entity)
        return view

    async def propose(self, brief_id: str) -> AssetBriefView:
        return await self.transition(brief_id, BRIEF_PROPOSED)

    async def approve(self, brief_id: str) -> AssetBriefView:
        return await self.transition(brief_id, BRIEF_APPROVED)

    async def reject(self, brief_id: str) -> AssetBriefView:
        return await self.transition(brief_id, "REJECTED")

    async def supersede(self, brief_id: str) -> AssetBriefView:
        return await self.transition(brief_id, BRIEF_SUPERSEDED)

    async def generation_spec(self, brief_id: str) -> dict[str, Any]:
        brief = await self.get(brief_id)
        return {
            "brief_id": brief.brief_id,
            "project_id": brief.project_id,
            "asset_category": brief.asset_category,
            "technical_constraints": brief.technical_constraints,
            "animation_requirements": brief.animation_requirements,
            "delivery_requirements": brief.delivery_requirements,
            "license_requirements": brief.license_requirements,
            "acceptance_criteria": list(brief.acceptance_criteria),
        }
