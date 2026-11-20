# E2 Backend Services 设计与任务拆解

- **状态：** ✅ 已评审通过（2026-11-18），M6 / M7 / M8 / M9 / M10 已实施
- **日期：** 2026-11-18
- **依据：** [E2.md](../../完整开发计划细分/E2.md)、[ADR-005 本地通信](../06-decisions/ADR-005-local-communication.md)、[E1 设计](e1-backend-core-design.md)
- **前置：** E1 已通过验收（[验收报告](../00-project/e1-acceptance-report.md)）

## 1. 目标与边界

在 E1 Backend Core 之上建立统一的对外服务层：API Server、路由与版本、客户端注册、挑战认证、
Token、Session、Project Access、统一授权、请求处理链、限流、审计、API 文档与诊断。

E2 只提供通用的服务与安全边界，不实现具体业务；以下能力仍由后续阶段负责：

| 能力 | 负责阶段 |
| --- | --- |
| Editor Bridge、WebSocket `/ws`、心跳、Session Lease、多 Editor 冲突 | E3 |
| Project CRUD、项目扫描与上下文 | E4 |
| Task / Workflow / Agent / Tool / Model / Asset / Verification | E5+ |

E2 的 API 只使用 HTTP（ADR-005 的 WebSocket 主通道在 E3 接入，直接复用本阶段的认证与授权）。

## 2. 现状与差距

| 能力 | E1 现状 | E2 需要补齐 |
| --- | --- | --- |
| API Server | `app/main.py` 直接 `uvicorn.run`，无端口占用报告 | 监听封装、启动/关闭校验、端口冲突明确错误 |
| 路由 | `/health`、`/diagnostics/summary` 平铺 | `/api/v1` 前缀、Router Registry、版本与废弃标记 |
| 认证 | 无（仅生产诊断令牌） | 客户端注册、挑战-响应认证、凭证撤销 |
| Token | 无 | 不透明 Token、哈希存储、过期/撤销/轮换 |
| Session | 无 | Session 模型、状态机、查询/撤销/过期 |
| 权限 | 无 | Project Access、RBAC + ABAC + Capability、UNKNOWN 默认拒绝 |
| 请求链 | Request ID / Correlation ID + 异常处理 | 大小限制、超时、认证/会话/项目/权限依赖、统一限流 |
| 审计 | 结构化日志 + 诊断环形缓冲 | 独立审计表与审计通道，关键操作强制记录 |
| 文档 | `/docs` 默认 OpenAPI | 接口说明、认证/权限标注、契约测试 |
| 契约 | `packages/contracts` 协议样例 | `api/` 请求/响应 Schema、manifest 扩展 |

## 3. 模块与依赖

```text
app (FastAPI 路由、中间件、依赖)          ← 只能调用 modules 的 Service
 │
bootstrap (装配、ServiceRegistry、生命周期)
 │
modules/{client,session,access,audit}     ← 领域服务与 Repository
 │
core (安全模型、授权策略、事件、错误、日志)  ← 不依赖 infrastructure
 │
infrastructure (数据库、仓储、keyring、限流存储)
```

新增依赖规则（评审检查项，E2-ARC-001…006）：

1. `app/` 不直接使用 SQLAlchemy Session 或 Repository，只调用模块 Service。
2. `core/security` 只包含纯策略与模型，不读数据库、不读 keyring。
3. 认证凭证明文只存在于 keyring 与进程内存，数据库仅存不可逆验证材料。
4. 受保护路由必须在 Router 级挂载认证依赖，禁止逐路由可选挂载。
5. 授权在服务端完成；客户端提交的 `client_id`、`session_id`、`project_id` 均视为不可信输入。
6. 审计失败对安全敏感操作默认拒绝（fail-closed），普通操作记录降级日志。

## 4. 目录映射（E2.md 建议 → 实际落地）

```text
apps/backend/src/
├── app/
│   ├── main.py                     # 保留入口，改用 app/server.py 的 run()
│   ├── server.py                   # 新增：监听、端口占用、启动/关闭
│   └── api/
│       ├── router.py               # 新增：/api/v1 汇总与 Router Registry
│       ├── deps.py                 # 新增：认证、会话、项目范围、授权依赖
│       ├── errors.py               # 新增：HTTP 错误码到错误体的映射
│       ├── system.py               # 新增：/system/info、/system/status
│       ├── auth.py                 # 新增：/auth/challenge、/auth/verify、/auth/refresh
│       ├── clients.py              # 新增：/clients
│       ├── sessions.py             # 新增：/sessions
│       ├── projects.py             # 新增：/projects/access
│       ├── health.py               # 保留：/health*，新增 /api/v1/health/*
│       └── diagnostics.py          # 扩展：/api/v1/diagnostics/summary
├── app/middleware/
│   ├── size_limit.py               # 新增：请求体大小限制
│   └── timeout.py                  # 新增：请求超时
├── app/schemas/
│   ├── auth.py                     # 新增：认证与 Token 请求/响应模型
│   ├── client.py                   # 新增：客户注册与信息
│   ├── session.py                  # 新增：会话
│   └── access.py                   # 新增：项目访问
├── core/
│   └── security/
│       ├── principal.py            # Principal / Action / Resource
│       ├── policy.py               # RBAC + ABAC + Capability 纯策略
│       └── tokens.py               # Token 生成、哈希、前缀校验
├── infrastructure/
│   ├── security/
│   │   ├── challenge.py            # 挑战存储与一次性校验（数据库）
│   │   └── rate_limit.py           # 进程内滑动窗口与并发计数
│   └── database/base.py            # 新增：Declarative Base（供模块实体复用）
└── modules/
    ├── client/{models,repository,service}.py
    ├── session/{models,repository,service}.py
    ├── access/{models,repository,service}.py
    └── audit/{models,repository,service}.py
```

迁移文件：`migrations/versions/000004_e2_clients_auth.py`、`000005_e2_sessions_access.py`、
`000006_e2_audit.py`。

契约：`packages/contracts/schemas/api/{system,auth,client,session,project-access}.schema.json`，
并登记到 `schemas/manifest.json`。

## 5. 关键设计

### 5.1 API Server（T01）

- `app/server.py` 提供 `run(settings)`：`uvicorn.run(create_app(settings), host=settings.host, port=settings.port)`。
- 绑定地址沿用 `Settings.host` 的 loopback 校验（默认 `127.0.0.1:8765`），禁止 `0.0.0.0`。
- 启动前用 `socket.bind` 探测端口；`OSError(EADDRINUSE)` 转为 `StartupError("端口已被占用", details={"host","port"})`。
- 关闭由 uvicorn 触发 FastAPI lifespan，复用 E1 的顺序关闭（events → database → flush_logging）。
- 请求日志沿用结构化日志与 `X-Request-ID` / `X-Correlation-ID`。

### 5.2 路由与版本（T02）

- 所有 E2 接口挂在 `/api/v1`；`/health` 保留为兼容别名，不再新增功能。
- `app/api/router.py` 按域注册子路由，并在启动时校验：路由名唯一、方法合法、必须带 `tags` 与 `summary`。
- 版本规则：不兼容变更升级到 `v2`；新增可选字段保持 `v1`；废弃接口在 OpenAPI 标 `deprecated=True` 并保留一个阶段。
- `api_version`（`"v1"`）与 Shared Contracts `protocol_version`（`"1.0"`）是两个独立字段，均通过 `/api/v1/system/info` 返回。

### 5.3 客户端注册与凭证（T06 / T03）

客户端注册：

- `POST /api/v1/clients` 需要 `X-Bootstrap-Token`；该令牌在启动时生成到 `data/bootstrap.token`（权限 0600，不写日志），
  用于首次与恢复性注册。已有 `admin` 客户端后，也可用 admin Session 注册新客户端。
- 服务端生成 `client_id`（`cli_` + 12 位 base32）与 `client_secret`（32 字节随机，base64url），
  Secret 写入 keyring（`KEYRING_SERVICE`，名 `client.<client_id>`），数据库仅存 `credential_id` 与状态。
- `client_secret` 只在注册响应中返回一次；重复注册同一 `client_id` 返回 `CLIENT_EXISTS`。

挑战-响应认证：

```text
POST /auth/challenge {client_id}
  → {challenge_id, challenge, expires_at}         # 60s，一次性，DB 持久化
POST /auth/verify {challenge_id, client_id, proof}
  → {access_token, token_type="Bearer", expires_at}
proof = base64url(HMAC-SHA256(secret, challenge_id + "." + challenge))
```

- 使用 `secrets.token_bytes(32)`；比较使用 `hmac.compare_digest`。
- `challenge` 只能消费一次：校验成功时在同一事务内标记 `used_at`；过期或重复返回 `AUTH_CHALLENGE_INVALID`。
- 认证失败按客户端记录连续失败次数并限流（10 次/分钟），失败写审计事件；不记录 proof/secret。
- 请求体统一 `client_type ∈ {godot_editor, admin, tool}`；`client_type` 不直接授予任何权限。

### 5.4 Token 管理（T04）

| 类型 | 前缀 | TTL（默认） | 存储 | 用途 |
| --- | --- | --- | --- | --- |
| Access Token | `gda_` | 10 分钟 | `e2_access_tokens.token_hash` | 创建/轮换 Session |
| Session Token | `gds_` | 8 小时 | `e2_sessions.token_hash` | 调用受保护接口 |

- 采用不透明随机 Token（32 字节），不使用 JWT；数据库存 `sha256(token)`，查询后 `compare_digest` 校验。
- `POST /auth/refresh`：用有效 Access Token 换新 Token，旧 Token 立即 `revoked_at`（轮换）。
- 过期清理：启动时与每小时清理过期/撤销记录（保留撤销记录 7 天用于审计）。
- Token 不进入日志、审计和错误响应；日志只允许记录 `token_id` 前 8 位。

### 5.5 Session（T05）

- 状态机：`CREATED → ACTIVE → (EXPIRED | REVOKED | CLOSED)`；创建即 `ACTIVE`，非法迁移拒绝。
- `POST /api/v1/sessions`（Access Token）：创建 Session 并返回 Session Token；绑定 `client_id`。
- `GET /api/v1/sessions/current`：返回当前 Session（不含 Token 哈希）。
- `DELETE /api/v1/sessions/current`：撤销（`REVOKED`），后续请求立即返回 `SESSION_REVOKED`。
- 续期：`POST /api/v1/sessions/current/renew` 延长 `expires_at`（不超过 `session_max_ttl`），E2 只提供基础接口，
  Heartbeat/Lease 在 E3。
- Session 不能跨 Client 使用；Session 有效不代表拥有任何 Project 权限。

### 5.6 Project Access 与授权（T07 / T08）

Project Access：

- `POST /api/v1/projects/access`：**授予**访问（E2.md 草案为“申请”，为避免客户端自授权改为管理操作），
  需要 `project.access.grant` 且授予者在该项目具备 `owner`，或为 admin。
- `GET /api/v1/projects/access/current?project_id=`：查询当前 Session 的有效访问。
- `DELETE /api/v1/projects/access/current?project_id=`：撤销（owner/admin）。
- 记录字段：`access_id, project_id, client_id, session_id, access_level, granted_by, granted_at, expires_at, status`。
- 校验：项目 ID 必须同时匹配 Session 绑定的 `client_id` 与服务端记录；未知项目默认拒绝（E4 才引入项目注册表）。

授权模型：

| 层 | 输入 | 规则 |
| --- | --- | --- |
| RBAC | Principal.role | `admin` 全局；`owner` / `editor` / `viewer` 仅作用于已授权项目 |
| ABAC | project_scope、resource、上下文 | Access 必须 `ACTIVE` 且未过期；资源 `project_id` 必须等于请求范围 |
| Capability | `Action` | 每次请求显式声明动作，映射到最小能力集合 |

Action 目录（首版）：`system.read`、`client.register`、`client.read`、`session.create`、`session.read`、
`session.revoke`、`project.access.read`、`project.access.grant`、`project.access.revoke`、`diagnostics.read`。

- 决策结果：`ALLOW / DENY(reason)`；`reason ∈ {unknown_principal, session_invalid, project_denied, role_denied, capability_missing, resource_mismatch}`。
- UNKNOWN 一律 DENY；策略缺失、Access 过期、资源归属不明均 DENY。
- 每次 DENY 写审计事件；ALLOW 仅记录调试日志，避免审计膨胀。

### 5.7 请求处理链（T09）

实现方式：传输层用 ASGI 中间件，身份/范围/授权用 FastAPI 依赖（路由级统一挂载）。

| 顺序 | 组件 | 失败返回 |
| --- | --- | --- |
| 1 | Request ID / Correlation ID（已有） | — |
| 2 | 请求体大小限制（`Content-Length` + 流式计数） | 413 `REQUEST_TOO_LARGE` |
| 3 | 请求超时（`asyncio.timeout`） | 504 `REQUEST_TIMEOUT` |
| 4 | 认证依赖：解析 Bearer，查 Access/Session Token | 401 `AUTH_REQUIRED` / `TOKEN_INVALID` / `TOKEN_EXPIRED` / `TOKEN_REVOKED` |
| 5 | Session 依赖：状态与 Client 绑定 | 401 `SESSION_INVALID` / `SESSION_EXPIRED` / `SESSION_REVOKED` |
| 6 | Project Scope 依赖：解析并校验 `project_id` | 403 `PROJECT_ACCESS_DENIED` |
| 7 | 授权依赖：`require(Action, Resource)` | 403 `PERMISSION_DENIED` |
| 8 | 限流（按 Client/Session/Endpoint） | 429 `RATE_LIMITED` + `Retry-After` |
| 9 | 业务处理与响应 | — |

- 受保护路由通过 `APIRouter(dependencies=[Depends(require_authenticated)])` 挂载；认证/健康/系统信息除外。
- 契约测试扫描 `app.routes`，断言 `/api/v1` 下除白名单外的路由都包含认证依赖（防绕过）。
- 公开白名单：`/health*`、`/api/v1/health/*`、`/api/v1/system/info`、`/api/v1/auth/challenge`、
  `/api/v1/auth/verify`、`/api/v1/clients`（需 Bootstrap Token）、OpenAPI 文档。

### 5.8 限流与请求保护（T10）

- 进程内滑动窗口（60s）+ 并发计数，按 `client_id`（认证前按来源 IP）与 `endpoint group` 计数。
- 默认值（可配置，不写死）：认证 10/min、普通接口 120/min、并发 20、请求体 1 MiB、超时 30s。
- 触发限流返回 429 + `Retry-After`，记录 `rate_limit_exceeded`（含 client 摘要，不含 Token）。
- 单进程实现；引入多 worker 时替换为共享存储（记录为 E2-Q4）。

### 5.9 审计（T11）

- 独立表 `e2_audit_events` 与独立 logger `backend.audit`，不与业务调试日志混用。
- 审计动作：`client.registered`、`auth.succeeded`、`auth.failed`、`session.created`、`session.revoked`、
  `access.granted`、`access.revoked`、`authorization.denied`、`high_risk.call`、`config.changed`。
- 字段：`audit_id, actor_id, client_id, session_id, action, resource, decision, reason, timestamp, correlation_id`。
- 脱敏：不记录 Secret、Token、proof、完整请求体；`details` 只允许白名单键。
- 敏感操作（注册、认证、授权变更）采用 fail-closed：审计写入失败返回 `AUDIT_FAILED` 并拒绝操作；
  普通读取采用 fail-open + ERROR 日志（`audit_fail_closed` 可配置，默认 `true`）。

### 5.10 文档与诊断（T12）

- OpenAPI 自动生成，路由必须带 `summary`、`description`、`tags`、`responses`（含错误码）与安全方案 `bearerAuth`。
- 新增 `docs/03-development/api.md`：接口目录、认证流程、权限矩阵、错误码、幂等性与超时约定。
- `GET /api/v1/system/info`：`app_version`、`api_version`、`protocol_version`、环境（公开白名单）。
- `GET /api/v1/system/status`：生命周期、uptime、数据库可用性（不含路径）。
- `GET /api/v1/diagnostics/summary`：需要 `diagnostics.read`，复用 E1 诊断摘要，不返回 Secrets/路径/payload。
- 契约测试：每个 `api/` Schema 至少 1 个有效与 1 个无效样例，登记 `manifest.json`。

### 5.11 统一错误

沿用 `errors/error.schema.json` 响应体；E2 新增错误码：

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| `AUTH_REQUIRED` | 401 | 缺少 Bearer |
| `AUTH_INVALID` | 401 | 客户端/凭证无效 |
| `AUTH_CHALLENGE_INVALID` | 401 | 挑战过期、重复或 proof 错误 |
| `TOKEN_INVALID` / `TOKEN_EXPIRED` / `TOKEN_REVOKED` | 401 | Access/Session Token 状态 |
| `SESSION_INVALID` / `SESSION_EXPIRED` / `SESSION_REVOKED` | 401 | Session 状态 |
| `PROJECT_ACCESS_DENIED` | 403 | 无有效项目访问 |
| `PERMISSION_DENIED` | 403 | 授权拒绝 |
| `CLIENT_EXISTS` | 409 | 重复注册 |
| `RATE_LIMITED` | 429 | 触发限流 |
| `REQUEST_TOO_LARGE` | 413 | 请求体超限 |
| `REQUEST_TIMEOUT` | 504 | 请求超时 |
| `AUDIT_FAILED` | 503 | 审计 fail-closed 拒绝 |
| `SERVER_PORT_IN_USE` | — | 启动阶段 `StartupError` |

## 6. 数据模型

迁移 `000004`：

- `e2_clients(client_id PK, client_type, client_name, client_version, godot_version, platform, status, created_at, last_seen_at)`
- `e2_client_credentials(credential_id PK, client_id FK, credential_type, status, created_at, expires_at, revoked_at)`
- `e2_auth_challenges(challenge_id PK, client_id FK, challenge, status, created_at, expires_at, used_at)`
  （实现说明：HMAC 校验需要服务端持有原始 nonce，故持久化 `challenge` 而非摘要；
  它不是凭证，`used_at` 保证一次性。）
- `e2_access_tokens(token_id PK, client_id FK, token_hash UNIQUE, issued_at, expires_at, revoked_at)`

迁移 `000005`：

- `e2_sessions(session_id PK, client_id FK, token_hash UNIQUE, status, created_at, last_seen_at, expires_at, revoked_at, closed_at)`
- `e2_project_access(access_id PK, project_id, client_id, session_id, access_level, granted_by, granted_at, expires_at, status)`
  + 索引 `(client_id, project_id, status)`。

迁移 `000006`：

- `e2_audit_events(audit_id PK, actor_id, client_id, session_id, action, resource, decision, reason, timestamp, correlation_id, details)`
  + 索引 `(timestamp)`、`(client_id, timestamp)`。

约定：时间统一 UTC ISO-8601；状态用短字符串；所有写入走事务；外键开启（E1 PRAGMA）。

## 7. 任务拆解与批次

| 批次 | 任务 | 主要交付 | 测试 |
| --- | --- | --- | --- |
| **M6** | T01 API Server、T02 路由与版本 | `app/server.py`、`app/api/router.py`、`system` 接口、`api/` 契约骨架、端口占用错误 | T01-UT-001…003、T01-IT-001…002；T02-UT-001…004、T02-CT-001 |
| **M7** | T06 客户端注册、T03 挑战认证、T04 Token | 迁移 `000004`、`modules/client`、`/clients`、`/auth/challenge|verify|refresh`、Bootstrap Token、keyring 凭证 | T06-UT-001…004、T06-IT-001；T03-UT-001…006；Token 过期/撤销/轮换 |
| **M8** | T05 Session、T07 Project Access | 迁移 `000005`、`modules/session`、`modules/access`、`/sessions*`、`/projects/access*` | T05-UT-001…005、T05-IT-001；T07-UT-001…004、T07-IT-001 |
| **M9** | T08 授权、T09 请求链、T10 限流 | `core/security`、`deps.py`、大小/超时中间件、`/api/v1` 路由级认证、限流器与配置 | T08-UT-001…005、T08-IT-001；T10-UT-001…004、T10-IT-001；E2-IT-008/009/010；路由防绕过扫描 |
| **M10** | T11 审计、T12 文档与诊断 + 收尾 | 迁移 `000006`、`modules/audit`、审计接线、`api.md`、`/system/*`、安全测试报告、验收报告 | T11-UT-001…003、T11-IT-001；T12-CT；安全测试 12 项；E2-IT-001…012 汇总 |

批次依赖：M6 → M7 → M8 → M9 → M10；每批结束运行 pytest、ruff 与 `check_all`，并更新进度文档。

### 新增配置项

```text
auth_challenge_ttl_seconds       60
access_token_ttl_seconds         600
session_ttl_seconds              28800
session_max_ttl_seconds          86400
request_max_bytes                1048576
request_timeout_seconds          30
rate_limit_per_minute            120
rate_limit_auth_per_minute       10
rate_limit_max_concurrent        20
audit_fail_closed                true
```

新增启动步骤 `auth`（凭证与清理任务）在 `migration` 之后、`events` 之前注册；关闭时逆序停止。

## 8. 待确认项（评审时决定）

| 编号 | 问题 | 建议决策 |
| --- | --- | --- |
| E2-Q1 | 客户端首次凭证如何下发 | `data/bootstrap.token`（0600）+ 首次注册审计；管理员可在本机读取 |
| E2-Q2 | 是否引入独立 Refresh Credential | E2 不引入；Access Token 过期后重新挑战，Session 用 renew 续期 |
| E2-Q3 | Access Token 与 Session Token 是否合并 | 保持分离：Access 只用于建会话，Session 用于业务请求 |
| E2-Q4 | 限流存储 | 进程内实现；多 worker 前替换为 SQLite 共享表 |
| E2-Q5 | 审计失败策略 | 敏感操作 fail-closed，普通读取 fail-open（可配置） |
| E2-Q6 | `/health` 是否迁到 `/api/v1` | 保留 `/health` 兼容别名，新接口挂 `/api/v1/health/*` |
| E2-Q7 | Project 授予权限 | 仅 admin/owner 可授予；客户端不能为自己申请（偏离 E2.md 草案的“申请”语义） |

## 9. 验收映射

| 目标 | 任务 | 证据 |
| --- | --- | --- |
| E2-G01 API Server | T01 | T01-UT/IT、端口占用测试 |
| E2-G02 路由与版本 | T02 | T02-UT/CT、路由扫描 |
| E2-G03 身份认证 | T03 | T03-UT-001…006 |
| E2-G04 Session | T05 | T05-UT/IT |
| E2-G05 客户端管理 | T06 | T06-UT/IT |
| E2-G06 项目隔离 | T07 | T07-UT-004、T07-IT-001、E2-IT-007 |
| E2-G07 权限检查 | T08 | T08-UT/IT、E2-IT-008 |
| E2-G08 请求处理 | T09/T10 | E2-IT-009/010、路由防绕过扫描 |
| E2-G09 审计 | T11 | T11-UT/IT、E2-IT-011 |
| E2-G10 API 文档 | T12 | `api.md`、OpenAPI 契约测试 |
| E2-G11 服务安全 | T03/T04/T09/T10 | 安全测试 12 项报告 |
| E2-G12 服务测试 | 全部 | pytest + check_all + E2 验收报告 |

## 10. 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 认证实现错误（重放、时序） | 未授权访问 | 一次性挑战、常量时间比较、失败限流与审计；安全测试覆盖 12 项 |
| 授权分散到各路由 | 绕过漏洞 | 路由级统一依赖 + 扫描测试 + Action 目录白名单 |
| 客户端伪造 `project_id` | 跨项目泄露 | 只信任服务端 `e2_project_access`，ABAC 强制资源归属 |
| 审计写入阻塞业务 | 可用性下降 | 独立短事务；fail-closed 仅限敏感操作，可配置 |
| Token 泄漏到日志 | 安全事件 | 日志字段白名单 + 脱敏测试；只记录 token_id 前 8 位 |
| 限流参数不合理 | 误伤正常客户端 | 默认宽松，配置化，M10 压测后校准 |
| API 版本演进 | 插件不兼容 | `/api/v1` 冻结、契约测试、废弃标记 |
| 单进程限流/挑战状态 | 扩展受限 | E2 明确单进程；多 worker 前迁移共享存储 |
