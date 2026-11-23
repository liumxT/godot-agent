# E7 验收报告：Multi-Agent & Game Development

**阶段：** E7
**文档版本：** V1.0
**验收日期：** 2026-11-23
**迁移版本：** `000021`
**结论：** 通过（22 个任务全部完成；已知限制见第 7 节）

---

## 1. 交付范围

| 批次 | 任务 | 状态 | 主要实现 |
|---|---|---|---|
| M1 | T01 领域模型与契约、T02 Capability Registry | 完成 | `modules/multi_agent/{models,repository,service,capabilities}.py`、`000019` 迁移 |
| M2 | T03 Orchestrator、T04 Team Manager、T05 Task Decomposition、T06 Assignment | 完成 | `decomposition.py`、`orchestrator.py` |
| M3 | T07 Handoff、T08 Lead Agent、T09 Context、T12 Communication | 完成 | `context.py`、`communication.py`、`lead.py` |
| M4 | T10 Parallel、T11 Resource、T17 Conflict Resolution | 完成 | `resources.py`、`conflicts.py`、`000020` 迁移 |
| M5 | T13 Specialized Definitions、T14 Workflows、T15 Result Integration、T16 Review | 完成 | `specialized.py`、`workflows.py`、`review.py`、`lead.py` 扩展 |
| M6 | T18 Team Budget、T19 Observability、T20 API、T21 UI、T22 Platformer Demo | 完成 | `budget.py`、`observability.py`、`demo.py`、`app/api/multi_agent.py`、`app/schemas/multi_agent.py`、管理页、`000021` 迁移 |
| M7 | 安全 / 并发 / 恢复 / E2E 测试与验收 | 完成 | `tests/integration/test_e7_e2e.py`（4 个测试）、本报告 |

专业 Agent Definition 共 38 个（15 P0 / 18 P1 / 5 P2），其中 6 个 P0 标记可执行，
超过"至少 5 个 P0 实际执行能力"的交付要求。

## 2. 架构边界

- **Orchestrator 是唯一 Assignment 创建入口**：`AssignmentService.create` 校验
  `authorized_by=ORCHESTRATOR`；Orchestrator 自身只接受 `TASK_SYSTEM` 授权。
- **状态所有权不变**：Task/Attempt 由 Task System 拥有，Workflow/Phase/Node 由 Workflow
  Engine 拥有，Agent Instance/Execution 由 Agent Runtime 拥有；Multi-Agent 模块只保存引用。
- **权限与能力分离**：Capability 只表示能力；实际权限由 E5 Permission System 与 Tool
  System 判定，Handoff 目标 Agent 必须重新满足能力、工具与权限上限。
- **Lead Agent 默认只读**：写权限（ChangeSet 等）必须显式授予，Lead 不自动批准。
- **项目操作仍经 Tool System**：多 Agent 不直接写项目文件，写入受 Resource Lock 与
  Fencing Token 约束。
- **Verification 独立**：评审（Review）标记 `requires_verification=True`，不替代
  Verification System；集成提交验证必须携带 `verification_reference`。

## 3. 验收场景与证据

### 场景 A：编排、分解与分配（M1–M2）

- Capability Registry 幂等登记 32 个内置能力；硬性过滤（启用状态、能力、权限上限、Tool、
  Model 能力、项目访问、预算）与软性排序（覆盖度、成功率、负载、成本）分离。
- Task Decomposition 校验唯一 key、依赖存在、无环、验收覆盖；1 个子任务判定单 Agent。
- Team 状态机 `CREATED → INITIALIZING → READY`，Assignment 无依赖 `READY`、有依赖
  `BLOCKED`；claim 使用条件更新防并发抢占。
- 证据：`tests/unit/test_e7_capability_matching.py`、`test_e7_decomposition.py`、
  `tests/integration/test_e7_multi_agent_domain.py`、`test_e7_orchestrator.py`。

### 场景 B：Handoff、Context 与通信（M3）

- Handoff Payload 结构化且拒绝未知字段与隐藏推理；执行时校验源 Assignment/Team 未结束、
  目标 Definition 已发布、能力/工具/权限上限与 Context 归属，成功后创建目标 Assignment。
- Shared Context 引用+哈希版本化，`PRIVATE` 不可共享，重复发布幂等，替换需
  `expected_version`；过期支持 ACCEPT/REFRESH/PAUSE/REANALYZE。
- 消息绑定 Team 与收发者，发送者结束拒绝发送，重复消费幂等。
- 证据：`tests/unit/test_e7_handoff_payload.py`、`tests/integration/test_e7_handoff_context.py`。

### 场景 C：并行、资源锁与冲突（M4）

- 同一资源同一时刻最多一个写者；读锁并行但排斥写者；Fencing Token 拒绝旧令牌写入或释放。
- 并行管理器按依赖、优先级与资源集合生成受 `max_parallel` 限制的批次；失败只阻塞依赖者。
- 冲突检测暂停 RUNNING→WAITING、READY→BLOCKED；接口/Schema 冲突必须 USER_DECISION；
  策略白名单不含 LAST_WRITE_WINS。
- 证据：`tests/unit/test_e7_resource_policy.py`、`tests/integration/test_e7_handoff_context.py`
  （读锁并行、写锁互斥与 Fencing、并行批次、依赖就绪、失败隔离、冲突升级）。

### 场景 D：专业 Agent、工作流、集成与评审（M5）

- 38 个角色 Definition 具备身份、职责、能力、工具、权限上限、输入/输出契约与验收标准；
  启动自检校验能力/权限/验收完整性。
- 5 条游戏工作流模板（概念设计、核心玩法、UI、TileMap 关卡、代码质量），实例化后处于
  READY，Phase/Node 状态由 Workflow Engine 独占。
- 结果集成要求全部 Assignment 完成且有输出，重复 `output_reference` 视为接口冲突；
  评审要求审查人独立并携带证据。
- 证据：`tests/unit/test_e7_specialized_workflows.py`、
  `tests/integration/test_e7_m5_assets_integration.py`。

### 场景 E：预算、可观测性、API/UI 与 Demo（M6）

- Team Budget 分配严格限定维度、非负、已知项与合法超限策略；重新分配需原因与版本；
  超限持久化 `EXHAUSTED` 并失败关闭。
- 可观测性提供 Team/Assignment Dashboard、依赖图、事件时间线与项目总览，全部只读。
- API 覆盖 Team/Assignment/Handoff/Capability/Conflict，全部认证 + 项目授权；
  重复活动 Team 被拒绝；未完成 Assignment 结果返回 409。
- Platformer Demo 固化 5 个子任务与依赖。
- 证据：`tests/unit/test_e7_demo_plan.py`、`tests/integration/test_e7_m6_budget.py`、
  `test_e7_m6_api.py`。

### 场景 F：E2E 全流程（M7，E7.md §29.5 十二步）

| 步骤 | 断言 |
|---|---|
| 1. 创建 Task | 注册项目、创建 Task 与 Attempt |
| 2. Orchestrator 分解任务 | 4 个子任务、验收覆盖校验通过 |
| 3. 创建 Team | Team 进入 `READY` |
| 4. 匹配专业 Agent | 按能力选择已发布 Definition |
| 5. 创建 Assignment | `design`/`level` 为 `READY`，`player`/`integration` 为 `BLOCKED` |
| 6. 并行执行独立子任务 | `asyncio.gather` 同时 claim 后均为 `RUNNING` |
| 7. 完成 Handoff | Orchestrator 执行后 Handoff `COMPLETED`、目标 Assignment `READY` |
| 8. Lead Agent 整合结果 | `IntegrationService.prepare` 收集 5 个来源 |
| 9. 检查冲突 | 同一 Scene 写锁第二次获取抛 `AgentResourceConflict`；报告并 `RESOLVED` |
| 10. 执行项目集成 | `APPLYING → VERIFYING → COMPLETED` |
| 11. 提交 Verification | 携带 `verification://e2e/run-1` |
| 12. Task System 接收 | `READY → QUEUED → RUNNING → REVIEW_PENDING` |

- Context 版本化：发布后 `context_version == 1`。
- 可观测性：Team Dashboard `COMPLETED` Assignment 计数为 5。
- 证据：`tests/integration/test_e7_e2e.py::test_platformer_multi_agent_end_to_end`。

## 4. 安全要求核对（E7.md §28）

| 要求 | 结论 | 证据 |
|---|---|---|
| Agent 无法绕过 Orchestrator 创建 Assignment | 通过 | `test_assignment_requires_orchestrator_authorization` |
| Agent 无法自行创建其他 Agent Instance | 通过 | Multi-Agent 模块无 Instance 创建路径，Instance 归 Agent Runtime |
| Lead Agent 无法自动获得写权限 | 通过 | `test_lead_permissions_are_read_only_by_default` |
| Agent 不能把自己的权限转交给另一个 Agent | 通过 | `execute_handoff` 校验目标能力/工具/权限上限；`test_handoff_rejects_target_without_capability` |
| Handoff 后目标 Agent 必须重新授权 | 通过 | 目标 Assignment 以 `READY` 创建，需重新 claim；E2E Handoff 步骤 |
| Agent 不能访问其他 Project | 通过 | API 项目授权 + 403 测试；Context/Assignment 按 Team 校验 |
| Agent 不能修改其他 Assignment 的状态 | 通过 | Assignment 状态只经领域服务；Team 作用域校验 |
| Agent 不能绕过 Resource Lock | 通过 | 写锁互斥 + 冲突报告；E2E 资源冲突步骤 |
| 旧 Fencing Token 无法执行写入 | 通过 | `test_resource_write_locks_are_exclusive_and_fenced` |
| Agent Message 不能直接触发越权工具调用 | 通过 | 消息为持久化记录，工具执行仍经 Agent Runtime + Tool System |
| 未授权 Agent 无法获取 Team Context | 通过 | Context 团队归属校验 + `PRIVATE` 不可共享 |
| Team Budget 不得突破 Task Budget | 通过 | `test_budget_must_stay_within_task_and_orchestrator` |
| Assignment 不能改变原 Task 的验收标准 | 通过 | 验收标准来自分解结果，Assignment 作用域必须匹配 Team |
| Lead Agent 不能自动批准 ChangeSet | 通过 | Lead 默认只读，ChangeSet 审批归 Approval System |
| 未验证结果不能被标记为已验收 | 通过 | 集成提交验证需 `verification_reference`；Review `requires_verification=True` |

## 5. 可靠性验收

| 场景 | 结论 | 证据 |
|---|---|---|
| Orchestrator 崩溃后可以恢复 Team | 通过（同库重启后 Team/Assignment 可读且状态保留） | `test_team_recovers_after_restart_and_rejects_duplicates` |
| Assignment 重复消费不会产生重复执行 | 通过（重复编排 `TEAM_ALREADY_EXISTS`；重复 claim 被拒） | 同上 |
| Handoff 中断可以恢复 | 通过（源 Assignment 取消 → Handoff `FAILED`，不产生目标 Assignment） | `test_handoff_is_not_executed_after_source_cancelled` |
| 并行执行不会发生未授权写入 | 通过（写锁互斥、Fencing Token、项目授权） | M4 资源测试 + E2E |
| 资源冲突不会被静默覆盖 | 通过（策略白名单不含 LAST_WRITE_WINS） | `test_last_write_wins_is_not_a_resolution_strategy` |
| Team Budget 不会突破 Task Budget | 通过（分配即校验 Task 预算） | `test_e7_m6_budget.py` |
| Agent 失败不会破坏无关 Assignment | 通过（失败只阻塞依赖者） | `test_failure_isolation_blocks_only_dependents` |

## 6. 质量门禁

| 项目 | 结果 |
|---|---|
| 后端 pytest | 591 passed（unit + integration 549 / contract 42） |
| 后端 ruff | 全部通过（line-length 100） |
| Alembic head | `000021` |
| Godot 测试 | 68 / 68 passed（headless 编辑器入口，E7 未改动插件侧） |
| 新增 E7 测试 | 75 个测试函数（13 个文件），覆盖单元、集成、E2E、安全、恢复 |

E2E 实战记录（Platformer Demo）：4 个子任务 + 1 个 Handoff 目标 Assignment 共 5 个
Assignment 全部 `COMPLETED`，经历资源写冲突、冲突解决、Context 发布、Handoff、
独立评审与集成验证，最终 Task 进入 `REVIEW_PENDING`。

## 7. 已知限制

1. 多 Agent 并发以单进程 asyncio 模拟，未做多进程或多后端压测；写入依赖资源锁与 SQLite
   事务串行化。
2. Attempt 失效时运行中多 Agent 的联动回收未做专项测试；编排入口会拒绝不可运行 Attempt，
   运行中隔离依赖 Agent Runtime（E6）。
3. 资源锁覆盖到资源键粒度（文件/Scene/Project Settings 等统一建模），未实现文件内
   行级或节点级细粒度锁。
4. Agent 自动执行与真实 Godot 工具调用由 Agent Runtime/E5 Tool System 承担；E7 E2E 以
   领域驱动脚本模拟执行并验证状态契约，未做真实模型驱动的多 Agent 自动跑通。
5. 管理界面为浏览器单页，未提供 Godot 编辑器 Dock。
6. Team Budget 成本估算依赖 E5 价格版本；缺失价格时记 `UNAVAILABLE`，不阻断但无法精确核算。

## 8. E8 准入材料

E7 向 E8（Asset Pipeline）提供可复用的协作基础设施：

- Orchestrator 与 Capability Registry（资产类 Agent 可通过注册新能力接入）。
- Agent Team / Assignment / Handoff / Lead / Context / Resource / Result Integration。
- 38 个专业 Agent Definition（后续可按 E8 需求扩展资产生产、处理、导入与质量验证能力）。

E8 不应重新实现 Agent 协作基础设施，而应将资产流水线作为新的专业能力接入现有体系。

## 9. 结论与后续

E7 的 22 个任务全部落地，Orchestrator 作为唯一 Assignment 入口稳定运行，Team 可创建、
运行、交接与整合；多 Agent 在资源锁、上下文版本化、预算与权限约束下安全并行；E2E 证明
Task 最终状态仍由 Task System 合法路径推进。E7.md §31 功能 / 架构 / 可靠性验收项均有
自动化证据。E7 阶段完成，可进入 E8 Asset Pipeline。
