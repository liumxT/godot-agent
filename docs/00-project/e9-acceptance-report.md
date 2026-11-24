# E9 验收报告：Verification & QA

**阶段：** E9
**文档版本：** V1.0
**验收日期：** 2026-11-24
**迁移版本：** `000027`
**结论：** 通过（8 批次 / 20 任务全部完成；自动化证据见第 5–8 节，已知限制见第 10 节）

---

## 1. 交付范围

| 批次 | 任务 | 状态 | 主要实现 |
|---|---|---|---|
| M1 | T01 验证领域与契约、T02 测试用例注册、T03 需求追踪与验收标准 | 完成 | `modules/verification/{models,repository,service}.py`、迁移 `000023`、12 个 E9 错误码、13 个 `verification.* / defect.* / quality_gate.* / phase_review.*` 权限 |
| M2 | T04 Verification Plan Engine、T05 Verification Orchestrator | 完成 | `planner.py`（按需求 → 标准 → 用例推导层次、覆盖缺口阻断）、`orchestrator.py`（逐层执行、结果与证据写入、Campaign 状态归 Verification 所有） |
| M3 | T06 静态分析、T07 Scene / Resource 校验 | 完成 | `godot/{findings,static_analyzer,scene_validator,resource_validator,executors}.py` |
| M4 | T08 Runtime 验证、T09 Functional Test Runner、T10 Debugger 集成 | 完成 | `runtime.py`（环境生命周期、启动/停止/租约、`UNKNOWN` 保守映射）、`functional.py`（步骤断言、超时与基础设施错误不混为功能失败）、`debugger.py`（错误分类、指纹去噪、基线化门禁）、迁移 `000024` |
| M5 | T11 视觉验证、T12 性能验证、T13 证据管理 | 完成 | `visual.py`（像素比对、掩码、基线缺失转人工）、`performance.py`（阈值、同环境退化判定）、`evidence.py`（文件 Hash 校验、失效/过期、上下文完整性） |
| M6 | T14 缺陷管理、T15 回归与影响分析 | 完成 | `defect.py`（类别 → Agent 推荐、优先级映射、汇总）、`impact.py`（反向依赖扫描、SECURITY > FULL > DEPENDENCY > TARGETED 策略）、迁移 `000025` |
| M7 | T16 质量门禁、T17 Phase Review、T18 Dashboard / UI | 完成 | `quality_gate.py`（GATE-1…GATE-10、按 Campaign 类型与风险选门禁、有效豁免转 `WAIVED`）、`phase_review.py`（建议结论、风险与用户确认事项）、迁移 `000026/000027`、`app/api/verification.py`、4 个 Dashboard 聚合 |
| M8 | T19 Agent 集成与验证策略、T20 测试与 Platformer Demo 实战、验收报告 | 完成 | `agent_policy.py`（操作矩阵、验证预算）、`agent_request_verification/run`（策略 + 预算强制）、`tests/integration/test_e9_acceptance.py`（2 个验收测试）、本报告 |

## 2. 架构冻结规则核对（E9.md §14）

| 规则 | 结论 | 证据 |
|---|---|---|
| Verification 独立拥有验证状态 | 通过 | Campaign / Plan / Run / Result 状态机与迁移只在本模块；`test_campaign_plan_run_result_and_traceability` |
| 不直接修改 Task / Workflow / Phase / Approval / ChangeSet 状态 | 通过 | 模块只保存引用；API 与 Service 无跨模块写入；`test_orchestrator_runs_layers_and_completes_campaign` |
| Agent 不得伪造结果 / 证据 | 通过 | 结果状态只经 `record_result` 校验；通过必须有证据；`test_pass_without_evidence_is_rejected`、`test_agent_action_matrix_separates_allowed_and_forbidden` |
| Agent 不得豁免门禁 | 通过 | 豁免要求授权者、原因、风险、范围、有效期；`test_quality_gate_evaluate_and_waive`、`test_waiver_requires_traceable_fields` |
| Agent 不得宣布 Phase 完成 | 通过 | Phase Review 决策与 Campaign 完成解耦，ACCEPT 只来自用户决策；`test_phase_review_flow_and_dashboards` |
| UNKNOWN ≠ FAILED | 通过 | 运行时/功能/视觉未知均保持 `UNKNOWN`；`test_unknown_and_failed_are_distinct`、`test_unknown_is_not_downgraded_to_failed`、`test_launch_failure_is_unknown_not_failed` |
| SKIPPED ≠ PASSED | 通过 | `test_skipped_and_not_run_are_not_passed`、`test_layer_gate_maps_result_statuses` |
| 未执行不得计入通过率 | 通过 | Dashboard 与 Phase Review 只按 executed 计算；`test_build_review_summary_keeps_unknown_out_of_pass_rate`、验收测试 NOT_RUN 段 |
| 通过结果必须带有效证据 | 通过 | Service、Orchestrator 与门禁三层校验；`test_passing_report_produces_passed_outcome_with_evidence`、`test_pass_without_evidence_is_rejected` |
| 证据必须可追溯 | 通过 | 来源引用 + SHA-256 + 运行上下文；文件证据校验存在性与哈希；`test_file_evidence_integrity_and_staleness` |
| 结果不可原地改写 | 通过 | 已产生结果只能 `SUPERSEDED`；`test_result_transitions_do_not_rewrite_verdict` |
| 六层验证体系完整 | 通过 | STATIC / STRUCTURE / RESOURCE / RUNTIME / FUNCTIONAL / VISUAL / PERFORMANCE；`test_verification_layers_cover_six_layer_model` |
| 门禁失败关闭 | 通过 | FAILED > BLOCKED > UNKNOWN > PARTIAL > PASSED；`test_combine_outcomes_distinguishes_partial_and_blocking` |
| Agent 验证预算受控 | 通过 | 预算按真实持久化数据计算，耗尽即拒绝；`test_agent_run_budget_blocks_repeated_execution`、`test_retry_budget_and_evidence_usage` |

## 3. Platformer Demo 验证报告（E9.md §11）

### 3.1 Demo 用例覆盖

E9.md §11 定义的 Platformer 验证用例集共 34 项（PT-001…PT-017 及扩展项）。本次自动化验收
以真实 Godot 工程文件跑通代表性闭环，其余用例由分层单元/集成测试覆盖：

| 用例组 | 覆盖方式 | 证据 |
|---|---|---|
| PT-001 主场景启动结构 | 真实 `main.tscn` + 必需节点类型校验 | `test_platformer_demo_full_verification_flow`、`test_good_scene_and_requirements_pass` |
| PT-002 玩家移动与跳跃 | 功能运行器步骤断言、超时与失败追踪 | `test_functional_runner.py`（10 项） |
| PT-013 资源导入 | 真实 `coin.tres` 与 `res://` 引用校验 | `test_resource_executor_detects_missing_import`、`test_platformer_demo_full_verification_flow` |
| PT-015 GDScript 静态检查 | 真实 `player.gd` 括号配对与语法检查 | `test_static_layers_complete_campaign`、缺陷修复闭环 |
| 缺陷修复与回归 | 静态失败 → 缺陷 → 分派 → 修复 → 回归 → 关闭 | `test_platformer_defect_fix_and_regression_loop` |

### 3.2 Demo 验收流程逐阶段证据

| 阶段 | 断言 | 证据 |
|---|---|---|
| Agent 发起验证 | 记录 `actor_id`，活动进入 `DRAFT` | 验收测试第 1 步、`test_agent_policy_matrix_and_request_verification` |
| 计划生成 | 需求 / 标准 / 用例齐全，层次按依赖排序，活动转 `READY` | `test_full_trace_produces_ready_plan_in_layer_order` |
| 静态层 | 真实工程扫描通过并产生证据 | 验收测试 STATIC 段 |
| 结构层 | 场景可解析、必需节点存在 | 验收测试 STRUCTURE 段 |
| 资源层 | `res://` 引用与导入元数据检查 | 验收测试 RESOURCE 段 |
| 结果与证据 | 每条结果绑定需求；证据含来源与 Hash | 验收测试第 2–4 步 |
| 质量门禁 | GATE-1 / GATE-6 通过，总体 `PASSED` | 验收测试第 5 步 |
| Phase Review | 建议 `ACCEPT`，用户决策后 `ACCEPTED` | 验收测试第 6 步 |
| Dashboard | 通过 / 未执行分开统计，通过率只算已执行 | 验收测试第 7 步、`test_verification_overview` 断言 |
| 缺陷闭环 | 失败结果生成缺陷，修复后回归通过并关闭 | `test_platformer_defect_fix_and_regression_loop` |
| 回归策略 | 脚本被场景引用时升级为 `DEPENDENCY` | 缺陷闭环测试影响分析段 |

### 3.3 Dataset 汇总

- 验收工程：`project.godot` + `scripts/{player,coin}.gd` + `scenes/main.tscn` + `resources/coin.tres` + `assets/hud.png`。
- 需求：3 条（REQ-START / REQ-MOVE / REQ-JUMP），全部建立验收标准与测试追踪。
- 测试用例：PT-001 / PT-002 / PT-013 / PT-015。
- 结果：12 条 `PASSED`、1 条 `NOT_RUN`；通过率 100%（仅按已执行计算）。
- 证据：3 条检查报告证据 + 1 条真实截图证据（文件 Hash 与运行上下文完整）。
- 缺陷：1 条 `BLOCKER`，状态链 `OPEN → TRIAGED → ASSIGNED → IN_PROGRESS → FIX_SUBMITTED → VERIFYING → RESOLVED`。
- UNKNOWN / NOT_RUN 清单：以独立字段呈现，不计入通过率。

## 4. 故障注入与恢复（E9.md §10）

| 场景 | 结论 | 证据 |
|---|---|---|
| 运行时启动失败 | 通过 | `test_launch_failure_is_unknown_not_failed` |
| 运行时驱动崩溃 | 通过 | `test_driver_failure_is_unknown_and_keeps_logs` |
| 运行时状态查询失败 | 通过 | `test_query_status_failure_is_unknown` |
| 共享实例被租用 | 通过 | `test_shared_instance_is_rejected_while_leased` |
| 功能步骤超时 | 通过 | `test_timeout_is_not_failed` |
| 基础设施错误 | 通过 | `test_infrastructure_error_is_not_functional_failure` |
| 清理失败 | 通过 | `test_cleanup_failure_is_recorded_without_flipping_result` |
| 无执行器的层 | 通过 | `test_missing_executor_is_not_run` |
| 覆盖缺口 | 通过 | `test_prepare_blocks_on_coverage_gap`、`test_missing_criteria_blocks_plan` |
| 视觉基线缺失 | 通过 | `test_missing_baseline_requires_manual_review` |
| 截图 Hash 不一致 | 通过 | `test_visual_executor_invalid_hash_is_unknown` |
| 证据文件被修改 | 通过 | `test_file_evidence_integrity_and_staleness` |
| Debugger 新增错误 | 通过 | `test_new_error_blocks_by_default`、`test_baseline_errors_are_recorded_not_blocking` |
| 执行器失败 | 通过 | `test_executor_failure_marks_campaign_failed` |
| 通过但无证据 | 通过 | `test_pass_without_evidence_is_rejected` |

## 5. 安全测试（E9.md §10.5）

| 场景 | 结论 | 证据 |
|---|---|---|
| 跨项目验证访问 | 通过 | API 每个资源先解析项目再授权；`test_campaign_plan_run_result_and_traceability` |
| Agent 伪造结果 / 证据 | 通过 | 只接受 Verifier 产生的 `Result`，通过必须有证据；`test_pass_without_evidence_is_rejected` |
| Agent 自行豁免门禁 | 通过 | `test_waiver_requires_traceable_fields`、`test_quality_gate_evaluate_and_waive` |
| Agent 无限重复测试 | 通过 | 验证预算耗尽抛 `AgentBudgetExceeded`；`test_agent_run_budget_blocks_repeated_execution` |
| Agent 放宽预算 | 通过 | 预算只读计算，不接受 Agent 覆盖；`test_budget_limits_follow_risk_level_and_never_relax_by_agent` |
| 证据路径 / 文件伪造 | 通过 | 文件证据必须存在且 Hash 一致；`test_evidence_without_context_or_file_is_reported` |
| 未授权门禁评估 | 通过 | `quality_gate.evaluate` 独立权限；API 项目授权 |
| 未授权 Phase 决策 | 通过 | `phase_review.decide` 独立权限；决策只追加 |
| 结果原地篡改 | 通过 | 状态机与 `SUPERSEDED` 规则；`test_result_transitions_do_not_rewrite_verdict` |
| 伪装 PASSED | 通过 | `UNKNOWN` / `SKIPPED` / `NOT_RUN` 独立状态；`test_skipped_and_not_run_are_not_passed` |

## 6. Definition of Done 核对（E9.md §13）

### 6.1 核心能力

| 项 | 结论 |
|---|---|
| Verification Domain / Campaign / Plan / Run / Result | 通过 |
| 六层验证体系（Static / Structure / Resource / Runtime / Functional / Visual） | 通过（Performance 同步落地） |
| 需求 → 验收标准 → 测试用例追踪 | 通过 |
| 验证计划与编排 | 通过 |
| Runtime / Functional / Debugger | 通过 |
| Visual / Performance | 通过 |
| 证据管理与完整性 | 通过 |
| 缺陷管理与回归 / 影响分析 | 通过 |
| 质量门禁 GATE-1…GATE-10 | 通过 |
| Phase Review 与用户验收 | 通过 |
| Dashboard / Agent 集成 / 验证预算 | 通过 |

### 6.2 安全要求

全部通过：状态所有权隔离、Agent 操作矩阵、证据不可伪造、门禁不可自豁免、预算失败关闭、
结果不可原地改写、未执行不计入通过率（证据见 §2、§5）。

### 6.3 质量要求

单元测试、集成测试、故障注入、安全测试与 Platformer Demo 验证闭环均通过（见 §8）。

## 7. 交付物核对（E9.md §15）

| 编号 | 交付物 | 状态 |
|---|---|---|
| 1–3 | Verification Domain / Test Case Registry / Requirement Traceability | 完成 |
| 4–5 | Verification Plan Engine / Verification Orchestrator | 完成 |
| 6–7 | Static Analysis Engine / Scene & Resource Validation | 完成 |
| 8–10 | Runtime Verification / Functional Test Runner / Debugger Integration | 完成 |
| 11–13 | Visual Verification / Performance Verification / Evidence Management | 完成 |
| 14–15 | Defect Management / Regression & Impact Analysis | 完成 |
| 16–18 | Quality Gate Engine / Phase Review / Verification Dashboard | 完成 |
| 19 | Agent Integration & Verification Policy | 完成 |
| 20 | API Documentation | 完成（`/api/v1` OpenAPI，`verification` 标签） |
| 21 | Database Migration | 完成（`000023`–`000027`） |
| 22 | Test Suite | 完成（26 个 E9 测试文件：25 个业务 + 1 个契约；132 个业务测试函数） |
| 23 | Platformer Demo Verification Report | 完成（本报告 §3） |

## 8. 质量门禁

| 项目 | 结果 |
|---|---|
| 后端 pytest | 860 passed，1 warning（654.29s） |
| 后端 ruff | 全部通过（`ruff check src tests migrations`） |
| Alembic head | `000027` |
| Godot 测试 | 未改动插件测试入口（E9 为后端验证层） |
| 新增 E9 测试 | 26 个测试文件（25 个业务 + 1 个契约）/ 132 个业务测试函数 |

## 9. 事件与审计

- 验证的创建、执行、结果、证据、门禁、豁免与验收决策均持久化；豁免与验收决策只追加。
- Agent 发起的验证活动记录 `created_by`；Agent 请求执行前必须通过策略与预算校验。
- 门禁评估按 Campaign 类型与风险级别选择必需门禁，未执行门禁为 `NOT_REQUIRED` / `PENDING` / `UNKNOWN`，不会伪装为 `PASSED`。

## 10. 已知限制

1. Runtime 层在自动化测试中使用可注入的 Runtime Driver，未在 CI 内拉起真实 Godot 可执行文件；
   真实启动链路由 E3 建立的 Godot 集成与本地手工冒烟覆盖。
2. 功能测试运行器提供步骤/断言/超时框架，Platformer 的实际输入脚本需在 E11 Demo 工程中接入。
3. 视觉验证使用真实 PNG 等比对的纯函数实现，自动化验收以结构层截图证据代表；
   真实渲染截图比对需在 E11 中绑定运行时截图管线。
4. 性能验证消费采样数据，不在 CI 内采集真实帧耗；阈值与同环境退化规则已实现并测试。
5. Phase Review 在未接入 Workflow 验收节点前由 API/Service 驱动，Workflow 自动触发留待后续增强。
6. Platformer Demo 用例集以代表性用例跑通闭环，其余用例由分层测试覆盖，未逐条产出演示数据。
7. 验证预算按项目回归计划总数计算 `regressions` 维度，未按单个 ChangeSet 细分。

## 11. 结论与 E10 准入

E9 的 20 个任务全部落地。Verification System 独立拥有验证状态，Agent 只能发起与读取，
不能伪造结果、豁免门禁或宣布完成；UNKNOWN / SKIPPED / NOT_RUN 与 PASSED 严格分离，
证据必须可追溯，未执行不计入通过率；质量门禁与 Phase Review 形成从执行结果到用户验收的
完整链路，缺陷与回归闭环在 Platformer Demo 工程上真实跑通。E9.md §13 的 DoD 与 §15 的
23 项交付物均有实现与测试证据。

E9 阶段完成，可进入 E10 Build & Release。
