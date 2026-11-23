"""E8-M6 单元测试：依赖记录、交付状态路径与恢复幂等键。"""

from __future__ import annotations

import pytest

from core.errors import (
    AssetDeliveryBlocked,
    AssetDependencyInvalid,
    AssetRecoveryRequired,
    AssetStateInvalid,
)
from modules.asset_pipeline.delivery import AssetDeliveryService, DeliveryRequest
from modules.asset_pipeline.dependencies import DependencyEntry
from modules.asset_pipeline.models import (
    DELIVERY_APPLYING,
    DELIVERY_DELIVERED,
    DELIVERY_DRAFT,
    DELIVERY_IMPORTING,
    DELIVERY_UNKNOWN,
    DELIVERY_VERIFYING,
    DELIVERY_WAITING_APPROVAL,
)
from modules.asset_pipeline.recovery import AssetRecoveryService


def test_dependency_entry_validates_fields() -> None:
    with pytest.raises(AssetDependencyInvalid):
        DependencyEntry(
            source_type="SCRIPT",
            source_reference="",
            target_type="TEXTURE",
            target_reference="assets/hero.png",
            dependency_type="SCRIPT_REFERENCE",
        )
    with pytest.raises(AssetDependencyInvalid):
        DependencyEntry(
            source_type="SCRIPT",
            source_reference="res://a.gd",
            target_type="TEXTURE",
            target_reference="assets/hero.png",
            dependency_type="NOT_A_TYPE",
        )


def test_delivery_transition_path() -> None:
    assert AssetDeliveryService._path_to(DELIVERY_IMPORTING, DELIVERY_DELIVERED) == [
        DELIVERY_VERIFYING,
        DELIVERY_DELIVERED,
    ]
    assert AssetDeliveryService._path_to(DELIVERY_UNKNOWN, DELIVERY_DELIVERED) == [
        DELIVERY_DELIVERED
    ]
    assert AssetDeliveryService._path_to(DELIVERY_WAITING_APPROVAL, DELIVERY_APPLYING) == [
        "APPROVED",
        DELIVERY_APPLYING,
    ]
    assert AssetDeliveryService._path_to(DELIVERY_DELIVERED, DELIVERY_DELIVERED) == []
    with pytest.raises(AssetStateInvalid):
        AssetDeliveryService._path_to(DELIVERY_DELIVERED, DELIVERY_DRAFT)


def test_delivery_request_rejects_invalid_input() -> None:
    with pytest.raises(AssetDeliveryBlocked):
        DeliveryRequest(
            project_id="prj_1",
            asset_id="ast_1",
            asset_version_id="av_1",
            target_path="assets/hero.png",
        )
    with pytest.raises(AssetDeliveryBlocked):
        DeliveryRequest(
            project_id="prj_1",
            asset_id="ast_1",
            asset_version_id="av_1",
            target_path="res://assets/hero.png",
            risk_level="EXTREME",
        )
    with pytest.raises(AssetDeliveryBlocked):
        DeliveryRequest(
            project_id="",
            asset_id="ast_1",
            asset_version_id="av_1",
            target_path="res://assets/hero.png",
        )


def test_recovery_idempotency_keys() -> None:
    assert (
        AssetRecoveryService.idempotency_key("import", "aij_1") == "import:aij_1"
    )
    assert (
        AssetRecoveryService.idempotency_key("project_write", " cs_1 ")
        == "project_write:cs_1"
    )
    with pytest.raises(AssetRecoveryRequired):
        AssetRecoveryService.idempotency_key("unknown", "x")
    with pytest.raises(AssetRecoveryRequired):
        AssetRecoveryService.idempotency_key("generation", "  ")
