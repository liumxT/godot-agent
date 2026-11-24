"""E9-T20 验收测试：Platformer Demo 验证闭环与缺陷修复闭环。

覆盖：

- 真实 Godot 工程文件上的 STATIC / STRUCTURE / RESOURCE 三层检查；
- Agent 发起验证 → 计划 → 执行 → 结果与证据 → 质量门禁 → Phase Review；
- 诚实性：UNKNOWN / 未执行单独统计，不进入通过率；证据必须可追溯；
- 缺陷发现 → 分派 → 修复 → 回归验证 → 关闭的完整闭环。
"""

from __future__ import annotations

import hashlib
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
    ResourceValidationExecutor,
    SceneStructureExecutor,
    StaticAnalysisExecutor,
)
from modules.verification.godot.scene_validator import NodeRequirement
from modules.verification.orchestrator import VerificationOrchestrator
from modules.verification.service import VerificationService

_SNAPSHOT = "\x89PNG\r\n\x1a\nplatformer-hud"


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e9accept.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, name: str, expected):
    return app.state.services.get(name, expected)


def _write_platformer(root: Path, *, broken_player: bool = False) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scenes").mkdir(exist_ok=True)
    (root / "resources").mkdir(exist_ok=True)
    (root / "assets").mkdir(exist_ok=True)

    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nrun/main_scene="res://scenes/main.tscn"\n',
        encoding="utf-8",
    )
    player = (
        "extends CharacterBody2D\n\n"
        "const SPEED := 220.0\n\n"
        "func _physics_process(delta: float) -> void:\n"
        "\tvelocity.x = SPEED\n"
        "\tvelocity.y += 980.0 * delta\n"
        "\tmove_and_slide(\n"
        if broken_player
        else "extends CharacterBody2D\n\n"
        "const SPEED := 220.0\n\n"
        "func _physics_process(delta: float) -> void:\n"
        "\tvelocity.x = SPEED\n"
        "\tvelocity.y += 980.0 * delta\n"
        "\tmove_and_slide()\n"
    )
    (root / "scripts" / "player.gd").write_text(player, encoding="utf-8")
    (root / "scripts" / "coin.gd").write_text("extends Area2D\n", encoding="utf-8")
    (root / "scenes" / "main.tscn").write_text(
        '[gd_scene load_steps=2 format=3]\n\n'
        '[ext_resource type="Script" path="res://scripts/player.gd" id="1_player"]\n\n'
        '[node name="Main" type="Node2D"]\n\n'
        '[node name="Player" type="CharacterBody2D" parent="."]\n'
        'script = ExtResource("1_player")\n\n'
        '[node name="HUD" type="CanvasLayer" parent="."]\n',
        encoding="utf-8",
    )
    (root / "resources" / "coin.tres").write_text(
        '[gd_resource type="Resource" format=3]\n\n'
        '[ext_resource type="Script" path="res://scripts/coin.gd" id="1_coin"]\n\n'
        "[resource]\n"
        'script = ExtResource("1_coin")\n',
        encoding="utf-8",
    )
    (root / "assets" / "hud.png").write_bytes(_SNAPSHOT.encode("utf-8"))
    (root / "assets" / "hud.png.import").write_text(
        '[remap]\n\nimporter="texture"\n', encoding="utf-8"
    )


async def _project(app, tmp_path: Path, *, broken_player: bool = False) -> tuple[str, Path]:
    registry = _service(app, "project_registry_service", ProjectRegistryService)
    root = tmp_path / "platformer"
    root.mkdir(exist_ok=True)
    _write_platformer(root, broken_player=broken_player)
    project = await registry.register(project_root=str(root), name="Platformer Demo")
    return project.project_id, root


async def _requirement(app, project_id: str, key: str, title: str) -> str:
    database = _service(app, "database", DatabaseService)
    now = utcnow()
    async with database.session() as session:
        session.add(
            RequirementModel(
                requirement_id=f"req_{key}",
                project_id=project_id,
                requirement_key=key,
                title=title,
                description=f"{title} 验收需求",
                category="FUNCTIONAL",
                priority="HIGH",
                status=REQUIREMENT_ACTIVE,
                source="USER",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    return f"req_{key}"


@pytest.mark.asyncio
async def test_platformer_demo_full_verification_flow(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        orchestrator = _service(
            app, "verification_orchestrator", VerificationOrchestrator
        )
        project_id, root = await _project(app, tmp_path)

        req_start = await _requirement(app, project_id, "REQ-START", "启动主场景")
        req_move = await _requirement(app, project_id, "REQ-MOVE", "玩家左右移动")
        req_jump = await _requirement(app, project_id, "REQ-JUMP", "玩家跳跃与重力")

        criterion_ids: dict[str, str] = {}
        for requirement_id, method, statement in (
            (req_start, "STRUCTURE_INSPECTION", "主场景可加载且 Player 节点存在"),
            (req_move, "FUNCTIONAL_TEST", "按下移动键玩家水平位移大于 0"),
            (req_jump, "FUNCTIONAL_TEST", "跳跃后玩家纵向位移大于 0 且落回地面"),
        ):
            criterion = await verification.register_criterion(
                project_id=project_id,
                requirement_id=requirement_id,
                criterion_type="STRUCTURAL" if requirement_id == req_start else "FUNCTIONAL",
                statement=statement,
                verification_method=method,
            )
            criterion_ids[requirement_id] = criterion.criterion_id

        pt001 = await verification.register_test_case(
            project_id=project_id,
            name="PT-001 启动主场景",
            test_type="STRUCTURAL",
            execution_method="SCENE_VALIDATION",
            description="加载 main.tscn 并检查关键节点",
            expected_result="场景加载成功",
        )
        pt002 = await verification.register_test_case(
            project_id=project_id,
            name="PT-002 玩家移动与跳跃",
            test_type="FUNCTIONAL",
            execution_method="SCRIPTED_INPUT",
            description="模拟输入驱动玩家移动与跳跃",
            expected_result="位移符合预期",
            automation_level="AUTOMATED",
        )
        pt013 = await verification.register_test_case(
            project_id=project_id,
            name="PT-013 资源导入",
            test_type="RESOURCE",
            execution_method="RESOURCE_VALIDATION",
            description="检查 main.tscn 与 coin.tres 引用的资源可解析",
            expected_result="资源全部可解析",
        )
        pt015 = await verification.register_test_case(
            project_id=project_id,
            name="PT-015 脚本静态检查",
            test_type="STATIC",
            execution_method="GDSCRIPT_STATIC",
            description="检查 GDScript 语法与括号配对",
            expected_result="无 ERROR 级问题",
        )

        await verification.link_test(
            requirement_id=req_start,
            test_case_id=pt001.test_case_id,
            criterion_id=criterion_ids[req_start],
        )
        await verification.link_test(
            requirement_id=req_move,
            test_case_id=pt002.test_case_id,
            criterion_id=criterion_ids[req_move],
        )
        await verification.link_test(
            requirement_id=req_jump,
            test_case_id=pt002.test_case_id,
            criterion_id=criterion_ids[req_jump],
        )

        # 1. Agent 发起验证并提交计划（Agent 不能决定结果）
        campaign = await verification.agent_request_verification(
            project_id=project_id, campaign_type="PHASE", actor_id="agent_qa"
        )
        plan = await verification.create_plan(
            campaign.campaign_id,
            requirement_ids=(req_start, req_move, req_jump),
            test_suite_ids=(
                pt001.test_case_id,
                pt002.test_case_id,
                pt013.test_case_id,
                pt015.test_case_id,
            ),
            verification_layers=("STATIC", "STRUCTURE", "RESOURCE"),
        )
        assert plan.status == "READY"

        # 2. 真实工程文件上执行三层验证
        orchestrator.register_executor("STATIC", StaticAnalysisExecutor(root))
        orchestrator.register_executor(
            "STRUCTURE",
            SceneStructureExecutor(
                root,
                scenes=("scenes/main.tscn",),
                required=(
                    NodeRequirement(
                        scene="scenes/main.tscn",
                        path="Player",
                        type="CharacterBody2D",
                        description="玩家节点",
                    ),
                ),
            ),
        )
        orchestrator.register_executor("RESOURCE", ResourceValidationExecutor(root))
        report = await orchestrator.run_plan(campaign.campaign_id)

        assert report.campaign_status == "COMPLETED"
        assert report.summary["TOTAL"] == 9
        assert report.summary["PASSED"] == 9
        assert report.summary["FAILED"] == 0
        layers = {item.layer: item for item in report.layers}
        assert set(layers) == {"STATIC", "STRUCTURE", "RESOURCE"}
        for layer in layers.values():
            assert len(layer.evidence_ids) == 1

        # 3. 真实截图证据（文件存在 + 哈希一致 + 运行上下文完整）
        screenshot_path = root / "assets" / "hud.png"
        screenshot = await verification.record_evidence(
            project_id=project_id,
            evidence_type="SCREENSHOT",
            source_type="GODOT_RUNTIME",
            source_reference=f"file://{screenshot_path.as_posix()}",
            content_hash=hashlib.sha256(screenshot_path.read_bytes()).hexdigest(),
            run_id=layers["STRUCTURE"].run_id,
            metadata={
                "project_revision": "rev-platformer-1",
                "runtime_instance_id": "rt-demo-1",
                "resolution": "1280x720",
            },
        )
        assert screenshot.validity_status == "VALID"

        # 4. 每条结果绑定测试用例，门禁才能按层聚合
        for layer_name, case in (
            ("STATIC", pt015),
            ("STRUCTURE", pt001),
            ("RESOURCE", pt013),
        ):
            layer = layers[layer_name]
            await verification.record_result(
                campaign_id=campaign.campaign_id,
                result_status="PASSED",
                run_id=layer.run_id,
                test_case_id=case.test_case_id,
                evidence_ids=layer.evidence_ids,
            )

        # 诚实性：未执行的用例记 NOT_RUN，单独统计，不进入通过率
        await verification.record_result(
            campaign_id=campaign.campaign_id,
            result_status="NOT_RUN",
            test_case_id=pt002.test_case_id,
            failure_reason="缺少自动化输入驱动环境",
        )

        # 5. 质量门禁：证据齐全、需求可追踪、缺陷为空 → PASSED
        gate = await verification.evaluate_quality_gate(
            project_id, campaign_id=campaign.campaign_id, risk_level="HIGH"
        )
        statuses = {item.gate_name: item.status for item in gate.gates}
        assert statuses["GATE-1_REQUIREMENT_COMPLETENESS"] == "PASSED"
        assert statuses["GATE-6_EVIDENCE_COMPLETENESS"] == "PASSED"
        assert gate.decision["status"] == "PASSED"

        # 6. Phase Review：建议 ACCEPT，但结论只能由用户给出
        review = await verification.create_phase_review(
            project_id,
            workflow_id="wf_platformer_mvp",
            phase_id="phase_platformer_mvp",
            campaign_id=campaign.campaign_id,
            goals=("玩家可移动", "玩家可跳跃"),
            completed=("玩家可移动", "资源导入通过"),
            incomplete=("跳跃自动化待补",),
            user_confirmations=("已人工试玩主场景",),
        )
        assert review.recommendation == "ACCEPT"
        assert review.status == "DRAFT"
        assert "确认未执行测试是否可接受" in review.summary["user_confirmations"]

        review = await verification.submit_phase_review(
            review.review_id, submitted_by="agent_qa"
        )
        assert review.status == "SUBMITTED"
        review = await verification.decide_phase_review(
            review.review_id,
            decision="ACCEPT",
            actor_id="user_owner",
            comment="冲刺阶段验收通过",
        )
        assert review.status == "ACCEPTED"
        assert review.decided_by == "user_owner"
        assert len(review.decisions) == 1

        # 7. Dashboard 诚实统计
        overview = await verification.verification_overview(project_id)
        assert overview["campaigns"]["total"] == 1
        assert overview["results"]["passed"] == 12
        assert overview["results"]["unknown_or_not_run"] == 1
        assert overview["results"]["executed"] == 12
        assert overview["results"]["pass_rate"] == 100.0


@pytest.mark.asyncio
async def test_platformer_defect_fix_and_regression_loop(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        verification = _service(app, "verification_service", VerificationService)
        orchestrator = _service(
            app, "verification_orchestrator", VerificationOrchestrator
        )
        project_id, root = await _project(app, tmp_path, broken_player=True)

        req_move = await _requirement(app, project_id, "REQ-MOVE", "玩家左右移动")
        criterion = await verification.register_criterion(
            project_id=project_id,
            requirement_id=req_move,
            criterion_type="FUNCTIONAL",
            statement="玩家脚本无语法错误",
            verification_method="STATIC_ANALYSIS",
        )
        pt015 = await verification.register_test_case(
            project_id=project_id,
            name="PT-015 脚本静态检查",
            test_type="STATIC",
            execution_method="GDSCRIPT_STATIC",
            description="检查 GDScript 语法与括号配对",
            expected_result="无 ERROR 级问题",
        )
        await verification.link_test(
            requirement_id=req_move,
            test_case_id=pt015.test_case_id,
            criterion_id=criterion.criterion_id,
        )

        campaign = await verification.agent_request_verification(
            project_id=project_id, campaign_type="TASK", actor_id="agent_qa"
        )
        await verification.create_plan(
            campaign.campaign_id,
            requirement_ids=(req_move,),
            test_suite_ids=(pt015.test_case_id,),
            verification_layers=("STATIC",),
        )
        orchestrator.register_executor("STATIC", StaticAnalysisExecutor(root))
        broken_report = await orchestrator.run_plan(campaign.campaign_id)
        assert broken_report.campaign_status == "FAILED"
        assert broken_report.summary["FAILED"] == 1

        results = await verification.list_results(campaign_id=campaign.campaign_id)
        failed_result = next(
            item for item in results["items"] if item.result_status == "FAILED"
        )

        # 缺陷发现 → 分派 → 修复 → 回归 → 关闭
        defect = await verification.create_defect(
            project_id=project_id,
            severity="BLOCKER",
            category="GDSCRIPT",
            title="player.gd 括号未闭合导致脚本编译失败",
            description="player.gd 中 move_and_slide( 缺少右括号",
            requirement_id=req_move,
            source_result_id=failed_result.result_id,
            assigned_agent_id="agent_gameplay",
        )
        for status in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "FIX_SUBMITTED", "VERIFYING"):
            defect = await verification.transition_defect(defect.defect_id, status)
        assert defect.assigned_agent_id == "agent_gameplay"

        # 修复脚本并执行回归
        _write_platformer(root, broken_player=False)
        impact = await verification.analyze_impact(
            project_id, changed_files=("scripts/player.gd",)
        )
        # main.tscn 反向依赖 player.gd，影响分析必须升级为依赖回归
        assert impact.strategy == "DEPENDENCY"
        assert "STATIC_ANALYSIS" in impact.required_checks
        assert "SCENE_VALIDATION" in impact.required_checks

        regression = await verification.agent_request_verification(
            project_id=project_id, campaign_type="REGRESSION", actor_id="agent_qa"
        )
        await verification.create_plan(
            regression.campaign_id,
            requirement_ids=(req_move,),
            test_suite_ids=(pt015.test_case_id,),
            verification_layers=("STATIC",),
        )
        fixed_report = await orchestrator.run_plan(regression.campaign_id)
        assert fixed_report.campaign_status == "COMPLETED"
        assert fixed_report.summary["PASSED"] == 1

        defect = await verification.transition_defect(
            defect.defect_id,
            "RESOLVED",
            resolution_reference=f"verification_run:{fixed_report.layers[0].run_id}",
        )
        assert defect.status == "RESOLVED"
        assert defect.resolution_reference.startswith("verification_run:")

        summary = await verification.defect_summary(project_id)
        assert summary["total"] == 1
        assert summary["by_status"]["RESOLVED"] == 1

        overview = await verification.verification_overview(project_id)
        assert overview["results"]["failed"] == 1
        assert overview["results"]["passed"] == 1
        assert overview["blocking_defects"] == 0

        # 未执行结果不得进入通过率
        await verification.record_result(
            campaign_id=regression.campaign_id,
            result_status="UNKNOWN",
            test_case_id=pt015.test_case_id,
            failure_reason="运行环境缺失",
        )
        overview = await verification.verification_overview(project_id)
        assert overview["results"]["unknown_or_not_run"] == 1
        assert overview["results"]["executed"] == 2
        assert overview["results"]["pass_rate"] == 50.0
