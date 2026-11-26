"""E11 Platformer Demo 应用服务（T01 / T02 / T20）。

职责边界：

- 只管理 Demo 项目专用数据（规格、需求、机制、关卡、功能、验收条件、场景、验收记录）；
- Task / Workflow / Agent / Approval / Verification / Build / Release 状态仍由各自模块拥有；
- ``system_report`` 只读取其他模块的公开查询接口，不直接修改其数据。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.errors import NotFoundError, ValidationFailed
from core.security.tokens import ensure_utc, isoformat, utcnow
from infrastructure.database.service import DatabaseService
from infrastructure.database.transaction import transaction
from modules.demo_game.models import (
    ACCEPTANCE_DECISIONS,
    CRITERION_MET,
    CRITERION_NOT_MET,
    CRITERION_PENDING,
    CRITERION_WAIVED,
    DECISION_REJECTED,
    DEMO_CRITERION_STATUSES,
    DEMO_SCENARIO_STATUSES,
    REQUIREMENT_IMPLEMENTED,
    REQUIREMENT_IN_PROGRESS,
    REQUIREMENT_PLANNED,
    REQUIREMENT_VERIFIED,
    SCENARIO_BLOCKED,
    SCENARIO_FAILED,
    SPEC_DRAFT,
    SPEC_FROZEN,
    DemoAcceptanceReportModel,
    DemoCriterionModel,
    DemoFeatureModel,
    DemoGameSpecModel,
    DemoLevelModel,
    DemoMechanicModel,
    DemoRequirementModel,
    DemoTestScenarioModel,
)
from modules.demo_game.repository import (
    DemoAcceptanceReportRepository,
    DemoCriterionRepository,
    DemoFeatureRepository,
    DemoLevelRepository,
    DemoMechanicRepository,
    DemoRequirementRepository,
    DemoScenarioRepository,
    DemoSpecRepository,
)
from modules.demo_game.specification import (
    LEVELS,
    MECHANICS,
    REQUIREMENTS,
    SCENARIOS,
    SPEC_BASELINE,
)

SYSTEM_NAMES = {
    "PLAYER": "玩家系统",
    "ENEMY": "敌人系统",
    "COMBAT": "战斗系统",
    "LEVEL": "关卡系统",
    "COLLECTIBLE": "收集与计分",
    "UI": "界面",
    "FLOW": "游戏流程",
    "SAVE": "存档",
}
_SYSTEM_ORDER = tuple(SYSTEM_NAMES)


def _new_id(prefix: str) -> str:
    return prefix + uuid4().hex[:12]


def _split(value: str | None) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def _join(values: Sequence[str]) -> str:
    return "|".join(values)


def _criterion_dict(entity: DemoCriterionModel) -> dict[str, Any]:
    return {
        "criterion_key": entity.criterion_key,
        "description": entity.description,
        "verification_method": entity.verification_method,
        "required_evidence": _split(entity.required_evidence),
        "status": entity.status,
    }


def _requirement_dict(
    entity: DemoRequirementModel,
    criteria: Sequence[DemoCriterionModel],
    scenario_keys: Sequence[str],
) -> dict[str, Any]:
    return {
        "requirement_key": entity.requirement_key,
        "title": entity.title,
        "description": entity.description,
        "system": entity.system,
        "category": entity.category,
        "priority": entity.priority,
        "status": entity.status,
        "source": entity.source,
        "criteria": [_criterion_dict(item) for item in criteria],
        "scenarios": list(scenario_keys),
    }


def _report_dict(entity: DemoAcceptanceReportModel) -> dict[str, Any]:
    return {
        "report_id": entity.report_id,
        "project_id": entity.project_id,
        "decision": entity.decision,
        "summary": entity.summary,
        "known_issues": _split(entity.known_issues),
        "remaining_risks": _split(entity.remaining_risks),
        "follow_up_title": entity.follow_up_title,
        "reviewer": entity.reviewer,
        "payload": json.loads(entity.payload_json),
        "created_at": isoformat(ensure_utc(entity.created_at)),
    }


def _spec_dict(entity: DemoGameSpecModel) -> dict[str, Any]:
    return {
        "spec_id": entity.spec_id,
        "project_id": entity.project_id,
        "codename": entity.codename,
        "title": entity.title,
        "genre": entity.genre,
        "godot_version": entity.godot_version,
        "summary": entity.summary,
        "core_loop": entity.core_loop,
        "scope": json.loads(entity.scope_json),
        "status": entity.status,
        "frozen_at": None if entity.frozen_at is None else isoformat(ensure_utc(entity.frozen_at)),
        "created_at": isoformat(ensure_utc(entity.created_at)),
        "updated_at": isoformat(ensure_utc(entity.updated_at)),
    }


class DemoGameService:
    def __init__(
        self,
        database: DatabaseService,
        *,
        clock: Callable[[], datetime] = utcnow,
        verification: Any | None = None,
        builds: Any | None = None,
        artifacts: Any | None = None,
        releases: Any | None = None,
    ) -> None:
        self._database = database
        self._clock = clock
        self._verification = verification
        self._builds = builds
        self._artifacts = artifacts
        self._releases = releases

    # ------------------------------------------------------------------ seed

    async def seed_platformer(self, project_id: str) -> dict[str, Any]:
        """写入 Platformer 规格基线；已存在时幂等返回。"""

        now = self._clock()
        async with self._database.session() as session, transaction(session):
            spec_repository = DemoSpecRepository(session)
            existing = await spec_repository.get_by_project(project_id)
            if existing is not None:
                return await self._assemble_spec(session, existing)

            spec = DemoGameSpecModel(
                spec_id=_new_id("demo_"),
                project_id=project_id,
                codename=SPEC_BASELINE["codename"],
                title=SPEC_BASELINE["title"],
                genre=SPEC_BASELINE["genre"],
                godot_version=SPEC_BASELINE["godot_version"],
                summary=SPEC_BASELINE["summary"],
                core_loop=SPEC_BASELINE["core_loop"],
                scope_json=json.dumps(SPEC_BASELINE["scope"], ensure_ascii=False),
                status=SPEC_DRAFT,
                frozen_at=None,
                created_at=now,
                updated_at=now,
            )
            await spec_repository.add(spec)

            requirements: list[DemoRequirementModel] = []
            for item in REQUIREMENTS:
                requirement = DemoRequirementModel(
                    demo_requirement_id=_new_id("dreq_"),
                    spec_id=spec.spec_id,
                    requirement_key=item["key"],
                    title=item["title"],
                    description=item["description"],
                    system=item["system"],
                    category="FUNCTIONAL",
                    priority=item["priority"],
                    status=REQUIREMENT_PLANNED,
                    source="USER_REQUIREMENT",
                )
                await DemoRequirementRepository(session).add(requirement)
                requirements.append(requirement)
                for criterion_key, description, method in item["criteria"]:
                    await DemoCriterionRepository(session).add(
                        DemoCriterionModel(
                            demo_criterion_id=_new_id("dcrt_"),
                            demo_requirement_id=requirement.demo_requirement_id,
                            criterion_key=criterion_key,
                            description=description,
                            verification_method=method,
                            required_evidence="runtime_trace|test_report",
                            status=CRITERION_PENDING,
                        )
                    )

            for system in _SYSTEM_ORDER:
                keys = [item["key"] for item in REQUIREMENTS if item["system"] == system]
                if not keys:
                    continue
                priorities = {item["priority"] for item in REQUIREMENTS if item["system"] == system}
                await DemoFeatureRepository(session).add(
                    DemoFeatureModel(
                        demo_feature_id=_new_id("dfeat_"),
                        spec_id=spec.spec_id,
                        feature_key=f"FEATURE-{system}",
                        name=SYSTEM_NAMES[system],
                        system=system,
                        priority="P0" if "P0" in priorities else "P1",
                        requirement_keys=_join(keys),
                        status="PLANNED",
                    )
                )

            for item in MECHANICS:
                await DemoMechanicRepository(session).add(
                    DemoMechanicModel(
                        demo_mechanic_id=_new_id("dmech_"),
                        spec_id=spec.spec_id,
                        mechanic_key=item["key"],
                        name=item["name"],
                        description=item["description"],
                        parameters_json=json.dumps(item["parameters"], ensure_ascii=False),
                        status="PLANNED",
                    )
                )

            for item in LEVELS:
                await DemoLevelRepository(session).add(
                    DemoLevelModel(
                        demo_level_id=_new_id("dlvl_"),
                        spec_id=spec.spec_id,
                        level_key=item["key"],
                        name=item["name"],
                        description=item["description"],
                        difficulty=item["difficulty"],
                        layout_json=json.dumps(item["layout"], ensure_ascii=False),
                        status="PLANNED",
                    )
                )

            for item in SCENARIOS:
                await DemoScenarioRepository(session).add(
                    DemoTestScenarioModel(
                        scenario_id=_new_id("dscn_"),
                        spec_id=spec.spec_id,
                        scenario_key=item["key"],
                        title=item["title"],
                        scenario_type=item["type"],
                        requirement_keys=_join(item["requirements"]),
                        steps_json=json.dumps(item["steps"], ensure_ascii=False),
                        expected_result=item["expected"],
                        status="PLANNED",
                    )
                )

            await session.flush()
            return await self._assemble_spec(session, spec)

    # ------------------------------------------------------------------- read

    async def get_spec(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            return await self._assemble_spec(session, spec)

    async def list_requirements(
        self,
        project_id: str,
        *,
        priority: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            rows = await DemoRequirementRepository(session).list_by_spec(
                spec.spec_id, priority=priority, system=system
            )
            criteria = await DemoCriterionRepository(session).list_by_spec(spec.spec_id)
            scenarios = await DemoScenarioRepository(session).list_by_spec(spec.spec_id)
        by_requirement: dict[str, list[DemoCriterionModel]] = {}
        for item in criteria:
            by_requirement.setdefault(item.demo_requirement_id, []).append(item)
        items = [
            _requirement_dict(
                row,
                sorted(
                    by_requirement.get(row.demo_requirement_id, []),
                    key=lambda criterion: criterion.criterion_key,
                ),
                [
                    scenario.scenario_key
                    for scenario in scenarios
                    if row.requirement_key in _split(scenario.requirement_keys)
                ],
            )
            for row in rows
        ]
        return {"items": items, "total": len(items)}

    async def list_features(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            rows = await DemoFeatureRepository(session).list_by_spec(spec.spec_id)
        items = [
            {
                "feature_key": row.feature_key,
                "name": row.name,
                "system": row.system,
                "priority": row.priority,
                "status": row.status,
                "requirement_keys": _split(row.requirement_keys),
            }
            for row in rows
        ]
        return {"items": items, "total": len(items)}

    async def list_mechanics(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            rows = await DemoMechanicRepository(session).list_by_spec(spec.spec_id)
        items = [
            {
                "mechanic_key": row.mechanic_key,
                "name": row.name,
                "description": row.description,
                "parameters": json.loads(row.parameters_json),
                "status": row.status,
            }
            for row in rows
        ]
        return {"items": items, "total": len(items)}

    async def list_levels(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            rows = await DemoLevelRepository(session).list_by_spec(spec.spec_id)
        items = [
            {
                "level_key": row.level_key,
                "name": row.name,
                "description": row.description,
                "difficulty": row.difficulty,
                "layout": json.loads(row.layout_json),
                "status": row.status,
            }
            for row in rows
        ]
        return {"items": items, "total": len(items)}

    async def list_scenarios(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            rows = await DemoScenarioRepository(session).list_by_spec(spec.spec_id)
        items = [
            {
                "scenario_key": row.scenario_key,
                "title": row.title,
                "scenario_type": row.scenario_type,
                "requirement_keys": _split(row.requirement_keys),
                "steps": json.loads(row.steps_json),
                "expected_result": row.expected_result,
                "status": row.status,
            }
            for row in rows
        ]
        return {"items": items, "total": len(items)}

    async def acceptance_summary(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            reports = await DemoAcceptanceReportRepository(session).list_by_spec(spec.spec_id)
            coverage = await self._coverage(session, spec.spec_id)
            spec_id, spec_status = spec.spec_id, spec.status
        return {
            "spec_id": spec_id,
            "spec_status": spec_status,
            "coverage": coverage,
            "latest": None if not reports else _report_dict(reports[0]),
            "history": [_report_dict(item) for item in reports],
        }

    # ----------------------------------------------------------------- update

    async def freeze_spec(self, project_id: str) -> dict[str, Any]:
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            spec = await self._require_spec(session, project_id)
            if spec.status == SPEC_FROZEN:
                return await self._assemble_spec(session, spec)
            spec.status = SPEC_FROZEN
            spec.frozen_at = now
            spec.updated_at = now
            await session.flush()
            return await self._assemble_spec(session, spec)

    async def set_criterion_status(
        self,
        project_id: str,
        requirement_key: str,
        criterion_key: str,
        status: str,
    ) -> dict[str, Any]:
        if status not in DEMO_CRITERION_STATUSES:
            raise ValidationFailed("验收条件状态非法", details={"status": status})
        async with self._database.session() as session, transaction(session):
            spec = await self._require_spec(session, project_id)
            requirement = await DemoRequirementRepository(session).get_by_key(
                spec.spec_id, requirement_key
            )
            if requirement is None:
                raise NotFoundError("需求不存在", details={"requirement_key": requirement_key})
            criteria = await DemoCriterionRepository(session).list_by_requirement(
                requirement.demo_requirement_id
            )
            target = next((item for item in criteria if item.criterion_key == criterion_key), None)
            if target is None:
                raise NotFoundError("验收条件不存在", details={"criterion_key": criterion_key})
            target.status = status
            if all(item.status in (CRITERION_MET, CRITERION_WAIVED) for item in criteria):
                requirement.status = REQUIREMENT_VERIFIED
            elif any(item.status == CRITERION_NOT_MET for item in criteria):
                requirement.status = REQUIREMENT_IMPLEMENTED
            elif any(item.status != CRITERION_PENDING for item in criteria):
                requirement.status = REQUIREMENT_IN_PROGRESS
            else:
                requirement.status = REQUIREMENT_PLANNED
            await session.flush()
            return _requirement_dict(requirement, criteria, [])

    async def set_scenario_status(
        self, project_id: str, scenario_key: str, status: str
    ) -> dict[str, Any]:
        if status not in DEMO_SCENARIO_STATUSES:
            raise ValidationFailed("测试场景状态非法", details={"status": status})
        async with self._database.session() as session, transaction(session):
            spec = await self._require_spec(session, project_id)
            repository = DemoScenarioRepository(session)
            scenario = await repository.get_by_key(spec.spec_id, scenario_key)
            if scenario is None:
                raise NotFoundError("测试场景不存在", details={"scenario_key": scenario_key})
            scenario.status = status
            await session.flush()
        return {
            "scenario_key": scenario.scenario_key,
            "status": scenario.status,
            "requirement_keys": _split(scenario.requirement_keys),
        }

    # -------------------------------------------------------------- acceptance

    async def review(
        self,
        project_id: str,
        *,
        decision: str,
        reviewer: str,
        summary: str,
        known_issues: Sequence[str] = (),
        remaining_risks: Sequence[str] = (),
        follow_up_title: str | None = None,
    ) -> dict[str, Any]:
        if decision not in ACCEPTANCE_DECISIONS:
            raise ValidationFailed("验收结论非法", details={"decision": decision})
        if decision == DECISION_REJECTED and not (follow_up_title or "").strip():
            raise ValidationFailed(
                "拒绝验收必须创建后续修复任务标题",
                details={"follow_up_title": follow_up_title},
            )
        now = self._clock()
        async with self._database.session() as session, transaction(session):
            spec = await self._require_spec(session, project_id)
            coverage = await self._coverage(session, spec.spec_id)
            report = DemoAcceptanceReportModel(
                report_id=_new_id("dacc_"),
                spec_id=spec.spec_id,
                project_id=project_id,
                decision=decision,
                summary=summary,
                known_issues=_join(known_issues),
                remaining_risks=_join(remaining_risks),
                follow_up_title=follow_up_title,
                reviewer=reviewer,
                payload_json=json.dumps(
                    {
                        "spec_status": spec.status,
                        "coverage": coverage,
                        "evidence": {
                            "requirements": "demo_game_requirements",
                            "criteria": "demo_game_acceptance_criteria",
                            "scenarios": "demo_game_test_scenarios",
                        },
                    },
                    ensure_ascii=False,
                ),
                created_at=now,
            )
            await DemoAcceptanceReportRepository(session).add(report)
            await session.flush()
            return _report_dict(report)

    # ----------------------------------------------------------------- report

    async def traceability(self, project_id: str) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            requirements = await DemoRequirementRepository(session).list_by_spec(spec.spec_id)
            features = await DemoFeatureRepository(session).list_by_spec(spec.spec_id)
            criteria = await DemoCriterionRepository(session).list_by_spec(spec.spec_id)
            scenarios = await DemoScenarioRepository(session).list_by_spec(spec.spec_id)
        rows: list[dict[str, Any]] = []
        for requirement in requirements:
            rows.append(
                {
                    "requirement_key": requirement.requirement_key,
                    "title": requirement.title,
                    "priority": requirement.priority,
                    "status": requirement.status,
                    "features": [
                        feature.feature_key
                        for feature in features
                        if requirement.requirement_key in _split(feature.requirement_keys)
                    ],
                    "criteria": [
                        item.criterion_key
                        for item in criteria
                        if item.demo_requirement_id == requirement.demo_requirement_id
                    ],
                    "scenarios": [
                        scenario.scenario_key
                        for scenario in scenarios
                        if requirement.requirement_key in _split(scenario.requirement_keys)
                    ],
                }
            )
        return rows

    async def system_report(self, project_id: str) -> dict[str, Any]:
        async with self._database.session() as session:
            spec = await self._require_spec(session, project_id)
            coverage = await self._coverage(session, spec.spec_id)
            reports = await DemoAcceptanceReportRepository(session).list_by_spec(spec.spec_id)
            spec_view = _spec_dict(spec)
        traceability = await self.traceability(project_id)
        report: dict[str, Any] = {
            "project_id": project_id,
            "spec": spec_view,
            "coverage": coverage,
            "traceability": traceability,
            "acceptance": None if not reports else _report_dict(reports[0]),
        }
        report["verification"] = await self._verification_summary(project_id)
        report["build"] = await self._build_summary(project_id)
        report["readiness"] = {
            "requirements_traced": all(
                row["criteria"] and row["scenarios"] for row in traceability
            ),
            "blocking_scenarios": coverage["scenarios"][SCENARIO_FAILED]
            + coverage["scenarios"][SCENARIO_BLOCKED],
            "criteria_not_met": coverage["criteria"]["NOT_MET"],
            "acceptance_decision": None if not reports else reports[0].decision,
        }
        return report

    # ---------------------------------------------------------------- helpers

    async def _require_spec(self, session: Any, project_id: str) -> DemoGameSpecModel:
        spec = await DemoSpecRepository(session).get_by_project(project_id)
        if spec is None:
            raise NotFoundError("Demo 规格不存在", details={"project_id": project_id})
        return spec

    async def _assemble_spec(self, session: Any, spec: DemoGameSpecModel) -> dict[str, Any]:
        return {
            "spec": _spec_dict(spec),
            "counts": await self._counts(session, spec.spec_id),
        }

    async def _counts(self, session: Any, spec_id: str) -> dict[str, int]:
        return {
            "requirements": len(await DemoRequirementRepository(session).list_by_spec(spec_id)),
            "mechanics": len(await DemoMechanicRepository(session).list_by_spec(spec_id)),
            "levels": len(await DemoLevelRepository(session).list_by_spec(spec_id)),
            "features": len(await DemoFeatureRepository(session).list_by_spec(spec_id)),
            "criteria": len(await DemoCriterionRepository(session).list_by_spec(spec_id)),
            "scenarios": len(await DemoScenarioRepository(session).list_by_spec(spec_id)),
        }

    async def _coverage(self, session: Any, spec_id: str) -> dict[str, Any]:
        requirements = await DemoRequirementRepository(session).list_by_spec(spec_id)
        criteria = await DemoCriterionRepository(session).list_by_spec(spec_id)
        scenarios = await DemoScenarioRepository(session).list_by_spec(spec_id)
        requirement_status: dict[str, int] = {}
        for item in requirements:
            requirement_status[item.status] = requirement_status.get(item.status, 0) + 1
        criterion_status = {
            CRITERION_PENDING: 0,
            CRITERION_MET: 0,
            CRITERION_NOT_MET: 0,
            CRITERION_WAIVED: 0,
        }
        for item in criteria:
            criterion_status[item.status] = criterion_status.get(item.status, 0) + 1
        scenario_status = {
            "PLANNED": 0,
            "PASSED": 0,
            SCENARIO_FAILED: 0,
            SCENARIO_BLOCKED: 0,
        }
        for item in scenarios:
            scenario_status[item.status] = scenario_status.get(item.status, 0) + 1
        total_criteria = len(criteria)
        met = criterion_status[CRITERION_MET] + criterion_status[CRITERION_WAIVED]
        return {
            "requirements": {"total": len(requirements), "by_status": requirement_status},
            "criteria": {"total": total_criteria, **criterion_status},
            "criteria_met_ratio": 0.0 if total_criteria == 0 else round(met / total_criteria, 4),
            "scenarios": {"total": len(scenarios), **scenario_status},
        }

    async def _verification_summary(self, project_id: str) -> dict[str, Any] | None:
        if self._verification is None:
            return None
        page = await self._verification.list_campaigns(project_id, limit=5)
        items = page.get("items", [])
        return {
            "total": page.get("total", len(items)),
            "recent": [
                {
                    "campaign_id": getattr(item, "campaign_id", None),
                    "campaign_type": getattr(item, "campaign_type", None),
                    "status": getattr(item, "status", None),
                }
                for item in items
            ],
        }

    async def _build_summary(self, project_id: str) -> dict[str, Any] | None:
        if self._builds is None:
            return None
        builds = await self._builds.list_builds(project_id, limit=1)
        summary: dict[str, Any] = {"builds": {"total": builds.get("total", 0)}}
        if self._artifacts is not None:
            artifacts = await self._artifacts.list_artifacts(project_id, limit=1)
            summary["artifacts"] = {"total": artifacts.get("total", 0)}
        if self._releases is not None:
            releases = await self._releases.list_releases(project_id, limit=5)
            summary["releases"] = {"total": releases.get("total", 0)}
        return summary
