"""E9-T14/T15 缺陷生命周期与回归影响分析集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ValidationFailed, VerificationStateInvalid
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.changeset.service import ChangeSetService
from modules.project_registry.service import ProjectRegistryService
from modules.requirement.models import REQUIREMENT_ACTIVE, RequirementModel
from modules.verification.service import VerificationService


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9defect.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


async def _project(app, tmp_path: Path, name: str = "Game") -> tuple[str, Path]:
    registry = _service(app, "project_registry_service", ProjectRegistryService)
    root = tmp_path / name.lower().replace(" ", "_")
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    project = await registry.register(project_root=str(root), name=name)
    return project.project_id, root


async def _requirement(app, project_id: str, key: str) -> str:
    database = _service(app, "database", DatabaseService)
    requirement_id = "req_" + key.lower().replace("-", "_")
    now = utcnow()
    async with database.session() as session:
        session.add(
            RequirementModel(
                requirement_id=requirement_id,
                project_id=project_id,
                requirement_key=key,
                title="玩家可以跳跃",
                description="玩家按下跳跃键后完成一次跳跃",
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


@pytest.mark.asyncio
async def test_defect_lifecycle_and_summary(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        project_id, _ = await _project(app, tmp_path)

        defect = await verification.create_defect(
            project_id=project_id,
            severity="MAJOR",
            category="GDSCRIPT",
            title="跳跃失效",
            description="按下空格没有反应",
            reproduction_steps=("启动游戏", "按下空格"),
        )
        assert defect.status == "OPEN"
        assert defect.priority == "P2"
        assert defect.reproduction_steps == ("启动游戏", "按下空格")

        for status in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "FIX_SUBMITTED", "VERIFYING"):
            defect = await verification.transition_defect(defect.defect_id, status)
        assert defect.assigned_agent_id == "gameplay_programmer"

        with pytest.raises(VerificationStateInvalid):
            await verification.transition_defect(defect.defect_id, "RESOLVED")

        resolved = await verification.transition_defect(
            defect.defect_id, "RESOLVED", resolution_reference="run_fix_1"
        )
        assert resolved.status == "RESOLVED"
        assert resolved.resolution_reference == "run_fix_1"

        reopened = await verification.transition_defect(defect.defect_id, "REOPENED")
        assert reopened.status == "REOPENED"

        summary = await verification.defect_summary(project_id)
        assert summary["total"] == 1
        assert summary["active"] == 1
        assert summary["by_category"]["GDSCRIPT"] == 1

        listed = await verification.list_defects(project_id, severity="MAJOR")
        assert listed["total"] == 1

        with pytest.raises(ValidationFailed):
            await verification.create_defect(
                project_id=project_id,
                severity="MAJOR",
                category="GDSCRIPT",
                title="缺少复现信息",
            )
        with pytest.raises(ValidationFailed):
            await verification.create_defect(
                project_id=project_id,
                severity="NOT_A_SEVERITY",
                category="GDSCRIPT",
                title="非法严重程度",
                description="有描述",
            )


@pytest.mark.asyncio
async def test_impact_analysis_from_changeset(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        changesets = _service(app, "changeset_service", ChangeSetService)
        project_id, root = await _project(app, tmp_path, "Platformer")

        (root / "scripts").mkdir()
        (root / "scenes").mkdir()
        (root / "scripts" / "player.gd").write_text("extends CharacterBody2D\n", encoding="utf-8")
        (root / "scenes" / "main.tscn").write_text(
            '[ext_resource path="res://scripts/player.gd" type="Script" id="1"]\n',
            encoding="utf-8",
        )

        requirement_id = await _requirement(app, project_id, "REQ-JUMP")
        uncovered_id = await _requirement(app, project_id, "REQ-DASH")
        test_case = await verification.register_test_case(
            project_id=project_id,
            name="test_player_jump",
            test_type="FUNCTIONAL",
            execution_method="GODOT_TEST",
            description="验证玩家跳跃流程",
        )
        await verification.link_test(
            requirement_id=requirement_id, test_case_id=test_case.test_case_id
        )

        changeset = await changesets.create(
            project_id=project_id,
            title="修复跳跃",
            items=[
                {
                    "resource_path": "scripts/player.gd",
                    "operation_type": "UPDATE",
                    "risk_level": "HIGH",
                }
            ],
        )

        plan = await verification.analyze_impact(
            project_id, changeset_id=changeset.changeset_id, security_requested=False
        )

        assert plan.strategy == "DEPENDENCY"
        assert plan.changed_files == ("scripts/player.gd",)
        assert plan.dependents == ("scenes/main.tscn",)
        assert plan.affected_scenes == ("scenes/main.tscn",)
        assert plan.affected_requirements == (requirement_id,)
        assert plan.affected_test_cases == (test_case.test_case_id,)
        assert plan.coverage_gaps == (uncovered_id,)
        assert "STATIC_ANALYSIS" in plan.required_checks
        assert "FUNCTIONAL_TESTS" in plan.required_checks

        fetched = await verification.get_regression_plan(plan.regression_plan_id)
        assert fetched.regression_plan_id == plan.regression_plan_id
        listed = await verification.list_regression_plans(project_id)
        assert listed["total"] == 1

        with pytest.raises(ValidationFailed):
            await verification.analyze_impact(project_id)
