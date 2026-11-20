# E4 验收报告

- **阶段：** E4 Project & Workflow Systems
- **日期：** 2026-11-20
- **任务计划：** [E4 开发计划](../../完整开发计划细分/E4.md)
- **结论：** ✅ 通过验收，可进入 E5

## 1. 范围与批次

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E4-M1 | T01 Project Domain、T02 Project Registry、T03 Project Lifecycle、T04 Project Configuration、T05 Project Access Integration | ✅ |
| E4-M2 | T06 Task System、T07 Task State Machine、T08 Attempt Manager、T09 Task Dependency、T10 Task Checkpoint、T11 Task Event Log | ✅ |
| E4-M3 | T12 Workflow Definition、T13 Workflow Instance、T14 Workflow Node Engine、T15 Phase Manager、T16 Workflow Scheduler、T17 Workflow Recovery | ✅ |
| E4-M4 | T18 Requirement Tracking、T19 ChangeSet Manager、T20 Approval System、T21 User Acceptance | ✅ |
| E4-M5 | T22 Project/Task/Workflow API、T23 Management UI | ✅ |
| E4-M6 | T24 测试、全量验证与验收报告 | ✅ |

E4 只负责项目、任务、工作流与治理状态；Agent 执行、AI 调用、工具执行、资源生成、QA、Build/Release 保留给 E5–E10。

## 2. 交付物核对

| 编号 | 交付物 | 位置 | 状态 |
| --- | --- | --- | --- |
| E4-D01 | Project Domain Model | `apps/backend/src/modules/project_registry/models.py`、迁移 `000010` | ✅ |
| E4-D02 | Project Registry | `modules/project_registry/service.py`（`ProjectRegistryService`） | ✅ |
| E4-D03 | Project Lifecycle | `ProjectLifecycleService`，含归档阻塞检查 | ✅ |
| E4-D04 | Project Configuration | `ProjectConfigurationService`，版本历史 + 乐观锁 | ✅ |
| E4-D05 | Project Access Integration | 复用 E2 `ProjectAccessService`、`app/api/projects_v1.py` | ✅ |
| E4-D06 | Task System | `modules/task/`（models/repository/service） | ✅ |
| E4-D07 | Task State Machine | `TASK_TRANSITIONS`、`TaskService.transition` | ✅ |
| E4-D08 | Attempt Manager | `AttemptService`、`task_attempts` | ✅ |
| E4-D09 | Task Dependency | `DependencyService`，含循环检测与完成解除 | ✅ |
| E4-D10 | Task Checkpoint | `CheckpointService`，SHA-256 校验、最多保留 100 条 | ✅ |
| E4-D11 | Task Event Log | `TaskEventWriter`，全局递增序号 + Outbox | ✅ |
| E4-D12 | Workflow Definition | `WorkflowDefinitionService`、`parse_definition` | ✅ |
| E4-D13 | Workflow Instance | `WorkflowInstanceService`，固定定义版本 | ✅ |
| E4-D14 | Workflow Node Engine | `WorkflowNodeService`（start/complete/fail/skip/advance） | ✅ |
| E4-D15 | Phase Manager | `WorkflowPhaseService`（review / accept / request-revision） | ✅ |
| E4-D16 | Workflow Scheduler | `WorkflowScheduler.tick` | ✅ |
| E4-D17 | Workflow Recovery | `WorkflowRecoveryService.recover`，启动时自动执行 | ✅ |
| E4-D18 | Requirement Tracking | `modules/requirement/`、验收标准与追踪 | ✅ |
| E4-D19 | ChangeSet Manager | `modules/changeset/`，规范化清单 + 内容哈希 | ✅ |
| E4-D20 | Approval System | `modules/approval/`，目标哈希绑定、过期与幂等 | ✅ |
| E4-D21 | User Acceptance System | `WorkflowPhaseService.accept_phase` + `TaskService.accept` | ✅ |
| E4-D22 | Project/Task/Workflow API | `app/api/{projects_v1,tasks,workflows,changesets,approvals}.py` | ✅ |
| E4-D23 | Project Management UI | `app/api/management_ui.py`（`/api/v1/manage`） | ✅ |
| E4-D24 | Approval UI | 同一管理页的“待处理审批”区域 | ✅ |
| E4-D25 | E4 Test Suite | `tests/{unit,integration}/test_e4_*.py` | ✅ |
| E4-D26 | E4 Acceptance Report | 本文件 | ✅ |

## 3. 验证证据

| 项 | 结果 |
| --- | --- |
| 后端单元 + 集成测试 | 377 passed |
| 后端契约测试 | 42 passed |
| 后端合计 | **419 passed**（`pytest -q`） |
| 静态检查 | `ruff check src tests migrations` / `ruff format --check` 全通过 |
| 全量检查 | `check_all.py` **8 阶段全 PASS**：仓库结构、敏感文件、代码格式、静态检查、Contracts Schema、Backend 测试、Godot Plugin、Godot Bridge Tests（Godot 68/68） |
| 数据库迁移 | head 为 `000010`；一次升级、重复幂等、checksum 篡改检测均通过 |
| 后端回归 | E1–E3 既有测试全部保持通过，无接口破坏 |

E4 新增测试：

| 文件 | 覆盖 |
| --- | --- |
| `tests/unit/test_e4_domain.py` | 清单规范化/去重/路径穿越、哈希顺序无关、定义引用校验、检查点校验和、Task/Attempt/Workflow 全状态迁移矩阵（所有合法与非法组合） |
| `tests/integration/test_e4_services.py` | 项目注册/配置版本/生命周期/归档阻塞/并发冲突、Task/Attempt/Event、依赖循环与阻塞解除、Workflow 节点与阶段验收、ChangeSet 审批/哈希绑定/跨 ChangeSet 审批拒绝、审批过期、恢复、定义版本固定 |
| `tests/integration/test_e4_api_e2e.py` | admin 全链路 HTTP E2E、未授权客户端 403、版本冲突 409、伪造状态 409、404 |
| `tests/integration/test_e4_management_ui.py` | 管理页可加载且不含凭证、数据接口必须认证 |
| `tests/unit/test_policy.py` | E4 viewer/editor/owner 的读写与审批权限矩阵 |

执行命令：

```powershell
# 后端
cd apps/backend
.\.venv\Scripts\python.exe -m ruff check src tests migrations
.\.venv\Scripts\python.exe -m ruff format --check src tests migrations
.\.venv\Scripts\python.exe -m pytest -q

# Godot 侧（E3 回归）
& $env:GODOT_BIN --headless --path apps/godot-plugin --editor --quit-after 1200 -- --e3-test

# 全量
$env:GODOT_BIN='D:\应用程序\godot\Godot_v4.5.1-stable_win64.exe\Godot_v4.5.1-stable_win64_console.exe'
cd apps/backend
.\.venv\Scripts\python.exe ..\..\scripts\testing\check_all.py
```

## 4. 安全验证

| 检查 | 证据 |
| --- | --- |
| 越权创建 Task / 归档项目 / 修改项目 | `test_unauthorized_client_cannot_manage_foreign_project`（403） |
| 伪造 Task 状态 | 同上，`INVALID_STATE_TRANSITION`（409） |
| 并发提交冲突 | 项目配置与项目更新均校验 `expected_version`，`VERSION_CONFLICT`（409） |
| 跨项目使用 Approval | `test_approval_cannot_be_reused_across_changesets`；服务在决策前校验 `target_id`/`project_id`，越权尝试不消耗审批 |
| 审批后修改内容 | 清单替换后回到 `DRAFT`，重新校验后旧审批因哈希不匹配被拒绝（`APPROVAL_HASH_MISMATCH`） |
| 过期审批 | `test_approval_expiry_is_persisted`，状态先落库为 `EXPIRED` 再返回 409 |
| 审批幂等 | 重复批准返回同一 `APPROVED` 状态 |
| 管理页凭证 | 页面为静态外壳，不内嵌 Token；所有数据请求必须携带 Bearer Token |

## 5. 状态权威与边界

- Project → `ProjectRegistryService`；Task/Attempt → `TaskService`；Workflow/Node/Phase → Workflow 服务；ChangeSet → `ChangeSetService`；Approval → `ApprovalService`；Requirement → `RequirementService`。
- 跨模块协作只通过公开方法或领域事件；Workflow 完成后先提交自身事务，再调用 Task 的验收请求，避免 SQLite 嵌套写锁。
- ChangeSet 不直接写文件；`APPLYING → APPLIED` 由后续阶段执行真实变更后回报。
- ChangeSet 的审批必须绑定当前 `content_hash`；审批失效不会静默放行。

## 6. 已知限制

1. 管理界面以浏览器单页提供（`/api/v1/manage`），未新增 Godot 编辑器 Dock；原因是 E4 所有管理接口均为 HTTP，Godot 侧当前只有 WebSocket 客户端，新增 Dock 会引入独立 HTTP 客户端与凭证传递逻辑，超出本阶段最小实现。页面已覆盖项目详情、任务操作、Workflow 查看与审批操作。
2. 归档阻塞统计按类别最多扫描 200 条 Workflow/ChangeSet 记录；对超大项目（单项目 >200 个未完成实例）建议 E5 改为聚合计数查询。
3. Workflow 节点推进当前按“输入依赖满足 + 无运行中节点”调度，未实现并行分支与节点超时重试；属于后续 Workflow 增强范围。
4. 启动恢复把未完成 Attempt 标记为 `UNKNOWN`、对应 Task 标记为 `BLOCKED`，自动重试策略留待 E5 Agent 执行层实现。

## 7. 结论

E4 的 Project / Task / Workflow / Requirement / ChangeSet / Approval / 验收 / API / 管理界面与测试均已完成，状态机、审批哈希绑定、版本冲突、越权与过期场景有自动化测试覆盖，E1–E3 回归全绿。满足 E4 DoD，可进入 E5。
