# 项目进度表

> 更新于 2026-11-23（E5 完成）。
> 阶段划分依据 [完整开发计划细分/](../../完整开发计划细分/)（E0–E12）。
> 单阶段细节见 [E0 验收报告](e0-acceptance-report.md)、[E0 测试报告](e0-test-report.md)、
> [E1 测试报告](e1-test-report.md)、[E1 验收报告](e1-acceptance-report.md)、
> [E2 安全测试报告](e2-security-test-report.md)、[E2 验收报告](e2-acceptance-report.md)、
> [E3 验收报告](e3-acceptance-report.md)、[E4 验收报告](e4-acceptance-report.md) 与
> [E5 验收报告](e5-acceptance-report.md)。

## 1. 总体进度

| 项 | 状态 |
| --- | --- |
| 当前阶段 | **E6 Agent Runtime（进行中，M3 已完成）** |
| 阶段进度 | 6 / 13 完成（E0–E5），E6 进行中 |
| 仓库 | `github.com/liumxT/godot-agent`，分支 `main` |
| CI | GitHub Actions 双 job（`Backend checks` + `Godot plugin checks`，ubuntu-24.04） |
| 后端测试 | 495 passed（unit + integration 453 / contract 42），ruff 全通过 |
| Godot 测试 | 68 / 68 passed（headless 编辑器入口） |
| 数据库迁移 | head 为 `000017` |

## 2. 阶段总览

| 阶段 | 名称 | 状态 | 说明 |
| --- | --- | --- | --- |
| E0 | Project Foundation | ✅ 已通过 | 2026-11-17 验收，条件 C1–C4 全部关闭 |
| E1 | Backend Core | ✅ 已完成 | 14 / 14 任务，P0 全部通过，见 [E1 验收报告](e1-acceptance-report.md) |
| E2 | Backend Services | ✅ 已完成 | 2026-11-18 验收，M6–M10 全部完成，见 [E2 验收报告](e2-acceptance-report.md) |
| E3 | Godot Integration | ✅ 已完成 | 2026-11-20 验收，18 任务，见 [E3 验收报告](e3-acceptance-report.md) |
| E4 | Project & Workflow Systems | ✅ 已完成 | 2026-11-20 验收，24 任务，见 [E4 验收报告](e4-acceptance-report.md) |
| E5 | AI & Tool Foundation | ✅ 已完成 | 2026-11-23 验收，31 任务，见 [E5 验收报告](e5-acceptance-report.md) |
| E6 | Agent Runtime | 🟡 进行中 | M1–M3（T01–T11）已完成 |
| E7 | Multi-Agent & Game Development | ⬜ 未开始 | |
| E8 | Asset Pipeline | ⬜ 未开始 | |
| E9 | Verification & QA | ⬜ 未开始 | 需补 Godot runtime 冒烟检查 |
| E10 | Build & Release | ⬜ 未开始 | 导出模板已就绪，见 §6 |
| E11 | Platformer Demo | ⬜ 未开始 | 系统级集成验收 |
| E12 | Productization | ⬜ 未开始 | 含存量文档归档 |

## 3. E0 任务明细（已完成）

| 任务 | 内容 | 关键交付物 |
| --- | --- | --- |
| E0-T01 | 仓库与工程规范 | Monorepo 目录、`.gitignore` / `.gitattributes` / `.editorconfig`、README / CONTRIBUTING / CHANGELOG |
| E0-T02 | 技术栈与运行环境 | [ADR-001…007](../06-decisions/README.md)、环境版本清单、打包 spike |
| E0-T03 | Backend 骨架 | FastAPI 入口、lifespan、配置加载、健康检查、统一异常与日志入口 |
| E0-T04 | Godot Plugin 骨架 | `plugin.cfg` / `plugin.gd`、状态面板、重复启用保护、契约探针插件 |
| E0-T05 | Shared Contracts | 协议 1.0 schema（request / response / event / error）、12 个错误码、11 个契约样例 |
| E0-T06 | 数据库规范 | Alembic 基线 `000001`、WAL 等 PRAGMA、升级前备份、[数据库规范](../03-development/database.md) |
| E0-T07 | 配置与 Secrets | 分区配置与校验、`.env.example`、系统凭据库、[配置规范](../03-development/configuration.md) / [Secrets 规范](../03-development/secrets.md) |
| E0-T08 | 日志与异常 | 双端结构化 JSON 日志、`request_id` / `correlation_id`、契约一致的错误体 |
| E0-T09 | CI | [check_all.py](../../scripts/testing/check_all.py) 7 阶段、[GitHub Actions](../../.github/workflows/ci.yml)、[CI 规范](../03-development/ci.md) |
| E0-T10 | 工程文档 | [10 类模板](../templates/README.md)、[开发流程](../00-project/development-workflow.md)、[Code Review](../00-project/code-review.md)、[Bug 管理](../00-project/bug-management.md) |

## 4. 质量与技术基线

| 项 | 状态 / 数值 |
| --- | --- |
| 后端测试 | 491 passed（pytest，asyncio auto） |
| 契约校验 | 38 个 manifest 用例，Backend 与 Godot 双向验证（契约测试 42 passed） |
| Godot 运行 | headless 编辑器模式加载插件、契约探针，E3 测试 68/68 passed，`exit 0` |
| 打包（onedir） | 39.1 MB，冷启动到 `/health` 1248 ms，迁移与健康检查通过 |
| 打包（onefile） | 23.4 MB，冷启动 1757 ms，整棵进程树可正常结束 |
| 技术基线 | Godot 4.5.1 / Python 3.14.2 / FastAPI / SQLite（WAL）/ Alembic / PyInstaller 6.22.3 |
| 远程 CI | `Backend checks` + `Godot plugin checks` 通过（ubuntu-24.04） |

## 5. E1 实施进度

设计文档：[E1 Backend Core 设计与任务拆解](../02-architecture/e1-backend-core-design.md)
（模块边界、关键设计、数据模型、5 个实施批次与测试映射）。

| 任务 | 内容 | 状态 |
| --- | --- | --- |
| E1-T01 | Backend 生命周期管理 | ✅ M1 |
| E1-T02 | 配置服务实现 | ✅ M1 |
| E1-T03 | SQLite 数据库服务 | ✅ M2 |
| E1-T04 | 数据库 Migration 服务 | ✅ M2 |
| E1-T05 | Repository 基础设施 | ✅ M2 |
| E1-T06 | 事务管理服务 | ✅ M2 |
| E1-T07 | 日志服务 | ✅ M1 |
| E1-T08 | 统一异常处理服务 | ✅ M1 |
| E1-T09 | 事件基础设施 | ✅ M3 |
| E1-T10 | Outbox / Inbox 基础机制 | ✅ M3 |
| E1-T11 | 数据库备份与恢复 | ✅ M4 |
| E1-T12 | Health Check 健康检查 | ✅ M4 |
| E1-T13 | 可观测性和诊断 | ✅ M4 |
| E1-T14 | Core 集成测试和性能验证 | ✅ M5 |

M1 交付：`core/lifecycle` 状态机与管理器、`bootstrap` 启动/关闭步骤与 `ServiceRegistry`、
`config/layers` / `config/policies` / `config/service`、日志文件轮转与脱敏、
完整异常层级与启动期错误码校验；新增 47 个测试（合计 99 passed）。

M2 交付：`DatabaseService`（初始化/会话/健康/幂等关闭）、数据库异常翻译与健康探测、
`MigrationService` 与 `000002_migration_history`（checksum、失败记录、head 校验、启动阻断）、
`BaseRepository` / `Page` 分页与异常映射、`transaction()`（超时、嵌套加入外层、失效会话）；
新增 29 个测试（合计 128 passed），启动失败保留领域错误码。

M3 交付：`core/events/{model,registry,bus}.py`（契约对齐的事件模型、`consumer_id` 唯一注册、
失败隔离的进程内发布）、`infrastructure/events/{outbox,inbox,dispatcher}.py` 与迁移
`000003_event_infrastructure`（`event_outbox` / `event_inbox`）、
启动 `events` 步骤与关闭 `events → database → flush_logging` 顺序、
`event_poll_interval_ms / event_batch_size / event_max_retries` 配置、
中断恢复（`publishing` 复位）与有界退避重试；新增 22 个测试（合计 150 passed），
规范见 [事件与 Outbox/Inbox](../03-development/events.md)。

M4 交付：`infrastructure/database/backup.py`（在线备份、元数据、校验、保留策略、
停派发/保护副本/失败回滚的恢复流程）、`app/health.py` 与 `/health/live`、`/health/ready`、
`/health` 聚合检查、`core/diagnostics.py` 最近错误环形缓冲 + `ERROR` 日志收集、
`/diagnostics/summary`（积压、迁移、备份、最近错误，生产环境要求 `X-Diagnostics-Token`）、
`backup_dir` / `backup_retention` 配置；新增 22 个测试（合计 172 passed），
规范见 [健康检查与诊断](../03-development/observability.md)。

M5 交付：`tests/integration/test_e1_core.py` 全链路集成（启动→配置→迁移→仓储→事务→事件→
Outbox 恢复→备份→恢复→健康→关闭）、`scripts/testing/perf_e1.py` 性能基线脚本
（产物 `artifacts/perf-e1.json`）、[E1 测试报告](e1-test-report.md)（14 项集成映射、
任务覆盖、性能数据、故障注入与 DoD 核对）。

E1 收尾：补齐只读数据库写探测与运行期损坏识别（新增 3 个测试，合计 176 passed），
输出 [E1 验收报告](e1-acceptance-report.md)（E1-D16），10 项故障注入全部 PASS。

下一步：E3 Godot Integration（见 §7）。

## 6. E2 实施进度（M10 已完成，E2 验收通过）

设计文档：[E2 Backend Services 设计与任务拆解](../02-architecture/e2-backend-services-design.md)
（模块边界、认证/Token/Session/授权/审计设计、数据模型、5 个批次与验收映射）。
设计已于 2026-11-18 按方案 A 评审通过。

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| M6 | T01 API Server、T02 路由与版本 | ✅ 已完成 |
| M7 | T06 客户端注册、T03 挑战认证、T04 Token | ✅ 已完成 |
| M8 | T05 Session、T07 Project Access | ✅ 已完成 |
| M9 | T08 授权、T09 请求链、T10 限流 | ✅ 已完成 |
| M10 | T11 审计、T12 文档与诊断、安全测试与验收 | ✅ 已完成 |

M6 交付：`app/server.py`（端口探测、`SERVER_PORT_IN_USE`、uvicorn 监听封装）、
`app/api/version.py` 与 `app/api/router.py`（`/api/v1` 汇总、路由/operationId/元数据校验）、
`app/api/system.py`（`/system/info`、`/system/status`）、`api/system.schema.json` 与 3 个契约样例、
`/api/v1/health*` 别名与根路径兼容、统一 404/405/422 错误输出、`docs/03-development/api.md`；
新增 23 个测试（合计 199 passed），ruff 与 `check_all` 通过。

评审确认项：设计文档 §8（E2-Q1…Q7，客户端凭证下发、Token/Refresh 策略、限流存储、
审计失败策略、`/health` 兼容、项目授予权限）。

M7 交付：`modules/client`（Client/Credential/AccessToken 实体、Repository、
`ClientService` 与 `AuthService`）、`core/security/tokens.py`（前缀、哈希、HMAC、常量时间比较）、
`infrastructure/security/{challenge,bootstrap,rate_limit}.py`、
`POST /api/v1/clients`、`/auth/challenge`、`/auth/verify`、`/auth/refresh`、
迁移 `000004_e2_clients_auth`（4 张表）、`api/client.schema.json` / `api/auth.schema.json`
与 5 个契约样例、Godot 契约校验器同步；认证失败 10 次/分钟限流与 `Retry-After`，
Token 过期/撤销与每小时清理任务；新增 35 个测试（合计 234 passed）。

M8 交付：`modules/session`（`SessionModel`/Repository/`SessionService`，
`CREATED → ACTIVE → (EXPIRED | REVOKED | CLOSED)` 状态机、`gds_` Token 摘要存储、
TTL 与 `session_max_ttl` 双重限制）、`modules/access`（`ProjectAccessModel`/Repository/
`ProjectAccessService`，Client + Session + Project 三重绑定）、
`POST /api/v1/sessions`、`GET|DELETE /api/v1/sessions/current`、`/sessions/current/renew`、
`POST /api/v1/projects/access`、`GET|DELETE /api/v1/projects/access/current`、
迁移 `000005_e2_sessions_access`（2 张表）、`api/session.schema.json` /
`api/project-access.schema.json` 与 5 个契约样例、Godot 契约校验器同步；
新增 `SESSION_INVALID` / `SESSION_EXPIRED` / `SESSION_REVOKED` / `PROJECT_ACCESS_DENIED`；
新增 20 个测试（合计 254 passed），ruff 与 `check_all` 通过。

M9 交付：`core/security/principal.py`（Principal / Action / Resource）、
`core/security/policy.py`（RBAC + ABAC + Capability 纯策略，未知 Action 默认 DENY）、
`app/api/deps.py`（`require_authenticated` / `require_session` / `require_access_token` /
`require_action` / `authorize_project_action` / `enforce_rate_limit`）、
`app/middleware/{errors,size_limit,timeout}.py`（413 `REQUEST_TOO_LARGE`、504 `REQUEST_TIMEOUT`）、
`infrastructure/security/rate_limit.py` 增加 `ConcurrencyLimiter`；
所有受保护 `/api/v1` 路由在 Router 级挂载认证与限流依赖，`/system/status` 改为需认证，
`/auth/refresh` 拆分到 `protected_router`；项目授予/撤销改由服务端访问记录判定角色；
新增 `request_max_body_bytes` / `request_timeout_seconds` / `rate_limit_default_per_minute` /
`rate_limit_max_concurrency` 配置与 429 `Retry-After`；
新增 22 个测试（合计 276 passed），ruff 与 `check_all` 通过。

M10 交付：`modules/audit`（`AuditEventModel` / Repository / `AuditService`；白名单 + 脱敏 details）、
迁移 `000006_e2_audit_events`、`AUDIT_FAILED` 与 `audit_fail_closed`；
注册/认证/Session/项目授予撤销/授权拒绝/诊断读取全部写入审计，
敏感操作审计失败 fail-closed；`GET /api/v1/diagnostics/summary`（认证 + `diagnostics.read`）
与 OpenAPI `bearerAuth` 安全方案；新增 23 个测试（合计 299 passed），
输出 [E2 安全测试报告](e2-security-test-report.md)（12 项）与
[E2 验收报告](e2-acceptance-report.md)（E2-D15）；ruff 与 `check_all` 通过。

## 7. E3 实施进度（6 批次 / 18 任务，验收通过）

设计文档：[E3 Godot Integration 设计与任务拆解](../02-architecture/e3-godot-integration-design.md)

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E3-M1 | T01 插件生命周期、T02 服务管理 | ✅ 已完成 |
| E3-M2 | T03 Backend Discovery、T04 Bridge 协议、T05 WebSocket Client | ✅ 已完成 |
| E3-M3 | T06 认证、T07 Session、T08 Lease、T17 连接 UI | ✅ 已完成 |
| E3-M4 | T09 心跳、T10 事件同步、T11 快照 | ✅ 已完成 |
| E3-M5 | T12 重连恢复、T13 多 Editor 隔离、T14 项目身份 | ✅ 已完成 |
| E3-M6 | T15 状态采集、T16 Runtime Bridge、T18 集成测试与收尾 | ✅ 已完成 |

交付：Godot 侧 `core/{plugin_lifecycle,service_registry,plugin_context}`、
`bridge/{editor_bridge_client,connection_state,protocol_adapter,action_registry}`、
`services/{backend_discovery,editor_auth,editor_session,heartbeat,event_sync,reconnection,snapshot}`、
`runtime/runtime_bridge.gd`、`state/{project_identity,editor_state_provider}`、
`ui/connection_panel.gd`、`tests/{test_runner,e3}`；
契约侧 `packages/contracts/bridge/`（7 个 schema）；
后端 `modules/{editor_session,lease,bridge_event,snapshot,project,runtime}`、
`app/ws/{editor,runtime}.py`、迁移 `000007`–`000009`；
后端 361 passed（unit + integration 319 / contract 42），Godot 68/68 passed，
`check_all.py` 8 阶段全 PASS，迁移 head `000009`，
安全要求 E3-SEC-001…010 均有测试或实现证据。

## 8. E4 实施进度（6 批次 / 24 任务，验收通过）

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E4-M1 | T01 Project Domain、T02 Registry、T03 Lifecycle、T04 Configuration、T05 Access Integration | ✅ 已完成 |
| E4-M2 | T06 Task System、T07 状态机、T08 Attempt、T09 依赖、T10 Checkpoint、T11 Event Log | ✅ 已完成 |
| E4-M3 | T12 Workflow Definition、T13 Instance、T14 Node Engine、T15 Phase、T16 Scheduler、T17 Recovery | ✅ 已完成 |
| E4-M4 | T18 Requirement、T19 ChangeSet、T20 Approval、T21 User Acceptance | ✅ 已完成 |
| E4-M5 | T22 Project/Task/Workflow API、T23 Management UI | ✅ 已完成 |
| E4-M6 | T24 测试、全量验证与验收报告 | ✅ 已完成 |

交付：`modules/{project_registry,project,task,requirement,changeset,approval,workflow}`、
`app/api/{projects_v1,tasks,workflows,changesets,approvals,management_ui}.py`、
迁移 `000010_e4_project_workflow`；Workflow 调度与启动恢复、审批哈希绑定、
项目配置版本乐观锁与归档阻塞检查；管理页 `/api/v1/manage` 覆盖项目、任务、
Workflow 与待处理审批；后端 419 passed（unit + integration 377 / contract 42），
`check_all.py` 8 阶段全 PASS，迁移 head `000010`；
E1–E3 回归全绿，无接口破坏。已知限制见 [E4 验收报告](e4-acceptance-report.md#6-已知限制)。

## 9. E5 实施进度（进行中）

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E5-M1 | T01 Domain、T02 Provider Interface、T03 Adapter Framework、T04 Provider Config、T05 Model Registry、T06 Capability Registry、T07 Routing | ✅ 已完成 |
| E5-M2 | T08 统一请求、T09 统一响应、T10 流式、T11 Token、T12 Cost、T13 调用审计、T14 重试与超时 | ✅ 已完成 |
| E5-M3 | T15 Prompt 版本化、T16 Context Assembly 接口 | ✅ 已完成 |
| E5-M4 | T17 Tool Registry、T18 Schema、T19 Permission、T20 Risk、T21 Approval | ✅ 已完成 |
| E5-M5 | T22 执行引擎、T23 幂等、T24 资源锁、T25 审计、T26 验证、T27 恢复 | ✅ 已完成 |
| E5-M6 | T28 Godot Adapter、T29 File Adapter、T30 Tool API 与管理页 | ✅ 已完成 |
| E5-M7 | T31 集成 / 安全 / 故障恢复测试、验收报告 | ✅ 已完成 |

交付（M1）：`modules/model_gateway/{models,repository,registry,routing,configuration}.py` 与
`providers/{base,errors,registry,openai,anthropic,local}.py`；迁移
`000011_e5_model_gateway`（Provider、配置版本、模型、能力、价格版本、请求/响应）；
错误码 `PROVIDER_CONFIGURATION_INVALID` / `PROVIDER_NOT_CONFIGURED` /
`MODEL_UNAVAILABLE` / `MODEL_CAPABILITY_UNSUPPORTED` / `MODEL_ALREADY_REGISTERED`；
Provider 配置使用 SecretStore 保存密钥并按版本审计；路由只接受有证据的
`SUPPORTED` 能力，模型不可用时返回原因与替代项，不静默降级。新增 15 个测试
（单元 11 / 集成 4），后端 434 passed，ruff 全通过。

交付（M2）：`schemas.py`（统一请求/响应/流式事件/Usage 模型与校验）、
`cost.py`（按价格版本计算，缺价格或用量记 `UNAVAILABLE`）、`gateway.py`
（`generate/stream`、请求状态机、重试与超时、Token/Cost/审计落库、流式取消）、
`providers/{base,openai,anthropic,local}.py` 完整实现；迁移
`000012_e5_model_invocation`（`model_usage_records`、`model_cost_records`、
`model_call_audits`，`model_requests.workflow_id`）；错误码 `MODEL_CALL_FAILED` /
`MODEL_REQUEST_UNKNOWN`。请求发送后超时或断网记 `UNKNOWN` 且不重试；HTTP 429/5xx
与连接失败按策略重试；流式由 Gateway 统一发出 STARTED/COMPLETED/FAILED/CANCELLED。
新增 14 个测试（单元 8 / 集成 6），后端 448 passed，ruff 全通过。

交付（M3）：`modules/prompt/{models,repository,service}.py`（版本化定义、变量 Schema
校验与渲染、测试结果追踪）、`modules/context/{models,repository,service}.py`（分层装配、
来源追踪、固定引用缺失显式失败、预算超限只报告不裁剪、token 估算按字符 / 4）；
迁移 `000013_e5_prompt_context`（`prompt_definitions`、`prompt_test_results`、
`context_assemblies`）；错误码 `PROMPT_VARIABLE_INVALID` / `CONTEXT_SOURCE_MISSING`。
Prompt 渲染明确标记未受信变量，未声明占位符在创建时即拒绝。新增 6 个集成测试，
后端 454 passed，ruff 全通过。

交付（M4）：`modules/tool/{models,repository,registry,risk,permissions,approval}.py`
（名称版本化工具定义与 JSON Schema 校验、R0–R4 风险分级与升级不改降级、项目访问 ×
工具权限 × 任务状态 × Agent 上限的权限决策、审批绑定工具版本/入参/资源范围并校验
内容哈希）；迁移 `000014_e5_tool_registry`（`tool_definitions`）；审批目标新增
`TOOL_REQUEST`；错误码 `TOOL_ALREADY_REGISTERED` / `TOOL_SCHEMA_INVALID` /
`TOOL_INPUT_INVALID` / `TOOL_OUTPUT_INVALID`。R2 要求 ChangeSet、R3+ 要求审批、
R4 要求强审批；Agent 请求只能升高风险等级。新增 5 个集成测试，后端 459 passed，
ruff 全通过。

交付（M5）：`modules/tool/{execution,adapters,idempotency,locks,audit,verification,recovery}.py`
（CREATED→VALIDATING→AUTHORIZED→READY→EXECUTING 状态机、Adapter 分发、幂等键与
UNKNOWN 先核验再重试、READ/WRITE/EXCLUSIVE 资源锁与 Fencing Token、只追加的脱敏审计、
基于执行状态/输出 Schema/Adapter 观测的验证结论、中断后按实际状态恢复）；迁移
`000015_e5_tool_execution`（`tool_executions`、`resource_locks`、`tool_audit_records`、
`tool_verification_results`）；错误码 `TOOL_ADAPTER_MISSING` / `RESOURCE_LOCK_CONFLICT` /
`RESOURCE_LOCK_EXPIRED`；执行完成发布 `tool.execution.completed`。新增 9 个集成测试与
4 个单元测试，后端 472 passed，ruff 全通过。

交付（M6）：`modules/tool/{catalog,godot_adapter,file_adapter}.py` 与
`modules/editor_command/hub.py`。内置 Godot/File 工具目录（幂等登记）、后端→编辑器
`editor.command.execute` 命令通道（响应帧分流、超时 UNKNOWN、断连失败）、插件侧
`tool_command_service.gd` 用真实 Editor API 执行场景/节点/Inspector/信号/组/动画/
TileMap/运行控制，File Adapter 实现 11 个 `file.*` 工具（`..`/绝对路径/符号链接逃逸/
隐藏路径/敏感文件拒绝，写后重新读取与 sha256 校验，Editor 刷新失败记为未确认而不阻断，
不伪造 UID）。新增 `app/api/tools.py`（工具、执行、取消、审计）与 `app/api/models.py`
（模型、Provider、用量、费用），执行服务新增 `cancel`，权限新增 `tool.read` /
`tool.manage` / `model.read` / `model.manage`，管理页增加工具、执行与模型区块。
新增 6 个集成测试，后端 478 passed，Godot 68/68 passed，ruff 全通过。迁移 head 仍为
`000015`（M6 未新增表）。

交付（M7）：`tests/integration/test_e5_acceptance.py` 覆盖只读工具端到端、写工具无
ChangeSet 拒绝且无磁盘副作用、UNKNOWN 经 Adapter 观测恢复；补充 Godot Adapter 超时
→ UNKNOWN 用例。新增 [E5 验收报告](e5-acceptance-report.md)，记录交付清单、场景证据、
安全核对、质量门禁与已知限制。后端 481 passed，Godot 68/68，契约探针 38/38，
ruff 全通过。

## 10. E6 实施进度

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E6-M1 | T01 Agent Domain & Contract、T02 Definition Registry | ✅ 已完成 |
| E6-M2 | T03 Instance Manager、T04 Lifecycle、T06 Task/Attempt Binding、T05 Scheduler | ✅ 已完成 |
| E6-M3 | T07 Execution Loop、T08 Planning & Step、T09 Context Binding、T10 Model Binding、T11 Tool Binding | ✅ 已完成 |
| E6-M4 | T12 Budget Manager、T13 Checkpoint & Event、T14 Pause/Resume/Cancel/Stop、T15 Recovery | ⬜ 未开始 |
| E6-M5 | T16 Observability、T17 API、T18 UI、T19 Generic Agent | ⬜ 未开始 |
| E6-M6 | T20 Integration / E2E / Security / Recovery、E6 验收报告 | ⬜ 未开始 |

交付（M1）：`modules/agent_runtime/{models,repository,service}.py`。领域模型覆盖
Definition、Definition Version、Config Snapshot、Instance、Execution、Plan、Step、
Checkpoint、Event；Instance / Execution 状态机内置迁移表，`UNKNOWN` 不允许直接回到
`RUNNING`。Definition Registry 支持草稿创建/更新、引用校验与发布：能力声明白名单、
Model Policy、Prompt 版本、Context Profile、Tool 白名单必须存在，且 Tool 风险等级
不得超过 Permission Ceiling；发布生成不可变版本（`content_hash`），发布后原地修改被
拒绝。迁移 `000016_e6_agent_runtime`（9 张表），错误码
`AGENT_DEFINITION_INVALID` / `AGENT_VERSION_IMMUTABLE` / `AGENT_CAPABILITY_UNSUPPORTED` /
`AGENT_STATE_INVALID` / `AGENT_BUDGET_EXCEEDED` / `AGENT_ACTION_INVALID` /
`AGENT_PERMISSION_DENIED` / `AGENT_RECOVERY_REQUIRED`。新增 5 个集成测试，
后端 486 passed，ruff 全通过。

交付（M2）：`modules/agent_runtime/{events,instance,lifecycle,scheduler}.py`。
Instance 只能由合法 Task + Attempt 创建，同一 Attempt 保持幂等；创建时冻结配置快照
（Definition 版本、Prompt、Model Policy、Context Profile、Tool 白名单、权限上限、预算、
Runtime Policy），快照带 `content_hash`。初始化校验冻结引用，工具停用等失效引用会让实例
进入 `FAILED`。生命周期按状态机执行并写只追加事件；`UNKNOWN` 不能直接回到 `RUNNING`。
Scheduler 只负责认领 `READY` 实例，并发认领由状态版本条件更新裁决。新增 5 个集成测试，
后端 491 passed，ruff 全通过。

交付（M3）：`modules/agent_runtime/{response_parser,planning,context_binding,model_binding,
tool_binding,loop,execution}.py`。模型响应严格解析为结构化 Agent Action（非法 JSON / 未知
动作 / 非法 Step 一律失败），Plan 重新规划生成新版本并把旧 ACTIVE 置为 SUPERSEDED，
Step 依赖未完成不会被调度，Plan 完成前必须全部 Step 成功。Context 只使用 Instance 冻结的
Prompt 版本与 Context Profile，预算超出失败关闭。模型选择经 Model Policy + E5 路由，
显式模型不可用不静默切换；模型侧工具名转换为合法别名并回映射到白名单工具。工具调用全部
经 E5 Tool System 与 `AgentPolicy`，R3+ 进入 `WAITING_APPROVAL` 且不执行。执行循环记录
模型 / 工具 / 审批 / 预算事件，模型或工具 `UNKNOWN` 进入 `UNKNOWN` 且不自动重试。
迁移 `000017_e6_agent_client_binding` 为快照与实例补充 `client_id`。新增 4 个集成测试，
后端 495 passed，ruff 全通过。

## 11. 已知问题与待办

| 事项 | 影响阶段 | 状态 |
| --- | --- | --- |
| Godot runtime 首次启动 `signal 11`，根因未确证，已不再复现 | E9 | 待 E9 增加 runtime 冒烟检查，复现则升级/重装 |
| Godot 4.5.1 导出模板 | E10 | ✅ 已安装（`%APPDATA%\Godot\export_templates\4.5.1.stable`） |
| 无 Python 干净机器上的打包验证 | E10 | 待安装包制作时执行 |
| CI 未覆盖打包冒烟与 Markdown 链接检查 | E10 / E12 | 待补 |
| onefile 便携产物的杀软误报 | E10 | 分发前在目标环境实测 |
| 管理界面为浏览器单页，未提供 Godot 编辑器 Dock | E5+ | 本期按最小实现处理 |
| Workflow 未实现并行分支与节点超时重试 | E5+ | 后续 Workflow 增强 |
| 启动恢复将未完成 Attempt 置 `UNKNOWN`、Task 置 `BLOCKED` | E5 | 自动重试策略由 Agent 执行层实现 |
| 归档阻塞统计最多扫描 200 条 Workflow/ChangeSet | E5 | 需要时改聚合计数查询 |
| Runtime 凭证（`client_type=tool`）API 已支持，管理界面未提供签发入口 | E5 | 客户端管理界面补齐 |
| 存量规划文档归档 `docs/` | E12 | 规则已定，E12 执行 |
| Godot 安装路径含中文（建议迁 ASCII） | — | 非阻塞，未执行 |

## 12. 维护规则

1. 每完成一个任务勾选或更新状态，每阶段结束同步本文件与阶段验收报告。
2. 状态符号：`✅ 已完成 / ⏳ 进行中 / ⬜ 未开始 / ⛔ 阻塞`。
3. 新增已知问题或风险时，必须写明影响阶段与处理状态。
4. 阶段验收结论以对应 `docs/00-project/e*-acceptance-report.md` 为准。
