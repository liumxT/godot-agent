"""E9-T06/T07 静态与结构执行器接入编排器的集成测试。

验证真实项目文件驱动 STATIC / STRUCTURE 层，失败时证据仍然落库。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.project_registry.service import ProjectRegistryService
from modules.requirement.models import REQUIREMENT_ACTIVE, RequirementModel
from modules.verification.godot.executors import (
    SceneStructureExecutor,
    StaticAnalysisExecutor,
)
from modules.verification.godot.scene_validator import NodeRequirement
from modules.verification.models import (
    LAYER_STATIC,
    LAYER_STRUCTURE,
    METHOD_STATIC_ANALYSIS,
    METHOD_STRUCTURE_INSPECTION,
)
from modules.verification.orchestrator import VerificationOrchestrator
from modules.verification.service import VerificationService

GOOD_SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/player.gd" id="1_player"]

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player")

[node name="Collision" type="CollisionShape2D" parent="."]
"""


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9static.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _get(app, name: str, expected):
    return app.state.services.get(name, expected)


def _write_project(root: Path) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("config_version=5\n[application]\n", encoding="utf-8")
    (root / "scripts" / "player.gd").write_text(
        "extends CharacterBody2D\n\nclass_name Player\n", encoding="utf-8"
    )
    (root / "player.tscn").write_text(GOOD_SCENE, encoding="utf-8")


async def _project(app, tmp_path: Path, name: str) -> str:
    registry = _get(app, "project_registry_service", ProjectRegistryService)
    root = tmp_path / name.lower()
    root.mkdir(parents=True, exist_ok=True)
    _write_project(root)
    project = await registry.register(project_root=str(root), name=name)
    return project.project_id


async def _requirement(app, project_id: str) -> str:
    database = _get(app, "database", DatabaseService)
    requirement_id = "req_scene"
    now = utcnow()
    async with database.session() as session:
        session.add(
            RequirementModel(
                requirement_id=requirement_id,
                project_id=project_id,
                requirement_key="REQ-SCENE",
                title="玩家场景结构正确",
                description="场景包含 CharacterBody2D 与碰撞体",
                category="FUNCTIONAL",
                priority="HIGH",
                status=REQUIREMENT_ACTIVE,
                source="USER",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    return requirement_id


async def _trace(verification: VerificationService, project_id: str, requirement_id: str) -> None:
    static_case = await verification.register_test_case(
        project_id=project_id,
        name="项目静态检查",
        test_type="STATIC",
        execution_method="static_analyzer",
        automation_level="AUTOMATED",
    )
    structure_case = await verification.register_test_case(
        project_id=project_id,
        name="场景结构检查",
        test_type="STRUCTURAL",
        execution_method="scene_validator",
        automation_level="AUTOMATED",
    )
    static_criterion = await verification.register_criterion(
        project_id=project_id,
        requirement_id=requirement_id,
        criterion_type="STRUCTURAL",
        statement="GDScript 无语法级错误",
        verification_method=METHOD_STATIC_ANALYSIS,
    )
    structure_criterion = await verification.register_criterion(
        project_id=project_id,
        requirement_id=requirement_id,
        criterion_type="STRUCTURAL",
        statement="player.tscn 根节点为 CharacterBody2D",
        verification_method=METHOD_STRUCTURE_INSPECTION,
    )
    await verification.link_test(
        requirement_id=requirement_id,
        test_case_id=static_case.test_case_id,
        criterion_id=static_criterion.criterion_id,
    )
    await verification.link_test(
        requirement_id=requirement_id,
        test_case_id=structure_case.test_case_id,
        criterion_id=structure_criterion.criterion_id,
    )


async def _prepare(app, tmp_path: Path, name: str):
    verification = _get(app, "verification_service", VerificationService)
    orchestrator = _get(app, "verification_orchestrator", VerificationOrchestrator)
    project_id = await _project(app, tmp_path, name)
    requirement_id = await _requirement(app, project_id)
    await _trace(verification, project_id, requirement_id)
    prepared = await orchestrator.prepare(
        project_id=project_id,
        campaign_type="TASK",
        requirement_ids=(requirement_id,),
    )
    root = tmp_path / name.lower()
    orchestrator.register_executor(LAYER_STATIC, StaticAnalysisExecutor(root))
    orchestrator.register_executor(
        LAYER_STRUCTURE,
        SceneStructureExecutor(
            root,
            scenes=("player.tscn",),
            required=(
                NodeRequirement(scene="player.tscn", path=".", type="CharacterBody2D"),
                NodeRequirement(scene="player.tscn", path="Collision", type="CollisionShape2D"),
            ),
        ),
    )
    return verification, orchestrator, prepared


@pytest.mark.asyncio
async def test_static_layers_complete_campaign(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification, orchestrator, prepared = await _prepare(app, tmp_path, "Static")

        assert prepared.proposal.verification_layers == (LAYER_STATIC, LAYER_STRUCTURE)
        report = await orchestrator.run_plan(prepared.campaign.campaign_id)

        assert report.blocking is False
        assert report.campaign_status == "COMPLETED"
        assert report.summary["PASSED"] == 2
        for layer in report.layers:
            assert layer.result_status == "PASSED"
            assert layer.evidence_ids

        evidence = await verification.list_evidence(prepared.campaign.project_id)
        kinds = {
            item.metadata.get("report", {}).get("kind")
            for item in evidence["items"]
        }
        assert kinds == {"STATIC_ANALYSIS", "STRUCTURE_VALIDATION"}


@pytest.mark.asyncio
async def test_structure_failure_fails_campaign_with_evidence(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification, orchestrator, prepared = await _prepare(app, tmp_path, "Broken")
        orchestrator.register_executor(
            LAYER_STRUCTURE,
            SceneStructureExecutor(
                tmp_path / "broken",
                required=(
                    NodeRequirement(scene="player.tscn", path=".", type="Node2D"),
                ),
            ),
        )

        report = await orchestrator.run_plan(prepared.campaign.campaign_id)

        assert report.blocking is True
        assert report.campaign_status == "FAILED"
        assert report.summary["FAILED"] == 1
        structure_layer = report.layers[-1]
        assert structure_layer.layer == LAYER_STRUCTURE
        assert "scene_required_node_type" in (structure_layer.failure_reason or "")
        # 失败报告同样是证据，不许出现无证据失败
        assert structure_layer.evidence_ids

        evidence = await verification.list_evidence(prepared.campaign.project_id)
        assert len(evidence["items"]) == 2
