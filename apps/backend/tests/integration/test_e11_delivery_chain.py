"""E11 交付链路集成测试（T14 / T15 / T16 / T17）。

覆盖真实 B 端链路：

1. 注册真实演示项目（`demo/platformer/godot_project`）；
2. Demo 规格冻结 → ChangeSet 校验/审批/应用；
3. 在真实工程文件上执行 STATIC / STRUCTURE / RESOURCE 三层验证，
   并绑定真实 Godot 运行日志作为证据；
4. Context 装配（项目层可追踪）；
5. 验收评审（ACCEPTED_WITH_NOTES，保留人工/视觉风险）；
6. 真实 Godot 导出 → 不可变制品 → 交付包 → 发布候选 → 冒烟 → 审批 →
   本地交付 → 发布后验证；
7. 系统报告聚合验证/构建/发布结果。

真实导出依赖本机 Godot 4.5.1 与导出模板；缺失时跳过构建用例。
"""

from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.security.tokens import utcnow
from infrastructure.database.service import DatabaseService
from modules.build_release.adapter import GodotHeadlessAdapter, LocalProcessExecutor
from modules.build_release.artifacts import ArtifactRegistryService
from modules.build_release.orchestrator import BuildOrchestrator
from modules.build_release.packaging import PackagingService
from modules.build_release.release_approvals import ReleaseApprovalService
from modules.build_release.release_candidates import ReleaseCandidateService
from modules.build_release.release_manager import ReleaseManagerService
from modules.build_release.service import BuildReleaseService
from modules.build_release.smoke_test import SmokeTestService
from modules.changeset.service import ChangeSetService
from modules.context.models import LAYER_PROJECT
from modules.context.service import ContextAssemblyRequest, ContextAssemblyService
from modules.demo_game.service import DemoGameService
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

REPO_ROOT = Path(__file__).resolve().parents[4]
DEMO_ROOT = REPO_ROOT / "demo" / "platformer"
PROJECT_ROOT = DEMO_ROOT / "godot_project"
EVIDENCE_DIR = DEMO_ROOT / "reports" / "evidence"
GODOT = Path(os.environ.get("GODOT_BIN", str(REPO_ROOT / ".tools" / "godot.exe")))

ENV_ALLOWLIST = [
    "PATH",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "WINDIR",
]


@asynccontextmanager
async def _running(tmp_path: Path, name: str):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / name).as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, key: str, expected):
    return app.state.services.get(key, expected)


async def _register_demo_project(app) -> str:
    registry = _service(app, "project_registry_service", ProjectRegistryService)
    project = await registry.register(
        project_root=str(PROJECT_ROOT),
        name="Platformer Demo (E11)",
        description="E11 端到端交付演示项目",
        project_type="GODOT_2D",
        godot_version="4.5.1",
        created_by="agent_delivery",
    )
    return project.project_id


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(name: str) -> tuple[Path, str]:
    path = EVIDENCE_DIR / name
    assert path.is_file(), f"缺少运行证据: {path}"
    return path, _digest(path)


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
async def test_demo_change_set_verification_context_and_acceptance(tmp_path: Path) -> None:
    async with _running(tmp_path, "e11chain.db") as app:
        project_id = await _register_demo_project(app)
        demo = _service(app, "demo_game_service", DemoGameService)

        # 1. 规格落库并冻结
        seeded = await demo.seed_platformer(project_id)
        assert seeded["counts"]["requirements"] == 21
        frozen = await demo.freeze_spec(project_id)
        assert frozen["spec"]["status"] == "FROZEN"

        # 2. ChangeSet：以真实文件哈希登记交付物，走完审批与申请
        changesets = _service(app, "changeset_service", ChangeSetService)
        items = [
            {
                "resource_path": relative,
                "operation_type": "CREATE",
                "new_content_hash": _digest(PROJECT_ROOT / relative),
            }
            for relative in (
                "project.godot",
                "export_presets.cfg",
                "scenes/main/main.tscn",
                "scenes/levels/level_01.tscn",
                "scenes/tests/runtime_verifier.tscn",
                "scripts/core/main.gd",
                "scripts/player/player_controller.gd",
                "scripts/tests/runtime_verifier.gd",
            )
        ]
        created = await changesets.create(
            project_id=project_id, title="E11 演示项目交付物", items=items
        )
        validated = await changesets.validate(created.changeset_id)
        assert validated["status"] == "VALID"
        approval = await changesets.submit_for_approval(
            created.changeset_id, requested_by="agent_delivery"
        )
        approved = await changesets.approve(
            created.changeset_id, approval.approval_id, actor_id="owner-1"
        )
        assert approved.status == "APPROVED"
        applying = await changesets.start_apply(
            created.changeset_id, approval.approval_id, actor_id="owner-1"
        )
        assert applying.status == "APPLYING"
        applied = await changesets.finish_apply(created.changeset_id, status="APPLIED")
        assert applied.status == "APPLIED"

        # 3. 真实工程文件上的三层验证
        verification = _service(app, "verification_service", VerificationService)
        orchestrator = _service(app, "verification_orchestrator", VerificationOrchestrator)
        req_start = await _requirement(app, project_id, "E11-START", "主场景可启动")
        req_move = await _requirement(app, project_id, "E11-MOVE", "玩家可移动与跳跃")
        req_resource = await _requirement(app, project_id, "E11-RES", "资源引用可解析")

        criteria = {
            req_start: await verification.register_criterion(
                project_id=project_id,
                requirement_id=req_start,
                criterion_type="STRUCTURAL",
                statement="main.tscn 加载成功且 World 节点存在",
                verification_method="STRUCTURE_INSPECTION",
            ),
            req_move: await verification.register_criterion(
                project_id=project_id,
                requirement_id=req_move,
                criterion_type="FUNCTIONAL",
                statement="模拟输入下玩家产生水平与纵向位移",
                verification_method="FUNCTIONAL_TEST",
            ),
            req_resource: await verification.register_criterion(
                project_id=project_id,
                requirement_id=req_resource,
                criterion_type="STRUCTURAL",
                statement="全部 res:// 引用可解析",
                verification_method="RESOURCE_VALIDATION",
            ),
        }
        pt_structure = await verification.register_test_case(
            project_id=project_id,
            name="E11-ST-001 主场景结构",
            test_type="STRUCTURAL",
            execution_method="SCENE_VALIDATION",
            description="加载 main.tscn 并检查 World/Player 节点",
            expected_result="结构与节点类型符合预期",
        )
        pt_functional = await verification.register_test_case(
            project_id=project_id,
            name="E11-FN-001 移动/跳跃/战斗",
            test_type="FUNCTIONAL",
            execution_method="SCRIPTED_INPUT",
            description="runtime_verifier 场景以真实输入驱动玩法",
            expected_result="24 项用例全部 PASS",
            automation_level="AUTOMATED",
        )
        pt_resource = await verification.register_test_case(
            project_id=project_id,
            name="E11-RS-001 资源导入",
            test_type="RESOURCE",
            execution_method="RESOURCE_VALIDATION",
            description="校验场景/资源引用与 .import 侧车",
            expected_result="资源全部可解析",
        )
        pt_static = await verification.register_test_case(
            project_id=project_id,
            name="E11-SC-001 GDScript 静态检查",
            test_type="STATIC",
            execution_method="GDSCRIPT_STATIC",
            description="检查 GDScript 语法与括号配对",
            expected_result="无 ERROR 级问题",
        )
        await verification.link_test(
            requirement_id=req_start,
            test_case_id=pt_structure.test_case_id,
            criterion_id=criteria[req_start].criterion_id,
        )
        await verification.link_test(
            requirement_id=req_move,
            test_case_id=pt_functional.test_case_id,
            criterion_id=criteria[req_move].criterion_id,
        )
        await verification.link_test(
            requirement_id=req_resource,
            test_case_id=pt_resource.test_case_id,
            criterion_id=criteria[req_resource].criterion_id,
        )

        campaign = await verification.agent_request_verification(
            project_id=project_id, campaign_type="PHASE", actor_id="agent_qa"
        )
        plan = await verification.create_plan(
            campaign.campaign_id,
            requirement_ids=(req_start, req_move, req_resource),
            test_suite_ids=(
                pt_structure.test_case_id,
                pt_functional.test_case_id,
                pt_resource.test_case_id,
                pt_static.test_case_id,
            ),
            verification_layers=("STATIC", "STRUCTURE", "RESOURCE"),
        )
        assert plan.status == "READY"

        orchestrator.register_executor("STATIC", StaticAnalysisExecutor(PROJECT_ROOT))
        orchestrator.register_executor(
            "STRUCTURE",
            SceneStructureExecutor(
                PROJECT_ROOT,
                scenes=("scenes/main/main.tscn", "scenes/player/player.tscn"),
                required=(
                    NodeRequirement(
                        scene="scenes/main/main.tscn",
                        path="World",
                        type="Node2D",
                        description="关卡容器",
                    ),
                    NodeRequirement(
                        scene="scenes/player/player.tscn",
                        path="Hitbox",
                        type="Area2D",
                        description="玩家攻击判定",
                    ),
                ),
            ),
        )
        orchestrator.register_executor("RESOURCE", ResourceValidationExecutor(PROJECT_ROOT))
        report = await orchestrator.run_plan(campaign.campaign_id)

        assert report.campaign_status == "COMPLETED"
        assert report.summary["FAILED"] == 0
        layers = {item.layer: item for item in report.layers}
        assert set(layers) == {"STATIC", "STRUCTURE", "RESOURCE"}

        # 4. 真实运行证据：24 项运行时用例全部 PASS
        runtime_log, runtime_hash = _evidence("runtime-verify.log")
        runtime_text = runtime_log.read_text(encoding="utf-8")
        assert "[VERIFY] RESULT=PASS" in runtime_text
        assert "[VERIFY] SUMMARY passed=24 failed=0" in runtime_text
        runtime_evidence = await verification.record_evidence(
            project_id=project_id,
            evidence_type="LOG",
            source_type="GODOT_RUNTIME",
            source_reference=f"file://{runtime_log.as_posix()}",
            content_hash=runtime_hash,
            run_id=layers["STRUCTURE"].run_id,
            metadata={
                "command": "godot --headless res://scenes/tests/runtime_verifier.tscn",
                "exit_code": "0",
                "cases": "24",
                "failed": "0",
                "engine": "4.5.1.stable",
            },
        )
        assert runtime_evidence.validity_status == "VALID"

        for layer_name, case in (
            ("STATIC", pt_static),
            ("STRUCTURE", pt_structure),
            ("RESOURCE", pt_resource),
        ):
            layer = layers[layer_name]
            await verification.record_result(
                campaign_id=campaign.campaign_id,
                result_status="PASSED",
                run_id=layer.run_id,
                test_case_id=case.test_case_id,
                evidence_ids=layer.evidence_ids,
            )
        await verification.record_result(
            campaign_id=campaign.campaign_id,
            result_status="PASSED",
            test_case_id=pt_functional.test_case_id,
            evidence_ids=(runtime_evidence.evidence_id,),
        )

        gate = await verification.evaluate_quality_gate(
            project_id, campaign_id=campaign.campaign_id, risk_level="HIGH"
        )
        assert gate.decision["status"] in {"PASSED", "PASSED_WITH_WARNINGS"}

        # 5. Context 装配：项目层可追踪
        contexts = _service(app, "context_assembly_service", ContextAssemblyService)
        assembled = await contexts.assemble(ContextAssemblyRequest(project_id=project_id))
        layer_names = {layer.layer for layer in assembled.layers}
        assert LAYER_PROJECT in layer_names
        assert assembled.token_estimate > 0

        # 6. 验收评审：保留人工/视觉风险
        review = await demo.review(
            project_id,
            decision="ACCEPTED_WITH_NOTES",
            reviewer="owner-1",
            summary="E11 演示项目通过自动化与真实运行验证，视觉与音频需人工确认",
            known_issues=("headless 环境无法验证视觉表现与音频输出",),
            remaining_risks=("导出包仅在本机 Windows 环境验证",),
        )
        assert review["decision"] == "ACCEPTED_WITH_NOTES"

        system_report = await demo.system_report(project_id)
        assert system_report["verification"]["total"] >= 1
        assert system_report["acceptance"]["decision"] == "ACCEPTED_WITH_NOTES"
        assert system_report["coverage"]["criteria_met_ratio"] >= 0.0


@pytest.mark.skipif(not GODOT.is_file(), reason="本机缺少通过白名单的 Godot 可执行文件")
@pytest.mark.asyncio
async def test_real_build_artifact_and_local_delivery(tmp_path: Path) -> None:
    async with _running(tmp_path, "e11build.db") as app:
        project_id = await _register_demo_project(app)
        demo = _service(app, "demo_game_service", DemoGameService)
        await demo.seed_platformer(project_id)

        builds = _service(app, "build_release_service", BuildReleaseService)
        await builds.register_export_preset(
            project_id=project_id,
            preset_name="Windows Desktop",
            platform="WINDOWS",
            export_path="build/PlatformerDemo.exe",
            template_required="windows_release",
            template_available=True,
        )
        environment = await builds.register_environment(
            project_id=project_id,
            os_name="Windows",
            os_version="11",
            cpu_architecture="x86_64",
            godot_version="4.5.1",
            export_template_version="4.5.1",
            toolchain_versions={"msvc": "19.40"},
            sdk_versions={"WINDOWS": "10.0"},
            target_platform="WINDOWS",
        )
        config = await builds.create_configuration(
            project_id=project_id,
            name="win-release",
            target_platform="WINDOWS",
            architecture="x86_64",
            export_preset_name="Windows Desktop",
            build_timeout_seconds=300,
            env_allowlist=ENV_ALLOWLIST,
        )

        orchestrator = BuildOrchestrator(
            _service(app, "database", DatabaseService),
            builds=builds,
            executor=LocalProcessExecutor(),
            projects=_service(app, "project_registry_service", ProjectRegistryService),
            godot_adapter=GodotHeadlessAdapter(str(GODOT)),
        )
        build = await orchestrator.create_build(
            project_id=project_id,
            build_config_id=config.configuration_id,
            environment_id=environment.environment_id,
        )
        started = await orchestrator.start_build(build.build_id)
        assert started.status == "SUCCEEDED", started
        attempts = await orchestrator.list_attempts(build.build_id)
        assert attempts[0].output_manifest

        artifacts = _service(app, "artifact_registry_service", ArtifactRegistryService)
        manifest = attempts[0].output_manifest
        exported = next(PROJECT_ROOT.rglob(manifest[0]["path"]))
        assert exported.is_file() and exported.stat().st_size > 1_000_000
        files = [
            {
                "path": str(exported) if item["path"] == manifest[0]["path"] else item["path"],
                "size": item["size"],
                "hash": item["hash"],
            }
            for item in manifest
        ]
        artifact = await artifacts.register_artifact(
            project_id=project_id,
            platform="WINDOWS",
            architecture="x86_64",
            storage_reference=files[0]["path"],
            files=files,
            build_id=build.build_id,
            attempt_id=attempts[0].attempt_id,
            format="exe",
        )
        artifact = await artifacts.mark_verified(artifact.artifact_id)

        packages = _service(app, "packaging_service", PackagingService)
        package = await packages.create_package(
            project_id=project_id, artifact_id=artifact.artifact_id, format="zip"
        )
        package = await packages.verify_package(package.package_id)

        candidates = _service(app, "release_candidate_service", ReleaseCandidateService)
        candidate = await candidates.create_candidate(
            project_id=project_id,
            version="1.0.0",
            artifact_id=artifact.artifact_id,
            package_id=package.package_id,
        )
        smoke = _service(app, "smoke_test_service", SmokeTestService)
        smoke_log, smoke_hash = _evidence("exported-smoke.log")
        assert "[SMOKE] RESULT=PASS" in smoke_log.read_text(encoding="utf-8")
        await smoke.record_smoke_test(
            project_id=project_id,
            artifact_id=artifact.artifact_id,
            release_candidate_id=candidate.release_candidate_id,
            checks=[
                {
                    "name": "exported-binary-smoke",
                    "status": "PASSED",
                    "evidence_hash": smoke_hash,
                }
            ],
        )
        validation = await candidates.validate_candidate(candidate.release_candidate_id)
        assert validation.ready is True

        approvals = _service(app, "release_approval_service", ReleaseApprovalService)
        approval = await approvals.request_approval(
            release_candidate_id=candidate.release_candidate_id,
            distribution_channel="LOCAL_EXPORT",
        )
        await approvals.approve(approval.approval_id, approved_by="owner-1")

        releases = _service(app, "release_manager_service", ReleaseManagerService)
        release = await releases.create_release(
            release_candidate_id=candidate.release_candidate_id,
            approval_id=approval.approval_id,
            channel="LOCAL_EXPORT",
        )
        await releases.authorize_release(release.release_id)
        delivery = tmp_path / "delivery"
        delivery.mkdir()
        published = await releases.start_release(release.release_id, target_reference=str(delivery))
        assert published.status == "PUBLISHED"
        delivered = delivery / exported.name
        assert delivered.is_file()
        assert _digest(delivered) == _digest(exported)
        verified = await releases.verify_release(release.release_id)
        assert verified.status == "COMPLETED"

        system_report = await demo.system_report(project_id)
        assert system_report["build"]["builds"]["total"] >= 1
        assert system_report["build"]["artifacts"]["total"] >= 1
        assert system_report["build"]["releases"]["total"] >= 1
