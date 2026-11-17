# Godot AI Agent 完整开发实施计划

**文档编号：** DOC-02-001  
**版本：** V1.0  
**状态：** DRAFT（初稿）  
**文档类型：** 软件工程实施计划  
**关联文档：** DOC-01-001《Godot AI Agent 完整项目设计说明书》  
**项目名称：** Godot AI Agent

---

# 第一章 开发计划总则

## 1.1 文档目的

本文件用于指导 Godot AI Agent 项目的实际软件开发。

本文件需要回答以下问题：

1. 整个项目分为多少个开发阶段？
2. 每个阶段要完成什么目标？
3. 每个阶段需要开发哪些模块？
4. 每个模块需要拆分成哪些任务？
5. 各任务之间有什么依赖关系？
6. 每个任务具体需要实现什么？
7. 需要新增或修改哪些代码和文件？
8. 每个任务完成后需要进行什么测试？
9. 每个阶段需要交付什么？
10. 如何判断一个阶段已经完成？
11. 如果开发失败、任务中断或测试不通过，如何处理？
12. 如何避免后续阶段破坏之前已经完成的功能？

本文件是开发执行依据，不是单纯的项目时间表。

## 1.2 开发总体原则

### 原则一：先基础设施，后业务能力

先建立可运行、可测试、可恢复的 Backend，再逐步开发项目管理、AI、Agent 和游戏开发能力。

### 原则二：先打通真实链路，再扩展功能

每个重要系统必须至少具备一个真实可运行的端到端流程。

不能只完成接口定义而没有实际执行能力。

### 原则三：每个模块独立验收

每个模块必须具备：

- 明确职责。
- 公开接口。
- 数据模型。
- 状态管理。
- 错误处理。
- 权限检查。
- 单元测试。
- 契约测试。
- 集成测试。

### 原则四：阶段交付必须可运行

每个阶段交付的内容应当能够运行或被自动化测试验证。

不能把大量未实现的接口、空类和占位实现当作阶段完成。

### 原则五：所有项目修改必须受控

所有 Agent 对 Godot 项目的实际修改，必须通过 Tool System，并遵守 ChangeSet、Approval、Resource Lock 和 Verification 规则。

### 原则六：测试贯穿整个项目

每个阶段完成后都需要进行测试和回归。

测试不是 E9 才开始的工作。

### 原则七：保留可恢复能力

Task、Workflow、Agent、Tool 和 Backend 都需要考虑异常退出和恢复。

不能因为 Backend 重启就丢失任务历史或重复执行已经产生的副作用。

---

# 第二章 项目开发阶段总览

## 2.1 十三个阶段

| 阶段 | 阶段名称 | 核心目标 |
|---|---|---|
| E0 | Project Foundation | 建立工程基础 |
| E1 | Backend Core | 建立 Backend 核心 |
| E2 | Backend Services | 建立 Backend 服务 |
| E3 | Godot Integration | 实现 Godot 集成 |
| E4 | Project & Workflow Systems | 实现项目和工作流 |
| E5 | AI & Tool Foundation | 实现模型和工具基础 |
| E6 | Agent Runtime | 实现 Agent 运行系统 |
| E7 | Multi-Agent & Game Development | 实现多 Agent 和游戏开发能力 |
| E8 | Asset Pipeline | 实现游戏资产生产链路 |
| E9 | Verification & QA | 实现验证和质量保证 |
| E10 | Build & Release | 实现构建和交付 |
| E11 | Platformer Demo | 完成端到端游戏开发 Demo |
| E12 | Productization | 产品化、安装和最终验收 |

## 2.2 阶段依赖关系

主要开发依赖如下：

E0 → E1 → E2 → E3 → E4 → E5 → E6 → E7。

E8 依赖 E4、E5、E6 的基础能力。

E9 需要随着 E0–E8 持续建设，并在本阶段完成完整质量体系。

E10 依赖 E3、E9 和 Godot CLI 能力。

E11 集成 E3–E10 的实际能力。

E12 在完整端到端验证基础上完成产品化。

说明：

- E9 的测试框架不能等到 E9 才建立。
- E8 可以提前进行独立 Provider 和资源处理模块的技术验证，但正式业务链路依赖前置基础设施。
- E11 是系统完整能力的综合验收，不是用 Demo 代替各模块测试。
- E12 不允许通过降低质量门槛来完成交付。

## 2.3 开发优先级

每项任务使用以下优先级：

- P0：第一阶段产品不可缺少的功能。
- P1：重要能力，可以在核心闭环之后交付。
- P2：高级扩展能力。

优先级决定开发重要性，不代表任务一定按数字顺序执行。

## 2.4 每个任务的统一记录格式

每项工程任务必须记录：

| 字段 | 说明 |
|---|---|
| Task ID | 唯一任务编号 |
| Task Name | 任务名称 |
| Objective | 任务目标 |
| Scope | 任务范围 |
| Prerequisites | 前置依赖 |
| Implementation | 具体实现内容 |
| Files | 需要创建或修改的文件 |
| Interface | 对外接口 |
| Data | 数据模型 |
| Security | 权限和安全要求 |
| Tests | 测试要求 |
| Deliverables | 交付物 |
| Acceptance | 验收标准 |

每个任务必须有明确的完成证据。

---

# 第三章 E0：Project Foundation

## 3.1 阶段目标

建立整个项目的软件工程基础。

E0 完成后，开发人员应当能够：

- 获取项目代码。
- 安装开发环境。
- 启动基础 Backend。
- 执行自动化测试。
- 检查代码质量。
- 构建开发版本。
- 使用统一的代码和文档规范。

## 3.2 开发范围

- 项目仓库。
- 代码目录。
- Python 运行环境。
- Godot 插件基础工程。
- 配置管理基础。
- 测试基础设施。
- CI。
- 日志基础。
- 文档管理。

## 3.3 任务分解

### E0.1 项目仓库初始化

具体工作：

1. 创建 Git Repository。
2. 建立主分支和开发分支策略。
3. 配置 `.gitignore`。
4. 配置 License 和项目说明。
5. 建立版本号规则。
6. 建立 Pull Request 模板。
7. 建立 Issue 模板。
8. 配置提交信息规范。

交付物：

- Git Repository。
- CONTRIBUTING.md。
- LICENSE。
- README.md。

### E0.2 Backend 工程初始化

具体工作：

1. 创建 Backend Python 项目。
2. 配置 Python 版本。
3. 建立依赖管理文件。
4. 建立应用入口。
5. 建立开发环境配置。
6. 建立测试环境配置。
7. 建立统一异常基类。
8. 建立基础日志输出。

交付物：

- 可启动的 Backend Skeleton。
- 依赖锁定文件。
- 基础启动命令。

### E0.3 Godot Plugin 工程初始化

具体工作：

1. 建立插件目录。
2. 创建 `plugin.cfg`。
3. 创建 EditorPlugin 主入口。
4. 建立插件启用和禁用逻辑。
5. 建立插件 UI 基础容器。
6. 建立插件配置读取接口。
7. 建立插件调试日志。

交付物：

- 可以被 Godot 正常识别的空插件。
- 插件启用和禁用测试。

### E0.4 工程代码规范

建立：

- Python 类型规范。
- GDScript 编码规范。
- 命名规范。
- 文件命名规范。
- 模块命名规范。
- 错误处理规范。
- 日志规范。
- API 规范。
- 文档规范。

### E0.5 测试框架

具体工作：

1. 配置 Python 单元测试。
2. 配置 GDScript 测试工具链。
3. 建立测试目录。
4. 建立测试数据目录。
5. 建立 Mock 和 Fixture。
6. 建立测试结果输出。
7. 建立测试失败时的 CI 阻断规则。

### E0.6 CI 基础

建立自动化流程：

1. 代码格式检查。
2. 静态类型检查。
3. 静态代码检查。
4. 单元测试。
5. 构建检查。
6. 测试报告归档。

## 3.4 推荐代码结构

```text
godot-ai-agent/
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   └── godot_ai/
│   │       ├── __init__.py
│   │       └── main.py
│   └── tests/
├── godot_plugin/
│   ├── plugin.cfg
│   ├── plugin.gd
│   └── ui/
├── shared/
│   └── contracts/
├── scripts/
├── tests/
├── docs/
├── .github/
│   └── workflows/
├── .gitignore
└── README.md
```

这是初始工程结构。后续阶段可以在不破坏模块边界的前提下扩展。

## 3.5 阶段测试

- T-E0-001：Backend 能够启动。
- T-E0-002：Backend 能够正常关闭。
- T-E0-003：Godot 能识别插件。
- T-E0-004：插件可以启用和禁用。
- T-E0-005：测试框架能够执行测试。
- T-E0-006：CI 能够发现测试失败。
- T-E0-007：依赖安装能够复现。
- T-E0-008：项目结构和代码规范检查通过。

## 3.6 阶段交付

- 工程仓库。
- 开发环境配置。
- Backend Skeleton。
- Godot Plugin Skeleton。
- CI 基础流程。
- 测试基础框架。
- 工程规范文档。

## 3.7 阶段完成标准

- 新开发人员能够按照文档建立环境。
- Backend 能启动和关闭。
- Godot 插件能够加载。
- 自动化测试可以执行。
- CI 可以阻断失败提交。
- 没有依赖不明或无法复现的基础环境。

---

# 第四章 E1：Backend Core

## 4.1 阶段目标

建立 Backend 的核心运行基础。

E1 结束时应有一个真正可运行的模块化 Backend，具备模块注册、数据库、事件和基础生命周期能力。

## 4.2 开发范围

- Backend Lifecycle。
- Module Registry。
- Service Container。
- Module Interface Registry。
- SQLite。
- Repository。
- Unified Data Model。
- Event System。
- Internal Message Bus。
- Outbox。

## 4.3 任务分解

### E1.1 Backend Application Lifecycle

实现：

1. 启动入口。
2. Bootstrap。
3. 模块加载。
4. 健康检查。
5. 受控关闭。
6. 启动失败处理。
7. 生命周期状态记录。

需要实现的生命周期状态：

- INITIALIZING。
- STARTING。
- READY。
- READY_DEGRADED。
- SHUTTING_DOWN。
- STOPPED。
- FAILED。

### E1.2 Service Container

实现：

- Service Registration。
- Service Resolution。
- Singleton Scope。
- Scoped Service。
- Lifecycle Hook。
- Dependency Validation。

禁止模块自行创建无法管理的全局共享服务。

### E1.3 Module Interface Registry

实现：

- Module Definition。
- Interface Definition。
- Schema Definition。
- Interface Version。
- Dependency Registration。
- Compatibility Check。
- Permission Metadata。
- Timeout Metadata。
- Retry Metadata。
- Idempotency Metadata。

### E1.4 Module Dependency Graph

实现：

1. 模块依赖登记。
2. 依赖关系图生成。
3. 拓扑排序。
4. 循环依赖检测。
5. 缺失依赖检测。
6. 启动顺序计算。
7. 模块停机顺序计算。

启动时必须阻止未满足依赖的模块进入 READY。

### E1.5 Unified Data Model

实现：

- UUIDv7 ID Generator。
- Entity Base Model。
- Version Metadata。
- Timestamp。
- Provenance。
- Lifecycle Metadata。
- Correlation ID。
- Execution ID。

区分实体 ID、执行 ID、版本 ID 和 Godot UID。

### E1.6 SQLite Database

实现：

1. SQLite 连接管理。
2. WAL 模式。
3. Schema Version。
4. Migration Runner。
5. Backup。
6. Transaction。
7. Connection Lifecycle。
8. Database Health Check。

### E1.7 Repository Layer

实现：

- Repository Base。
- Entity Repository。
- Transaction Boundary。
- Unit of Work。
- Optimistic Concurrency。
- Query Specification。

Repository 必须由对应业务模块拥有。

### E1.8 Event System

实现：

- Event Envelope。
- Event ID。
- Aggregate ID。
- Sequence。
- Event Version。
- Timestamp。
- Correlation ID。
- Causation ID。
- Event Persistence。

### E1.9 Internal Message Bus

实现：

- Event Subscription。
- Event Dispatch。
- At-least-once Delivery。
- Inbox Idempotency。
- Retry。
- Dead Letter。
- Aggregate Ordering。
- Gap Detection。

### E1.10 Outbox Dispatcher

实现：

1. 业务状态和 Outbox 记录在同一数据库事务提交。
2. 后台扫描待派发记录。
3. 成功派发后标记完成。
4. 失败进入重试。
5. 超过策略限制进入 Dead Letter。
6. 支持服务重启后继续派发。

### E1.11 Backend Contract Catalog

登记：

- Module。
- Interface。
- Schema。
- Event。
- Error。
- Permission。
- Version。
- Test。

## 4.4 主要代码结构

```text
backend/src/godot_ai/
├── bootstrap/
│   ├── application.py
│   └── startup.py
├── core/
│   ├── identity/
│   ├── lifecycle/
│   ├── errors/
│   └── context/
├── module_system/
│   ├── registry.py
│   ├── dependency_graph.py
│   └── service_container.py
├── contracts/
│   ├── module_registry.py
│   ├── interface_registry.py
│   └── schema_registry.py
├── database/
│   ├── connection.py
│   ├── migrations/
│   ├── repositories/
│   └── unit_of_work.py
├── events/
│   ├── envelope.py
│   ├── event_store.py
│   ├── message_bus.py
│   ├── outbox.py
│   └── inbox.py
└── main.py
```

## 4.5 阶段测试

- 模块启动顺序测试。
- 循环依赖测试。
- 缺失依赖测试。
- 数据库迁移测试。
- 事务回滚测试。
- 乐观并发冲突测试。
- Event 重复投递测试。
- Outbox 重启恢复测试。
- Dead Letter 测试。
- Backend Graceful Shutdown 测试。

## 4.6 阶段交付

- 可运行 Backend Core。
- Module Registry。
- Interface Registry。
- SQLite。
- Repository Layer。
- Event System。
- Internal Message Bus。
- Outbox。
- Contract Catalog。

## 4.7 阶段完成标准

Backend 能够在不依赖 Godot Editor 的情况下独立运行，模块依赖明确，数据库可迁移，事件可持久化，进程重启后可以恢复未完成的事件派发。

---

# 第五章 E2：Backend Services

## 5.1 阶段目标

建立 Backend 面向插件和内部业务系统的完整服务能力。

## 5.2 任务分解

### E2.1 API Gateway

实现：

- HTTP Server。
- API Version。
- Request Validation。
- Response Standardization。
- Authentication。
- Authorization Hook。
- Rate Limiting。
- Error Mapping。
- Health Endpoint。

### E2.2 WebSocket Gateway

实现：

- WebSocket Connection。
- Client Identity。
- Session Binding。
- Heartbeat。
- Message Envelope。
- Subscription。
- Reconnection。
- Connection Timeout。

### E2.3 Unified Invocation Gateway

实现：

- 统一调用身份。
- 调用者类型。
- Project Context。
- Execution Context。
- Correlation ID。
- Permission Context。
- Timeout。
- Cancellation Token。
- Invocation Result。

API Gateway 和 Unified Invocation Gateway 必须保持职责分离。

### E2.4 Configuration Manager

实现六类配置：

- System Configuration。
- Module Configuration。
- Provider Configuration。
- Project Configuration。
- User Configuration。
- Runtime Configuration。

配置读取需要有优先级和安全策略。

### E2.5 Secrets Manager

实现：

- OS Credential Store Adapter。
- Encrypted Vault。
- Secret Reference。
- Secret Rotation。
- Secret Access Audit。
- Secret Redaction。

数据库不得保存明文 Provider 凭证。

Agent 不得直接读取明文凭证。

### E2.6 Security Policy Engine

实现：

- Identity。
- RBAC。
- ABAC。
- Capability。
- Trust Domain。
- Permission Decision。
- Policy Version。
- Security Audit。

UNKNOWN 默认拒绝。

### E2.7 Logging

实现：

- Structured Logging。
- Log Level。
- Correlation ID。
- Project ID。
- Task ID。
- Agent ID。
- Tool Execution ID。
- Secret Redaction。

### E2.8 Metrics

实现：

- Backend Health。
- Request Count。
- Request Latency。
- Task Count。
- Worker Utilization。
- Database Operation。
- Event Queue。
- Error Count。

具体性能目标需要通过实际设备基准测试确定。

### E2.9 Tracing

实现跨模块执行追踪：

用户请求 → Task → Workflow → Agent → Model Call / Tool Call → Verification。

### E2.10 Recovery Coordinator

实现统一恢复协调入口。

负责协调模块恢复，不直接代替模块恢复自身业务状态。

## 5.3 阶段测试

- API 认证和授权测试。
- WebSocket 心跳测试。
- Session 过期测试。
- 配置优先级测试。
- Secrets 加密和脱敏测试。
- 权限拒绝测试。
- 日志敏感信息扫描。
- Metrics 完整性测试。
- Trace 关联测试。
- Backend Crash Recovery 测试。

## 5.4 阶段交付

- API Gateway。
- WebSocket Gateway。
- Invocation Gateway。
- Configuration Manager。
- Secrets Manager。
- Security Policy Engine。
- Logging、Metrics、Tracing。
- Recovery Coordinator。

---

# 第六章 E3：Godot Integration

## 6.1 阶段目标

建立 Backend 与真实 Godot Editor、Runtime 和 CLI 之间的通信和操作能力。

这是本项目最重要的基础阶段之一。

## 6.2 开发范围

- Godot Editor Plugin。
- Backend Discovery。
- Authentication。
- Session。
- Editor Bridge。
- Runtime Bridge。
- CLI Runner。
- Filesystem Adapter。
- Version Adapter。
- Capability Detector。
- Project State Synchronization。

## 6.3 任务分解

### E3.1 Plugin Lifecycle

实现插件状态：

- DISABLED。
- INITIALIZING。
- DISCOVERING_BACKEND。
- WAITING_BACKEND。
- AUTHENTICATING。
- SYNCHRONIZING。
- READY。
- DEGRADED。
- RECONNECTING。
- SHUTTING_DOWN。
- STOPPED。
- FAILED。

测试启用、禁用、重载和 Editor 关闭场景。

### E3.2 Backend Discovery

实现：

1. Backend 发现。
2. Backend Identity 获取。
3. PID 检查。
4. Process Start Time 检查。
5. Startup Nonce 检查。
6. Backend Version 检查。
7. Protocol Version 检查。
8. Data Directory Identity 检查。

不得只凭端口响应就认定 Backend 身份正确。

### E3.3 Session Authentication

实现：

- Challenge-Response。
- Session Lease。
- Heartbeat。
- Session Token。
- Session Expiration。
- Session Renewal。
- Reauthentication。

### E3.4 Editor WebSocket Bridge

实现：

- 建立连接。
- 消息发送。
- 消息接收。
- 请求响应关联。
- Event Subscription。
- 心跳。
- 断线检测。
- 重连。

### E3.5 Editor Snapshot & Event Recovery

实现：

1. 连接后获取 Snapshot。
2. 获取上次已确认事件位置。
3. 检测事件缺口。
4. 补偿可恢复事件。
5. 核实实际操作副作用。
6. 处理 UNKNOWN 状态。
7. 重建 Editor Session 状态。

### E3.6 Editor State Adapter

获取真实 Editor 状态：

- 当前项目。
- 当前 Scene。
- Scene Tree。
- 当前选择。
- 当前 Inspector 对象。
- 当前编辑器状态。
- 未保存资源状态。

不得由 Backend 自行模拟这些状态。

### E3.7 Godot Editor 操作基础

先实现基础操作：

- 获取项目信息。
- 获取 Scene。
- 获取 Node Tree。
- 获取 Node 属性。
- 创建 Node。
- 删除 Node。
- 修改 Node 属性。
- 保存 Scene。
- 获取 Resource 信息。

所有写入必须走 Tool System。

### E3.8 Godot Editor 高级操作

逐步实现：

- Inspector。
- Signal。
- Group。
- Resource。
- Animation。
- TileMapLayer。
- Scene 结构调整。
- 资源引用检查。

每种工具需要单独的输入 Schema、输出 Schema、权限和测试。

### E3.9 Filesystem Adapter

实现：

- 授权根目录。
- 路径规范化。
- 路径穿越防护。
- 符号链接逃逸防护。
- 文件读取。
- 文件写入。
- 目录扫描。
- 文件哈希。
- 原子替换。
- 备份恢复。
- 文件变更通知。

### E3.10 Godot Runtime Bridge

实现：

- Runtime Probe。
- Runtime Identity。
- Session Authentication。
- Runtime Snapshot。
- Runtime Event。
- Debug 信息获取。
- 游戏状态读取。
- 受控 Runtime Mutation。

### E3.11 Godot CLI Runner

实现：

- EDITOR 模式。
- STANDALONE 模式。
- HEADLESS 模式。
- TEST 模式。
- IMPORT 模式。
- BUILD 模式。

统一管理进程启动、超时、退出码、输出和取消。

### E3.12 Version Adapter & Capability Detector

实现：

- Godot Version Detection。
- Feature Capability。
- Tool Compatibility。
- Unsupported Feature。
- UNKNOWN Capability。
- Compatibility Report。

未知能力不得默认开放操作。

### E3.13 Project State Synchronization

协调 Disk、Editor、Runtime 三种状态。

处理：

- 未保存 Scene。
- 外部文件修改。
- 资源导入。
- Editor Refresh。
- Runtime 旧版本。
- 新 Runtime 测试实例。

## 6.4 阶段交付

- 可用 Godot 插件。
- Editor Bridge。
- Runtime Bridge。
- CLI Runner。
- Filesystem Adapter。
- Version Adapter。
- Capability Detector。
- Project State Synchronization。

## 6.5 阶段验收

必须通过 G01 的 `GodotBackendLifecycleTestSuite` 16 项测试。

此外需要验证：

- 插件断线重连。
- Backend 重启恢复。
- 多 Editor 连接。
- 多项目隔离。
- 未保存 Scene 冲突。
- Editor 与文件系统状态冲突。
- Runtime Session 恢复。

---

# 第七章 E4：Project & Workflow Systems

## 7.1 阶段目标

建立项目管理、需求、任务、工作流、审批和变更管理能力。

## 7.2 任务分解

### E4.1 Project Manager

实现：

- Project 创建。
- Project 绑定。
- Project Registry。
- Project Configuration。
- Project Status。
- Project Isolation。
- Project History。

### E4.2 Project Scanner

实现：

- Godot 项目扫描。
- 项目结构识别。
- Project Configuration 解析。
- Scene 清单。
- Script 清单。
- Resource 清单。
- 文件哈希。
- 项目版本快照。

### E4.3 Requirement Management

实现：

- Requirement。
- Requirement Version。
- Acceptance Criteria。
- Requirement Dependency。
- Requirement Change。
- Requirement Confirmation。

Agent 的推测不能自动视为用户确认的需求。

### E4.4 Task System

实现：

- Task Model。
- Task State Machine。
- Task Attempt。
- Task Dependency DAG。
- Task Queue。
- Task Pause。
- Task Resume。
- Task Cancel。
- Task Retry。
- Task History。

Task 状态由 Task System 独占管理。

### E4.5 Workflow Definition

实现：

- Workflow Definition。
- Workflow Version。
- Workflow Node。
- Workflow Edge。
- Workflow Variable。
- Workflow Condition。
- Workflow Template。

### E4.6 Workflow Runtime

实现：

- Workflow Instance。
- Node Execution。
- Parallel Execution。
- Conditional Branch。
- Human Node。
- Retry。
- Pause。
- Resume。
- Compensation。
- Recovery。

### E4.7 Phase Manager

实现自主开发阶段管理。

Phase 状态、完成条件和验收结果必须明确记录。

Phase ACCEPTED 后才允许进入下一阶段。

### E4.8 Approval System

实现：

- Approval Request。
- Approval Scope。
- Approval Decision。
- Approval Expiration。
- Approval Audit。
- Hash Binding。

审批对象发生实质变化时必须重新审批。

### E4.9 ChangeSet Manager

实现：

- ChangeSet。
- Change Item。
- Before Hash。
- After Hash。
- Change Reason。
- Change Risk。
- Approval Binding。
- Apply Result。
- Rollback Metadata。

取消任务不等于回滚 ChangeSet。

## 7.3 阶段交付

- Project Manager。
- Requirement Management。
- Task System。
- Workflow Engine。
- Phase Manager。
- Approval System。
- ChangeSet Manager。

## 7.4 阶段验收

能够完成：

创建项目 → 创建需求 → 创建 Task → 建立 Workflow → 执行节点 → 生成 ChangeSet → 用户审批 → 执行 → 验收。

同时必须通过任务暂停、取消、重试、崩溃恢复和阶段验收测试。

---

# 第八章 E5：AI & Tool Foundation

## 8.1 阶段目标

建立统一 AI 模型服务和工具执行基础，为 Agent Runtime 提供安全的模型调用和项目操作能力。

## 8.2 Model Gateway 任务

### E5.1 Provider Registry

实现：

- Provider Definition。
- Provider Configuration。
- Provider Identity。
- Authentication Reference。
- Provider Health。
- Provider Trust Level。

### E5.2 Model Registry

实现：

- Model Identity。
- Model Capability。
- Context Window。
- Input Modality。
- Output Modality。
- Tool Calling Capability。
- Model Version。
- Availability。

### E5.3 Deployment Registry

管理真实可用的模型部署和连接参数引用。

### E5.4 Provider Adapter

建立统一 Adapter 接口。

至少支持第一阶段选定的模型 Provider。

各 Provider 必须有独立适配器和契约测试。

### E5.5 Model Gateway

实现：

- 统一请求。
- 请求标准化。
- Provider 调用。
- 结果标准化。
- Streaming。
- Multimodal。
- Timeout。
- Cancellation。
- Retry。
- Error Mapping。

### E5.6 Model Router

实现：

- 用户指定模型。
- Capability Filter。
- Policy Filter。
- Budget Filter。
- Provider Health。
- Fallback Policy。

### E5.7 Token & Cost Manager

实现：

- Token Usage。
- Cost Calculation。
- Pricing Registry。
- Budget Reservation。
- Cost Ledger。
- Threshold Alert。
- Budget Enforcement。

预算告警阈值按已确认策略实现 70%、85%、95%、100% 级别。

### E5.8 Data Governance

实现：

- D0–D3 数据分类。
- Provider Trust T0–T4。
- Data Authorization。
- DLP。
- Redaction。
- Prompt Injection Guard。
- Retention。
- Deletion。

## 8.3 Tool System 任务

### E5.9 Tool Registry

实现：

- Tool Definition。
- Tool Version。
- Tool Schema。
- Tool Capability。
- Tool Permission。
- Tool Side Effect。
- Tool Risk Level。

### E5.10 Tool Permission

实现：

- Definition Permission。
- Instance Permission。
- Execution Authorization。
- Project Scope。
- User Approval。
- External Data Authorization。

### E5.11 Tool Execution Engine

实现：

- Request Validation。
- Authorization。
- Risk Assessment。
- Precondition Check。
- Queue。
- Execution Intent。
- Execution。
- Postcondition Check。
- Result Persistence。
- Event Publication。

### E5.12 Tool Result Management

实现执行结果和副作用状态的独立管理。

### E5.13 Resource Lock

实现：

- Lock Identity。
- Lock Scope。
- Lease。
- Fencing Token。
- Lock Renewal。
- Lock Release。
- Stale Lock Recovery。

### E5.14 Adapter Framework

建立统一 Adapter 生命周期。

第三方和自定义工具默认在受控隔离进程运行。

## 8.4 阶段交付

- Model Gateway。
- Provider Registry。
- Model Registry。
- Model Router。
- Token & Cost Manager。
- Data Governance。
- Tool Registry。
- Tool Execution Engine。
- Permission System。
- Resource Lock。
- Adapter Framework。

## 8.5 阶段验收

必须证明：

- Agent 不能直接调用 Provider。
- 工具不能绕过权限。
- 写入必须经过 ChangeSet。
- UNKNOWN 不会被当作成功。
- 预算能够阻止超限调用。
- 外部数据传输必须得到授权。
- Tool 重试不会导致未知副作用重复执行。

---

# 第九章 E6：Agent Runtime

## 9.1 阶段目标

建立可以真实运行、管理、暂停、恢复和监控 Agent 的执行系统。

## 9.2 任务分解

### E6.1 Agent Definition Schema

实现完整 Agent Definition：

- Identity。
- Role。
- Capabilities。
- Skills。
- Tools。
- Permissions。
- Model。
- Context。
- Instructions。
- Interface。
- Execution。
- Validation。

### E6.2 Agent Registry

实现：

- Agent Registration。
- Built-in Agent。
- Plugin Agent。
- Custom Agent。
- Version Management。
- Compatibility Check。

### E6.3 Capability Registry

维护 Agent 能力定义和匹配索引。

### E6.4 Skill Registry

管理 Skill 定义、版本和适用条件。

Capability、Skill、Tool 必须是不同的实体和职责。

### E6.5 Agent Instance Manager

实现：

- Instance Creation。
- Definition Snapshot。
- Permission Snapshot。
- Context Binding。
- Execution Identity。
- Instance Lifecycle。

### E6.6 Agent Execution Loop

实现受控 Agent Loop：

1. 获取任务。
2. 组织上下文。
3. 调用模型。
4. 解析行动请求。
5. 检查预算。
6. 请求 Tool。
7. 收集执行结果。
8. 更新执行状态。
9. 决定继续、等待、完成或失败。

### E6.7 Agent Checkpoint

实现：

- Checkpoint ID。
- Agent State Snapshot。
- Context Revision。
- Tool History Reference。
- Execution Budget。
- Recovery Metadata。

### E6.8 Agent Handoff Interface

实现：

- Handoff Request。
- Handoff Context。
- Shared Contract Reference。
- Result Contract。
- Handoff Status。
- Handoff History。

Agent 只能向 Orchestrator 提交 Handoff。

### E6.9 Agent Monitoring

实现：

- Agent State。
- Current Task。
- Current Attempt。
- Model Call。
- Tool Call。
- Token Usage。
- Cost。
- Time。
- Error。
- Checkpoint。

### E6.10 Agent Result Trust

实现：

- VERIFIED。
- OBSERVED。
- INFERRED。
- UNVERIFIED。
- FAILED。

未验证的 Agent 结果不能直接作为公共项目事实。

## 9.3 阶段交付

- Agent Registry。
- Agent Definition。
- Agent Runtime。
- Agent Instance Manager。
- Agent Execution Loop。
- Checkpoint。
- Handoff Interface。
- Monitoring。

## 9.4 阶段验收

至少实现一个能够真实运行的 Agent，完成：

接收 Task → 获取 Context → 调用 Model → 请求 Tool → 获取结果 → 生成输出 → 保存 Checkpoint → 完成任务。

必须通过 Agent 超时、模型失败、Tool 失败、Backend 重启和 Agent 恢复测试。

---

# 第十章 E7：Multi-Agent & Game Development

## 10.1 阶段目标

让系统从单 Agent 执行升级为多 Agent 协作，并开始具备实际游戏开发能力。

## 10.2 多 Agent 任务

### E7.1 Orchestrator

实现唯一 Agent 分配和 Handoff 协调入口。

### E7.2 Agent Matching

按照以下顺序筛选：

1. 能力。
2. 权限。
3. 预算。
4. 专业度。
5. 历史表现。
6. 可用性。

能力和权限是硬过滤条件。

### E7.3 Multi-Agent Task Graph

实现：

- 子任务 DAG。
- 依赖关系。
- 并行分支。
- 失败分支。
- 结果汇总。
- Integration Status。

### E7.4 Shared Context

实现：

- Project Knowledge Reference。
- Task Shared Context。
- Agent Private Context。
- Shared Contract Reference。
- Context Revision。

### E7.5 Resource Coordination

实现：

- 文件资源锁。
- Scene 资源锁。
- Resource 锁。
- Project 锁。
- 租约。
- Fencing Token。
- 统一锁获取顺序。

### E7.6 Collaboration Result

实现：

- 子任务结果。
- 完成状态。
- 证据。
- 变更引用。
- 依赖影响。
- 整合状态。

Lead Agent 负责整合结果，Verification 独立验收。

### E7.7 Failure Isolation

实现：

- Agent Failure。
- Branch Isolation。
- Lead Failure。
- Orchestrator Takeover。
- Failed Result Preservation。
- Retry Planning。

## 10.3 专业 Agent 开发

按产品优先级分批实现 38 个 Agent。

第一批 P0：

- game_designer。
- gameplay_designer。
- level_designer。
- game_architect。
- gameplay_programmer。
- ui_developer。
- scene_developer。
- inspector_property_specialist。
- tilemap_level_specialist。
- godot_resource_specialist。
- godot_integration_specialist。
- 2d_artist。
- ui_ux_designer。
- animation_specialist。
- qa_engineer。

每个 Agent 必须完成：

1. Definition。
2. Role。
3. Capabilities。
4. Skills。
5. Tool Allowlist。
6. Permission。
7. Model Policy。
8. Context Policy。
9. Input Contract。
10. Output Contract。
11. Escalation Rule。
12. Collaboration Rule。
13. Validation Rule。
14. 单元和集成测试。

P1 和 P2 Agent 按后续具体需求逐批开发，不以数量完成作为唯一验收条件。

## 10.4 游戏开发能力

实现：

- 游戏需求分析。
- Game Design Document。
- 游戏系统设计。
- 游戏架构设计。
- 玩家控制系统。
- Gameplay 代码生成。
- Scene 结构规划。
- Node 创建与配置。
- UI 开发。
- Signal 连接。
- TileMap 关卡。
- Resource 引用管理。
- 游戏交互。

## 10.5 阶段交付

- Multi-Agent Orchestrator。
- Agent Matching。
- Collaboration Runtime。
- Resource Coordination。
- P0 专业 Agent。
- 游戏设计和程序开发能力。

## 10.6 阶段验收

至少完成一个跨多个专业 Agent 的真实游戏开发任务。

验证：

- 正确分配 Agent。
- 子任务依赖正确。
- 写入不冲突。
- Handoff 正确。
- Lead 能整合结果。
- Lead 故障能够恢复。
- Verification 能独立判断结果。

---

# 第十一章 E8：Asset Pipeline

## 11.1 阶段目标

实现从游戏资源需求到生成、处理、管理、导入和验证的完整流程。

## 11.2 任务分解

### E8.1 Asset Request

实现：

- Asset Request。
- Asset Specification。
- Resource Requirement。
- Style Requirement。
- Format Requirement。
- Size Requirement。

### E8.2 Generation Job

实现：

- Job Creation。
- Job Validation。
- Planning。
- Queue。
- Submission。
- Generation。
- Result Collection。
- Verification。
- Retry。
- Cancellation。
- Recovery。

### E8.3 Provider Integration

实现统一 Provider Adapter。

需要支持：

- 图片生成 Provider。
- 音频生成 Provider。
- 后续可扩展的视频和 3D Provider。

### E8.4 Raw Asset Collection

实现：

- 生成结果接收。
- 原始文件保存。
- 文件哈希。
- 来源记录。
- 结果关联。
- Provider 调用记录。

### E8.5 Asset Processing

实现：

- 格式转换。
- 图片尺寸处理。
- 透明通道检查。
- Sprite Sheet 切帧。
- 音频格式处理。
- 音频时长和基本属性检查。
- 批量变体处理。

### E8.6 Quality Control

实现：

- 文件完整性。
- 尺寸检查。
- 格式检查。
- Alpha 检查。
- 内容质量检查。
- 变体一致性检查。

### E8.7 Asset Registry

实现：

- Asset Identity。
- Asset Version。
- Asset File。
- Asset Relationship。
- Version History。
- Reference Tracking。

### E8.8 Provenance & License

实现：

- Provider Source。
- Model Source。
- Generation Parameters Reference。
- License Record。
- Derivation Relationship。
- Review Status。
- Delivery Eligibility。

### E8.9 Asset Storage

实现：

- Raw Storage。
- Processed Storage。
- Accepted Storage。
- Temporary Storage。
- Versioned Storage。
- Recovery Metadata。

### E8.10 Godot Import

实现：

1. 生成候选资源。
2. 检查项目写入权限。
3. 创建 ChangeSet。
4. 等待审批。
5. 通过 Tool System 写入。
6. 通知 Godot Editor。
7. 等待资源导入。
8. 检查 UID。
9. 检查 Resource Reference。
10. 执行实际场景集成验证。

### E8.11 Asset Verification

实现：

- Asset File Verification。
- Import Verification。
- Reference Verification。
- Scene Integration Verification。
- Provenance Verification。
- License Verification。

## 11.3 第一阶段资产范围

P0：

- 2D 图片。
- 图片变体。
- Sprite Sheet。
- 2D 音效。
- 格式和尺寸处理。
- Asset Registry。
- 版本管理。
- 基础 License Governance。
- Godot Import。

P1：

- 背景音乐。
- 复杂动画。
- 批量风格一致性。

P2：

- 视频。
- 3D 模型。
- 高级骨骼动画。

## 11.4 阶段交付

完整 Asset Pipeline、Provider Adapter、Processing Pipeline、Asset Registry、Governance、Godot Import 和验证能力。

## 11.5 阶段验收

必须通过：

- Generation Job 生命周期测试。
- Provider 超时恢复测试。
- 非幂等请求 UNKNOWN 测试。
- 部分成功测试。
- 资产版本测试。
- License 阻断测试。
- Godot Import 测试。
- UID 和资源引用测试。
- Asset Pipeline Test Suite。

---

# 第十二章 E9：Verification & QA

## 12.1 阶段目标

建立贯穿项目的统一质量保证体系。

本阶段完成的是完整验证平台；之前各阶段已经建立的测试不能删除或替代。

## 12.2 任务分解

### E9.1 Requirement Traceability

实现：

Requirement → Acceptance Criteria → Task → ChangeSet → Test Case → Evidence → Verification Result。

### E9.2 Test Case Management

实现：

- Test Case。
- Test Suite。
- Test Plan。
- Test Environment。
- Test Data。
- Test Version。
- Test Dependency。

### E9.3 Test Execution Engine

实现：

- Test Scheduling。
- Test Execution。
- Timeout。
- Retry Policy。
- Result Collection。
- Evidence Collection。
- Test Report。

### E9.4 Evidence Management

实现：

- Evidence ID。
- Evidence Source。
- Test Run。
- Project Revision。
- Build Revision。
- Timestamp。
- Evidence Validity。
- Evidence Expiration。

旧版本证据不能证明新版本通过。

### E9.5 Verification Engine

实现六层验证：

1. Operation。
2. Structural。
3. Static。
4. Runtime。
5. Integration & Regression。
6. Requirement & Phase Acceptance。

### E9.6 Defect Management

实现：

- Bug Creation。
- Severity。
- Priority。
- Assignment。
- Reproduction Steps。
- Root Cause。
- Fix Reference。
- Retest。
- Regression。
- Closure。

### E9.7 Regression Manager

实现：

- Test Baseline。
- Impact Analysis。
- Regression Selection。
- Full Regression。
- Test Result Comparison。
- Regression Report。

### E9.8 Phase Review

实现：

- Phase Deliverable Check。
- Requirement Coverage。
- Test Result Review。
- Open Defect Review。
- Risk Review。
- User Acceptance。
- Phase Decision。

### E9.9 Release Gate

实现统一质量门禁。

真实测试失败不能被修改成通过。

非关键缺陷的延期处理必须有明确的用户授权和风险记录。

## 12.3 阶段交付

- Test Management。
- Test Execution Engine。
- Verification Engine。
- Evidence Management。
- Defect Management。
- Regression Manager。
- Phase Review。
- Release Gate。

## 12.4 阶段验收

能够追踪一个需求从提出到实现、测试、缺陷修复和最终验收的完整过程。

---

# 第十三章 E10：Build & Release

## 13.1 阶段目标

建立 Godot 游戏构建、导出、打包和交付能力。

## 13.2 任务分解

### E10.1 Build Configuration

实现：

- Build Profile。
- Godot Version。
- Target Platform。
- Export Preset。
- Build Environment。
- Build Variables。

### E10.2 Project Validation

构建前检查：

- 项目结构。
- Scene 引用。
- Script。
- Resource。
- UID。
- Import 状态。
- License。
- Test Result。

### E10.3 Godot Export Adapter

通过 Godot CLI 执行真实导出。

管理：

- 参数。
- 工作目录。
- 进程。
- 标准输出。
- 标准错误。
- 超时。
- 退出码。

### E10.4 Artifact Manager

实现：

- Artifact Identity。
- Artifact Version。
- Artifact Hash。
- Build Metadata。
- Artifact Storage。
- Artifact Retention。

### E10.5 Package Manager

实现：

- Package Manifest。
- 文件清单。
- 依赖清单。
- 版本信息。
- 校验信息。

### E10.6 Release Manager

实现：

- Release Candidate。
- Release Approval。
- Release Package。
- Release Record。
- Release History。

### E10.7 Build Recovery

处理：

- 构建进程异常。
- 导出超时。
- 部分产物。
- 重复构建。
- 产物损坏。
- 校验失败。

## 13.3 阶段交付

- Build Manager。
- Godot Export Adapter。
- Artifact Manager。
- Package Manager。
- Release Manager。

## 13.4 阶段验收

至少完成一个 Godot 游戏项目的完整构建、导出、产物校验和打包。

---

# 第十四章 E11：Platformer Demo

## 14.1 阶段目标

通过一个真实 2D Platformer 游戏，验证系统是否具备端到端自主开发能力。

这是系统级综合验收阶段。

## 14.2 Demo 需求

### 玩家系统

- 移动。
- 跳跃。
- 攻击。
- 受伤。
- 死亡。
- 重生。

### 关卡系统

- TileMapLayer。
- 地面。
- 平台。
- 碰撞。
- 陷阱。
- 出生点。
- 终点。

### 敌人系统

- 巡逻。
- 发现玩家。
- 攻击。
- 受伤。
- 死亡。

### 游戏系统

- 生命值。
- 收集物。
- 计分。
- 游戏状态。
- 暂停。
- 胜利结算。
- 失败结算。

### UI

- 主菜单。
- HUD。
- 生命显示。
- 计分显示。
- 暂停菜单。
- 游戏结束界面。

### 游戏表现

- 玩家动画。
- 敌人动画。
- 特效。
- 音效。
- 基础背景。

## 14.3 开发任务

### E11.1 游戏需求确认

生成：

- Game Concept。
- Game Design Document。
- Feature List。
- Acceptance Criteria。

### E11.2 游戏架构设计

生成：

- Scene Architecture。
- Node Architecture。
- Script Architecture。
- Resource Plan。
- Gameplay System Design。

### E11.3 开发计划生成

创建：

- Phase Plan。
- Task DAG。
- Agent Assignment。
- Asset Plan。
- Test Plan。

### E11.4 玩家开发

实现玩家控制、状态、攻击、受伤和死亡。

### E11.5 关卡开发

创建 TileMapLayer、碰撞、陷阱和关卡布局。

### E11.6 敌人开发

实现巡逻、攻击和受伤机制。

### E11.7 游戏系统开发

实现生命、计分、收集物和游戏流程。

### E11.8 UI 开发

实现主菜单、HUD、暂停和结算。

### E11.9 资源生产

通过 Asset Pipeline 创建并导入需要的资源。

### E11.10 游戏集成

整合 Scene、Node、Script、Resource、Signal 和 Animation。

### E11.11 测试和缺陷修复

执行：

- 单元测试。
- Scene 检查。
- Runtime 测试。
- Gameplay 测试。
- 集成测试。
- 回归测试。

### E11.12 构建和交付

完成桌面平台导出和产物校验。

### E11.13 E2E 验收

完整验证：

用户需求 → 游戏设计 → 任务规划 → Agent 协作 → Godot 开发 → 资源生成 → 运行测试 → Bug 修复 → 回归 → 用户验收 → Build。

## 14.4 阶段完成标准

不能只看 Demo 能否运行。

必须证明系统能够通过自身的 Agent、Tool、Godot Integration、Asset、Verification 和 Build 能力完成实际开发闭环。

---

# 第十五章 E12：Productization

## 15.1 阶段目标

把开发版本整理为可安装、可配置、可升级、可维护的正式产品。

## 15.2 任务分解

### E12.1 Application Packaging

实现 Backend 和必要运行环境的打包。

### E12.2 Installer

实现：

- 安装。
- 卸载。
- 安装路径选择。
- 权限检查。
- 环境检查。

### E12.3 Runtime Management

实现 Backend Launcher 和 Process Supervisor。

### E12.4 Configuration UX

实现：

- Provider 配置。
- Model 配置。
- 项目配置。
- 用户配置。
- 预算配置。
- 权限配置。

### E12.5 Upgrade

实现：

- 版本检测。
- 数据备份。
- Schema Migration。
- 配置迁移。
- 升级验证。
- 失败回滚。

### E12.6 Diagnostics

实现：

- 健康检查。
- 环境检测。
- 日志导出。
- 诊断报告。
- 故障信息脱敏。

### E12.7 Compatibility

验证支持的 Godot 版本和目标操作系统。

第一阶段优先支持 Windows 和 Linux，macOS 按产品兼容计划扩展。

### E12.8 Documentation

完善：

- 用户安装指南。
- 用户操作手册。
- Provider 配置指南。
- 项目使用指南。
- Agent 使用说明。
- 故障排查手册。
- 开发者文档。
- API 文档。

### E12.9 Final Acceptance

执行：

- 全模块测试。
- 全系统集成测试。
- 全量回归测试。
- 安全测试。
- 故障恢复测试。
- Demo E2E。
- 安装升级测试。
- 最终发布门禁。

## 15.3 最终交付

- 正式软件包。
- Godot Plugin。
- Backend。
- 安装和升级工具。
- Agent 和 Tool 配置。
- 测试报告。
- 用户文档。
- 开发文档。
- 版本发布记录。

---

# 第十六章 项目级代码目录规划

随着 E0–E12 的推进，代码仓库逐步扩展为以下结构：

```text
godot-ai-agent/
├── backend/
│   ├── src/godot_ai/
│   │   ├── bootstrap/
│   │   ├── core/
│   │   ├── module_system/
│   │   ├── contracts/
│   │   ├── api/
│   │   ├── websocket/
│   │   ├── database/
│   │   ├── events/
│   │   ├── security/
│   │   ├── configuration/
│   │   ├── observability/
│   │   ├── projects/
│   │   ├── requirements/
│   │   ├── tasks/
│   │   ├── workflows/
│   │   ├── approvals/
│   │   ├── changesets/
│   │   ├── orchestration/
│   │   ├── agents/
│   │   ├── context/
│   │   ├── intelligence/
│   │   ├── models/
│   │   ├── tools/
│   │   ├── assets/
│   │   ├── verification/
│   │   ├── builds/
│   │   └── releases/
│   └── tests/
│
├── godot_plugin/
│   ├── plugin.cfg
│   ├── plugin.gd
│   ├── core/
│   ├── connection/
│   ├── session/
│   ├── bridge/
│   ├── editor_state/
│   ├── tools/
│   ├── ui/
│   └── tests/
│
├── shared/
│   ├── contracts/
│   ├── schemas/
│   ├── events/
│   ├── errors/
│   └── test_fixtures/
│
├── agents/
│   ├── definitions/
│   ├── skills/
│   └── templates/
│
├── tools/
│   ├── definitions/
│   └── adapters/
│
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   ├── regression/
│   ├── security/
│   ├── recovery/
│   └── fixtures/
│
├── demo/
│   └── platformer/
│
├── scripts/
│   ├── development/
│   ├── testing/
│   ├── build/
│   └── release/
│
├── docs/
│   ├── 00-governance/
│   ├── 01-product/
│   ├── 02-development/
│   ├── 03-testing/
│   └── appendices/
│
└── README.md
```

该目录是目标结构。各阶段只创建当阶段需要的目录和文件，禁止为了提前形成目录而大量创建空模块。

---

# 第十七章 开发任务管理规范

## 17.1 Task 层级

建议采用：

Project → Phase → Module → Task → Subtask。

例如：

E3 Godot Integration  
→ E3.5 Editor Snapshot & Event Recovery  
→ E3.5.1 Snapshot 数据结构  
→ E3.5.2 Event Cursor  
→ E3.5.3 Gap Detection  
→ E3.5.4 Event Replay  
→ E3.5.5 副作用核实  
→ E3.5.6 Recovery Integration Test。

## 17.2 任务状态

开发任务可以采用：

- BACKLOG。
- READY。
- IN_PROGRESS。
- BLOCKED。
- REVIEW。
- TESTING。
- DONE。
- CANCELLED。

具体业务 Task 状态仍由 Task System 的正式状态机管理，不能用开发看板状态替代。

## 17.3 任务依赖

每个 Task 必须声明：

- 前置 Task。
- 后续 Task。
- 依赖模块。
- 所需接口。
- 所需测试环境。

依赖关系必须构成无环图。

## 17.4 代码提交

每次代码提交应当：

1. 对应明确 Task。
2. 说明修改目的。
3. 列出影响模块。
4. 运行相关测试。
5. 检查代码规范。
6. 记录数据库迁移。
7. 检查接口兼容性。
8. 更新必要文档。

## 17.5 阶段冻结

每个阶段通过验收后：

- 保存代码版本。
- 保存测试结果。
- 保存接口版本。
- 保存数据库 Schema 版本。
- 保存阶段交付清单。
- 建立回归基线。

已冻结的架构和接口不得静默修改。

---

# 第十八章 阶段验收与 Definition of Done

每个阶段必须满足以下条件才能标记完成。

## 18.1 功能完成

- 本阶段 P0 范围已经实现。
- 主要流程真实可运行。
- 不存在用空实现伪装完成的核心模块。
- 接口与设计一致。

## 18.2 代码质量

- 代码通过静态检查。
- 类型和参数定义完整。
- 异常处理明确。
- 日志完整。
- 没有未经说明的临时绕过。

## 18.3 测试

- 单元测试通过。
- 契约测试通过。
- 集成测试通过。
- 相关回归测试通过。
- 关键异常场景已经验证。
- 测试结果和证据已经归档。

## 18.4 安全

- 权限检查已实现。
- 未授权访问被拒绝。
- 敏感信息未泄露。
- 项目写入遵循 Tool System。
- UNKNOWN 不会被误判为成功。

## 18.5 文档

- 接口文档已更新。
- 数据模型已更新。
- 代码目录已更新。
- 测试用例已更新。
- 已知问题已记录。

## 18.6 阶段验收

- 阶段交付清单完整。
- 重要缺陷有处理结论。
- 验收报告已生成。
- 用户需要验收的阶段已获得用户决定。
- 下一阶段依赖已经满足。

---

# 第十九章 项目风险与控制措施

| 风险 | 影响 | 控制措施 |
|---|---|---|
| Godot 版本差异 | 工具不兼容 | Version Adapter 与 Capability Detector |
| Editor 状态不同步 | 错误修改资源 | Snapshot、Revision、冲突检测 |
| AI 生成代码错误 | 游戏无法运行 | Static、Runtime、Integration Verification |
| Agent 并行冲突 | 文件被覆盖 | DAG、Resource Lock、Fencing Token |
| Provider 超时 | 重复生成和重复费用 | 副作用核实、UNKNOWN 管理 |
| 资产许可证不明 | 交付风险 | Provenance 和 License Gate |
| Backend 崩溃 | 任务状态不一致 | Event Log、Checkpoint、Recovery Coordinator |
| 数据库迁移失败 | 项目不可启动 | Backup、Migration Validation、Rollback |
| 接口版本变化 | 模块无法协作 | Contract Catalog 和兼容性测试 |
| 测试覆盖不足 | 回归缺陷 | Requirement Traceability |
| 项目规模失控 | 开发延期 | P0/P1/P2 分批交付 |
| 功能提前宣称完成 | 实际能力不足 | Definition of Done 和真实证据 |

---

# 第二十章 项目执行与进度管理

## 20.1 阶段进度

阶段进度应当依据真实 Task 完成情况计算，而不是由 Agent 自行估计。

每个阶段至少记录：

- 总任务数。
- 已完成任务数。
- 进行中任务数。
- 阻塞任务数。
- 未开始任务数。
- 测试通过率。
- 未解决缺陷。
- 交付物完成度。

## 20.2 阶段报告

每个阶段结束后提交：

1. 阶段目标。
2. 实际完成范围。
3. 未完成任务。
4. 实现模块。
5. 代码提交记录。
6. 测试结果。
7. 缺陷清单。
8. 风险清单。
9. 已知限制。
10. 是否满足进入下一阶段条件。

## 20.3 阶段决策

阶段完成后由用户决定：

- ACCEPT：接受并进入下一阶段。
- REVISE：修改当前阶段内容。
- PAUSE：暂停项目。
- REPLAN：重新规划。
- TERMINATE：终止项目。

不得因为自动化流程完成就默认获得下一阶段授权。

## 20.4 计划变更

变更开发计划时必须记录：

- 原计划。
- 变更原因。
- 影响模块。
- 影响任务。
- 影响测试。
- 兼容性风险。
- 用户决策。
- 新计划版本。

---

# 第二十一章 本文件与测试计划的关系

本文件定义每阶段需要完成的开发工作。

第三份文档 DOC-03-001《Godot AI Agent 全项目测试与质量保证计划》将进一步定义：

- 完整测试分类。
- 每个模块的测试范围。
- 测试用例编号。
- 测试环境。
- 测试数据。
- 测试执行步骤。
- 预期结果。
- 通过标准。
- 自动化测试方式。
- 回归测试选择策略。
- 版本发布门禁。

所有开发任务必须能够追踪到对应测试用例。

不能出现核心功能已经实现，却没有任何测试方法和验收标准的情况。

---

# 第二十二章 当前状态与后续细化

## 22.1 已确定

- 十三个开发阶段。
- 阶段总体顺序。
- 核心模块的开发范围。
- 核心模块依赖。
- 每阶段主要任务。
- 阶段交付目标。
- 统一 Definition of Done。
- 阶段验收原则。

## 22.2 后续需要进一步细化

本文件目前属于项目级实施计划。正式进入编码之前，还需要把任务继续细化为工程级任务卡。

例如 E1.6 SQLite Database 还需要进一步确定：

- 具体表结构。
- 字段类型。
- 主键和外键。
- 索引。
- Migration 文件。
- Repository 方法。
- 事务边界。
- 数据校验。
- 测试 Fixture。
- 测试 SQL。
- 迁移失败恢复方式。

其他模块同样需要细化。

这些细节应当逐模块形成可执行任务和接口规范，但不改变三份核心文档的总体结构。

## 22.3 文档状态

本文件为 DRAFT V1.0。

在审查、任务拆分和阶段依赖验证完成之前，不作为已批准的正式开发基线。

---

**文档结束**

**下一份关联文件：DOC-03-001《Godot AI Agent 全项目测试与质量保证计划》**