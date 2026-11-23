"""资产质量控制服务（E8-T10）。

机器检查与人工审核是两套独立机制：

- 机器检查针对具体的 ``AssetVersion``，每次运行都创建新的审核记录与结构化发现；
- 人工审核拥有独立记录，只能在 ``HUMAN_REVIEW_REQUIRED`` 状态下做一次终审；
- 审核记录绑定版本，版本变化后旧审核不会被复用；
- 已结束的审核不能静默覆盖；
- 所有失败项保留证据（对象路径、Hash、指标与阈值）。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from core.errors import AssetQualityInvalid, NotFoundError
from core.events.bus import EventBus
from core.events.model import Event
from core.logging import get_logger, log_event
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.asset_pipeline.models import (
    CATEGORY_AUDIO,
    CATEGORY_IMAGE,
    CATEGORY_MODEL_3D,
    QUALITY_HUMAN_APPROVED,
    QUALITY_HUMAN_REJECTED,
    QUALITY_HUMAN_REQUIRED,
    QUALITY_MACHINE_FAILED,
    QUALITY_MACHINE_PASSED,
    QUALITY_TRANSITIONS,
    REVIEW_TYPE_HUMAN,
    REVIEW_TYPE_MACHINE,
    AssetQualityFindingModel,
    AssetQualityReviewModel,
)
from modules.asset_pipeline.repository import (
    AssetQualityFindingRepository,
    AssetQualityReviewRepository,
    AssetRepository,
    AssetStorageObjectRepository,
    AssetVersionRepository,
)
from modules.asset_pipeline.storage import AssetStorage
from modules.model_gateway.asset_adapters.audio import inspect_audio
from modules.model_gateway.asset_adapters.model3d import (
    inspect_geometry,
    inspect_materials,
)

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"
STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@dataclass(frozen=True, slots=True)
class QualityFinding:
    rule_id: str
    severity: str
    status: str
    message: str
    evidence: dict[str, Any]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class QualityReviewView:
    review_id: str
    project_id: str
    asset_id: str
    asset_version_id: str
    review_type: str
    review_status: str
    machine_result: dict[str, Any]
    human_result: dict[str, Any] | None
    evidence: dict[str, Any]
    reviewer_id: str | None
    notes: str | None
    findings: tuple[dict[str, Any], ...]
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class _StoredObject:
    storage_area: str
    relative_path: str
    content_hash: str
    size_bytes: int
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class _Scope:
    project_id: str
    asset_id: str
    category: str
    version_id: str
    content_hash: str
    objects: tuple[_StoredObject, ...]


def _finding(
    rule_id: str,
    passed: bool,
    message: str,
    *,
    severity: str = SEVERITY_ERROR,
    evidence: Mapping[str, Any] | None = None,
    skipped: bool = False,
) -> QualityFinding:
    return QualityFinding(
        rule_id=rule_id,
        severity=severity,
        status=STATUS_SKIPPED if skipped else (STATUS_PASSED if passed else STATUS_FAILED),
        message=message,
        evidence=dict(evidence or {}),
    )


def _reference_evidence(reference: str, **extra: Any) -> dict[str, Any]:
    payload = {"reference": reference}
    payload.update(extra)
    return payload


def _format_of(reference: str) -> str:
    suffix = Path(reference).suffix.lstrip(".").strip().lower()
    return suffix or "bin"


def _rule_int(rules: Mapping[str, Any], name: str) -> int | None:
    value = rules.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssetQualityInvalid("检查规则参数必须是整数", details={"rule": name})
    return value


def _rule_float(
    rules: Mapping[str, Any], name: str, *, default: float | None = None
) -> float | None:
    value = rules.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AssetQualityInvalid("检查规则参数必须是数字", details={"rule": name})
    return float(value)


def _average_hash(image: Image.Image) -> str:
    gray = image.convert("L").resize((8, 8), Image.Resampling.BILINEAR)
    pixels = list(gray.tobytes())
    average = sum(pixels) / max(len(pixels), 1)
    bits = 0
    for index, value in enumerate(pixels):
        if value >= average:
            bits |= 1 << (63 - index)
    return f"{bits:016x}"


class QualityControlService:
    """机器检查与人工审核。"""

    def __init__(
        self,
        database: DatabaseService,
        *,
        storage: AssetStorage,
        events: EventBus | None = None,
        clock=utcnow,
    ) -> None:
        self._database = database
        self._storage = storage
        self._events = events
        self._clock = clock
        self._logger = get_logger("backend.asset.quality")

    async def run_machine_review(
        self,
        project_id: str,
        asset_id: str,
        version_id: str,
        *,
        rules: Mapping[str, Any] | None = None,
        reviewer_id: str | None = None,
    ) -> QualityReviewView:
        rule_set = dict(rules or {})
        if not isinstance(rule_set, Mapping):
            raise AssetQualityInvalid("检查规则必须是对象")
        scope = await self._load_scope(project_id, asset_id, version_id)
        other_hashes = await self._other_version_hashes(asset_id, version_id)
        findings: list[QualityFinding] = []
        for item in scope.objects:
            data = self._storage.read_bytes(
                project_id, item.storage_area, item.relative_path
            )
            reference = item.relative_path
            if scope.category == CATEGORY_IMAGE:
                findings.extend(
                    _check_image(data, _format_of(reference), rule_set, reference)
                )
            elif scope.category == CATEGORY_AUDIO:
                findings.extend(
                    _check_audio(data, _format_of(reference), rule_set, reference)
                )
            elif scope.category == CATEGORY_MODEL_3D:
                findings.extend(
                    _check_model3d(data, _format_of(reference), rule_set, reference)
                )
            else:
                findings.append(
                    _finding(
                        "asset.category_supported",
                        False,
                        "资产类别不支持机器检查",
                        evidence=_reference_evidence(reference, category=scope.category),
                        skipped=True,
                    )
                )
        findings.extend(_check_duplicates(scope.objects, other_hashes))
        failed = any(
            item.status == STATUS_FAILED and item.severity == SEVERITY_ERROR
            for item in findings
        )
        status = QUALITY_MACHINE_FAILED if failed else QUALITY_MACHINE_PASSED
        summary = {
            "total": len(findings),
            "passed": sum(1 for item in findings if item.status == STATUS_PASSED),
            "failed": sum(1 for item in findings if item.status == STATUS_FAILED),
            "skipped": sum(1 for item in findings if item.status == STATUS_SKIPPED),
            "warnings": sum(1 for item in findings if item.severity == SEVERITY_WARNING),
        }
        evidence = {
            "asset_category": scope.category,
            "version_content_hash": scope.content_hash,
            "objects": [
                {
                    "reference": item.relative_path,
                    "content_hash": item.content_hash,
                    "size_bytes": item.size_bytes,
                }
                for item in scope.objects
            ],
            "rules": [item.to_mapping() for item in findings],
        }
        now = self._clock()
        review_id = "aqr_" + uuid4().hex[:12]
        async with self._database.session() as session, transaction(session):
            await AssetQualityReviewRepository(session).add(
                AssetQualityReviewModel(
                    review_id=review_id,
                    asset_id=asset_id,
                    asset_version_id=version_id,
                    review_type=REVIEW_TYPE_MACHINE,
                    machine_result_json=_dump(
                        {"status": status, "summary": summary}
                    ),
                    human_result_json=None,
                    review_status=status,
                    evidence_json=_dump(evidence),
                    reviewer_id=reviewer_id,
                    notes=None,
                    created_at=now,
                    completed_at=now,
                )
            )
            findings_repository = AssetQualityFindingRepository(session)
            for item in findings:
                await findings_repository.add(
                    AssetQualityFindingModel(
                        finding_id="aqf_" + uuid4().hex[:12],
                        review_id=review_id,
                        rule_id=item.rule_id,
                        severity=item.severity,
                        status=item.status,
                        message=item.message,
                        evidence_json=_dump(item.evidence),
                        created_at=now,
                    )
                )
        await self._publish(
            "asset.quality.machine_reviewed",
            {
                "review_id": review_id,
                "asset_id": asset_id,
                "asset_version_id": version_id,
                "status": status,
            },
            project_id=project_id,
        )
        return await self.get_review(review_id)

    async def request_human_review(
        self,
        project_id: str,
        asset_id: str,
        version_id: str,
        *,
        notes: str | None = None,
        reviewer_id: str | None = None,
    ) -> QualityReviewView:
        scope = await self._load_scope(project_id, asset_id, version_id)
        await self._ensure_machine_reviewed(asset_id, version_id)
        now = self._clock()
        review_id = "aqr_" + uuid4().hex[:12]
        evidence = {
            "asset_category": scope.category,
            "version_content_hash": scope.content_hash,
            "requested_by": reviewer_id,
        }
        async with self._database.session() as session, transaction(session):
            await AssetQualityReviewRepository(session).add(
                AssetQualityReviewModel(
                    review_id=review_id,
                    asset_id=asset_id,
                    asset_version_id=version_id,
                    review_type=REVIEW_TYPE_HUMAN,
                    machine_result_json=None,
                    human_result_json=None,
                    review_status=QUALITY_HUMAN_REQUIRED,
                    evidence_json=_dump(evidence),
                    reviewer_id=reviewer_id,
                    notes=notes,
                    created_at=now,
                    completed_at=None,
                )
            )
        await self._publish(
            "asset.quality.human_review_requested",
            {
                "review_id": review_id,
                "asset_id": asset_id,
                "asset_version_id": version_id,
            },
            project_id=project_id,
        )
        return await self.get_review(review_id)

    async def record_human_decision(
        self,
        project_id: str,
        asset_id: str,
        review_id: str,
        *,
        approved: bool,
        reviewer_id: str,
        notes: str | None = None,
        findings: Mapping[str, Any] | None = None,
    ) -> QualityReviewView:
        if not reviewer_id.strip():
            raise AssetQualityInvalid("人工审核必须记录审核人")
        async with self._database.session() as session, transaction(session):
            asset = await AssetRepository(session).get_active(asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产不存在或不属于该项目",
                    details={"project_id": project_id, "asset_id": asset_id},
                )
            review = await AssetQualityReviewRepository(session).get(review_id)
            if review is None or review.asset_id != asset_id:
                raise NotFoundError(
                    "质量审核记录不存在",
                    details={"asset_id": asset_id, "review_id": review_id},
                )
            if review.review_type != REVIEW_TYPE_HUMAN:
                raise AssetQualityInvalid(
                    "只有人工审核记录可以写入人工结论",
                    details={"review_id": review_id, "review_type": review.review_type},
                )
            if review.review_status != QUALITY_HUMAN_REQUIRED:
                raise AssetQualityInvalid(
                    "审核已结束或状态不允许再次结论，禁止静默覆盖",
                    details={"review_id": review_id, "status": review.review_status},
                )
            target = QUALITY_HUMAN_APPROVED if approved else QUALITY_HUMAN_REJECTED
            if target not in QUALITY_TRANSITIONS.get(review.review_status, frozenset()):
                raise AssetQualityInvalid(
                    "人工审核状态迁移非法",
                    details={"from": review.review_status, "to": target},
                )
            now = self._clock()
            review.review_status = target
            review.human_result_json = _dump(
                {
                    "approved": approved,
                    "notes": notes,
                    "findings": dict(findings or {}),
                }
            )
            review.reviewer_id = reviewer_id
            review.notes = notes
            review.completed_at = now
            await session.flush()
            version_id = review.asset_version_id
        await self._publish(
            "asset.quality.human_reviewed",
            {
                "review_id": review_id,
                "asset_id": asset_id,
                "asset_version_id": version_id,
                "status": target,
            },
            project_id=project_id,
        )
        return await self.get_review(review_id)

    async def get_review(self, review_id: str) -> QualityReviewView:
        async with self._database.session() as session:
            review = await AssetQualityReviewRepository(session).get(review_id)
            if review is None:
                raise NotFoundError(
                    "质量审核记录不存在", details={"review_id": review_id}
                )
            asset = await AssetRepository(session).get(review.asset_id)
            if asset is None:
                raise NotFoundError(
                    "质量审核关联资产不存在", details={"asset_id": review.asset_id}
                )
            findings = await AssetQualityFindingRepository(session).list_for_review(
                review_id
            )
            return _review_view(
                review, project_id=asset.project_id, findings=findings
            )

    async def list_for_version(
        self, project_id: str, asset_id: str, version_id: str
    ) -> list[QualityReviewView]:
        scope = await self._load_scope(project_id, asset_id, version_id)
        async with self._database.session() as session:
            reviews = await AssetQualityReviewRepository(session).list_for_version(
                version_id
            )
            findings_repository = AssetQualityFindingRepository(session)
            views: list[QualityReviewView] = []
            for review in reviews:
                findings = await findings_repository.list_for_review(review.review_id)
                views.append(
                    _review_view(
                        review, project_id=scope.project_id, findings=findings
                    )
                )
            return views

    # ------------------------------------------------------------------
    # 内部流程
    # ------------------------------------------------------------------

    async def _load_scope(
        self, project_id: str, asset_id: str, version_id: str
    ) -> _Scope:
        async with self._database.session() as session:
            asset = await AssetRepository(session).get_active(asset_id)
            if asset is None or asset.project_id != project_id:
                raise NotFoundError(
                    "资产不存在或不属于该项目",
                    details={"project_id": project_id, "asset_id": asset_id},
                )
            version = await AssetVersionRepository(session).get(version_id)
            if version is None or version.asset_id != asset_id:
                raise NotFoundError(
                    "审核版本不属于该资产",
                    details={"asset_id": asset_id, "version_id": version_id},
                )
            objects = await AssetStorageObjectRepository(session).list_for_version(
                version_id
            )
            if not objects:
                raise AssetQualityInvalid(
                    "审核版本没有存储对象",
                    details={"asset_id": asset_id, "version_id": version_id},
                )
            return _Scope(
                project_id=project_id,
                asset_id=asset_id,
                category=asset.category,
                version_id=version_id,
                content_hash=version.content_hash,
                objects=tuple(
                    _StoredObject(
                        storage_area=item.storage_area,
                        relative_path=item.relative_path,
                        content_hash=item.content_hash,
                        size_bytes=item.size_bytes,
                        mime_type=item.mime_type,
                    )
                    for item in objects
                ),
            )

    async def _other_version_hashes(
        self, asset_id: str, version_id: str
    ) -> set[str]:
        async with self._database.session() as session:
            versions = await AssetVersionRepository(session).list_for_asset(asset_id)
            storage_repository = AssetStorageObjectRepository(session)
            hashes: set[str] = set()
            for version in versions:
                if version.version_id == version_id:
                    continue
                for item in await storage_repository.list_for_version(
                    version.version_id
                ):
                    hashes.add(item.content_hash)
            return hashes

    async def _ensure_machine_reviewed(self, asset_id: str, version_id: str) -> None:
        async with self._database.session() as session:
            reviews = await AssetQualityReviewRepository(session).list_for_version(
                version_id
            )
        if not any(item.review_type == REVIEW_TYPE_MACHINE for item in reviews):
            raise AssetQualityInvalid(
                "必须先完成机器检查才能发起人工审核",
                details={"asset_id": asset_id, "version_id": version_id},
            )

    async def _publish(
        self, event_type: str, payload: dict[str, Any], *, project_id: str
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.publish(
                Event.create(event_type, payload, project_id=project_id)
            )
        except Exception:  # noqa: BLE001 - 事件失败不阻断已提交审核
            log_event(
                self._logger,
                logging.WARNING,
                "asset.quality.event_failed",
                component="asset",
                error_code="EVENT_PUBLISH_FAILED",
            )


def _review_view(
    review: AssetQualityReviewModel,
    *,
    project_id: str,
    findings: list[AssetQualityFindingModel],
) -> QualityReviewView:
    return QualityReviewView(
        review_id=review.review_id,
        project_id=project_id,
        asset_id=review.asset_id,
        asset_version_id=review.asset_version_id,
        review_type=review.review_type,
        review_status=review.review_status,
        machine_result=_load(review.machine_result_json, {}),
        human_result=_load(review.human_result_json, None),
        evidence=_load(review.evidence_json, {}),
        reviewer_id=review.reviewer_id,
        notes=review.notes,
        findings=tuple(
            _finding_mapping(item) for item in findings
        ),
        created_at=review.created_at,
        completed_at=review.completed_at,
    )


def _finding_mapping(entity: AssetQualityFindingModel) -> dict[str, Any]:
    return {
        "finding_id": entity.finding_id,
        "rule_id": entity.rule_id,
        "severity": entity.severity,
        "status": entity.status,
        "message": entity.message,
        "evidence": _load(entity.evidence_json, {}),
    }


def _check_image(
    data: bytes,
    image_format: str,
    rules: Mapping[str, Any],
    reference: str,
) -> list[QualityFinding]:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return [
            _finding(
                "image.decodable",
                False,
                "图片无法解码",
                evidence=_reference_evidence(reference, format=image_format),
            )
        ]
    findings: list[QualityFinding] = [
        _finding(
            "image.decodable",
            True,
            "图片可解码",
            evidence=_reference_evidence(
                reference, format=image_format, width=image.width, height=image.height
            ),
        )
    ]
    expected_formats = rules.get("expected_format")
    if expected_formats is not None:
        allowed = (
            {str(item).strip().lower() for item in expected_formats}
            if isinstance(expected_formats, (list, tuple, set))
            else {str(expected_formats).strip().lower()}
        )
        findings.append(
            _finding(
                "image.format",
                image_format in allowed,
                "图片格式符合要求" if image_format in allowed else "图片格式不符合要求",
                evidence=_reference_evidence(
                    reference, expected=sorted(allowed), actual=image_format
                ),
            )
        )
    expected_width = _rule_int(rules, "expected_width")
    if expected_width is not None:
        findings.append(
            _finding(
                "image.width",
                image.width == expected_width,
                "图片宽度符合要求" if image.width == expected_width else "图片宽度不符合要求",
                evidence=_reference_evidence(
                    reference, expected=expected_width, actual=image.width
                ),
            )
        )
    expected_height = _rule_int(rules, "expected_height")
    if expected_height is not None:
        findings.append(
            _finding(
                "image.height",
                image.height == expected_height,
                "图片高度符合要求" if image.height == expected_height else "图片高度不符合要求",
                evidence=_reference_evidence(
                    reference, expected=expected_height, actual=image.height
                ),
            )
        )
    max_file_bytes = _rule_int(rules, "max_file_bytes")
    if max_file_bytes is not None:
        findings.append(
            _finding(
                "image.file_size",
                len(data) <= max_file_bytes,
                "图片大小符合限制" if len(data) <= max_file_bytes else "图片超过大小限制",
                evidence=_reference_evidence(
                    reference, size_bytes=len(data), max_file_bytes=max_file_bytes
                ),
            )
        )
    allowed_modes = rules.get("allowed_color_modes")
    if allowed_modes is not None:
        modes = {str(item).strip().upper() for item in allowed_modes}
        findings.append(
            _finding(
                "image.color_mode",
                image.mode.upper() in modes,
                "颜色模式符合要求" if image.mode.upper() in modes else "颜色模式不符合要求",
                evidence=_reference_evidence(
                    reference, expected=sorted(modes), actual=image.mode
                ),
            )
        )
    has_alpha = image.mode in ("RGBA", "LA", "PA")
    if bool(rules.get("require_alpha")):
        findings.append(
            _finding(
                "image.alpha",
                has_alpha,
                "图片包含 Alpha 通道" if has_alpha else "图片缺少 Alpha 通道",
                evidence=_reference_evidence(reference, mode=image.mode),
            )
        )
    if has_alpha and (
        bool(rules.get("require_transparency")) or bool(rules.get("forbid_transparency"))
    ):
        histogram = image.convert("RGBA").getchannel("A").histogram()
        total = max(sum(histogram), 1)
        transparent_ratio = histogram[0] / total
        if bool(rules.get("require_transparency")):
            findings.append(
                _finding(
                    "image.transparency_present",
                    transparent_ratio > 0.0,
                    "存在透明区域" if transparent_ratio > 0.0 else "没有任何透明区域",
                    evidence=_reference_evidence(
                        reference, transparent_ratio=round(transparent_ratio, 6)
                    ),
                )
            )
        if bool(rules.get("forbid_transparency")):
            findings.append(
                _finding(
                    "image.transparency_absent",
                    transparent_ratio == 0.0,
                    "没有透明像素" if transparent_ratio == 0.0 else "存在透明像素",
                    evidence=_reference_evidence(
                        reference, transparent_ratio=round(transparent_ratio, 6)
                    ),
                )
            )
        max_partial = _rule_float(rules, "max_partial_alpha_ratio", default=0.05)
        partial = 1.0 - transparent_ratio - histogram[255] / total
        findings.append(
            _finding(
                "image.transparent_edge",
                partial <= max_partial,
                (
                    "半透明边缘比例正常"
                    if partial <= max_partial
                    else "半透明边缘像素过多"
                ),
                severity=SEVERITY_WARNING,
                evidence=_reference_evidence(
                    reference,
                    partial_ratio=round(partial, 6),
                    max_partial_alpha_ratio=max_partial,
                ),
            )
        )
    frames = int(getattr(image, "n_frames", 1) or 1)
    expected_frames = _rule_int(rules, "expected_frames")
    if expected_frames is not None:
        findings.append(
            _finding(
                "image.frame_count",
                frames == expected_frames,
                "帧数符合要求" if frames == expected_frames else "帧数不符合要求",
                evidence=_reference_evidence(
                    reference, expected=expected_frames, actual=frames
                ),
            )
        )
    grid = rules.get("sprite_grid")
    if isinstance(grid, Mapping):
        frame_width = int(grid.get("frame_width", 0))
        frame_height = int(grid.get("frame_height", 0))
        columns = int(grid.get("columns", 0))
        rows = int(grid.get("rows", 0))
        margin = int(grid.get("margin", 0))
        spacing = int(grid.get("spacing", 0))
        expected = (
            margin * 2 + columns * frame_width + max(columns - 1, 0) * spacing,
            margin * 2 + rows * frame_height + max(rows - 1, 0) * spacing,
        )
        ok = expected == (image.width, image.height)
        findings.append(
            _finding(
                "image.sprite_grid",
                ok,
                "Sprite Sheet 网格正确" if ok else "Sprite Sheet 网格与尺寸不匹配",
                evidence=_reference_evidence(
                    reference, expected=list(expected), actual=[image.width, image.height]
                ),
            )
        )
    findings.append(
        _finding(
            "image.perceptual_hash",
            True,
            "已计算感知 Hash",
            severity=SEVERITY_INFO,
            evidence=_reference_evidence(
                reference,
                average_hash=_average_hash(image),
                content_hash=hashlib.sha256(data).hexdigest(),
            ),
        )
    )
    return findings


def _check_audio(
    data: bytes,
    audio_format: str,
    rules: Mapping[str, Any],
    reference: str,
) -> list[QualityFinding]:
    try:
        metrics = inspect_audio(data, audio_format)
    except Exception:  # noqa: BLE001 - 解码库异常统一转为检查失败
        return [
            _finding(
                "audio.decodable",
                False,
                "音频无法解码",
                evidence=_reference_evidence(reference, format=audio_format),
            )
        ]
    if not metrics.get("decodable", False):
        return [
            _finding(
                "audio.decodable",
                False,
                "音频不可解码",
                evidence=_reference_evidence(reference, format=audio_format),
            )
        ]
    findings: list[QualityFinding] = [
        _finding(
            "audio.decodable",
            True,
            "音频可解码",
            evidence=_reference_evidence(
                reference, format=audio_format, sample_rate=metrics.get("sample_rate")
            ),
        )
    ]
    expected_rate = _rule_int(rules, "expected_sample_rate")
    if expected_rate is not None:
        actual = metrics.get("sample_rate")
        findings.append(
            _finding(
                "audio.sample_rate",
                actual == expected_rate,
                "采样率符合要求" if actual == expected_rate else "采样率不符合要求",
                evidence=_reference_evidence(
                    reference, expected=expected_rate, actual=actual
                ),
            )
        )
    expected_channels = _rule_int(rules, "expected_channels")
    if expected_channels is not None:
        actual = metrics.get("channels")
        findings.append(
            _finding(
                "audio.channels",
                actual == expected_channels,
                "声道数符合要求" if actual == expected_channels else "声道数不符合要求",
                evidence=_reference_evidence(
                    reference, expected=expected_channels, actual=actual
                ),
            )
        )
    duration = metrics.get("duration_seconds")
    min_duration = _rule_float(rules, "min_duration_seconds")
    if min_duration is not None and duration is not None:
        findings.append(
            _finding(
                "audio.min_duration",
                duration >= min_duration,
                "音频时长不低于下限" if duration >= min_duration else "音频时长低于下限",
                evidence=_reference_evidence(
                    reference, duration_seconds=duration, minimum=min_duration
                ),
            )
        )
    max_duration = _rule_float(rules, "max_duration_seconds")
    if max_duration is not None and duration is not None:
        findings.append(
            _finding(
                "audio.max_duration",
                duration <= max_duration,
                "音频时长不超过上限" if duration <= max_duration else "音频时长超过上限",
                evidence=_reference_evidence(
                    reference, duration_seconds=duration, maximum=max_duration
                ),
            )
        )
    max_peak_db = _rule_float(rules, "max_peak_db")
    peak_db = metrics.get("peak_db")
    if max_peak_db is not None and peak_db is not None:
        findings.append(
            _finding(
                "audio.peak",
                peak_db <= max_peak_db,
                "峰值符合限制" if peak_db <= max_peak_db else "峰值超过限制",
                evidence=_reference_evidence(
                    reference, peak_db=peak_db, max_peak_db=max_peak_db
                ),
            )
        )
    if bool(metrics.get("clipping")):
        forbid_clipping = bool(rules.get("forbid_clipping"))
        findings.append(
            _finding(
                "audio.clipping",
                False,
                "音频存在削波",
                severity=SEVERITY_ERROR if forbid_clipping else SEVERITY_WARNING,
                evidence=_reference_evidence(reference, peak=metrics.get("peak")),
            )
        )
    silence_ratio = metrics.get("silence_ratio")
    max_silence = _rule_float(rules, "max_silence_ratio", default=0.98)
    if silence_ratio is not None and max_silence is not None:
        findings.append(
            _finding(
                "audio.silence",
                silence_ratio <= max_silence,
                "静音比例正常" if silence_ratio <= max_silence else "静音比例异常",
                severity=SEVERITY_WARNING,
                evidence=_reference_evidence(
                    reference, silence_ratio=silence_ratio, max_silence_ratio=max_silence
                ),
            )
        )
    if bool(rules.get("check_loop_seam")):
        threshold = _rule_float(rules, "loop_seam_threshold", default=0.25)
        seam = metrics.get("head_tail_discontinuity")
        if seam is not None and threshold is not None:
            findings.append(
                _finding(
                    "audio.loop_seam",
                    seam <= threshold,
                    "循环接缝正常" if seam <= threshold else "循环接缝跳变过大",
                    severity=SEVERITY_WARNING,
                    evidence=_reference_evidence(
                        reference, seam_delta=seam, threshold=threshold
                    ),
                )
            )
    return findings


def _check_model3d(
    data: bytes,
    model_format: str,
    rules: Mapping[str, Any],
    reference: str,
) -> list[QualityFinding]:
    try:
        geometry = inspect_geometry(data, model_format)
    except Exception:  # noqa: BLE001 - 解析库异常统一转为检查失败
        return [
            _finding(
                "model3d.parse",
                False,
                "3D 文件无法解析",
                evidence=_reference_evidence(reference, format=model_format),
            )
        ]
    findings: list[QualityFinding] = [
        _finding(
            "model3d.parse",
            True,
            "3D 文件可解析",
            evidence=_reference_evidence(reference, format=model_format),
        ),
        _finding(
            "model3d.geometry_present",
            not geometry.empty,
            "几何体存在" if not geometry.empty else "几何体为空",
            evidence=_reference_evidence(
                reference,
                mesh_count=geometry.mesh_count,
                triangle_count=geometry.triangle_count,
            ),
        ),
    ]
    max_triangles = _rule_int(rules, "max_triangles")
    if max_triangles is not None:
        findings.append(
            _finding(
                "model3d.triangle_budget",
                geometry.triangle_count <= max_triangles,
                (
                    "面数符合限制"
                    if geometry.triangle_count <= max_triangles
                    else "面数超过限制"
                ),
                evidence=_reference_evidence(
                    reference,
                    triangle_count=geometry.triangle_count,
                    max_triangles=max_triangles,
                ),
            )
        )
    if bool(rules.get("require_uv")):
        findings.append(
            _finding(
                "model3d.uv",
                geometry.has_uv,
                "包含 UV" if geometry.has_uv else "缺少 UV",
                evidence=_reference_evidence(reference, has_uv=geometry.has_uv),
            )
        )
    if bool(rules.get("require_materials")):
        findings.append(
            _finding(
                "model3d.materials",
                geometry.material_count > 0,
                "材质存在" if geometry.material_count > 0 else "缺少材质",
                evidence=_reference_evidence(
                    reference, material_count=geometry.material_count
                ),
            )
        )
    if bool(rules.get("require_skin")):
        findings.append(
            _finding(
                "model3d.skin",
                geometry.skin_count > 0,
                "骨骼引用存在" if geometry.skin_count > 0 else "缺少骨骼引用",
                evidence=_reference_evidence(reference, skin_count=geometry.skin_count),
            )
        )
    if bool(rules.get("require_textures")):
        try:
            materials = inspect_materials(data, model_format)
            has_textures = materials.has_textures
        except Exception:  # noqa: BLE001 - 材质解析失败视为检查失败
            has_textures = False
        findings.append(
            _finding(
                "model3d.textures",
                has_textures,
                "贴图完整" if has_textures else "缺少贴图",
                evidence=_reference_evidence(reference, has_textures=has_textures),
            )
        )
    return findings


def _check_duplicates(
    objects: tuple[_StoredObject, ...], other_hashes: set[str]
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    seen: dict[str, str] = {}
    for item in objects:
        if item.content_hash in seen:
            findings.append(
                _finding(
                    "asset.duplicate_content",
                    False,
                    "同一版本存在重复文件",
                    severity=SEVERITY_WARNING,
                    evidence={
                        "reference": item.relative_path,
                        "duplicate_of": seen[item.content_hash],
                        "content_hash": item.content_hash,
                    },
                )
            )
        else:
            seen[item.content_hash] = item.relative_path
        if item.content_hash in other_hashes:
            findings.append(
                _finding(
                    "asset.duplicate_version",
                    False,
                    "与其他版本内容重复",
                    severity=SEVERITY_WARNING,
                    evidence={
                        "reference": item.relative_path,
                        "content_hash": item.content_hash,
                    },
                )
            )
    return findings
