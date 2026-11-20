# API 服务规范（E2）

- **适用范围：** Backend HTTP 接口的版本、路由、响应与错误约定
- **最后更新：** 2026-11-18（E2-M10）
- **契约事实源：** [packages/contracts](../../packages/contracts/)（本文只做解释）

## 1. 版本与前缀

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| API Version | `v1` | HTTP 接口版本，前缀固定为 `/api/v1` |
| Protocol Version | `1.0` | Shared Contracts 跨端消息协议，独立于 API Version |

- 不兼容变更升级到 `v2`；新增可选字段保持 `v1`。
- 废弃接口在 OpenAPI 标记 `deprecated`，至少保留一个阶段。
- `API_VERSION` / `API_PREFIX` 定义在 [version.py](../../apps/backend/src/app/api/version.py)，
  `protocol_version` 由 `packages/contracts/common/protocol.json` 提供。
- 路由注册与元数据校验见 [router.py](../../apps/backend/src/app/api/router.py)：
  `/api/v1` 下每条路由必须有 `summary` 与 `tags`，路由名、路径与 `operationId` 均不可重复。

## 2. 当前端点（E2-M10）

| 方法与路径 | 作用 | 鉴权 |
| --- | --- | --- |
| `GET /api/v1/system/info` | 应用版本、API 版本、协议版本、环境 | 公开 |
| `GET /api/v1/system/status` | 生命周期、启动时间、运行时长、数据库可用性 | `Authorization: Bearer gda_...` 或 `gds_...` |
| `GET /api/v1/diagnostics/summary` | 应用/数据库/迁移/事件/备份/最近错误摘要 | `Authorization: Bearer gda_...` 或 `gds_...`（`diagnostics.read`） |
| `GET /diagnostics/summary` | E1 兼容入口 | 开发/测试公开；生产要求 `X-Diagnostics-Token` |
| `POST /api/v1/clients` | 注册客户端，返回一次性 `client_secret` | `X-Bootstrap-Token` |
| `POST /api/v1/auth/challenge` | 获取一次性认证挑战（60s） | 公开 |
| `POST /api/v1/auth/verify` | 校验 proof 并签发 Access Token | 公开 |
| `POST /api/v1/auth/refresh` | 轮换 Access Token | `Authorization: Bearer gda_...` |
| `POST /api/v1/sessions` | 创建 Session，返回一次性 Session Token | `Authorization: Bearer gda_...` |
| `GET /api/v1/sessions/current` | 查询当前 Session | `Authorization: Bearer gds_...` |
| `DELETE /api/v1/sessions/current` | 撤销当前 Session | `Authorization: Bearer gds_...` |
| `POST /api/v1/sessions/current/renew` | 续期当前 Session | `Authorization: Bearer gds_...` |
| `POST /api/v1/projects/access` | 授予项目访问 | `Authorization: Bearer gds_...`（admin/owner） |
| `GET /api/v1/projects/access/current` | 查询当前项目访问 | `Authorization: Bearer gds_...`（viewer 起） |
| `DELETE /api/v1/projects/access/current` | 撤销项目访问 | `Authorization: Bearer gds_...`（admin/owner） |
| `GET /api/v1/health` | 完整健康视图，始终 200 | 公开 |
| `GET /api/v1/health/live` | 存活探测 | 公开 |
| `GET /api/v1/health/ready` | 就绪探测，未就绪返回 503 | 公开 |
| `GET /health`、`/health/live`、`/health/ready` | E1 兼容别名，语义与 v1 一致 | 公开 |

- 健康检查细节见 [observability.md](observability.md)。
- 响应体约束：`/system/info` 与 `/system/status` 见
  [api/system.schema.json](../../packages/contracts/api/system.schema.json)；
  客户端注册响应见 [api/client.schema.json](../../packages/contracts/api/client.schema.json)；
  challenge / token 响应见 [api/auth.schema.json](../../packages/contracts/api/auth.schema.json)；
  Session 响应见 [api/session.schema.json](../../packages/contracts/api/session.schema.json)；
  项目访问响应见
  [api/project-access.schema.json](../../packages/contracts/api/project-access.schema.json)。

### 2.1 客户端注册与认证（M7）

**Bootstrap Token**：启动时生成到 `data/bootstrap.token`（权限 0600，不写日志），
已存在则复用；测试环境仅保存在内存。请求头 `X-Bootstrap-Token` 缺失返回
`AUTH_REQUIRED`，错误返回 `AUTH_INVALID`。

**注册请求**：

```json
{
  "client_type": "godot_editor",
  "client_name": "Godot Editor",
  "client_version": "0.1.0",
  "godot_version": "4.5.1",
  "platform": "windows"
}
```

- `client_type ∈ {godot_editor, admin, tool}`，不授予任何权限。
- `client_id` 可选（`^cli_[a-z0-9]{12}$`）；缺省由服务端生成，重复返回 `CLIENT_EXISTS`。
- `client_secret`（32 字节随机，base64url）只返回一次，写入操作系统凭证库
  `client.<client_id>`；数据库不保存明文。

**认证流程**：

```text
POST /auth/challenge {client_id}
  → {challenge_id, challenge, expires_at}

proof = base64url(HMAC-SHA256(client_secret, challenge_id + "." + challenge))

POST /auth/verify {challenge_id, client_id, proof}
  → {access_token, token_type: "Bearer", expires_at}
```

- 挑战 60s、一次性；过期/重复/proof 错误均返回 `AUTH_CHALLENGE_INVALID`。
- 失败按 client_id 限流（默认 10 次/分钟），超限返回 429 `RATE_LIMITED` + `Retry-After`。
- Access Token 前缀 `gda_`、默认 10 分钟，数据库只存 SHA-256 摘要。
- 刷新时旧 Token 立即撤销；再次使用返回 `TOKEN_REVOKED`。
- 日志与错误响应绝不包含 Secret、Token 或 proof。

### 2.2 Session（M8）

```text
POST /api/v1/sessions                      Authorization: Bearer gda_...
  → {session_token, token_type: "Bearer", expires_at, session}
GET /api/v1/sessions/current               Authorization: Bearer gds_...
POST /api/v1/sessions/current/renew        Authorization: Bearer gds_...
DELETE /api/v1/sessions/current            Authorization: Bearer gds_...
  → session
```

- Session Token 前缀 `gds_`、默认 8 小时；数据库只存 SHA-256 摘要，Token 只返回一次。
- 状态机：`CREATED → ACTIVE → (EXPIRED | REVOKED | CLOSED)`；创建即 `ACTIVE`，非法迁移拒绝。
- Session 与 `client_id` 绑定；Session 有效不代表拥有任何项目权限。
- 续期不超过 `session_max_ttl_seconds`（默认 24 小时），Heartbeat/Lease 在 E3 实现。
- 撤销后立即返回 `SESSION_REVOKED`；过期返回 `SESSION_EXPIRED`；未知 Token 返回 `SESSION_INVALID`。

### 2.3 Project Access（M8）

```text
POST /api/v1/projects/access               Authorization: Bearer gds_...
  {project_id, session_id, access_level: "owner" | "editor" | "viewer", expires_at?}
GET /api/v1/projects/access/current?project_id=...
DELETE /api/v1/projects/access/current?project_id=...[&session_id=...]
```

- 访问记录同时绑定 `client_id` 与 `session_id`；查询要求记录 `ACTIVE` 且未过期。
- 授予与撤销需要调用者是 `admin` 客户端，或在该项目持有 `owner` 访问；客户端不能自行申请。
- 未知项目没有访问记录，默认返回 `PROJECT_ACCESS_DENIED`（项目注册表在 E4 引入）。
- 撤销默认作用于当前 Session；owner/admin 可通过 `session_id` 撤销其他 Session 的访问。

### 2.4 认证、授权与请求保护（M9）

**认证链**：除 `/clients`、`/auth/challenge`、`/auth/verify`、`/health*`、`/system/info`
之外的 `/api/v1` 路由全部在 Router 级挂载 `require_authenticated` 与 `enforce_rate_limit`。
Access Token（`gda_`）与 Session Token（`gds_`）都可用于认证，但各接口对 Token 类型有要求：

- `POST /auth/refresh`、`POST /sessions` 要求 Access Token（否则 `TOKEN_INVALID`）；
- `/sessions/current*`、`/projects/access*` 要求 Session Token（否则 `SESSION_INVALID`）。

**统一授权**：`Principal(client_id, client_type, session_id, role, project_id)` +
`Action` + `Resource` 三元组交给纯函数 [policy.py](../../apps/backend/src/core/security/policy.py) 求值：

| 规则 | 结果 |
| --- | --- |
| 未知 Action 或未认证 Principal | `DENY`（`capability_missing` / `unknown_principal`） |
| `client_type == admin` | 全局 `ALLOW` |
| 非项目级 Action（如 `system.read`、`session.create`） | 已认证即 `ALLOW` |
| 项目级 Action | 需服务端访问记录且 `principal.project_id == resource.project_id`；`*_read` 允许 owner/editor/viewer，`grant` / `revoke` 仅 owner |

- 客户端提交的 `client_id` / `session_id` / `project_id` 只用于定位资源，不作为授权依据。
- 项目级授权由 `authorize_project_action` 先通过 `ProjectAccessService` 加载真实访问记录，
  再以服务端记录的 `access_level` 作为角色求值；无记录 → `PROJECT_ACCESS_DENIED`，
  有记录但角色不足 → `PERMISSION_DENIED`（`details.reason` 说明原因）。
- 请求体超过 `request_max_body_bytes`（默认 1 MiB）返回 413 `REQUEST_TOO_LARGE`；
  处理超过 `request_timeout_seconds`（默认 30s）返回 504 `REQUEST_TIMEOUT`（`retryable=true`）。
- 限流按 `Session/Client + 接口组` 做进程内滑动窗口，默认 `rate_limit_default_per_minute = 120`；
  并发上限 `rate_limit_max_concurrency = 20`。超限返回 429 `RATE_LIMITED` 并带 `Retry-After`。

### 2.5 审计与诊断（M10）

**审计事件**（[audit](../../apps/backend/src/modules/audit/)）：写入独立表 `e2_audit_events`，
同时输出到 `backend.audit` logger；只追加，不提供修改/删除接口。

| Action | 触发点 | 说明 |
| --- | --- | --- |
| `client.registered` | 客户端注册 | 敏感操作，审计失败拒绝注册并清理 Secret |
| `auth.succeeded` / `auth.failed` | 挑战认证 | 失败事件 `decision=DENY` |
| `session.created` / `session.revoked` | Session 生命周期 | 记录 session_id |
| `access.granted` / `access.revoked` | 项目访问变更 | 敏感操作 |
| `authorization.denied` | 授权拒绝 | 含 `details.action` / `role` / `policy_id` |
| `high_risk.call` | 诊断摘要读取 | 记录 endpoint 与 method |

- `details` 只允许白名单键（`project_id`、`access_level`、`role`、`policy_id`、`endpoint` 等），
  字符串值统一脱敏并截断至 128 字符；Secret、Token、proof 永不落库。
- 敏感操作（注册、认证、授权变更）审计写入失败时返回 503 `AUDIT_FAILED`（fail-closed）；
  普通事件 fail-open 并记录 `audit_write_failed` ERROR 日志。
- 审计 `correlation_id` 复用请求上下文，便于与 `X-Request-ID` 关联。

**诊断接口**：`GET /api/v1/diagnostics/summary` 与 E1 入口响应一致，要求 Bearer 认证与
`diagnostics.read` Action；输出仅包含脱敏摘要，不返回数据库连接串、事件 payload 或任何凭证。

**OpenAPI 安全方案**：文档为受保护操作声明 `bearerAuth`（HTTP Bearer），
公开路由不声明 `security`；服务端来源见
[openapi.py](../../apps/backend/src/app/api/openapi.py)。

## 3. 响应与错误

成功响应为 JSON 对象，不额外包裹 `data`。错误统一为：

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Not Found",
    "details": {},
    "retryable": false,
    "correlation_id": "req-9f2c"
  }
}
```

框架层错误同样转换为上述结构：

| HTTP | 错误码 | 场景 |
| --- | --- | --- |
| 404 | `NOT_FOUND` | 未知路由 |
| 405 | `METHOD_NOT_ALLOWED` | 请求方法不被支持 |
| 422 | `VALIDATION_FAILED` | 参数或请求体校验失败（`details.errors` 列出字段） |
| 413 | `REQUEST_TOO_LARGE` | 请求体超过 `request_max_body_bytes` |
| 429 | `RATE_LIMITED` | 频率或并发超限，响应头含 `Retry-After` |
| 504 | `REQUEST_TIMEOUT` | 请求处理超过 `request_timeout_seconds`（`retryable=true`） |
| 400 / 401 / 403 / 409 / 503 | 对应登记错误码 | 见 [errors.md](errors.md) |

- `correlation_id` 与响应头 `X-Request-ID` 一致。
- 已登记认证与授权错误码：`AUTH_REQUIRED`、`AUTH_INVALID`、`AUTH_CHALLENGE_INVALID`、
  `TOKEN_INVALID`、`TOKEN_EXPIRED`、`TOKEN_REVOKED`、`CLIENT_EXISTS`、`RATE_LIMITED`、
  `SESSION_INVALID`、`SESSION_EXPIRED`、`SESSION_REVOKED`、`PROJECT_ACCESS_DENIED`、
  `PERMISSION_DENIED`、`REQUEST_TOO_LARGE`、`REQUEST_TIMEOUT`、`AUDIT_FAILED`。

## 4. 监听与启动

- 默认 `127.0.0.1:8765`，仅允许回环地址；`0.0.0.0` 会被配置校验拒绝。
- 启动前由 [server.py](../../apps/backend/src/app/server.py) 探测端口：
  被占用时抛出 `StartupError(code="SERVER_PORT_IN_USE", details={host, port})`。
- 关闭由 uvicorn 触发 FastAPI lifespan，复用 E1 的逆序关闭流程。

## 5. 批次状态

| 批次 | 状态 | 新增接口 |
| --- | --- | --- |
| M6 | ✅ | `/api/v1/system/*`、路由与版本 |
| M7 | ✅ | `/api/v1/clients`、`/api/v1/auth/challenge` / `verify` / `refresh` |
| M8 | ✅ | `/api/v1/sessions*`、`/api/v1/projects/access*` |
| M9 | ✅ | 路由级认证依赖、请求大小/超时中间件、限流 |
| M10 | ✅ | `/api/v1/diagnostics/summary`、OpenAPI 安全方案与完整接口说明 |

## 6. 验收命令

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_server.py tests/unit/test_security_tokens.py `
  tests/unit/test_rate_limit.py tests/unit/test_policy.py tests/unit/test_request_protection.py `
  tests/unit/test_audit.py tests/integration/test_api_routing.py tests/integration/test_clients.py `
  tests/integration/test_auth_flow.py tests/integration/test_sessions.py `
  tests/integration/test_project_access.py tests/integration/test_authorization.py `
  tests/integration/test_audit_events.py tests/integration/test_security.py tests/contract -q
```

覆盖：服务启动/关闭、端口占用、路由注册与元数据、版本前缀、健康别名、OpenAPI 安全方案、
客户端注册（Bootstrap Token/重复 ID/多客户端/更新与注销）、
挑战认证（正常、错误 proof、过期、重放、凭证撤销、限流）、
Token 轮换/过期/撤销、Session 生命周期（创建/查询/续期/过期/撤销/Client 隔离）、
Project Access（授予/拒绝/撤销/多项目隔离/篡改）、
统一授权策略与项目范围（admin/viewer/editor/owner、未知 Action）、
请求保护（413 / 504 / 429 + Retry-After、受保护路由认证依赖扫描）、
审计（生命周期事件、拒绝事件、脱敏、fail-closed/fail-open）、
12 项安全测试（未认证、过期/撤销 Token、跨 Client、项目篡改、未知权限、自助授权、重放、
日志脱敏、大请求、回环监听、诊断脱敏），
以及 `system` / `client` / `auth` / `session` / `project-access` 契约样例。
