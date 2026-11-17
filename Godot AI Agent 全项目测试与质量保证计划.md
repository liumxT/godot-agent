# Godot AI Agent 全项目测试与质量保证计划

**文档编号：** DOC-03-001  
**版本：** V1.0  
**状态：** DRAFT（初稿）  
**文档类型：** 全项目测试计划与质量保证规范  
**关联文档：**
- DOC-01-001《Godot AI Agent 完整项目设计说明书》
- DOC-02-001《Godot AI Agent 完整开发实施计划》
- ARC-BASE-001《完整架构决策基线与模块总索引》

---

# 第一章 测试计划概述

## 1.1 文档目的

本文件规定 Godot AI Agent 项目从开发开始到最终发布的完整测试体系。

测试目标不只是确认某个函数能够正常执行，而是确认整个系统在真实环境中能够安全、稳定、正确地完成游戏开发任务。

需要验证：

1. Backend 能否正常启动、运行和关闭。
2. Godot Plugin 能否正确连接 Backend。
3. 多个 Godot Editor 能否同时使用同一个 Backend。
4. 不同项目之间是否完全隔离。
5. Task、Workflow、Agent 的状态是否一致。
6. Agent 是否按照授权执行任务。
7. Model Provider 调用是否正确。
8. Tool System 是否能安全执行项目操作。
9. Godot Editor 操作是否真正作用于实际项目。
10. Scene、Node、Resource、Signal 等对象是否正确创建和修改。
11. 资产生成、处理、导入和引用是否正确。
12. Verification 是否能够独立判断实际结果。
13. Backend 崩溃后是否能够正确恢复。
14. 新功能是否会破坏旧功能。
15. 最终能否通过系统完成一个完整游戏项目的开发、测试和导出。

## 1.2 测试原则

### 原则一：测试必须对应需求

每一项正式需求必须至少关联：

- 一个或多个验收标准。
- 一个或多个测试用例。
- 对应测试执行记录。
- 测试证据。
- 最终验证结果。

### 原则二：测试实际结果，不测试虚假成功

例如：

- Agent 返回“Scene 创建成功”，不代表 Scene 真的创建成功。
- Godot 文件写入成功，不代表 Editor 已正确导入。
- Editor 导入成功，不代表游戏运行正常。
- 游戏运行正常，不代表所有需求都实现。
- Build 成功，不代表发布包完整。

必须使用实际环境和独立证据验证结果。

### 原则三：修改必须触发回归分析

每次代码、接口、数据库、配置、Agent、Tool 或 Godot 集成发生变化，都必须评估影响范围。

不能只测试刚刚修改的文件。

### 原则四：验证权威独立

Agent、开发人员和测试执行器不能自行宣布 Task 或 Phase 成功。

Verification System 负责验证结果，Task System 根据验证结果和业务规则管理 Task 状态。

### 原则五：UNKNOWN 不等于成功或失败

当操作是否产生副作用无法确定时，必须进入核实流程。

不能因为没有收到响应就直接重复执行。

### 原则六：保留测试证据

每次正式测试都需要记录测试环境、代码版本、项目版本、输入数据、执行过程、结果和证据。

旧版本测试证据不能证明新版本已经通过。

---

# 第二章 测试体系总体结构

## 2.1 测试分类

整个项目采用以下测试层级：

| 编号 | 测试类型 | 主要目标 |
|---|---|---|
| T01 | Unit Test | 单个函数和类的正确性 |
| T02 | Component Test | 单个组件内部协作 |
| T03 | Contract Test | 模块接口和数据契约 |
| T04 | Integration Test | 多模块协同 |
| T05 | System Test | 整体系统功能 |
| T06 | E2E Test | 真实用户业务闭环 |
| T07 | Regression Test | 确认旧功能未被破坏 |
| T08 | Security Test | 权限、数据和安全边界 |
| T09 | Performance Test | 性能、并发和资源占用 |
| T10 | Reliability Test | 长时间运行和稳定性 |
| T11 | Recovery Test | 崩溃、断线和恢复 |
| T12 | Compatibility Test | Godot 和操作系统兼容性 |
| T13 | Usability Test | 用户操作体验 |
| T14 | Acceptance Test | 需求和阶段验收 |

## 2.2 测试执行层级

测试分为五个执行层级。

### Level 1：开发者本地测试

执行时机：

- 每次开发完成。
- 每次代码提交。
- 每次修复 Bug。

主要内容：

- Unit Test。
- Component Test。
- 基础 Contract Test。
- 静态代码检查。

### Level 2：模块 CI 测试

执行时机：

- Pull Request。
- 模块合并。
- 接口修改。

主要内容：

- Unit Test。
- Contract Test。
- Component Test。
- 数据库测试。
- 相关安全测试。

### Level 3：系统集成测试

执行时机：

- 阶段集成。
- 跨模块修改。
- 重要功能完成。

主要内容：

- Integration Test。
- System Test。
- Recovery Test。
- Security Test。
- Regression Test。

### Level 4：完整项目测试

执行时机：

- 阶段验收。
- Demo 验收。
- 发布候选版本。

主要内容：

- E2E Test。
- Full Regression。
- Compatibility Test。
- Performance Test。
- Acceptance Test。

### Level 5：正式发布测试

执行时机：

- 正式发布前。
- 重大升级前。

主要内容：

- 全量自动化测试。
- 手工验收。
- 安装升级测试。
- 数据迁移测试。
- 安全审查。
- 发布包完整性检查。

## 2.3 测试分类与开发阶段关系

| 阶段 | 必须建立或重点执行的测试 |
|---|---|
| E0 | 测试框架、CI、基础单元测试 |
| E1 | Backend、Database、Event、Contract Test |
| E2 | API、Security、Observability、Recovery Test |
| E3 | Godot Integration、Session、Editor、Runtime Test |
| E4 | Task、Workflow、Approval、ChangeSet Test |
| E5 | Model、Tool、Permission、Provider Test |
| E6 | Agent Runtime、Checkpoint、Handoff Test |
| E7 | Multi-Agent、Concurrency、Collaboration Test |
| E8 | Asset、Generation、Import、License Test |
| E9 | Verification、Defect、Regression Test |
| E10 | Build、Artifact、Package、Release Test |
| E11 | Platformer E2E、Gameplay、全系统回归 |
| E12 | 安装、升级、兼容性、安全和最终验收 |

---

# 第三章 测试环境规范

## 3.1 Backend 测试环境

至少准备以下环境：

**Backend Unit Environment**

用于单元测试。

特点：

- 不需要真实 Godot Editor。
- Provider 使用 Mock。
- 数据库使用独立测试数据库。
- 文件操作限制在临时目录。

**Backend Integration Environment**

用于模块集成测试。

特点：

- 使用真实 Backend。
- 使用独立 SQLite 数据库。
- 使用真实 API 和 WebSocket。
- 需要时启动模拟 Provider。

**Backend Recovery Environment**

用于恢复测试。

特点：

- 可以主动终止 Backend。
- 可以模拟数据库异常。
- 可以制造消息投递中断。
- 可以模拟外部服务超时。
- 能够检查恢复前后的数据一致性。

## 3.2 Godot 测试环境

准备：

- 支持版本的 Godot Editor。
- Godot Headless。
- Godot Runtime。
- Godot CLI。
- 测试用 Godot Project。
- 测试 Scene。
- 测试 Script。
- 测试 Resource。
- 测试 Asset。

必须同时具备 Editor 环境和非 Editor 环境。

不能仅依靠 Mock 验证 Godot 集成。

## 3.3 多实例测试环境

至少测试：

- 一个 Backend、一个 Editor。
- 一个 Backend、两个 Editor。
- 一个 Backend、多个项目。
- 一个项目、多个 Editor。
- 多项目同时执行 Task。
- 一个 Editor 断线，其他 Editor 继续工作。

重点验证 Session、Project Context、Resource Lock 和状态隔离。

## 3.4 Provider 测试环境

区分：

**Mock Provider**

用于：

- 单元测试。
- 错误注入。
- 超时测试。
- 重试测试。
- 边界条件测试。

**真实 Provider**

用于：

- 真实调用验证。
- 模型能力验证。
- 多模态验证。
- Token 和费用核对。
- 实际生成质量抽检。

真实 Provider 测试需要单独的测试凭证和预算，不得使用生产密钥。

## 3.5 测试数据隔离

测试数据必须使用独立的：

- Project ID。
- Task ID。
- Agent Instance ID。
- Database。
- Storage Directory。
- Provider Credential。
- Test Session。

测试不得直接修改用户真实项目。

---

# 第四章 测试编号与用例管理

## 4.1 测试编号格式

统一使用：

`GAA-[测试域]-[模块]-[序号]`

例如：

- GAA-UNIT-DB-001
- GAA-CONTRACT-TASK-001
- GAA-INTEGRATION-GODOT-001
- GAA-RECOVERY-BACKEND-001
- GAA-SECURITY-TOOL-001
- GAA-E2E-PLATFORMER-001

测试编号创建后保持稳定。

测试内容发生较大变化时，修改用例版本，不随意复用编号表达完全不同的测试。

## 4.2 测试用例模板

每个正式测试用例必须包含：

| 字段 | 内容 |
|---|---|
| Test ID | 唯一编号 |
| Test Name | 测试名称 |
| Test Type | 测试类型 |
| Requirement IDs | 关联需求 |
| Module | 关联模块 |
| Priority | P0/P1/P2 |
| Preconditions | 前置条件 |
| Test Data | 测试数据 |
| Steps | 执行步骤 |
| Expected Result | 预期结果 |
| Actual Result | 实际结果 |
| Evidence | 证据 |
| Environment | 测试环境 |
| Version | 软件版本 |
| Status | 测试状态 |
| Defect ID | 关联缺陷 |

## 4.3 测试状态

测试执行状态：

- NOT_RUN。
- READY。
- RUNNING。
- PASSED。
- FAILED。
- BLOCKED。
- SKIPPED。
- CANCELLED。
- INVALID。

说明：

- FAILED 表示真实测试未通过。
- BLOCKED 表示测试无法按计划执行。
- INVALID 表示测试条件或证据无效。
- SKIPPED 必须记录原因和批准信息。
- UNKNOWN 表示执行结果无法确定，应进入核实流程，不能自动归为 PASSED。

## 4.4 测试优先级

**P0：发布阻断测试**

涉及核心业务、安全、数据完整性、项目写入、权限、恢复和端到端闭环。

**P1：重要功能测试**

涉及主要产品能力和重要边界情况。

**P2：扩展能力测试**

涉及高级功能、低频场景和非第一阶段核心能力。

---

# 第五章 Backend Core 测试计划

## 5.1 Application Lifecycle

测试范围：

- Bootstrap。
- Module Initialization。
- Module Dependency。
- READY。
- READY_DEGRADED。
- Graceful Shutdown。
- Startup Failure。
- Shutdown Timeout。

测试用例：

| Test ID | 测试内容 | 预期结果 | 优先级 |
|---|---|---|---|
| GAA-UNIT-LIFE-001 | 正常启动 | Backend 进入 READY | P0 |
| GAA-UNIT-LIFE-002 | 模块初始化失败 | 按依赖策略阻止 READY | P0 |
| GAA-UNIT-LIFE-003 | 模块循环依赖 | 启动前检测并报告 | P0 |
| GAA-UNIT-LIFE-004 | 模块缺失依赖 | 阻止相关模块启动 | P0 |
| GAA-UNIT-LIFE-005 | Graceful Shutdown | 按顺序关闭模块 | P0 |
| GAA-INTEGRATION-LIFE-006 | 部分模块不可用 | 进入符合策略的 DEGRADED 状态 | P1 |
| GAA-RECOVERY-LIFE-007 | Backend 重启 | 恢复持久化状态 | P0 |

## 5.2 Module Interface Registry

测试：

- Module Registration。
- Interface Registration。
- Schema Validation。
- Dependency Validation。
- Version Compatibility。
- Permission Metadata。
- Timeout Metadata。
- Idempotency Metadata。

重点测试：

1. 重复注册同一版本。
2. 不兼容版本。
3. 缺失 Schema。
4. 错误 Request。
5. 错误 Response。
6. 循环依赖。
7. 已运行任务使用旧契约版本。
8. 新契约发布后旧任务是否仍按固定版本执行。

## 5.3 Database & Repository

必须测试：

- SQLite WAL。
- Migration。
- Backup。
- Restore。
- Transaction。
- Rollback。
- Optimistic Concurrency。
- Repository Ownership。
- Unit of Work。

关键用例：

| Test ID | 测试内容 | 预期结果 |
|---|---|---|
| GAA-DB-001 | 正常 Migration | Schema 升级成功 |
| GAA-DB-002 | Migration 中途失败 | 不留下半迁移状态 |
| GAA-DB-003 | Transaction Rollback | 未提交数据不生效 |
| GAA-DB-004 | 并发更新 | 冲突被正确检测 |
| GAA-DB-005 | Backup & Restore | 数据能够恢复 |
| GAA-DB-006 | Repository 跨模块访问 | 架构检查阻止违规访问 |
| GAA-DB-007 | Event 与业务状态提交 | 两者在同一事务边界保持一致 |
| GAA-DB-008 | 数据库损坏模拟 | 报告故障并进入恢复流程 |

## 5.4 Event System

测试：

- Event Persistence。
- Event Ordering。
- At-least-once Delivery。
- Inbox Idempotency。
- Outbox Dispatch。
- Dead Letter。
- Event Replay。
- Event Gap Detection。

特别验证三种 Replay：

1. DELIVERY_REPLAY。
2. PROJECTION_REBUILD。
3. STATE_RECONCILIATION。

禁止把普通 Event Replay 当成项目写入操作重放。

## 5.5 Observability

验证：

- 日志结构正确。
- Trace ID 可以跨模块关联。
- Task ID 和 Project ID 可查询。
- Secret 不会出现在日志。
- Metrics 不会因为重复事件重复计数。
- Security Audit 与普通运行日志分离。
- 不记录模型隐藏推理。

---

# 第六章 Godot Integration 测试计划

## 6.1 Plugin Lifecycle

必须覆盖：

- 插件首次启用。
- 插件禁用。
- 插件重新加载。
- Backend 不存在。
- Backend 启动中。
- Backend 认证失败。
- Session 过期。
- WebSocket 断开。
- 重连。
- Editor 关闭。
- Editor 崩溃。
- Backend 崩溃。

重点规则：

插件卸载、重载或 Editor 关闭不得自动关闭独立 Backend。

## 6.2 Backend Identity

验证：

- backend_instance_id。
- PID。
- process_start_time。
- executable_identity。
- backend_version。
- protocol_versions。
- startup_nonce。
- data_directory_identity。

测试错误进程响应、PID 复用、旧启动信息和伪造身份等场景。

## 6.3 Session & Heartbeat

测试：

- Session 创建。
- Session 认证。
- Lease 续期。
- Heartbeat 超时。
- Session 过期。
- 重新认证。
- 旧 Token 拒绝。
- 多 Editor Session 独立。

## 6.4 Editor Bridge

测试：

- WebSocket 建立。
- 消息格式验证。
- 请求与响应关联。
- 消息重复。
- 消息乱序。
- 消息缺失。
- Snapshot。
- Event 补偿。
- 重连。

## 6.5 Godot Editor Operation

必须使用真实 Godot Editor 测试：

- 获取当前项目。
- 获取 Scene。
- 获取 Node Tree。
- 获取 Node 属性。
- 创建 Node。
- 删除 Node。
- 修改属性。
- 创建和连接 Signal。
- 修改 Group。
- 保存 Scene。
- Resource 引用。
- Animation 操作。
- TileMapLayer 操作。

每种操作都需要验证：

1. 输入是否正确。
2. 权限是否正确。
3. 是否产生预期变更。
4. 实际 Editor 状态是否正确。
5. Disk 状态是否正确。
6. 是否产生 ChangeSet。
7. 是否记录执行证据。
8. 是否能处理失败和 UNKNOWN。

## 6.6 Project State Synchronization

重点测试：

| 场景 | 预期行为 |
|---|---|
| Editor 有未保存 Scene 修改 | 暂停相关 Scene 写入 |
| 修改无关文件 | 不应无理由阻塞全部项目操作 |
| 外部修改资源文件 | 检测版本变化 |
| Godot 尚未重新导入 | 不得假设资源已可用 |
| Runtime 仍运行旧版本 | 保留旧 Runtime 身份 |
| 新版本测试 | 使用独立测试 Runtime |
| 多 Editor 编辑同一资源 | 检测冲突并阻止静默覆盖 |

## 6.7 Godot Runtime Bridge

测试：

- Runtime Probe 注册。
- Runtime 身份。
- Session 认证。
- Snapshot。
- Event。
- Debug 状态。
- 游戏运行状态。
- Runtime Mutation Authorization。
- Runtime 断线恢复。

Runtime Mutation 必须独立授权，不能用普通文件写入审批代替。

## 6.8 GodotBackendLifecycleTestSuite

本测试集必须作为 E3 和最终发布门禁。

| ID | 测试场景 | 预期结果 |
|---|---|---|
| G01-01 | Backend 首次启动 | Plugin 能发现正确 Backend |
| G01-02 | Backend 未启动 | Plugin 进入等待状态 |
| G01-03 | Backend 启动中 | 不误判为 READY |
| G01-04 | Backend 身份错误 | 拒绝连接 |
| G01-05 | Session 认证失败 | 不进入 READY |
| G01-06 | Heartbeat 超时 | Session 进入失效流程 |
| G01-07 | WebSocket 断开 | 进入 RECONNECTING |
| G01-08 | Backend 重启 | 重新发现并认证 |
| G01-09 | Snapshot 恢复 | 重建真实 Editor 状态 |
| G01-10 | Event Gap | 检测并补偿 |
| G01-11 | Plugin Reload | 不关闭 Backend |
| G01-12 | Plugin Disable | 不自动取消独立 Task |
| G01-13 | Editor 关闭 | 不擅自处理未保存 Scene |
| G01-14 | 多 Editor | Session 独立 |
| G01-15 | 多项目 | 项目上下文隔离 |
| G01-16 | Editor 关闭期间后台任务 | 独立任务按策略继续，依赖 Editor 的任务等待重连 |

---

# 第七章 Project、Task、Workflow 与 ChangeSet 测试计划

## 7.1 Project Management

测试：

- 项目创建。
- 项目绑定。
- 项目扫描。
- 项目配置。
- 项目版本。
- 多项目隔离。
- 项目关闭。
- 项目恢复。

## 7.2 Requirement Management

测试：

- 需求创建。
- 需求版本。
- 需求修改。
- 验收标准。
- 需求依赖。
- 需求确认。
- 未确认推测。
- 需求冲突。

未被用户确认的重要需求不得被静默视为最终需求。

## 7.3 Task System

重点测试：

- Task 创建。
- Attempt 创建。
- DAG 依赖。
- 多前置条件。
- 条件分支。
- 循环依赖检测。
- Pause。
- Resume。
- Cancel。
- Retry。
- Attempt History。
- Task Recovery。

必须验证重试创建新 Attempt，不覆盖旧 Attempt 历史。

## 7.4 Workflow Engine

测试：

- 顺序执行。
- 并行执行。
- 条件分支。
- 人工审批节点。
- 用户确认节点。
- 阶段节点。
- 失败阻断。
- 补偿。
- 暂停恢复。
- Definition Version 固定。

## 7.5 Approval System

测试：

- 审批请求创建。
- 审批范围。
- 审批拒绝。
- 审批过期。
- 审批哈希匹配。
- 审批后内容变化。
- 重新审批。
- 审批审计。

必须验证需求确认、ChangeSet Approval、Runtime Mutation Authorization 和 External Data Authorization 是不同授权。

## 7.6 ChangeSet Manager

测试：

- 新增文件。
- 修改文件。
- 删除文件。
- 文件哈希变化。
- 变更分组。
- 风险等级。
- 审批绑定。
- 审批后文件变化。
- 应用失败。
- 部分应用。
- 回滚信息。

取消 Task 不应自动将已经产生的副作用视为已回滚。

---

# 第八章 Model Gateway 与 Tool System 测试计划

## 8.1 Model Gateway

测试：

- Provider Registration。
- Model Registration。
- Deployment Registration。
- Provider Authentication。
- Model Capability。
- Model Routing。
- User Model Preference。
- Streaming。
- Multimodal。
- Timeout。
- Cancellation。
- Retry。
- Fallback。
- Token Accounting。
- Cost Accounting。

## 8.2 Model Routing

必须验证：

1. 用户指定模型可用时优先使用指定模型。
2. 指定模型不可用时不静默切换。
3. 用户允许 Fallback 时才按策略切换。
4. 模型能力 UNKNOWN 时不能默认支持。
5. 预算不足时阻止调用。
6. Provider 健康状态变化能够影响路由。

## 8.3 Token & Cost

测试：

- Token 记录。
- Cost 计算。
- 价格版本。
- 预算预留。
- 预算释放。
- 超预算阻断。
- 并发预算竞争。
- 账单对账。
- 阈值通知。

70%、85%、95%、100% 阈值需要分别验证。

## 8.4 Tool Registry

测试：

- Tool 注册。
- Tool 版本。
- Schema 验证。
- Tool 权限。
- Side Effect 标签。
- Risk Level。
- 不兼容 Tool Version。
- Tool Disabled。

## 8.5 Tool Execution Engine

执行生命周期：

ACCEPTED → VALIDATING → QUEUED → RUNNING → SUCCEEDED / FAILED / TIMEOUT / UNKNOWN。

测试：

- 输入错误。
- 未授权。
- 权限过期。
- ChangeSet 缺失。
- Resource Lock 失败。
- 前置条件失败。
- 执行超时。
- 部分副作用。
- 后置验证失败。
- 结果持久化失败。
- Backend 中断。

## 8.6 副作用与重试测试

必须覆盖：

- NO_EFFECT。
- EFFECT_APPLIED。
- PARTIAL_EFFECT。
- EFFECT_UNKNOWN。

特别测试：

**场景 A：工具执行前崩溃**

预期：核实没有产生副作用后，才允许按策略重新执行。

**场景 B：工具执行后、返回结果前崩溃**

预期：通过实际文件、Editor 或 Runtime 状态核实操作结果，不直接重复执行。

**场景 C：操作部分完成**

预期：记录部分副作用，进入核实或补偿流程。

**场景 D：外部服务超时**

预期：根据 Provider 请求身份和结果核实是否已经产生费用或资源。

## 8.7 Tool Security

必须测试：

- 路径穿越。
- 符号链接逃逸。
- 未授权文件访问。
- 任意 Python 执行绕过。
- 未授权 CLI。
- Process Control。
- Runtime Mutation。
- External Data Transfer。
- Agent 权限扩大。
- Tool Adapter 隔离。

---

# 第九章 Context、Project Intelligence 与 Agent 测试计划

## 9.1 Project Intelligence

测试：

- Godot 项目扫描。
- 文件解析。
- Scene 解析。
- Script 解析。
- Resource 解析。
- Entity 创建。
- Relationship 创建。
- 稳定 ID。
- Hash。
- Version。
- Provenance。
- 全文检索。
- 向量检索。
- 索引重建。

确定性 Parser 的事实与 AI Analyzer 的推断必须分开保存。

## 9.2 Context System

测试：

- Context Retrieval。
- Context Package。
- Context Revision。
- Context Budget。
- PINNED。
- NORMAL。
- EXCLUDED。
- Conflict Resolver。
- Context Lifecycle。
- Context Reference。

特别验证：

- 用户固定的 Context 不得静默移除。
- Context 不等于文件读取授权。
- Context 不等于写入审批。
- 不同项目 Context 不得混用。
- Agent Private Context 不得泄漏给其他 Agent。

## 9.3 Agent Runtime

测试：

- Agent Definition。
- Agent Registration。
- Agent Instance。
- Model Binding。
- Context Binding。
- Tool Allowlist。
- Permission Snapshot。
- Execution Loop。
- Budget Enforcement。
- Checkpoint。
- Resume。
- Handoff。
- Failure。
- Result Trust。

## 9.4 Agent 权限边界

测试：

1. Agent 不能扩大 Definition Permission。
2. Agent Instance 不能扩大自身权限。
3. Agent 不能直接访问 Provider。
4. Agent 不能绕过 Tool System。
5. Agent 不能自行批准 ChangeSet。
6. Agent 不能自行授权 Runtime Mutation。
7. Agent 不能直接委派给其他 Agent。
8. Agent 不能将未验证推断当作项目事实。

## 9.5 Multi-Agent Collaboration

测试：

- Agent Matching。
- Capability Filter。
- Permission Filter。
- Budget Filter。
- Task DAG。
- Shared Context。
- Handoff。
- Shared Contract。
- Resource Lock。
- Fencing Token。
- Lead Integration。
- Integration Status。
- Lead Failure。
- Orchestrator Takeover。

特别验证：同一 Scene 或文件默认单写者，多个 Agent 不得静默覆盖彼此修改。

---

# 第十章 Asset Pipeline 测试计划

## 10.1 Asset Identity

测试：

- Asset ID。
- Asset Version。
- Asset File。
- Generation Job。
- Processing Job。
- Import Job。
- Asset Relationship。
- Provenance。
- License Record。

验证不同版本不会错误共用身份。

## 10.2 Generation Job

测试：

- Job Creation。
- Validation。
- Planning。
- Queue。
- Submission。
- Generation。
- Result Collection。
- Verification。
- Completion。
- Partial Success。
- Retry。
- Cancellation。
- Recovery。

## 10.3 Provider Integration

测试：

- Provider 不可用。
- 请求拒绝。
- 认证失败。
- 限流。
- 超时。
- 重复提交。
- 结果缺失。
- 部分结果。
- 费用记录。
- 取消失败。

## 10.4 Processing Pipeline

测试：

- 图片格式转换。
- 图片尺寸。
- 透明通道。
- Sprite Sheet 切帧。
- 音频格式。
- 音频属性。
- 文件损坏。
- 不支持格式。
- 处理进程中断。
- 输出哈希。

## 10.5 Provenance & License

测试：

- 来源完整。
- Provider 信息缺失。
- License UNKNOWN。
- License PENDING_REVIEW。
- 衍生关系。
- License 不兼容。
- 交付集合阻断。

License 状态不明确的资产不得自动进入正式交付集合。

## 10.6 Godot Import

必须在真实 Godot 项目中验证：

- 文件写入。
- Editor 同步。
- 资源导入。
- UID。
- Resource Reference。
- Sprite Sheet 使用。
- Audio Resource 使用。
- Scene 引用。
- 重新导入。
- 版本替换。

已有资源更新不得静默破坏已有引用。

## 10.7 AssetPipelineTestSuite

必须覆盖：

- Generation。
- Provider。
- Processing。
- Registry。
- Governance。
- Storage。
- Import。
- ChangeSet。
- Multi-Agent。
- Verification。

---

# 第十一章 Verification、QA 与 Defect 测试计划

## 11.1 Requirement Traceability

测试需求链路是否完整：

Requirement → Acceptance Criteria → Task → ChangeSet → Test Case → Evidence → Verification Result。

检查是否存在：

- 无验收标准的需求。
- 无测试用例的 P0 需求。
- 无关联 Task 的变更。
- 无证据的通过结果。
- 过期证据。
- 无法追溯的最终交付。

## 11.2 六层验证

**第一层：Operation Verification**

检查工具操作是否真实执行。

**第二层：Structural Verification**

检查文件、Scene、Node、Resource 等结构。

**第三层：Static Verification**

检查代码、引用、类型、静态规则。

**第四层：Runtime Verification**

运行 Godot 项目，检查实际行为。

**第五层：Integration & Regression Verification**

检查跨模块和旧功能。

**第六层：Requirement & Phase Acceptance**

检查是否满足用户需求和阶段验收标准。

## 11.3 Defect Lifecycle

缺陷流程：

OPEN → TRIAGED → ASSIGNED → IN_PROGRESS → FIXED → RETEST → VERIFIED → CLOSED。

如果 Retest 失败，重新进入缺陷处理流程。

不能仅因为开发人员提交了修复就关闭 Bug。

## 11.4 缺陷等级

| 等级 | 定义 | 处理要求 |
|---|---|---|
| Critical | 数据丢失、安全突破、重大错误写入 | 阻断发布 |
| High | 核心功能不可用或关键业务错误 | 阻断相关阶段 |
| Medium | 重要功能异常，有有限替代方案 | 评估后处理 |
| Low | 轻微问题、外观或非关键体验问题 | 记录并排期 |

缺陷优先级与严重程度应分别记录。

## 11.5 Verification 独立性

必须验证：

- Agent 无权直接修改 Verification Result。
- QA 执行器不能单方面改变 Task 状态。
- Verification 不直接修改 Task 状态。
- Task System 根据 Verification Result 和业务规则处理 Task。
- Phase Acceptance 必须遵循用户确认流程。

---

# 第十二章 回归测试计划

## 12.1 回归测试目的

回归测试用于确保新增功能、Bug 修复、架构调整、接口变化和版本升级没有破坏既有能力。

本项目必须建立持续更新的回归测试体系。

## 12.2 回归测试触发条件

以下变化必须触发回归影响分析：

1. 修改公共接口。
2. 修改数据 Schema。
3. 修改数据库 Migration。
4. 修改 Event Schema。
5. 修改权限策略。
6. 修改 Tool Execution Engine。
7. 修改 Godot Bridge。
8. 修改 Agent Runtime。
9. 修改 Workflow。
10. 修改 Resource Lock。
11. 修改 Asset Import。
12. 修改 Verification。
13. 修改 Build。
14. 修改配置和 Secrets。
15. 修复任何 P0 或 P1 Bug。

## 12.3 回归测试分级

### R1：局部回归

适用于局部、低风险修改。

执行：

- 被修改模块的单元测试。
- 直接依赖模块的契约测试。
- 相关组件测试。

### R2：关联回归

适用于跨模块修改。

执行：

- 受影响模块测试。
- 上下游契约测试。
- 关联集成测试。
- 相关安全测试。

### R3：系统回归

适用于核心基础设施或公共接口变化。

执行：

- Backend 核心测试。
- Godot Integration。
- Task/Workflow。
- Model/Tool。
- Agent。
- Asset。
- Verification。
- Recovery。
- 多项目隔离。

### R4：全量回归

适用于：

- 重大版本。
- 数据库结构重大变化。
- 全局架构变化。
- 发布候选版本。
- E11 和 E12 验收。

执行全部 P0、P1 回归测试和约定范围内的 P2 测试。

## 12.4 回归影响分析

每次修改前后必须检查：

- 修改了哪些模块？
- 使用了哪些接口？
- 哪些数据模型发生变化？
- 哪些 Event 发生变化？
- 哪些权限发生变化？
- 哪些任务状态可能受到影响？
- 哪些旧测试需要重新执行？
- 哪些测试需要新增？

回归选择必须有依据，不能只由开发人员凭感觉决定。

## 12.5 回归基线

每个正式阶段建立回归基线：

- 代码版本。
- Contract Version。
- Database Schema Version。
- Godot Version。
- Plugin Version。
- Test Suite Version。
- Test Result。
- Evidence Reference。

## 12.6 回归失败处理

发现回归失败后：

1. 阻止相关变更进入稳定分支或发布流程。
2. 创建 Defect。
3. 记录失败测试和环境。
4. 分析是否由本次变更引起。
5. 修复问题。
6. 重新执行失败测试。
7. 执行相关回归。
8. 更新回归基线。

不能通过删除测试、降低预期结果或修改证据来消除失败。

---

# 第十三章 故障注入与恢复测试

## 13.1 测试目标

主动制造异常，验证系统能否正确识别、隔离和恢复。

故障注入必须在隔离测试环境执行。

## 13.2 Backend 故障

测试：

- 启动时崩溃。
- 运行中崩溃。
- 数据库不可用。
- 数据库写入失败。
- Outbox 派发中断。
- Event 重复投递。
- Worker 退出。
- Graceful Shutdown 超时。

## 13.3 Editor 故障

测试：

- Editor 关闭。
- Editor 崩溃。
- Plugin Reload。
- WebSocket 断线。
- Session 过期。
- 未保存 Scene。
- Editor 状态无法读取。
- 多 Editor 冲突。

## 13.4 Agent 故障

测试：

- Model Timeout。
- Tool Timeout。
- Agent Process Crash。
- Agent Budget Exhausted。
- Checkpoint 损坏。
- Handoff 中断。
- Lead Agent Crash。
- Orchestrator Restart。

## 13.5 Tool 故障

测试：

- 执行前崩溃。
- 执行中崩溃。
- 执行后响应丢失。
- 文件部分写入。
- 原子替换失败。
- Editor 同步失败。
- Runtime Mutation 结果未知。

## 13.6 Recovery 测试要求

每次故障注入必须验证：

1. 是否识别故障。
2. 是否保存故障前状态。
3. 是否识别已产生的副作用。
4. 是否避免重复执行。
5. 是否恢复合法状态。
6. 是否记录恢复证据。
7. 是否通知用户需要处理的事项。

恢复成功不代表原始操作一定成功。

---

# 第十四章 Security 测试计划

## 14.1 身份和认证

测试：

- 无效身份。
- 伪造 Backend。
- 伪造 Editor。
- Session Token 过期。
- 重放旧 Token。
- 未授权 Session。
- 跨项目身份混用。

## 14.2 权限和授权

测试：

- RBAC。
- ABAC。
- Capability。
- Agent Permission。
- Tool Permission。
- ChangeSet Approval。
- Runtime Mutation Authorization。
- External Data Authorization。

验证 UNKNOWN 默认拒绝。

## 14.3 文件系统安全

测试：

- 路径穿越。
- 符号链接。
- 未授权目录。
- 敏感文件。
- 非法文件名。
- 临时文件残留。
- 并发覆盖。
- 原子替换失败。

## 14.4 AI 输入安全

测试：

- Prompt Injection。
- 恶意项目文件。
- 恶意 README。
- 恶意脚本注释。
- 外部文档注入。
- 不可信 Asset Metadata。
- Agent Handoff 内容污染。

必须区分项目数据、外部数据和系统指令。

## 14.5 数据和 Secrets

测试：

- 凭证加密。
- 凭证轮换。
- 日志脱敏。
- Provider 数据传输授权。
- DLP。
- 数据删除。
- 备份保护。
- 诊断包脱敏。

---

# 第十五章 Performance、Reliability 与 Compatibility 测试

## 15.1 Performance

需要测量：

- Backend 启动时间。
- API 响应时间。
- WebSocket 消息延迟。
- Event Dispatch 延迟。
- SQLite 查询时间。
- Project Scan 时间。
- Context Retrieval 时间。
- Agent 启动时间。
- Tool Execution 时间。
- Godot Editor 操作时间。
- Asset Processing 时间。

具体 P50、P95、P99 和资源使用目标，应在目标硬件与代表性项目基准测试后确定。

不能在没有实测的情况下宣称性能达标。

## 15.2 Reliability

测试：

- 长时间运行。
- 高频 Event。
- 高频 Task。
- 多 Agent 并行。
- 多项目同时工作。
- 大量资源扫描。
- 大量资产生成任务。
- Backend 长时间连接。
- 多次重启恢复。

## 15.3 Compatibility

需要验证：

- 支持的 Godot 版本。
- GDScript 兼容性。
- Editor Plugin API。
- Runtime API。
- CLI 参数。
- Export Template。
- Windows。
- Linux。
- macOS（按支持计划）。

每个支持组合必须有兼容性测试记录。

## 15.4 Compatibility Matrix

建议建立：

| Godot Version | OS | Plugin | Backend | Editor Bridge | Runtime | CLI Export |
|---|---|---|---|---|---|---|
| 支持版本 A | Windows | 待测 | 待测 | 待测 | 待测 | 待测 |
| 支持版本 A | Linux | 待测 | 待测 | 待测 | 待测 | 待测 |
| 支持版本 A | macOS | 待测 | 待测 | 待测 | 待测 | 待测 |
| 支持版本 B | Windows | 待测 | 待测 | 待测 | 待测 | 待测 |
| 支持版本 B | Linux | 待测 | 待测 | 待测 | 待测 | 待测 |

正式支持的 Godot 版本范围应在产品兼容性决策中确定。

---

# 第十六章 2D Platformer Demo 端到端测试

## 16.1 测试目标

验证系统是否真正具备使用 AI Agent 开发完整 Godot 游戏的能力。

## 16.2 E2E-01：项目创建

步骤：

1. 创建 Godot 测试项目。
2. 绑定 Backend。
3. 扫描项目。
4. 建立 Project Intelligence。
5. 生成项目摘要。

预期结果：

- 项目身份正确。
- 项目结构完整。
- 文件清单正确。
- 项目知识索引可用。

## 16.3 E2E-02：需求分析

步骤：

1. 输入 Platformer 游戏需求。
2. 分析需求。
3. 识别缺失信息。
4. 生成游戏设计方案。
5. 生成验收标准。
6. 等待用户确认。

预期结果：

- 需求完整。
- 重要假设明确。
- 用户确认记录完整。

## 16.4 E2E-03：开发计划

步骤：

1. 生成模块规划。
2. 生成 Phase。
3. 生成 Task DAG。
4. 分配专业 Agent。
5. 生成资源需求。
6. 生成测试计划。

预期结果：

- 依赖关系无循环。
- Agent 能力匹配。
- 预算和权限正确。
- 计划可执行。

## 16.5 E2E-04：玩家系统

验证：

- 玩家 Scene 创建。
- 玩家 Script 创建。
- 移动。
- 跳跃。
- 攻击。
- 受伤。
- 死亡。
- 重生。

通过真实 Runtime 验证行为。

## 16.6 E2E-05：关卡系统

验证：

- TileMapLayer。
- 地面。
- 平台。
- 碰撞。
- 陷阱。
- 出生点。
- 终点。

通过 Scene 结构和实际运行双重验证。

## 16.7 E2E-06：敌人系统

验证：

- 敌人巡逻。
- 敌人攻击。
- 玩家受伤。
- 敌人受伤。
- 敌人死亡。

## 16.8 E2E-07：游戏状态和 UI

验证：

- 生命值。
- 收集物。
- 计分。
- 主菜单。
- HUD。
- 暂停。
- 胜利。
- 失败。

## 16.9 E2E-08：资产生产

验证：

- 图片生成。
- 资源处理。
- Sprite Sheet。
- 音效。
- 来源记录。
- License。
- Godot 导入。
- Resource 引用。

## 16.10 E2E-09：缺陷修复

步骤：

1. 注入已知缺陷。
2. QA 发现缺陷。
3. 创建 Defect。
4. 分配 Agent。
5. 生成 ChangeSet。
6. 审批。
7. 执行修改。
8. 重新验证。
9. 执行回归测试。

预期结果：

- 缺陷有完整记录。
- 修改范围明确。
- 原功能不被破坏。
- 测试证据有效。

## 16.11 E2E-10：最终构建

步骤：

1. 执行完整测试。
2. 检查 Release Gate。
3. 生成 Build。
4. 执行 Export。
5. 校验 Artifact。
6. 打包。
7. 生成交付报告。

预期结果：

- 游戏能够运行。
- 产物完整。
- 文件哈希正确。
- 测试证据关联正确。
- 发布审批有效。

## 16.12 Demo E2E 验收标准

必须同时满足：

- 游戏主要功能真实运行。
- Scene 和 Resource 结构正确。
- Agent 执行过程可追踪。
- 项目写入经过授权。
- 资产来源可追溯。
- 关键测试通过。
- 缺陷有明确处理结论。
- Build 产物可验证。
- 用户完成最终验收。

---

# 第十七章 Global Architecture Integration Test Suite

以下 20 项作为 G07 全局架构门禁。

| ID | 测试内容 | 验收重点 |
|---|---|---|
| T01 | Module Dependency | 不存在违规循环依赖 |
| T02 | State Ownership | 状态唯一权威 |
| T03 | Repository Access | 不存在跨模块 Repository 访问 |
| T04 | Interface Registry | 接口注册一致 |
| T05 | Event Ownership | Event 所有权正确 |
| T06 | Schema Compatibility | Schema 兼容性正确 |
| T07 | Tool System Bypass | 不存在绕过 Tool System 的项目写入 |
| T08 | Agent Permission | Agent 权限边界正确 |
| T09 | ChangeSet Scope | 变更范围和审批匹配 |
| T10 | Runtime Mutation | Runtime 操作独立授权 |
| T11 | External Data | 外部数据授权有效 |
| T12 | Backend Crash Recovery | Backend 崩溃后正确恢复 |
| T13 | Multi-Agent Resource Lock | 多 Agent 资源冲突可控 |
| T14 | Context Revision | Context Revision 一致 |
| T15 | Asset Provenance | 资产来源完整 |
| T16 | Verification Ownership | Verification 状态权威正确 |
| T17 | Build Artifact Integrity | Build 产物完整性正确 |
| T18 | Phase Acceptance | Phase 验收流程正确 |
| T19 | Multi-Project Isolation | 多项目隔离 |
| T20 | Platformer Demo E2E | 端到端交付闭环 |

所有 T01–T20 必须形成可执行测试或可审计的架构检查。

仅有文档审查记录不能代替实际可自动化的检查。

---

# 第十八章 测试报告与证据管理

## 18.1 Test Run

每次测试运行必须创建独立 Test Run。

记录：

- Test Run ID。
- Test Suite Version。
- Software Version。
- Project Revision。
- Environment。
- Start Time。
- End Time。
- Test Result。
- Evidence References。

## 18.2 Evidence 类型

支持：

- Test Log。
- Application Log。
- Backend Log。
- Godot Editor Log。
- Runtime Log。
- Screenshot。
- Video。
- File Hash。
- Scene Snapshot。
- API Response。
- Build Artifact。
- Performance Metrics。

## 18.3 Evidence 有效性

证据必须能够关联：

- 被测需求。
- 对应代码版本。
- 对应项目版本。
- 测试环境。
- Test Run。
- Test Case。

发生代码或项目变更后，需要根据影响分析判断原证据是否失效。

## 18.4 测试报告

阶段测试报告至少包含：

1. 测试范围。
2. 测试环境。
3. 软件版本。
4. 测试用例数量。
5. Passed 数量。
6. Failed 数量。
7. Blocked 数量。
8. Skipped 数量。
9. 缺陷清单。
10. 风险。
11. 证据位置。
12. 阶段验收建议。

---

# 第十九章 发布质量门禁

## 19.1 门禁级别

**Gate 1：模块门禁**

要求：

- 模块单元测试通过。
- 模块契约测试通过。
- 静态检查通过。
- 安全边界测试通过。

**Gate 2：阶段门禁**

要求：

- 本阶段 P0 测试通过。
- 关联集成测试通过。
- 相关回归通过。
- 阶段交付完整。
- 缺陷有处理结论。

**Gate 3：系统门禁**

要求：

- 全系统集成测试通过。
- 关键恢复测试通过。
- 关键安全测试通过。
- 多项目隔离通过。
- 端到端核心流程通过。

**Gate 4：正式发布门禁**

要求：

- 全量 P0 回归通过。
- 全量 P1 回归通过，或存在经过正式批准的明确延期项。
- Critical 缺陷为零。
- 未授权写入和权限绕过测试通过。
- 备份与恢复验证通过。
- 安装升级验证通过。
- Demo E2E 通过。
- 发布包完整性通过。
- 用户验收完成。

## 19.2 禁止通过的情况

以下情况不能被标记为通过：

- 测试未执行。
- 测试结果 UNKNOWN。
- 证据无效。
- 测试版本不匹配。
- 关键测试被跳过但无批准。
- Critical 缺陷仍未解决。
- 存在未处理的数据丢失风险。
- 权限绕过测试失败。
- 核心功能只能通过 Mock 证明。
- 仅凭 Agent 自述成功。

## 19.3 缺陷延期

非 Critical 缺陷是否允许延期，需要用户明确批准。

批准记录必须包括：

- 缺陷编号。
- 影响范围。
- 风险说明。
- 临时措施。
- 修复计划。
- 用户决定。
- 适用版本。

不得把失败测试修改成通过。

---

# 第二十章 测试自动化与持续集成

## 20.1 CI 测试流水线

建议流水线：

1. Checkout。
2. Dependency Validation。
3. Format Check。
4. Lint。
5. Type Check。
6. Unit Test。
7. Contract Test。
8. Component Test。
9. Database Migration Test。
10. Security Static Check。
11. Integration Test。
12. Test Report。
13. Artifact Archive。

## 20.2 自动化测试目录

```text
tests/
├── unit/
│   ├── backend/
│   ├── godot_plugin/
│   ├── agents/
│   ├── tools/
│   └── assets/
│
├── component/
├── contract/
├── integration/
│   ├── backend/
│   ├── godot/
│   ├── agent/
│   ├── asset/
│   └── verification/
│
├── system/
├── e2e/
│   └── platformer/
├── regression/
├── security/
├── performance/
├── reliability/
├── recovery/
├── compatibility/
├── acceptance/
└── fixtures/
```

## 20.3 自动化原则

- 确定性逻辑优先自动化。
- 数据库迁移必须自动化测试。
- 公共接口必须契约测试。
- 关键权限必须自动化测试。
- Godot 核心操作必须有真实 Editor 测试。
- Runtime 行为必须有真实运行测试。
- 资产导入必须有真实 Godot 项目测试。
- 发布必须有产物完整性测试。

AI 生成内容的主观质量评价可以结合人工审核，但文件完整性、结构正确性、授权和引用完整性不能依赖主观判断。

---

# 第二十一章 Requirement-to-Test Traceability Matrix

建立全项目需求追踪矩阵。

| 需求域 | 需求范围 | 主要测试集 | 发布门禁 |
|---|---|---|---|
| Backend | 生命周期、数据库、事件 | Backend Core Suite | P0 |
| Godot Integration | Plugin、Editor、Runtime | Godot Integration Suite | P0 |
| Project | 项目管理和扫描 | Project Suite | P0 |
| Task | Task、Attempt、DAG | Task Suite | P0 |
| Workflow | Workflow、Phase | Workflow Suite | P0 |
| Approval | 授权和审批 | Approval Suite | P0 |
| Tool | Tool Execution 和权限 | Tool Suite | P0 |
| Model | Provider、Router、Budget | Model Suite | P0 |
| Context | Knowledge 和 Context | Context Suite | P1 |
| Agent | Agent Runtime | Agent Suite | P0 |
| Multi-Agent | 协作和锁 | Collaboration Suite | P0 |
| Asset | 生成、处理、导入 | Asset Pipeline Suite | P0 |
| Verification | QA 和 Evidence | Verification Suite | P0 |
| Build | Export 和 Artifact | Build Suite | P0 |
| Productization | 安装、升级 | Productization Suite | P0 |

正式需求编号应引用产品需求规格说明书中的 FR 编号。

每个 FR 必须在追踪矩阵中填写：

- Acceptance Criteria。
- Test Case IDs。
- Test Run。
- Evidence。
- Verification Result。

没有测试映射的 P0 需求不得通过阶段验收。

---

# 第二十二章 各阶段测试完成标准

| 阶段 | 测试完成条件 |
|---|---|
| E0 | 基础工程和 CI 测试通过 |
| E1 | Backend Core、Database、Event 测试通过 |
| E2 | API、Security、Recovery、Observability 测试通过 |
| E3 | GodotBackendLifecycleTestSuite 16 项通过 |
| E4 | Project、Task、Workflow、Approval 测试通过 |
| E5 | Model、Tool、Permission、Budget 测试通过 |
| E6 | Agent Runtime、Checkpoint、Handoff 测试通过 |
| E7 | Multi-Agent、Resource Lock、Collaboration 测试通过 |
| E8 | AssetPipelineTestSuite 通过 |
| E9 | Verification、Defect、Regression 体系通过验收 |
| E10 | Build、Artifact、Package、Release 测试通过 |
| E11 | Platformer Demo E2E 完整通过 |
| E12 | 全量回归、安装升级、安全和发布验收通过 |

各阶段还必须通过自身范围内的单元、契约和集成测试，不能仅凭表中列出的专项测试判断完成。

---

# 第二十三章 当前测试体系待细化事项

本文件已经建立全项目测试体系，但正式进入工程执行前还需要补充以下内容：

## 23.1 具体测试用例

每个模块需要将测试范围继续细化成：

- 输入。
- 前置条件。
- 操作步骤。
- 测试数据。
- 预期结果。
- 实际结果。
- 证据。
- 自动化实现方式。

## 23.2 性能基准

需要在目标硬件上进行基准测试，再确定：

- API 延迟目标。
- WebSocket 延迟目标。
- 项目扫描性能。
- Context 检索性能。
- Agent 并发量。
- Backend 内存上限。
- 数据库容量和查询性能。

## 23.3 Godot 兼容矩阵

需要明确：

- 正式支持的 Godot 版本。
- 目标操作系统。
- 插件兼容性。
- Runtime 兼容性。
- CLI 导出兼容性。

## 23.4 测试覆盖率目标

覆盖率应当按模块风险和测试类型制定。

不能仅使用一个全局代码覆盖率数字作为质量结论。

建议重点保证：

- 状态机分支。
- 权限决策分支。
- 错误处理分支。
- Recovery 分支。
- 数据迁移。
- 资源写入。
- UNKNOWN 处理。
- 关键业务路径。

## 23.5 发布基线

正式发布前必须冻结：

- 软件版本。
- 数据库版本。
- Contract Catalog。
- Godot 兼容矩阵。
- 测试用例版本。
- 测试证据。
- 已知缺陷。
- 发布审批记录。

---

# 第二十四章 文档最终状态

本文件 V1.0 建立了 Godot AI Agent 项目的全生命周期测试与质量保证框架。

它与项目总设计和开发实施计划共同组成三份核心项目文档：

1. DOC-01-001：完整项目设计说明书。
2. DOC-02-001：完整开发实施计划。
3. DOC-03-001：全项目测试与质量保证计划。

三份文档共同定义：

- 要开发什么。
- 按什么顺序开发。
- 每阶段要做哪些任务。
- 如何验证实现正确。
- 如何进行回归。
- 如何处理故障。
- 如何决定阶段完成。
- 如何决定最终发布。

**当前状态：DRAFT V1.0，尚未经过完整审查和批准，不代表系统已经实现或测试通过。**

---

**文档结束**