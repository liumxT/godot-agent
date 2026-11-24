"""静态与结构验证执行器（E9-T06 / T07 接入 Orchestrator）。

执行器只负责产生报告与证据草案，不写库、不修改项目、不修改 Task 状态。
失败报告本身就是证据，保证 FAILED 结果可追溯。
"""

from __future__ import annotations

from pathlib import Path

from modules.verification.functional import (
    FunctionalStepHandler,
    FunctionalTestRunner,
    FunctionalTestSpec,
)
from modules.verification.godot.findings import AnalysisReport
from modules.verification.godot.resource_validator import validate_resources
from modules.verification.godot.scene_validator import NodeRequirement, validate_scenes
from modules.verification.godot.static_analyzer import analyze_project
from modules.verification.models import (
    FUNCTIONAL_FAILED,
    FUNCTIONAL_PASSED,
    FUNCTIONAL_SKIPPED,
    FUNCTIONAL_TO_RESULT_STATUS,
    TEST_TYPE_RESOURCE,
    TEST_TYPE_STATIC,
    TEST_TYPE_STRUCTURAL,
)
from modules.verification.orchestrator import (
    EvidenceDraft,
    LayerOutcome,
    VerificationContext,
)
from modules.verification.runtime import (
    RuntimeEnvironment,
    RuntimeTestEngine,
    RuntimeTestSpec,
    map_runtime_result,
)

_LABELS = {
    TEST_TYPE_STATIC: ("STATIC_ANALYSIS", "TEST_REPORT", "TEST_RUNNER"),
    TEST_TYPE_STRUCTURAL: ("STRUCTURE_VALIDATION", "STRUCTURE_SNAPSHOT", "GODOT_EDITOR"),
    TEST_TYPE_RESOURCE: ("RESOURCE_VALIDATION", "TEST_REPORT", "TEST_RUNNER"),
}


def report_outcome(report: AnalysisReport, *, test_type: str) -> LayerOutcome:
    _, evidence_type, source_type = _LABELS[test_type]
    evidence = EvidenceDraft(
        evidence_type=evidence_type,
        source_type=source_type,
        source_reference=f"verification://{report.kind.lower()}",
        content_hash=report.content_hash(),
        metadata={"report": report.to_dict()},
    )
    return LayerOutcome(
        execution_status="COMPLETED",
        result_status="PASSED" if report.passed else "FAILED",
        evidence=(evidence,),
        failure_reason=report.failure_reason(),
    )


class StaticAnalysisExecutor:
    """扫描 project.godot 与 GDScript 的确定性检查。"""

    def __init__(self, project_root: str | Path) -> None:
        self._root = Path(project_root)

    async def __call__(self, context: VerificationContext) -> LayerOutcome:
        return report_outcome(analyze_project(self._root), test_type=TEST_TYPE_STATIC)


class SceneStructureExecutor:
    """校验 .tscn 结构与验收要求的节点路径/类型。"""

    def __init__(
        self,
        project_root: str | Path,
        *,
        scenes: tuple[str, ...] = (),
        required: tuple[NodeRequirement, ...] = (),
    ) -> None:
        self._root = Path(project_root)
        self._scenes = scenes
        self._required = required

    async def __call__(self, context: VerificationContext) -> LayerOutcome:
        report = validate_scenes(self._root, scenes=self._scenes, required=self._required)
        return report_outcome(report, test_type=TEST_TYPE_STRUCTURAL)


class ResourceValidationExecutor:
    """校验 .tres 引用与资源导入元数据。"""

    def __init__(self, project_root: str | Path) -> None:
        self._root = Path(project_root)

    async def __call__(self, context: VerificationContext) -> LayerOutcome:
        return report_outcome(validate_resources(self._root), test_type=TEST_TYPE_RESOURCE)


class RuntimeTestExecutor:
    """通过 Runtime 引擎执行真实游戏运行测试。"""

    def __init__(
        self,
        engine: RuntimeTestEngine,
        environment: RuntimeEnvironment,
        spec: RuntimeTestSpec,
    ) -> None:
        self._engine = engine
        self._environment = environment
        self._spec = spec

    async def __call__(self, context: VerificationContext) -> LayerOutcome:
        execution = await self._engine.run(self._environment, self._spec)
        result_status = map_runtime_result(execution.status)
        evidence = EvidenceDraft(
            evidence_type="RUNTIME_TRACE",
            source_type="GODOT_RUNTIME",
            source_reference=(
                f"runtime://{self._environment.environment_id}/{self._spec.test_id}"
            ),
            content_hash=execution.content_hash(),
            metadata={
                "project_revision": self._environment.project_revision,
                "runtime_instance_id": (
                    execution.runtime_instance_id
                    or self._environment.runtime_instance_id
                    or ""
                ),
                "report": execution.to_report(),
            },
        )
        return LayerOutcome(
            execution_status=_runtime_execution_status(execution.status),
            result_status=result_status,
            evidence=(evidence,),
            failure_reason=execution.failure_reason(),
            details={"runtime_status": execution.status},
        )


class FunctionalTestExecutor:
    """执行功能测试步骤，并把结果保守映射为验证结果。"""

    def __init__(
        self,
        runner: FunctionalTestRunner,
        spec: FunctionalTestSpec,
        handler: FunctionalStepHandler | None = None,
    ) -> None:
        self._runner = runner
        self._spec = spec
        self._handler = handler

    async def __call__(self, context: VerificationContext) -> LayerOutcome:
        execution = await self._runner.run(self._spec, self._handler)
        result_status = FUNCTIONAL_TO_RESULT_STATUS[execution.status]
        evidence = EvidenceDraft(
            evidence_type="TEST_REPORT",
            source_type="TEST_RUNNER",
            source_reference=f"functional://{self._spec.name}",
            content_hash=execution.content_hash(),
            metadata={"report": execution.to_report()},
        )
        return LayerOutcome(
            execution_status=_functional_execution_status(execution.status),
            result_status=result_status,
            evidence=(evidence,),
            failure_reason=execution.failure_reason,
            details={
                "functional_status": execution.status,
                "failure_step": execution.failure_step,
            },
        )


def _runtime_execution_status(status: str) -> str:
    if status == "COMPLETED":
        return "COMPLETED"
    if status in {"FAILED", "TIMEOUT", "CRASHED"}:
        return "FAILED"
    return "UNKNOWN"


def _functional_execution_status(status: str) -> str:
    if status == FUNCTIONAL_PASSED:
        return "COMPLETED"
    if status == FUNCTIONAL_FAILED:
        return "FAILED"
    if status == FUNCTIONAL_SKIPPED:
        return "SKIPPED"
    return "UNKNOWN"
