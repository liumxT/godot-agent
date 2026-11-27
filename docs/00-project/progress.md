# 项目进度表

> 更新于 2026-11-27（E12 完成）。
> 阶段划分依据 [完整开发计划细分/](../../完整开发计划细分/)（E0–E12）。
> 单阶段细节见 [E0 验收报告](e0-acceptance-report.md)、[E0 测试报告](e0-test-report.md)、
> [E1 测试报告](e1-test-report.md)、[E1 验收报告](e1-acceptance-report.md)、
> [E2 安全测试报告](e2-security-test-report.md)、[E2 验收报告](e2-acceptance-report.md)、
> [E3 验收报告](e3-acceptance-report.md)、[E4 验收报告](e4-acceptance-report.md)、
> [E5 验收报告](e5-acceptance-report.md)、[E6 验收报告](e6-acceptance-report.md)、
> [E7 验收报告](e7-acceptance-report.md)、[E8 验收报告](e8-acceptance-report.md)、
> [E9 验收报告](e9-acceptance-report.md)、[E10 验收报告](e10-acceptance-report.md)、
> [E11 验收报告](e11-acceptance-report.md) 与 [E12 验收报告](e12-acceptance-report.md)。

## 1. 总体进度

| 项 | 状态 |
| --- | --- |
| 当前阶段 | **E12 Productization（已完成，20 / 20 任务，GA Ready）** |
| 阶段进度 | 13 / 13 完成（E0–E12） |
| 仓库 | `github.com/liumxT/godot-agent`，分支 `main` |
| CI | GitHub Actions 双 job（`Backend checks` + `Godot plugin checks`，ubuntu-24.04） |
| 后端测试 | 953 passed，1 warning（896 业务 + 57 契约，见 §16） |
| Godot 测试 | 68 / 68 passed（headless 编辑器入口） |
| Demo 运行时验证 | 24 / 24 passed（真实 Godot 4.5.1 headless） |
| 数据库迁移 | head 为 `000033` |

## 2. 阶段总览

| 阶段 | 名称 | 状态 | 说明 |
| --- | --- | --- | --- |
| E0 | Project Foundation | ✅ 已通过 | 2026-11-17 验收，条件 C1–C4 全部关闭 |
| E1 | Backend Core | ✅ 已完成 | 14 / 14 任务，P0 全部通过，见 [E1 验收报告](e1-acceptance-report.md) |
| E2 | Backend Services | ✅ 已完成 | 2026-11-18 验收，M6–M10 全部完成，见 [E2 验收报告](e2-acceptance-report.md) |
| E3 | Godot Integration | ✅ 已完成 | 2026-11-20 验收，18 任务，见 [E3 验收报告](e3-acceptance-report.md) |
| E4 | Project & Workflow Systems | ✅ 已完成 | 2026-11-20 验收，24 任务，见 [E4 验收报告](e4-acceptance-report.md) |
| E5 | AI & Tool Foundation | ✅ 已完成 | 2026-11-23 验收，31 任务，见 [E5 验收报告](e5-acceptance-report.md) |
| E6 | Agent Runtime | ✅ 已完成 | 2026-11-23 验收，20 任务，见 [E6 验收报告](e6-acceptance-report.md) |
| E7 | Multi-Agent & Game Development | ✅ 已完成 | 2026-11-23 验收，7 批次 / 22 任务，见 [E7 验收报告](e7-acceptance-report.md) |
| E8 | Asset Pipeline | ✅ 已完成 | 2026-11-24 验收，8 批次 / 20 任务，见 [E8 验收报告](e8-acceptance-report.md) |
| E9 | Verification & QA | ✅ 已完成 | 2026-11-24 验收，8 批次 / 20 任务，见 [E9 验收报告](e9-acceptance-report.md) |
| E10 | Build & Release | ✅ 已完成 | 2026-11-26 验收，6 批次 / 20 任务，见 [E10 验收报告](e10-acceptance-report.md) |
| E11 | Platformer Demo | ✅ 已完成 | 2026-11-26 验收，20 任务，见 [E11 验收报告](e11-acceptance-report.md) |
| E12 | Productization | ✅ 已完成 | 2026-11-27 验收，20 任务，GA Ready，见 [E12 验收报告](e12-acceptance-report.md) |

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
| 后端测试 | 953 passed，1 warning（E12 全量 pytest，见 §16） |
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
| E6-M4 | T12 Budget Manager、T13 Checkpoint & Event、T14 Pause/Resume/Cancel/Stop、T15 Recovery | ✅ 已完成 |
| E6-M5 | T16 Observability、T17 API、T18 UI、T19 Generic Agent | ✅ 已完成 |
| E6-M6 | T20 Integration / E2E / Security / Recovery、E6 验收报告 | ✅ 已完成 |

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

交付（M4）：`modules/agent_runtime/{budget,checkpoint,control,recovery}.py`。
预算用量持久化在 Execution（迁移 `000018_e6_agent_budget_usage`），调用前 reserve、
完成后 settle，重启不重置；超限按 Budget Profile 的 `FAIL` / `PAUSE` / `WAITING_INPUT` /
`STOP` 处理，禁止自动放宽。Checkpoint 与事件同事务原子写入，记录 Instance/Execution
状态、Plan/Step 进度、预算快照、pending action 与最后确认事件序号，并回填
`last_checkpoint_id`；执行循环在每轮结束、审批等待、暂停、预算超限与终止时写 Checkpoint。
Pause 先写 Checkpoint 再进入 PAUSED 并保留待审批动作；Resume 校验 Task/Attempt、Session、
Project Access、Model、Tool、Context、Budget 与 Approval，任一失败保持 PAUSED 并抛
`AGENT_RECOVERY_REQUIRED`。Cancel/Stop 放弃 Plan（未执行 Step 置 SKIPPED、可能已执行置
UNKNOWN），不回写 Task System。Recovery Coordinator 在启动时扫描非终止实例：Checkpoint
缺失、事件序号越界、Execution 不一致或 Task 失效则标记 UNKNOWN；有效 Checkpoint 则暂停为
PAUSED 等待显式 Resume，`READY` 交给 Scheduler，禁止自动重放副作用动作。新增 9 个集成测试，
后端 504 passed，ruff 全通过。

交付（M5）：`modules/agent_runtime/{observability,generic}.py`、`app/api/agents.py`、
`app/schemas/agent_runtime.py`。可观测性提供聚合指标（实例/执行、队列与执行耗时、迭代、
模型/工具调用、Token、成本、失败率、UNKNOWN、恢复成功率、审批等待）与一次 Execution 的
完整追踪（Task → Attempt → Instance → Execution → Plan/Step → Model/Tool/Approval → Event），
所有输出统一脱敏并截断超长字段。API 覆盖 Definition 创建/发布/版本、Instance 创建与
start/pause/resume/stop、Execution/Plan/Step/Event 查询、metrics 与 trace；定义接口为全局
资源（非 admin 需 `project_id` 授权），实例与执行按项目授权并校验 `client_id` 归属。
权限新增 `agent.read` / `agent.manage`。管理页扩展 Agent 概览、实例、执行监控、预算与恢复
区块。内置 `generic_agent` 幂等创建（Prompt、Definition、发布），默认 11 个只读优先工具、
权限上限 R2、预算超限 `PAUSE`，仅非 test 环境启动时自动确保存在。新增 7 个测试
（3 API + 1 Generic Agent + 3 脱敏单元），后端 511 passed，ruff 全通过。

交付（M6）：`tests/integration/test_e6_acceptance.py`、`tests/unit/test_e6_architecture.py`
与 [E6 验收报告](e6-acceptance-report.md)。验收测试补齐四类关键证据：E2E 证明 Agent 完成后
Task 仍为 `READY`、必须经 Task System 合法路径才能完成；白名单外工具被拒绝且无工具执行；
隐藏推理/思维链不进入事件与 trace；模型 UNKNOWN 不自动重试。架构守卫检查 Agent Runtime
不导入 Provider 适配器、HTTP 客户端、文件写入库或 Workflow 模块，确保只经 Gateway 与
Tool System 工作。新增 5 个测试（4 验收集成 + 1 架构单元），后端 516 passed，ruff 全通过。

## 11. E7 实施进度

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E7-M1 | T01 Multi-Agent Domain & Contract、T02 Capability Registry | ✅ 已完成 |
| E7-M2 | T03 Orchestrator、T04 Team Manager、T05 Task Decomposition、T06 Assignment | ✅ 已完成 |
| E7-M3 | T07 Handoff、T08 Lead Agent、T09 Context Coordination、T12 Agent Communication | ✅ 已完成 |
| E7-M4 | T10 Parallel Execution、T11 Resource/Conflict Coordination、T17 Conflict Resolution | ✅ 已完成 |
| E7-M5 | T13 Specialized Definitions、T14 Workflows、T15 Result Integration、T16 Review | ✅ 已完成 |
| E7-M6 | T18 Team Budget、T19 Observability、T20 API、T21 UI、T22 Platformer Demo | ✅ 已完成 |
| E7-M7 | 综合测试与验收、E7 验收报告 | ✅ 已完成 |

交付（M1）：`modules/multi_agent/{models,repository,service,capabilities}.py`。领域模型覆盖
Capability、Team、Team Member、Assignment、Assignment Dependency、Handoff、Collaboration、
Message、Conflict、Integration、Review、Team Budget、Shared Context；状态机常量与迁移表
内置，Team 状态不替代 Task 状态。Capability Registry 幂等登记 32 个内置能力（设计、程序、
Godot、美术、QA），支持自定义能力登记与查询；匹配分两阶段：启用状态、能力、权限上限、
Tool、Model 能力、项目访问与预算为硬性过滤，能力覆盖度、成功率、负载与成本为软性排序，
高负载只降权不排除。Assignment 只能由 `ORCHESTRATOR` 创建，必须绑定 Team/Task/Attempt，
依赖必须属于同一 Team 且拒绝自依赖与循环；Handoff 只创建请求，Collaboration 参与者必须
属于同一 Team。迁移 `000019_e7_multi_agent`（13 张表），错误码 `AGENT_CAPABILITY_UNSUPPORTED`
复用并新增 `AGENT_TEAM_INVALID` / `AGENT_ASSIGNMENT_INVALID` /
`AGENT_ASSIGNMENT_UNAUTHORIZED` / `AGENT_HANDOFF_INVALID` / `AGENT_COLLABORATION_INVALID`。
新增 16 个测试（10 单元匹配 + 6 集成领域），后端 532 passed，ruff 全通过。

交付（M2）：`modules/multi_agent/{decomposition,orchestrator}.py`，并扩展 `models`、`repository`
与 `service`。Task Decomposition 以 `SubtaskSpec` / `DecompositionPlan` 描述子任务，校验唯一
key、目标/能力/验收非空、风险合法、依赖存在、无自依赖、Kahn 拓扑无环，并要求原始验收条目被
子任务覆盖；复杂度按子任务数判定（1 个为 SIMPLE 单 Agent，多个为 COMPLEX 多 Agent）。
Orchestrator 仅接受 `TASK_SYSTEM` 授权，依次校验 Task/Attempt 可运行、同一 Attempt 无活动
Team，取 ACTIVE Definition 并通过 Capability Registry 两阶段匹配选择 Agent（Definition 的
`tool_whitelist` 存的是 tool_id，经 ToolRegistry 映射回工具名后参与匹配）；随后创建 Team
（CREATED → INITIALIZING → READY）、按拓扑序创建 Assignment（无依赖 READY、有依赖 BLOCKED）
并登记成员，失败时 Team 置 FAILED。Team Manager 新增状态迁移（乐观锁）、成员登记/移除、Lead
设置与关闭（存在未完成 Assignment 时拒绝）；Assignment 新增状态迁移、claim（条件 UPDATE 防
并发抢占）与 replace（旧记录 FAILED，新记录继承 parent_assignment_id）。新增 13 个测试
（7 单元分解 + 6 集成编排），后端 545 passed，ruff 全通过。

交付（M3）：新增 `modules/multi_agent/{context,communication,lead}.py`，并扩展 `models`、
`repository`、`service` 与 `orchestrator`。Handoff 增加结构化 payload（目标、范围、已完成/剩余
工作、下一步、验收等显式字段；未知字段一律拒绝，禁止夹带隐藏推理）、状态迁移表与
`Orchestrator.execute_handoff`：仅 Task System 可执行，校验源 Assignment/Team 未结束、目标
Definition 已发布、能力/工具/权限上限满足、移交 Context 属于该 Team，然后由 Orchestrator 创建
目标 Assignment（继承 parent、READY、登记成员）并推进 Handoff 至 COMPLETED，失败时落 FAILED。
Shared Context 以引用+哈希版本化，`PRIVATE` 不可共享，同内容重复发布幂等，替换需 expected_version
并保留 `superseded_by`；过期判定支持 ACCEPT/REFRESH/PAUSE/REANALYZE，PAUSE 抛 409
`AGENT_CONTEXT_STALE`。Agent 消息绑定 Team 与明确收发者，发送者结束状态拒绝发送，消费仅限接收者
且重复消费幂等。Lead 默认权限为只读集合（TEAM/ASSIGNMENT/RESULT 读取、集成规划、Handoff 请求、
冲突报告），写权限必须显式授予；提供状态看板、缺失输出、接口冲突检测（重复 output_reference）、
集成计划创建与执行摘要。新增 13 个测试（6 单元 payload/权限 + 7 集成交接/Context/消息/Lead），
后端 558 passed，ruff 全通过。

交付（M4）：新增迁移 `000020_e7_resource_locks.py`（`agent_resource_locks` 表，含 READ/WRITE
资源锁与单调 Fencing Token；`agent_conflicts` 增加解决策略与解决人字段），并新增
`modules/multi_agent/{resources,conflicts}.py`。资源协调保证同一资源同一时刻最多一个写者，
读锁可并行但排斥写锁；写冲突失败关闭并返回冲突持有者；旧 Fencing Token 的释放与有效性检查
均被拒绝；Assignment 结束可批量释放锁。并行管理器支持依赖完成后将 BLOCKED 提升为 READY、
按优先级与资源集合生成受 `max_parallel` 限制的批次，并在失败时只阻塞依赖失败结果的
Assignment，保留无关任务继续执行。冲突服务记录参与方/资源/严重级别，检测时暂停 RUNNING→
WAITING、READY→BLOCKED；接口/Schema 冲突若影响用户目标自动升级，必须 USER_DECISION 解决；
策略白名单不含 LAST_WRITE_WINS，避免静默覆盖。新增 10 个测试（4 单元策略 + 6 集成资源/并行/
冲突，集成文件累计 13 个并复用 M3 夹具），后端 568 passed，ruff 全通过。

交付（M5）：新增 `modules/multi_agent/{specialized,workflows,review}.py` 并扩展 `lead.py`。
专用 Agent 目录登记 38 个角色（15 P0 / 18 P1 / 5 P2），统一提供身份、职责、能力、工具、
权限上限、输入/输出契约、验收标准与协作规则；其中 6 个 P0 角色标记为可执行，能力映射到
已登记的 32 个内置能力，启动自检校验能力/权限/验收完整性。`SpecializedAgentCatalog` 会为
每个角色创建专属 Prompt（Draft v1）并幂等创建/发布 Definition，重复调用返回同一已发布
Definition。游戏工作流模板包含概念设计、核心玩法、UI、TileMap 关卡与代码质量 5 条，每条
步骤对应一个 Phase（review_required=True）与一个已登记 Agent，末尾为用户确认或客观验证节点；
服务复用 E4 Definition/Instance，实例化后 Workflow 处于 READY，Phase/Node 状态仍由 Workflow
Engine 独占。结果集成新增严格 `prepare`：要求 Team 内全部 Assignment 完成且有输出，重复
output_reference 视为接口冲突，随后可 APPLYING → VERIFYING → COMPLETED，提交验证必须携带
verification_reference、已存在集成计划且来源仍完成。评审服务支持 7 种 Review 类型与
ACCEPTED/NEEDS_REVISION/REJECTED 结论；被审查 Assignment 必须完成且有输出，审查人需属于
同一 Team 且与被审查者独立（不同 Definition 或同 Definition 的不同实例），自审拒绝；非通过
评审必须提供 findings 与修改建议，完成时必须提供证据，Review 明确标记 `requires_verification`
且不替代 Verification System。启动注册 `specialized_agent_catalog`、`game_workflow_service`
与 `review_service`。新增 12 个测试（6 单元目录/模板 + 6 集成目录/工作流/集成/评审），
后端 580 passed，ruff 全通过。

交付（M6）：新增 `multi_agent/{budget,observability,demo}.py`、`app/api/multi_agent.py`、
`app/schemas/multi_agent.py`，并扩展管理界面与安全策略。Team Budget 只允许 Orchestrator
在 Task 授权范围内分配，缺少必需维度、负数、未知项或非法超限策略均拒绝；重新分配必须提供
原因并按版本号更新，全部写入 `allocation_log_json`；运行期按 model/tool call、token、
cost、时长、重试、Agent 数与并发数累计，超出上限持久化 `EXHAUSTED` 并失败关闭。可观测性
提供 Team Dashboard（成员、Assignment 计数、预算、缺失输出、接口冲突、依赖图）、
Assignment Dashboard（依赖、资源锁、Handoff、评审、阻塞依赖）、Team 事件时间线与项目
总览，全部只读。API 以 `/api/v1/agent-teams`、`/agent-assignments`、`/agent-handoffs`、
`/agent-capabilities`、`/agent-conflicts` 暴露 Team/Assignment/Handoff/Capability/Conflict；
所有读写均要求认证并按 Project Scope 授权，Team 创建仍走 Orchestrator，重复活动 Team 被
拒绝；Handoff 接受由 Orchestrator 执行且重复接受返回既有结果，拒绝必须记录原因；未完成
Assignment 的结果返回 409。管理界面新增 Multi-Agent Team 列表、Team 详情（Assignment、
依赖图、Handoff、冲突、集成、预算）与能力浏览。Platformer Demo 固化 5 个实战子任务
（设计、玩家控制、TileMap 关卡、HUD、集成）及依赖关系，供 E7-M7 端到端演示与验收使用。
迁移 `000021` 增加 `agent_team_budgets.allocation_log_json` 与
`agent_handoffs.rejection_reason`。新增 7 个测试（2 单元 Demo 计划 + 2 集成预算 + 3 集成
可观测性/API/Demo 编排），后端 587 passed，ruff 全通过。

交付（M7）：新增 `tests/integration/test_e7_e2e.py`（4 个端到端测试）并输出
[E7 验收报告](e7-acceptance-report.md)。E2E 覆盖 E7.md §29.5 全部 12 步：创建 Task →
Orchestrator 分解 → 创建 Team → 能力匹配专业 Agent → 创建 Assignment（无依赖 READY、
有依赖 BLOCKED）→ 并行执行独立子任务 → 资源写冲突拒绝与冲突解决 → Shared Context
版本化 → Handoff 由 Orchestrator 执行并创建目标 Assignment → Lead 集成（APPLYING →
VERIFYING → COMPLETED）→ 提交 Verification → Task System 按合法路径
`READY → QUEUED → RUNNING → REVIEW_PENDING` 接收，Task 最终状态未被 Agent 直接改写。
恢复与幂等：同一 Attempt 重复编排被拒绝（`TEAM_ALREADY_EXISTS`）、重复 claim 被拒绝、
RUNNING Assignment 在重启后保持原状态与 `agent_instance_id`；中断场景：源 Assignment
取消后 Handoff 执行失败并落 `FAILED`，不产生目标 Assignment。安全：无项目访问的客户端
访问 `/api/v1/agent-teams` 返回 403。后端 591 passed（unit + integration 549 / contract
42），ruff 全通过，迁移 head `000021`。

## 12. E8 实施进度（8 批次 / 20 任务，验收通过）

设计文档：[E8 Asset Pipeline](../../完整开发计划细分/E8.md)。批次按依赖划分：

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E8-M1 | T01 资产领域与契约、T02 资产注册中心 | ✅ 已完成 |
| E8-M2 | T03 版本管理、T04 Asset Brief 与规格 | ✅ 已完成 |
| E8-M3 | T05 生成编排、T06/T07/T08 图像/音频/3D 适配器 | ✅ 已完成 |
| E8-M4 | T09 处理流水线、T10 质量门控与人工审核 | ✅ 已完成 |
| E8-M5 | T11 Godot 导入、T12 来源追踪、T13 License | ✅ 已完成 |
| E8-M6 | T14 依赖图、T15 交付与 ChangeSet、T16 恢复 | ✅ 已完成 |
| E8-M7 | T17 资产界面、T18 Agent 集成、T19 API 与事件 | ✅ 已完成 |
| E8-M8 | T20 测试与 Platformer Demo 资产实战、验收报告 | ✅ 已完成 |

M1 交付：`modules/asset_pipeline/{models,repository,storage,service}.py`，
迁移 `000022` 建立 19 张资产表（Asset / Version / Variant / Brief / Generation /
Processing / Import / Evidence / Provenance / License / Quality / Dependency /
Delivery / Storage / Provider Job），`AssetRegistry` 服务支持创建、查询、
类别/类型/标签/状态/来源/License 状态过滤、重复资产、孤儿资产、引用查询、
生命周期迁移与软删除；内部存储按项目与区域隔离，拒绝绝对路径、`..`、
平台保留名与静默覆盖，写入采用原子替换；新增 15 个 E8 错误码与 12 个
`asset.*` 权限动作（审批/交付/回滚/归档仅 Owner）；新增 10 个共享契约 schema、
5 个样例与契约测试；新增 35 个单元/集成测试。后端 626 passed，ruff 全通过，
迁移 head `000022`。

M2 交付：新增 `modules/asset_pipeline/versioning.py`（不可变版本创建、内容 Hash
校验、父版本关系、相同内容幂等返回、版本比较、回滚切换当前引用、变体创建与
版本关联），`modules/asset_pipeline/briefs.py`（图像/音频/3D/资源四类技术规格
校验、Godot 资源类型白名单、Brief 状态机与版本递增、生成规格导出）；
启动注册 `asset_version_service` 与 `asset_brief_service`；新增 27 个单元/集成
测试。后端 653 passed（unit + integration 611 / contract 42），ruff 全通过。

M3 交付：新增 `modules/model_gateway/asset_generation.py`（图像/音频/3D 统一
Adapter 契约、能力声明、`UNKNOWN` 不可用规则、Adapter 注册表）与
`asset_adapters/{image,audio,model3d}.py`（OpenAI Images、OpenAI Speech、
本地 3D 服务；图像尺寸/格式/透明度校验，WAV/OGG 技术指标检查，GLB/glTF/OBJ
几何与材质检查）；Model Gateway 增加 `resolve_asset_provider` /
`submit_asset_generation` / `query_asset_generation` / `cancel_asset_generation`，
显式 Provider/模型选择，禁止静默切换；新增 `IMAGE_OUTPUT` 与 `MODEL_3D_OUTPUT`
能力；新增 `modules/asset_pipeline/generation.py`（Brief 与规格校验、幂等键与
请求 Hash、预算预留、Provider Job、结果暂存、不可变版本与 Provenance 写入、
`UNKNOWN` 不重提交、失败状态持久化）；启动注册 `asset_generation_orchestrator`；
新增 21 个单元/集成测试。后端 674 passed（unit + integration 632 / contract 42），
ruff 全通过。

M4 交付：新增 `modules/asset_pipeline/processing_types.py`（处理产物/载荷、资源限制、
Processor 契约与注册表、DAG 拓扑排序与环检测、单输出校验、步骤执行记录）与
`processors/{image,audio,model3d}.py`（Pillow 图像解码/缩放/裁剪/留白/去背景/Alpha
校验/格式与颜色转换/Sprite Sheet 切分/图集打包/像素放大/压缩/元数据；PCM WAV
重采样/声道转换/格式与位宽转换/响度归一化/峰值限制/静音裁剪/淡入淡出/循环点检测/
位深压缩；GLB/glTF/OBJ 几何与材质检查，未实现能力不注册）；新增
`modules/asset_pipeline/processing.py`（图与处理器校验、幂等键与请求 Hash、
`QUEUED→RUNNING→SUCCEEDED/FAILED`、逐节点步骤记录、输出写入 `processed` 区域、
创建 `PROJECT_DERIVED` 不可变版本并登记存储对象、结构化失败持久化）与
`quality.py`（图像解码/格式/尺寸/文件大小/颜色模式/Alpha/透明边缘/帧数/Sprite 网格/
感知 Hash，音频解码/采样率/声道/时长/峰值/削波/静音/循环接缝，3D 解析/空几何/面数/
UV/材质/贴图/骨骼，重复内容检测；机器检查与人工审核独立记录、绑定版本、
`HUMAN_REVIEW_REQUIRED→APPROVED/REJECTED` 且禁止覆盖）；新增
`AssetQualityFindingRepository`；启动注册 `asset_processing_pipeline` 与
`asset_quality_control`；新增 18 个单元/集成测试。后端 692 passed
（unit + integration 650 / contract 42），ruff 全通过。

M5 交付：新增 `modules/asset_pipeline/imports.py`（真实验证目标文件 Hash 属于版本
存储对象、解析已连接 Editor Session、经 Editor Bridge 下发 `godot.asset.import` 并
读取真实 `uid://`、`REQUESTED→IMPORTING→IMPORTED/FAILED`、超时/断线记 `UNKNOWN`
且不重复导入、`refresh` 通过只读 `godot.asset.import_status` 恢复、每次终态写入
导入证据含源文件 Hash/会话/Godot 版本/UID）、`provenance.py`（按版本唯一来源记录、
重复请求幂等、冲突拒绝、沿父版本追溯、AI 生成与衍生资产的交付完整性校验）与
`license.py`（有凭证才进入 `PENDING_REVIEW`、未知来源保持 `UNKNOWN`、人工核验才
`VERIFIED`、权限字段与署名完整性、追加证据、过期自动 `EXPIRED`、`check_deliverable`
门禁）；处理流水线在创建衍生版本时同步写入 `PROJECT_DERIVED` 来源；Godot 插件新增
`godot.asset.import` / `import_status` / `resource_uid` 工具；启动注册
`asset_import_service`、`asset_provenance_service`、`asset_license_service`；
新增 9 个集成测试。后端 701 passed（unit + integration 659 / contract 42），
ruff 全通过。

M6 交付：新增 `modules/asset_pipeline/dependencies.py`（依赖记录幂等、按目标查询
引用、孤儿资产、失效引用、循环依赖检测、版本替换/删除影响分析且强制经
ChangeSet）、`delivery.py`（来源完整性 + 质量审核 + License 交付门禁、生成
ChangeSet 与审批请求、审批绑定内容 Hash、`DRAFT/READY → WAITING_APPROVAL →
APPROVED → APPLYING → IMPORTING → VERIFYING → DELIVERED` 状态机、缺少真实
`IMPORTED` 与 `uid://` 时拒绝交付、Hash 变化后审批失效、`reconcile` 按真实导入
证据恢复）与 `recovery.py`（按项目汇总 Generation/Processing/Import/Delivery 的
`UNKNOWN` 清单、统一幂等键、Provider/处理产物/导入状态逐项核对、无法确认时保持
`UNKNOWN` 并交由人工）；验收补充 repository 状态查询方法；启动注册
`asset_dependency_service`、`asset_delivery_service`、`asset_recovery_service`
（交付服务接入 Approval 校验）；新增 8 个集成测试与 4 个单元测试。后端 713
passed（unit + integration 671 / contract 42），ruff 全通过。

M7 交付：新增 `app/api/assets.py` 与 `app/schemas/asset_pipeline.py`（资产创建/过滤
查询/元数据更新/版本与依赖读取、生成与处理任务提交及状态读取、机器与人工质量
审核、License 登记与核验、Godot 导入与只读核对、交付计划/审批/审批有效性/结果
验证；全部按项目授权，Job 必须带 ID，交付仍经 ChangeSet、Approval 与 Tool
System）、`modules/asset_pipeline/dashboard.py`（资产浏览器聚合：当前版本、质量、
License、导入 UID、交付、依赖计数与四类 `UNKNOWN` 汇总）；管理界面新增资产面板
并调用仪表盘接口；Tool Registry 登记 10 个 `asset.*` 只读/请求工具；2D 美术、
动画、艺术总监、音频、VFX、3D 与资产管线专家接入资产契约且不授予 `file.write`；
新增 3 个 API 集成测试与 1 个 Agent 契约测试。后端 717 passed
（unit + integration 675 / contract 42），ruff 全通过。

M8 交付：新增 `tests/integration/test_e8_acceptance.py` 与
[E8 验收报告](e8-acceptance-report.md)。验收测试覆盖三类关键证据：
Platformer Demo 资产全生命周期（Brief 创建/提议/批准 → 生成来源 → 处理 DAG →
机器 QC → 人工审核 → License 核验 → 依赖记录 → 交付 ChangeSet/审批 →
项目文件写入 → Editor Bridge 导入获得 `uid://` → 交付 `DELIVERED` →
替换影响分析与仪表盘聚合）；路径穿越与跨项目隔离（`AssetPathInvalid`、
`NotFoundError`、跨项目交付拒绝）；故障注入（License 过期阻断交付、
Processing `UNKNOWN` 且无产物时恢复抛 `AssetRecoveryRequired`）。
E8 共 96 个测试函数（14 个文件）+ 4 个契约测试（10 schema / 5 样例）。
后端 720 passed（unit + integration 678 / contract 42），ruff 全通过，
迁移 head `000022`。E8 阶段完成，可进入 E9 Verification & QA。

## 13. E9 实施进度（8 批次 / 20 任务，验收通过）

设计文档：[E9 Verification & QA](../../完整开发计划细分/E9.md)。批次按依赖划分：

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E9-M1 | T01 验证领域与契约、T02 测试用例注册、T03 需求追踪与验收标准 | ✅ 已完成 |
| E9-M2 | T04 Verification Plan Engine、T05 Verification Orchestrator | ✅ 已完成 |
| E9-M3 | T06 静态分析、T07 Scene / Resource 校验 | ✅ 已完成 |
| E9-M4 | T08 Runtime 验证、T09 Functional Test Runner、T10 Debugger 集成 | ✅ 已完成 |
| E9-M5 | T11 视觉验证、T12 性能验证、T13 证据管理 | ✅ 已完成 |
| E9-M6 | T14 缺陷管理、T15 回归与影响分析 | ✅ 已完成 |
| E9-M7 | T16 质量门禁、T17 Phase Review、T18 Dashboard / UI | ✅ 已完成 |
| E9-M8 | T19 Agent 集成与验证策略、T20 Platformer Demo 验收、验收报告 | ✅ 已完成 |

M1 交付：`modules/verification/{models,repository,service}.py` 建立 Campaign / Plan /
Run / Result / TestCase / Criterion / TestLink / Evidence 等表与状态机；迁移 `000023`
新增核心验证表；新增 12 个 E9 错误码与 13 个 `verification.* / defect.* /
quality_gate.* / phase_review.*` 权限；六层验证体系与 `UNKNOWN ≠ FAILED`、
`SKIPPED ≠ PASSED`、结果不可原地改写等冻结规则以单元测试锁定。

M2 交付：`planner.py` 从需求 → 验收标准 → 测试用例推导验证层次，覆盖缺口会阻断计划并
给出 gap；`orchestrator.py` 按计划逐层执行，写入结果与证据并将 Campaign 推进到
`COMPLETED/FAILED`，无执行器、执行器失败、通过无证据均失败关闭。

M3 交付：`godot/static_analyzer.py`（project.godot、GDScript 括号/缩进/重复类名扫描）、
`scene_validator.py`（ext_resource、根节点、同级重名、连接目标、必需节点类型）、
`resource_validator.py`（`res://` 引用与 `.import` 元数据）、`executors.py`（报告 →
证据 + 结果草稿，来源用 `verification://` 标识报告而非伪造文件路径）。

M4 交付：`runtime.py`（环境 CRUD、租约、启动/停止/查询、驱动失败与查询失败保持
`UNKNOWN`）、`functional.py`（步骤断言、超时、基础设施错误与功能失败分离、清理失败不
反转结果）、`debugger.py`（错误分类、地址/数字去噪指纹、基线化阻断策略）；迁移
`000024` 新增运行时环境与 Debugger 错误表。

M5 交付：`visual.py`（像素差异、动态区域掩码、基线缺失转人工、截图 Hash/尺寸校验）、
`performance.py`（阈值、采样缺失、同环境退化判定）、`evidence.py`（文件存在性与 Hash
校验、失效/过期、截图/运行时上下文完整性）。

M6 交付：`defect.py`（缺陷类别 → 推荐 Agent、严重度 → 优先级、汇总）、`impact.py`
（`res://` 反向依赖扫描、SECURITY > FULL > DEPENDENCY > TARGETED 回归策略、
历史缺陷与覆盖缺口）；迁移 `000025`；新增缺陷 5 路由、影响分析与回归计划 API。

M7 交付：`quality_gate.py`（GATE-1…GATE-10、按 Campaign 类型/风险选门禁、FAILED >
BLOCKED > UNKNOWN > PARTIAL > PASSED 合并、有效豁免转 `WAIVED`）、`phase_review.py`
（建议结论、风险、用户确认事项，通过率只算已执行）；迁移 `000026/000027`；新增门禁
策略/评估/豁免、Phase Review 与 4 个 Dashboard API。

M8 交付：`agent_policy.py`（Agent 允许/禁止操作矩阵、按风险级别的验证预算）、
`agent_request_verification` / `agent_request_run`（策略 + 真实预算计算后执行）、
Agent 策略与预算 API；新增 `tests/unit/test_e9_agent_policy.py`、
`tests/integration/test_e9_agent_budget.py` 与 `tests/integration/test_e9_acceptance.py`
（Platformer 验证闭环 + 缺陷修复回归闭环）；[E9 验收报告](e9-acceptance-report.md)。
E9 共 26 个测试文件（25 个业务 + 1 个契约）/ 132 个业务测试函数。阶段完成，可进入 E10 Build & Release。

## 14. E10 实施进度（6 批次 / 20 任务，验收通过）

设计文档：[E10 Build & Release](../../完整开发计划细分/E10.md)。批次按依赖划分：

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E10-M1 | T01 领域与状态机、T02 构建配置与版本、T03 Export Preset、T04 环境管理 | ✅ 已完成 |
| E10-M2 | T05 Build Orchestrator、T06 Godot Headless Adapter、T07 平台导出适配器、T17 恢复 | ✅ 已完成 |
| E10-M3 | T08 Artifact Registry、T09 Packaging、T13 Provenance / Evidence | ✅ 已完成 |
| E10-M4 | T11 Release Candidate、T14 Artifact Verification / Smoke Test | ✅ 已完成 |
| E10-M5 | T10 Signing & Secrets、T12 Release Approval、T15 Release Manager、T16 Local Distribution | ✅ 已完成 |
| E10-M6 | T18 Dashboard / UI、T19 Agent 集成、T20 Platformer Demo 验收、验收报告 | ✅ 已完成 |

M1 交付：`modules/build_release/models.py` 建立 Build Configuration / Version / Export
Preset / Environment / Platform Capability / Build Job / Attempt / Log 表与状态机，
`service.py` 提供配置版本快照（未变化拒绝发布新版本）、Environment 指纹去重与
`READY / READY_WITH_WARNINGS / BLOCKED` 判定、平台能力默认集；迁移 `000028`；
新增 E10 错误码与 `build.* / artifact.* / release.* / signing.* / distribution.*`
权限动作。

M2 交付：`adapter.py`（受控执行器：可执行文件白名单、路径守卫、环境变量白名单、
超时与日志脱敏、`EXEC_*` 结果）、`orchestrator.py`（启动前门禁全部通过后才进入
`PREPARING/RUNNING`；exit=0 但无产物仍失败；超时/无法判定进入 `UNKNOWN`；
`recover_build` 依据产物存在性收敛，禁止直接重试 `UNKNOWN`）。

M3 交付：`artifacts.py`（内容不可变：同内容幂等、不同内容新版本；manifest 哈希重算
校验完整性）、`packaging.py`（清单哈希 + 包哈希、绑定校验失败转 `REJECTED`）、
`provenance.py`（按 build/attempt 幂等，追加 signing/approval/distribution 等证据）；
迁移 `000029`。

M4 交付：`smoke_test.py`（`SKIPPED ≠ PASSED`，空检查不得通过；冒烟结果写入证据）、
`release_candidates.py`（候选要求制品与交付包均 `VERIFIED` 且绑定一致；校验清单哈希、
制品验证、包验证、冒烟通过、验证证据，失败转 `REJECTED`，通过转
`READY_FOR_APPROVAL`）；迁移 `000030`。

M5 交付：`signing.py`（只保存证书/凭证引用，明文密钥拒绝；UNKNOWN 必须核对后收敛；
失败不覆盖制品）、`release_approvals.py`（审批绑定候选清单/制品/包哈希，内容变化
自动失效；审批结果写证据）、`release_manager.py` 与 `distribution.py`（发布状态机、
本地交付幂等键、复制后哈希校验、发布后验证、撤回与回滚标记）；迁移 `000031`。

M6 交付：`dashboard.py`（构建队列/制品/包/候选/审批/发布聚合与渠道能力）、
`agent_policy.py`（11 项允许操作、7 项禁止操作、5 个 Agent 角色权限矩阵）；
`app/api/releases.py` 与 `app/api/builds.py`、`app/api/artifacts.py` 覆盖签名、
审批、发布与分发；新增 `tests/integration/test_e10_acceptance.py`
（构建 → 制品 → 包 → 候选 → 冒烟 → 用户审批 → 本地交付 → 发布后验证闭环，
以及 `UNKNOWN` 构建恢复）。

## 15. E11 实施进度（20 任务，验收通过）

设计文档：[E11 Platformer Demo](../../完整开发计划细分/E11.md)。交付按 7 个批次：

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E11-M1 | T01 需求分析、T02 游戏设计、T03 技术架构 | ✅ 已完成 |
| E11-M2 | T04 项目初始化与工程基础 | ✅ 已完成 |
| E11-M3 | T05 玩家、T06 战斗、T07 敌人、T08 关卡、T09 收集与分数 | ✅ 已完成 |
| E11-M4 | T10 UI 与流程、T11 表现层、T12 存档 | ✅ 已完成 |
| E11-M5 | T13 多 Agent、T14 ChangeSet / Approval、T15 Context | ✅ 已完成 |
| E11-M6 | T16 验证与 QA、T17 构建与发布 | ✅ 已完成 |
| E11-M7 | T18 可观测性 / UX、T19 稳定性、T20 最终验收 | ✅ 已完成 |

M1 交付：`modules/demo_game/{specification,models,repository,service}.py` 把 21 条需求、
36 条验收条件、8 个机制、8 个功能、1 个关卡与 18 个测试场景编码为可追踪基线，
支持规格冻结、条件/场景状态更新、验收结论（`ACCEPTED / ACCEPTED_WITH_NOTES / REJECTED`，
拒绝必须带后续修复任务）与系统报告聚合；迁移 `000032` 新增 8 张 `demo_game_*` 表；
新增 `demo.read / demo.manage / demo.accept` 权限（验收仅 Owner）；`app/api/demo.py`
提供规格、需求、功能、机制、关卡、场景、验收与 `system-report` 端点。

M2 交付：`demo/platformer/godot_project` 可被 Godot 4.5.1 打开，主场景
`res://scenes/main/main.tscn`，5 个自动加载单例，`move_left / move_right / jump / attack /
pause` 输入映射，960 × 540 `gl_compatibility`；`test_e11_godot_project.py` 校验工程设置、
输入映射、场景/资源引用、资产齐备与无头冒烟入口。

M3 交付：玩家控制器（移动/跳跃/攻击/受伤/死亡）、Hitbox/Hurtbox 战斗、巡逻敌人、
`TileMapLayer` 地面与平台层、地刺陷阱、终点、金币/宝石收集与 ScoreManager；
`runtime_verifier.tscn` 用真实输入驱动 24 项用例，全部 PASS。

M4 交付：主菜单、HUD、暂停菜单、结算界面、`GameFlowManager`、`AudioManager`
（BGM + 跳跃/受伤/收集音效）、`SaveManager`（最佳分数，损坏存档回退默认值）。

M5 交付：复用 E4 ChangeSet 与 E7 多 Agent 编排；交付链路测试以真实文件 SHA-256
登记交付物并完成 `VALID → APPROVED → APPLYING → APPLIED`，Context 装配返回项目层。

M6 交付：`tests/integration/test_e11_delivery_chain.py` 在真实工程文件上执行
STATIC / STRUCTURE / RESOURCE 三层验证，绑定 `runtime-verify.log` 作为真实运行证据；
再以真实 Godot headless 导出 `PlatformerDemo.exe`，完成不可变制品、交付包、发布候选、
冒烟（`exported-smoke.log`，13 项检查）、用户审批、本地交付与发布后哈希复核。

M7 交付：`system-report` 聚合规格覆盖度、需求追踪、验证与构建摘要；用户验收
`ACCEPTED_WITH_NOTES`（视觉/音频保留人工确认）；输出 [E11 验收报告](e11-acceptance-report.md)
与 [Demo 交付说明](../../demo/platformer/reports/acceptance-report.md)。

质量门禁：E11 测试 17 passed（规格 6 / 工程 9 / 交付链路 2），后端全量 pytest 916 passed / 1 warning（956.89s），
ruff check / format 全通过，结构检查与敏感扫描通过，契约 57 passed，迁移 head `000032`，
Godot 运行时验证 24 / 24，导出冒烟 PASS。

## 16. E12 实施进度（20 任务，验收通过）

设计文档：[E12 Productization](../../完整开发计划细分/E12.md)。交付按 20 个任务展开：

| 任务组 | 任务 | 状态 |
| --- | --- | --- |
| 产品域 | T01 领域与契约、T02 架构与打包、T18 API/扩展稳定性 | ✅ 已完成 |
| 交付与运行 | T03 安装器与首运、T04 配置与 Secrets、T05 License、T06 更新、T07 迁移、T08 回滚恢复 | ✅ 已完成 |
| 质量与治理 | T09 兼容性、T10 安全加固、T11 隐私、T12 诊断、T15 性能、T16 长期运行、T17 支持维护 | ✅ 已完成 |
| 体验与发布 | T13 文档、T14 UX、T19 发布流水线、T20 GA 验收 | ✅ 已完成 |

T01/T02 交付：`modules/product/{models,repository,versioning,service}.py` 与迁移
`000033_e12_product_core.py`（20 张产品表），产品版本 `1.0.0` 与游戏制品版本域
`game_artifact` 强制隔离；11 个组件版本与 10 项契约登记，未知/超版本契约返回 `UNKNOWN`。

T03/T04 交付：`installer.py` 的安装状态机、目录隔离预检查、10 项验证、回滚与卸载、
插件 `SKIP/INSTALL/UPGRADE/CONFLICT` 计划、12 步首次运行向导；`configuration.py`
四层配置、受保护键、明文 Secrets 拒绝与脱敏导出；模型不可用直接失败。

T05/T06/T07/T08 交付：`licensing.py`（离线宽限、过期、时钟异常、Feature 默认关闭）、
`updates.py`（DEV/BETA/STABLE、HMAC 签名、哈希、批准、禁止降级）、
`migrations.py`（目标 schema、降级阻断、强制备份、失败标记）、
`recovery.py`（恢复点、UNKNOWN 人工核实、保留用户数据、不删除项目）。

T09–T12 交付：`compatibility.py` 平台/Godot/Python/协议/schema 矩阵与 UNKNOWN 规则；
产品动作 RBAC（读允许非 Agent、变更仅 admin、Agent 全拒绝）与产品审计；
`privacy.py` 遥测默认关闭、上下文预览脱敏、删除范围隔离；
`diagnostics.py` 9 个错误码、支持包脱敏与 SHA-256、崩溃报告 `LOCAL_ONLY`。

T13/T14/T19/T20 交付：[用户指南](../05-product/user-guide.md)、
[开发者指南](../05-product/developer-guide.md)、[运维手册](../04-operations/runbooks.md)、
[发布目录说明](../../release/README.md)、`scripts/release/build_product.py`
（产品/组件/契约/兼容性清单 + SBOM + 校验和）、`release_pipeline.py`
（7 类证据、签名、SBOM、审批与发布）、[E12 验收报告](e12-acceptance-report.md)。

质量门禁：E12 新增 37 个测试（单元 23 / 集成 14）；后端全量 pytest 953 passed / 1 warning，
ruff 全通过，迁移 head `000033`，`build_product.py --check` 通过，
`check_all.py` 8 阶段全 PASS（详见验收报告 §8）。

## 17. 已知问题与待办

| 事项 | 影响阶段 | 状态 |
| --- | --- | --- |
| Godot runtime 首次启动 `signal 11`，根因未确证，已不再复现 | E9 | E9 已建立 runtime 冒烟与 `UNKNOWN` 保守映射；真实启动链路留 E11 复验 |
| Runtime 自动化使用可注入 Driver，CI 未拉起真实 Godot | E9 / E11 | ✅ E11 接入真实 headless 运行时（24 项用例）；截图/视觉差异管线仍未接入 |
| Godot 4.5.1 导出模板 | E10 | ✅ 已安装（`%APPDATA%\Godot\export_templates\4.5.1.stable`） |
| 无 Python 干净机器上的打包验证 | E10 | 待安装包制作时执行 |
| CI 未覆盖打包冒烟与 Markdown 链接检查 | E10 / E12 | 待补；E12 已提供 `build_product.py --check` 供接入 |
| macOS / Linux 桌面安装器未真机验证 | E12 | 兼容性矩阵标记 UNVERIFIED / PARTIAL，不宣称 GA 支持 |
| 未执行 24 小时长稳与多进程压测 | E12 | 依赖状态机、幂等、健康检查与 E1 性能基线；后续补压测 |
| 产品管理页面复用浏览器管理页，未提供独立安装向导 UI | E12 | 产品流程以 API 与状态机交付，UI 后续增强 |
| 更新签名使用内置 HMAC 密钥 | E12 | 适用于本地/离线分发；公共分发需非对称签名与密钥轮换 |
| onefile 便携产物的杀软误报 | E10 | 分发前在目标环境实测 |
| Demo 视觉为静态占位 SVG，无逐帧动画；音频为占位音效 | E11 | P1 表现层，视觉/音频需人工确认 |
| Demo 未登记 12 Phase 专用 Workflow 模板，未新增独立多 Agent 编排场景 | E11 | 复用 E4 Workflow 与 E7 `game_workflow_service` / E2E 证据 |
| 导出产物（约 92 MB）不入库，CI 无 Godot 时跳过真实导出用例 | E11 | 需可执行文件时在目标环境重新导出 |
| 管理界面为浏览器单页，未提供 Godot 编辑器 Dock | E5+ | 本期按最小实现处理 |
| Workflow 未实现并行分支与节点超时重试 | E5+ | 后续 Workflow 增强 |
| 启动恢复将未完成 Attempt 置 `UNKNOWN`、Task 置 `BLOCKED` | E5 | 自动重试策略由 Agent 执行层实现 |
| 归档阻塞统计最多扫描 200 条 Workflow/ChangeSet | E5 | 需要时改聚合计数查询 |
| Runtime 凭证（`client_type=tool`）API 已支持，管理界面未提供签发入口 | E5 | 客户端管理界面补齐 |
| 多 Agent 并发以单进程 asyncio 模拟，未做多进程/多后端压测 | E7 | 单后端 SQLite，写入由资源锁与事务串行化 |
| Attempt 失效时运行中多 Agent 的联动回收未做专项测试 | E7 | 编排入口拒绝不可运行 Attempt；运行中隔离依赖 Agent Runtime |
| 存量规划文档归档 `docs/` | E12 | ⏳ 规则已定，归档不阻塞 GA |
| Godot 安装路径含中文（建议迁 ASCII） | — | 非阻塞，未执行 |

## 18. 维护规则

1. 每完成一个任务勾选或更新状态，每阶段结束同步本文件与阶段验收报告。
2. 状态符号：`✅ 已完成 / ⏳ 进行中 / ⬜ 未开始 / ⛔ 阻塞`。
3. 新增已知问题或风险时，必须写明影响阶段与处理状态。
4. 阶段验收结论以对应 `docs/00-project/e*-acceptance-report.md` 为准。
