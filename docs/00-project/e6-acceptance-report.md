# E6 验收报告：Agent Runtime

**阶段：** E6
**文档版本：** V1.0
**验收日期：** 2026-11-23
**迁移版本：** `000018`
**结论：** 通过（P0 范围全部完成；已知限制见第 6 节）

---

## 1. 交付范围

| 任务 | 内容 | 状态 | 主要实现 |
|---|---|---|---|
| T01–T02 | Agent 域模型与数据表 | 完成 | `modules/agent_runtime/models.py`、`000016` 迁移 |
| T03–T06 | Definition Registry、版本快照、Instance、生命周期与调度 | 完成 | `service.py`、`instance.py`、`lifecycle.py`、`scheduler.py`、`000017` 迁移 |
| T07–T11 | Execution Loop、Plan、Context、Model/Tool Binding | 完成 | `loop.py`、`planning.py`、`response_parser.py`、`context_binding.py`、`model_binding.py`、`tool_binding.py` |
| T12–T15 | 预算、Checkpoint、控制、恢复 | 完成 | `budget.py`、`checkpoint.py`、`control.py`、`recovery.py`、`000018` 迁移 |
| T16–T19 | 可观测性、API、管理页、Generic Agent | 完成 | `observability.py`、`generic.py`、`app/api/agents.py`、`app/schemas/agent_runtime.py`、管理页区块 |
| T20 | 集成 / 安全 / 恢复测试与验收 | 完成 | `test_e6_acceptance.py`、`test_e6_architecture.py` 等（见第 3 节） |

## 2. 架构边界

- Agent Runtime 只通过 Model Gateway 发起模型请求，只通过 Tool System 执行工具；
  不导入 Provider 适配器、HTTP 客户端或文件写入库。
- 同一 Run 不直接修改 Task/Workflow 状态；Task 的最终状态仍由 Task System 状态机推进。
- 实例绑定 Task/Attempt 与创建时的 Definition 版本快照；快照、工具白名单、权限上限
  与预算在执行期间不可变。
- 高风险工具沿用 E5 Tool System 审批；Agent 不持有审批开关。
- 所有跨项目访问按项目授权 + `client_id` 归属校验；运行记录不跨用户暴露。

## 3. 验收场景与证据

### 场景 A：定义、实例与生命周期

- Definition 创建/发布/版本不可变、DRAFT 可更新、乐观锁、失败输入不留下半成品；
  Instance 创建冻结配置快照、幂等复用、非法绑定与已取消 Attempt/Task 被拒绝；
  生命周期转换只允许合法路径并写事件。
- 证据：`tests/integration/test_e6_definition_registry.py`、
  `test_e6_instance_lifecycle.py`。

### 场景 B：Execution Loop

- 计划 → 工具 → 完成闭环；非结构化模型输出失败；R3 工具进入审批等待；
  迭代预算超限中止并写 `BUDGET_EXCEEDED`；工具执行记录由 Tool System 产生。
- 证据：`tests/integration/test_e6_agent_loop.py`、`test_e6_generic_agent.py`。

### 场景 C：控制、预算、Checkpoint 与恢复

- 暂停/恢复/取消；预算耗尽按 `PAUSE`/`STOP` 策略处理；Checkpoint 持久化与恢复校验
  （无效 Checkpoint、Session 失效、Task 已终态均拒绝恢复）；模型 UNKNOWN 不自动重试。
- 证据：`tests/integration/test_e6_runtime_control.py`（9 个场景）、
  `test_e6_acceptance.py::test_model_unknown_marks_unknown_without_retry`。

### 场景 D：API、可观测性与管理页

- Definition/Instance/Execution/Plan/Step/Event 查询，`start/pause/resume/stop`，
  聚合指标与单次执行 trace；所有输出统一脱敏；定义接口全局、实例与执行按项目授权。
- 证据：`tests/integration/test_e6_agent_api.py`（生命周期 + 越权 + 管理页）、
  `tests/unit/test_observability.py`。

### 场景 E：E2E 与边界

- Task → Attempt → Generic Agent → Context → Model Gateway → Plan → Tool → Checkpoint
  → 执行完成；完成后 Task 仍为 `READY`，必须先经 `QUEUED → RUNNING → REVIEW_PENDING`
  才可由用户验收为 `COMPLETED`，证明 Agent Runtime 未直接改变 Task 最终状态。
- 证据：`test_e6_acceptance.py::test_agent_completion_does_not_mutate_task_status`。

## 4. 安全要求核对

| 要求 | 结论 | 证据 |
|---|---|---|
| 未授权用户无法启动 Agent | 通过 | `test_e6_agent_api.py::test_agent_instance_requires_project_access`（403） |
| Agent 无法访问其他 Project | 通过 | 实例项目由 Task 决定；API 项目授权 + `client_id` 归属校验 |
| Agent 无法提高自身权限 | 通过 | Definition 校验未知工具/模型策略并按权限上限拒绝；实例快照不可变 |
| Agent 无法调用白名单之外的 Tool | 通过 | `test_e6_acceptance.py::test_tool_outside_whitelist_is_rejected_without_execution` |
| Agent 无法绕过 Approval | 通过 | `test_e6_agent_loop.py::test_loop_waits_for_approval_on_high_risk_tool` |
| Agent 无法直接调用 Provider SDK | 通过 | `tests/unit/test_e6_architecture.py` 禁止导入 Provider 适配器/HTTP 客户端 |
| Agent 无法直接操作项目文件 | 通过 | 架构守卫禁止文件写入库；项目操作统一经 Tool System |
| Agent 无法篡改 Task 状态 | 通过 | `test_agent_completion_does_not_mutate_task_status`；`accept` 从 `READY` 被拒绝 |
| Agent 无法篡改 Workflow 状态 | 通过 | 架构守卫禁止导入 `modules.workflow` |
| Agent 无法读取其他用户运行记录 | 通过 | API 实例/执行归属校验（`INSTANCE_OWNERSHIP_DENIED`） |
| 隐藏推理不会被持久化或展示 | 通过 | `test_hidden_reasoning_is_not_persisted`；`test_observability.py` 脱敏与截断 |

### 恢复场景覆盖

| 场景 | 结论 | 证据 |
|---|---|---|
| Backend / Worker 执行期间崩溃 | 通过（以 Checkpoint + 恢复协调器模拟） | `test_e6_runtime_control.py` |
| Model 请求超时 / 响应丢失 | 通过：转 UNKNOWN，不盲目重发 | `test_model_unknown_marks_unknown_without_retry` |
| Tool 执行超时 / Editor 断开 | 通过：由 Tool System 返回 UNKNOWN/失败，Agent 不重放副作用 | `test_e6_agent_loop.py`、E5 工具恢复 |
| Session Lease 失效 | 通过：恢复校验失败 → `AGENT_RECOVERY_REQUIRED` | `test_e6_runtime_control.py`、`control.py` |
| Resource Lock 过期 | 通过：复用 E5 Tool System 锁与恢复 | E5 锁测试 + 工具绑定 |
| SQLite 写入失败 | 通过（事务回滚，无半成品） | Definition 失败不留半成品测试；各服务统一 `transaction()` |
| Checkpoint 创建失败 | 通过：恢复校验失败进入人工恢复，不猜测继续 | `test_e6_runtime_control.py` |

## 5. 质量门禁

| 项目 | 结果 |
|---|---|
| 后端 pytest | 516 passed（unit + integration / contract） |
| 后端 ruff | 全部通过（line-length 100） |
| Alembic head | `000018` |
| 新增 E6 测试 | 定义/生命周期/Loop/控制恢复/API/Generic/可观测/验收/架构守卫 |

## 6. 已知限制

1. `Agent Result` 主动提交 Task System 与 Verification System 验证由上层编排/后续阶段完成；
   E6 负责执行与事件，不直接推进 Task 最终状态。
2. Backend/Worker 崩溃以恢复协调器与 Checkpoint 状态验证替代真实进程 kill。
3. SQLite 写入失败、磁盘故障未做故障注入测试。
4. 未建立独立的 9 个模块 contract 测试文件；接口稳定性由全链路集成测试覆盖。
5. 未进行高并发 Agent 压测；并发保护依赖状态机与唯一活动执行约束。
6. Generic Agent 仅在非 test 环境启动时自动确保存在。
7. 管理页仅提供监控与控制入口，Agent 定义/实例创建仍通过 API 完成。

## 7. 结论与后续

E6 P0 目标（T01–T20）均已落地并有自动化证据支撑。Agent Runtime 在权限、预算、上下文、
项目边界与审批约束下完成计划、模型调用、工具执行、Checkpoint 与恢复，并在 E2E 中证明
不会直接改变 Task 最终状态。可以进入后续 Multi-Agent（E7）阶段。
