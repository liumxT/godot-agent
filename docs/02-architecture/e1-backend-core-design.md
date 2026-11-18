# E1 Backend Core 设计与任务拆解

- **状态：** DRAFT（待评审）
- **日期：** 2026-11-18
- **依据：** [E1.md](../../完整开发计划细分/E1.md)、[实施蓝图.md](../../实施蓝图.md)、[ADR-004](../06-decisions/ADR-004-database.md)
- **前置：** E0 已通过验收（[验收报告](../00-project/e0-acceptance-report.md)）

## 1. 目标与边界

把 E0 的骨架升级为可长期承载业务模块的 Backend Core：统一生命周期、配置、数据库、迁移、
仓储、事务、日志、异常、事件、备份、健康检查与诊断。

E1 不实现 Task / Workflow / Agent / Tool / Godot Bridge / Asset 等业务能力；只提供它们
将来依赖的基础接口，且 Core 不允许反向依赖业务模块（E1-ARC-001）。

## 2. 现状与差距

| 能力 | E0 现状 | E1 需要补齐 |
| --- | --- | --- |
| 生命周期 | `bootstrap/lifecycle.py` 顺序执行 hook，无状态机、无超时、无资源清理登记 | 状态机、有序步骤、失败回滚、关闭超时、信号处理 |
| 配置 | `config/settings.py`（pydantic-settings，env + `.env`） | 默认 → 文件 → 环境 → 运行时覆盖、字段变更策略、快照 |
| 数据库 | `engine.py`（PRAGMA）、`manager.py`（Alembic upgrade + 备份） | Database Manager 统一生命周期、健康检查、错误分类、完整性检查 |
| 迁移 | 仅 upgrade + 版本读取 | 历史记录（checksum/耗时/状态）、失败记录、版本兼容检查 |
| 仓储 / 事务 | 无 | BaseRepository、分页、异常映射、统一事务边界与超时 |
| 日志 | 控制台 JSON、上下文绑定 | 文件输出、轮转与保留、脱敏过滤器、测试工具 |
| 异常 | `AppError` + 两个子类 | 完整分类、数据库/超时/权限错误映射、错误码登记 |
| 事件 | 契约 schema 已有，无实现 | 事件模型、注册表、发布/订阅、Outbox/Inbox、重试与恢复 |
| 备份 / 恢复 | 升级前自动备份 | 手动/自动备份、元数据、完整性校验、保留策略、恢复与保护副本 |
| 健康 / 诊断 | `/health` 静态占位 | live / ready、依赖聚合、HEALTHY/DEGRADED/UNHEALTHY、诊断摘要 |

## 3. 模块与依赖

```text
app (HTTP 入口、路由)
 │
bootstrap (装配、ServiceRegistry、FastAPI lifespan 适配)
 │
core (生命周期状态机、事件抽象、错误、日志抽象)   ← 不依赖 infrastructure
 │
infrastructure (SQLite、迁移、事务、仓储、备份、事件持久化、Secrets)
 │
modules/* (E2 起填充业务模块；只能依赖 Core 公开接口)
```

依赖规则（评审检查项，对应 E1-ARC-001…010）：

1. `core/` 不导入 `infrastructure/`、`modules/`、`app/`。
2. `modules/*` 不导入其他模块的 `repositories/`，跨模块只走 Service API 或事件。
3. 数据库连接只能由 `infrastructure.database` 创建，Repository 不持有引擎。
4. 事务边界只能出现在 Service / 应用层，Repository 内不提交。
5. 事务内禁止外部 AI 调用与人工审批等待。
6. 事件消费必须假设重复投递。
7. 异常不得吞掉；日志不得输出 Secrets。

## 4. 目录映射（E1.md 建议 → 实际落地）

```text
apps/backend/src/
├── app/
│   ├── main.py                     # 已有，保留
│   └── api/
│       ├── health.py               # 扩展：/health、/health/live、/health/ready
│       └── diagnostics.py          # 新增：/diagnostics/summary
├── bootstrap/
│   ├── application.py              # 已有：create_app 装配
│   ├── lifecycle.py                # 改为 FastAPI lifespan 适配器
│   ├── service_registry.py         # 新增：服务持有与按名获取
│   ├── startup.py                  # 新增：启动步骤注册
│   └── shutdown.py                 # 新增：关闭步骤注册
├── config/
│   ├── settings.py                 # 已有：Settings 保持不变
│   ├── layers.py                   # 新增：默认/文件/环境/覆盖分层
│   ├── policies.py                 # 新增：IMMUTABLE / RESTART_REQUIRED / HOT_RELOAD
│   └── service.py                  # 新增：ConfigService（快照、变更校验、日志）
├── core/
│   ├── errors.py                   # 扩展异常层级
│   ├── logging.py                  # 扩展文件输出、轮转、脱敏
│   ├── events/
│   │   ├── model.py                # Event 模型（对齐契约）
│   │   ├── bus.py                  # Publisher / Subscriber
│   │   └── registry.py             # 事件类型与处理器注册
│   └── lifecycle/
│       ├── states.py               # CREATED…FAILED
│       └── manager.py              # 状态机、步骤、超时、回滚
└── infrastructure/
    ├── database/
    │   ├── engine.py               # 已有
    │   ├── manager.py              # 改动：迁移历史、版本检查
    │   ├── service.py              # 新增：DatabaseService（引擎/会话/关闭/健康）
    │   ├── transaction.py          # 新增：事务上下文与超时
    │   ├── repository.py           # 新增：BaseRepository、分页、异常映射
    │   ├── backup.py               # 新增：备份/恢复/保留
    │   ├── health.py               # 新增：integrity_check、revision 状态
    │   └── errors.py               # 新增：数据库异常分类
    ├── events/
    │   ├── outbox.py               # 新增：Outbox 仓储
    │   ├── inbox.py                # 新增：Inbox 仓储
    │   └── dispatcher.py           # 新增：轮询派发与重试
    └── secrets/store.py            # 已有
```

迁移文件继续放在 `apps/backend/migrations/versions/`，新增 `000002_event_infrastructure`。

## 5. 关键设计

### 5.1 生命周期（T01）

- 状态：`CREATED → INITIALIZING → STARTING → RUNNING → STOPPING → STOPPED`，异常进入 `FAILED`。
- `LifecycleManager` 注册有序步骤，每步有名称、超时与回滚动作；启动失败按已执行步骤逆序回滚。
- 启动顺序：读取配置 → 日志 → 错误处理 → 数据库 → 迁移 → 基础服务（事件/备份）→ 健康检查 → RUNNING。
- 关闭顺序：停止接收请求 → 停止事件派发 → 等待进行中事务（有上限）→ 关闭事件 → 关闭数据库 → 刷新日志 → STOPPED。
- 重复关闭幂等；关闭超时记录 `error_code=SHUTDOWN_TIMEOUT` 并强制进入 `STOPPED`。
- 信号处理由 uvicorn 负责，`lifespan` 适配器只调用 manager，不重复注册信号。

### 5.2 配置（T02）

优先级（后者覆盖前者）：`Settings` 默认值 → TOML 文件（`GODOT_AI_CONFIG_FILE`，默认
`config/backend.toml`，不存在则跳过）→ 环境变量 `GODOT_AI_*` → 运行时 `overrides`。

| 变更策略 | 字段 | 行为 |
| --- | --- | --- |
| IMMUTABLE | `database_url`、`environment`、`app_name` | 运行时修改一律抛 `CONFIG_ERROR` |
| RESTART_REQUIRED | `host`、`port`、`data_dir`、`log_dir` | 运行时修改被拒绝并提示需重启 |
| HOT_RELOAD | `log_level` | 允许更新并重建日志 handler |

`ConfigService.snapshot()` 返回只读副本；每次加载与变更记录 `config_loaded` / `config_rejected`
事件（值脱敏）。Secrets 不进入配置文件与环境变量合并，仍走 `infrastructure.secrets`。

### 5.3 数据库（T03）

`DatabaseService` 持有 `AsyncEngine` 与会话工厂，负责初始化、健康检查、关闭和错误翻译：

- 初始化：建目录 → 引擎（PRAGMA 沿用 `engine.py`）→ `SELECT 1` → `PRAGMA quick_check`。
- 错误分类：`OperationalError` → `DatabaseError(DATABASE_UNAVAILABLE, retryable=True)`；
  `IntegrityError` → `DatabaseError(DATABASE_INTEGRITY_ERROR, retryable=False)`；
  文件不可写/只读在启动阶段直接 `StartupError`。
- 关闭：`dispose()`，幂等。
- 并发：单写者模型，写事务尽量短，冲突依赖 `busy_timeout=5000` + 上层重试策略。

### 5.4 迁移（T04）

Alembic 仍是执行器与版本事实源（`alembic_version`），新增 `migration_history` 记录审计信息：

| 字段 | 说明 |
| --- | --- |
| revision / name | Alembic revision 与文件名 |
| checksum | 迁移文件 SHA256 |
| status | `applied` / `failed` |
| applied_at / duration_ms | 时间与耗时 |
| error | 失败摘要（脱敏） |

- 执行前备份，执行后写 `applied`；异常写 `failed` 后抛 `MIGRATION_FAILED`。
- 启动时校验 `current_revision == head`，不一致则拒绝进入 RUNNING（E1-FI-004）。
- 已执行迁移文件禁止修改，checksum 变化在评审和测试中检测。

### 5.5 仓储与事务（T05 / T06）

- `BaseRepository(session)`：提供 `get / add / delete / paginate`，分页参数 `limit(1–200)`、
  `offset≥0`，统一返回 `Page(items, total, limit, offset)`。
- 仓储不提交事务、不创建引擎；异常统一翻译为 `DatabaseError`。
- `transaction(session)` 规则：
  - 无事务时 `begin`，退出时提交，异常回滚；
  - 已在事务中则加入外层（不启用 savepoint），E1 不支持真正的嵌套事务；
  - `timeout` 通过 `asyncio.timeout` 包裹，超时回滚并抛 `OperationTimeout(TRANSACTION_TIMEOUT)`；
  - 结束后禁止复用失效会话（由测试覆盖）。
- 模块隔离：每个 Repository 位于 `modules/<name>/repositories/`，禁止跨模块导入；
  以架构测试扫描 `modules/*/repositories` 的导入关系，数据库层不做运行时拦截。

### 5.6 日志（T07）

- 输出：控制台 JSON（已有）+ `log_dir/backend.log`，`RotatingFileHandler(maxBytes=5MB, backupCount=5)`。
- 保留策略：最多 5 个历史文件；启动时校验目录可写，失败则 `StartupError`（E1-FI-005）。
- 脱敏：过滤器按 key 屏蔽 `api_key/token/secret/password/authorization`，并用 Secrets 的
  `redact()` 处理显式值；异常堆栈保留但过滤已知 Secret 字符串。
- 分类通过 `component` 约定：`app.*`、`infra.*`、`db.*`、`security.*`、`audit.*`，不新增字段。
- 测试工具：`capture_logs()` 上下文，断言结构化字段。

### 5.7 异常（T08）

| 异常 | code | HTTP | retryable |
| --- | --- | --- | --- |
| `ValidationFailed` | `INVALID_REQUEST` | 400 | false |
| `AuthenticationError` | `UNAUTHORIZED` | 401 | false |
| `PermissionDenied` | `PERMISSION_DENIED` | 403 | false |
| `NotFoundError` | `NOT_FOUND` | 404 | false |
| `OperationTimeout` | `TIMEOUT` / `TRANSACTION_TIMEOUT` | 504 | true |
| `DatabaseError` | `DATABASE_UNAVAILABLE` / `DATABASE_INTEGRITY_ERROR` | 503 / 500 | true / false |
| `InfrastructureError` | `INFRASTRUCTURE_ERROR` | 500 | 视原因 |
| `MigrationError` | `MIGRATION_FAILED` | 500 | false |
| `BackupError` | `BACKUP_FAILED` / `RESTORE_FAILED` | 500 | false |

新增错误码需同步 `packages/contracts/errors/error-codes.json` 与契约测试；数据库异常统一由
基础设施层翻译，禁止把 SQLAlchemy 异常透出到 API。

### 5.8 事件与 Outbox/Inbox（T09 / T10）

事件模型对齐 `packages/contracts/events/event.schema.json`：
`event_id / event_type / event_version / occurred_at / producer / correlation_id / payload`。

- 发布：业务事务内只写 `event_outbox`；提交后由 `EventDispatcher` 轮询发送给进程内订阅者。
- 派发：`pending → publishing → published`，失败 `failed` 并记录 `retry_count`、`last_error`；
  退避重试（上限可配），进程重启从 `pending` 继续（E1-FI-006/007）。
- 订阅：`EventRegistry` 按 `event_type` 注册处理器，处理器与 `consumer_id` 绑定；
  消费前查 `event_inbox(event_id, consumer_id)`，已处理则返回既有结果（至少一次 + 幂等）。
- 事件处理失败不得静默丢弃；记录失败并暴露到诊断摘要。

### 5.9 备份与恢复（T11）

- 备份：SQLite 在线备份 API（已有实现迁移到 `backup.py`），生成 `.db` + `.json` 元数据
  （时间、revision、大小、sha256）。
- 校验：`PRAGMA integrity_check` + revision 匹配；不通过则拒绝恢复（E1-FI-008）。
- 恢复：停止派发与写入 → 保护副本 → 恢复 → 完整性检查 → revision 检查 → 恢复服务；
  任一步失败回滚到保护副本（E1-FI-009）。
- 保留：按数量保留最近 N 份（默认 10），删除前记录审计日志。

### 5.10 健康与诊断（T12 / T13）

| 接口 | 内容 | 鉴权 |
| --- | --- | --- |
| `GET /health` | 兼容 E0 返回结构，增加 `checks` | 无（仅回环） |
| `GET /health/live` | 进程存活，始终快速返回 | 无（仅回环） |
| `GET /health/ready` | 生命周期 RUNNING、DB 可用、迁移到 head | 无（仅回环） |
| `GET /diagnostics/summary` | 启动时间、状态、DB 版本、Outbox/Inbox 积压、最近错误摘要 | 见 §8 待定项 |

状态：`HEALTHY / DEGRADED / UNHEALTHY / STARTING / STOPPING`。检查不得执行危险写入；
ready 不通过返回 503，`/health` 保留 200 但 `status` 反映真实状态（避免误报健康）。

## 6. 数据模型（E1 新增迁移 `000002`）

```text
event_outbox
  id            INTEGER PK AUTOINCREMENT
  event_id      TEXT NOT NULL UNIQUE
  event_type    TEXT NOT NULL
  event_version INTEGER NOT NULL DEFAULT 1
  payload       TEXT NOT NULL            -- JSON
  correlation_id TEXT
  status        TEXT NOT NULL DEFAULT 'pending'  -- pending/publishing/published/failed
  retry_count   INTEGER NOT NULL DEFAULT 0
  last_error    TEXT
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
  published_at  DATETIME
  INDEX (status, id)

event_inbox
  event_id     TEXT NOT NULL
  consumer_id  TEXT NOT NULL
  status       TEXT NOT NULL DEFAULT 'processed'  -- processed/failed
  received_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
  processed_at DATETIME
  last_error   TEXT
  PRIMARY KEY (event_id, consumer_id)

migration_history
  id           INTEGER PK AUTOINCREMENT
  revision     TEXT NOT NULL
  name         TEXT NOT NULL
  checksum     TEXT NOT NULL
  status       TEXT NOT NULL             -- applied/failed
  applied_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
  duration_ms  INTEGER NOT NULL DEFAULT 0
  error        TEXT
  INDEX (revision, applied_at)
```

## 7. 任务拆解与批次

```text
M1 基础            M2 持久化               M3 事件              M4 韧性              M5 验收
T01 生命周期 ─┬─> T03 数据库服务 ─┬─> T04 迁移服务            T11 备份恢复        T14 集成/性能
              ├─> T02 配置服务 ───┤        T06 事务 ──┐        T12 健康检查
              ├─> T07 日志 ───────┘        T05 仓储 ──┴─> T09 事件 ──> T10 Outbox/Inbox
              └─> T08 异常                                  T13 诊断
```

| 批次 | 任务 | 交付物 | 主要测试 |
| --- | --- | --- | --- |
| M1 | T01 生命周期 | `core/lifecycle/*`、`bootstrap/{service_registry,startup,shutdown}.py` | T01 UT-001…005、IT-001 |
| M1 | T02 配置 | `config/{layers,policies,service}.py` | T02 UT-001…006 |
| M1 | T07 日志 | 文件输出、轮转、脱敏、测试工具 | T07 UT-001…004、IT-001 |
| M1 | T08 异常 | 异常层级、映射、错误码登记 | T08 UT-001…004、IT-001 |
| M2 | T03 数据库 | `database/service.py`、`health.py`、`errors.py` | T03 UT-001…004、IT-001…003 |
| M2 | T04 迁移 | 历史表、checksum、版本检查、`000002` 前置 | T04 UT-001…005、IT-001 |
| M2 | T06 事务 | `transaction.py`、超时、嵌套策略 | T06 UT-001…004、IT-001 |
| M2 | T05 仓储 | `repository.py`、分页、隔离测试 | T05 UT-001…004、IT-001 |
| M3 | T09 事件 | `core/events/*`、注册表、发布订阅 | T09 UT-001…004、IT-001 |
| M3 | T10 Outbox/Inbox | `infrastructure/events/*`、迁移 `000002` | T10 UT-001…004、IT-001…002 |
| M4 | T11 备份恢复 | `backup.py`、元数据、恢复保护 | T11 UT-001…003、IT-001…003 |
| M4 | T12 健康 | live/ready、依赖聚合 | T12 UT-001…004、IT-001 |
| M4 | T13 诊断 | `/diagnostics/summary`、积压与错误摘要 | T13 UT-001…002、IT-001…002 |
| M5 | T14 集成/性能 | 全链路测试、性能基线记录 | 阶段门禁 §9 |

每个任务的 DoD 统一为：代码 + 测试 + 文档更新（`docs/03-development/` 对应章节）+
`check_all.py` 通过；涉及契约变更时同步 `packages/contracts` 与双向契约测试。

## 8. 待确认项（评审时决定）

| 编号 | 事项 | 建议 |
| --- | --- | --- |
| E1-Q1 | 配置文件格式与路径 | TOML（标准库 `tomllib`），默认 `config/backend.toml` |
| E1-Q2 | 是否新增 `migration_history` | 新增，Alembic 仍为版本事实源 |
| E1-Q3 | 嵌套事务策略 | 加入外层事务，不启用 savepoint |
| E1-Q4 | 诊断接口鉴权 | 开发环境免鉴权；生产要求 `X-Diagnostics-Token`（存 Secrets） |
| E1-Q5 | 事件派发方式 | 事务只写 Outbox，提交后轮询派发（100 ms） |
| E1-Q6 | 性能是否设硬阈值 | 不设，E1 只记录基线（硬件、版本、样本数、中位数/P95） |

## 9. 验收映射

| E1 验收项 | 证据 |
| --- | --- |
| P0 单元/集成测试全通过 | `pytest` + CI |
| 故障注入 E1-FI-001…010 | 对应集成测试用例，逐条登记在 E1 测试报告 |
| 备份与恢复真实证据 | T11 集成测试（备份→损坏→恢复→完整性） |
| 异常可定位 | `correlation_id` 贯穿日志、错误体与诊断摘要 |
| 性能基线完整 | `artifacts/perf-e1.json` + E1 测试报告章节 |

## 10. 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| SQLite 单写者在事件派发下争锁 | 写超时 | 派发与业务写分离、短事务、`busy_timeout` + 有界重试 |
| 恢复流程中断导致数据不可用 | 数据完整性 | 保护副本 + 失败自动回滚 + 集成测试覆盖 |
| 迁移 history 与 alembic 版本不一致 | 误判升级状态 | 以 `alembic_version` 为准，history 仅审计；启动校验 head |
| 配置分层引入隐式覆盖 | 环境行为不一致 | 快照 + 加载日志（值脱敏）+ 非法配置阻断启动 |
| 诊断接口泄露路径/密钥 | 安全 | 字段白名单 + 脱敏 + 鉴权（E1-Q4） |
