"""E11 Platformer Demo 模型（T01 / T02）。

E11 只补充 Demo 项目专用的需求、设计、验收数据，不建立第二套
Task / Workflow / Agent / Approval / Verification / Build 状态管理。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base

SPEC_DRAFT = "DRAFT"
SPEC_FROZEN = "FROZEN"
SPEC_STATUSES = frozenset({SPEC_DRAFT, SPEC_FROZEN})

REQUIREMENT_PLANNED = "PLANNED"
REQUIREMENT_IN_PROGRESS = "IN_PROGRESS"
REQUIREMENT_IMPLEMENTED = "IMPLEMENTED"
REQUIREMENT_VERIFIED = "VERIFIED"
DEMO_REQUIREMENT_STATUSES = frozenset(
    {REQUIREMENT_PLANNED, REQUIREMENT_IN_PROGRESS, REQUIREMENT_IMPLEMENTED, REQUIREMENT_VERIFIED}
)

CRITERION_PENDING = "PENDING"
CRITERION_MET = "MET"
CRITERION_NOT_MET = "NOT_MET"
CRITERION_WAIVED = "WAIVED"
DEMO_CRITERION_STATUSES = frozenset(
    {CRITERION_PENDING, CRITERION_MET, CRITERION_NOT_MET, CRITERION_WAIVED}
)

DECISION_ACCEPTED = "ACCEPTED"
DECISION_ACCEPTED_WITH_NOTES = "ACCEPTED_WITH_NOTES"
DECISION_REJECTED = "REJECTED"
ACCEPTANCE_DECISIONS = frozenset(
    {DECISION_ACCEPTED, DECISION_ACCEPTED_WITH_NOTES, DECISION_REJECTED}
)

SCENARIO_PLANNED = "PLANNED"
SCENARIO_PASSED = "PASSED"
SCENARIO_FAILED = "FAILED"
SCENARIO_BLOCKED = "BLOCKED"
DEMO_SCENARIO_STATUSES = frozenset(
    {SCENARIO_PLANNED, SCENARIO_PASSED, SCENARIO_FAILED, SCENARIO_BLOCKED}
)


class DemoGameSpecModel(Base):
    """Demo 项目规格基线：需求与设计冻结后不可随意改写。"""

    __tablename__ = "demo_game_specs"

    spec_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    codename: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    genre: Mapped[str] = mapped_column(String(64), nullable=False)
    godot_version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    core_loop: Mapped[str] = mapped_column(Text, nullable=False)
    scope_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("project_id", name="uq_demo_spec_project"),)


class DemoRequirementModel(Base):
    """Demo 需求注册表：每条需求拥有唯一 ID 与优先级。"""

    __tablename__ = "demo_game_requirements"

    demo_requirement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("demo_game_specs.spec_id", ondelete="CASCADE"), nullable=False
    )
    requirement_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    system: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("spec_id", "requirement_key", name="uq_demo_requirement_key"),
    )


class DemoMechanicModel(Base):
    """玩法机制定义：参数必须可配置且可追踪。"""

    __tablename__ = "demo_game_mechanics"

    demo_mechanic_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("demo_game_specs.spec_id", ondelete="CASCADE"), nullable=False
    )
    mechanic_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (UniqueConstraint("spec_id", "mechanic_key", name="uq_demo_mechanic_key"),)


class DemoLevelModel(Base):
    """关卡设计：布局与难度以结构化数据保存。"""

    __tablename__ = "demo_game_levels"

    demo_level_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("demo_game_specs.spec_id", ondelete="CASCADE"), nullable=False
    )
    level_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    layout_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (UniqueConstraint("spec_id", "level_key", name="uq_demo_level_key"),)


class DemoFeatureModel(Base):
    """功能清单：功能与需求的关联用于反向追踪。"""

    __tablename__ = "demo_game_features"

    demo_feature_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("demo_game_specs.spec_id", ondelete="CASCADE"), nullable=False
    )
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    system: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    requirement_keys: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (UniqueConstraint("spec_id", "feature_key", name="uq_demo_feature_key"),)


class DemoCriterionModel(Base):
    """Demo 验收条件：必须可转化为 E9 测试用例。"""

    __tablename__ = "demo_game_acceptance_criteria"

    demo_criterion_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    demo_requirement_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("demo_game_requirements.demo_requirement_id", ondelete="CASCADE"),
        nullable=False,
    )
    criterion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    verification_method: Mapped[str] = mapped_column(String(64), nullable=False)
    required_evidence: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        UniqueConstraint("demo_requirement_id", "criterion_key", name="uq_demo_criterion_key"),
    )


class DemoTestScenarioModel(Base):
    """测试场景：需求 → 场景的追踪，供 E9 测试计划引用。"""

    __tablename__ = "demo_game_test_scenarios"

    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("demo_game_specs.spec_id", ondelete="CASCADE"), nullable=False
    )
    scenario_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requirement_keys: Mapped[str] = mapped_column(Text, nullable=False)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (UniqueConstraint("spec_id", "scenario_key", name="uq_demo_scenario_key"),)


class DemoAcceptanceReportModel(Base):
    """用户验收记录：ACCEPTED / ACCEPTED_WITH_NOTES / REJECTED。"""

    __tablename__ = "demo_game_acceptance_reports"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("demo_game_specs.spec_id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    known_issues: Mapped[str] = mapped_column(Text, nullable=False)
    remaining_risks: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
