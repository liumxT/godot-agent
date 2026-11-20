# 错误码与异常处理规范（E0-T08 / E1-T08）

## 1. 原则

1. 业务异常（可预期，如参数非法）与系统异常（配置、依赖、未预期错误）分开。
2. 不允许静默吞掉异常：要么处理并记录，要么转换后抛出。
3. 对外错误信息不得泄露 Secrets、堆栈或内部路径细节。
4. 异常输出必须保留 `correlation_id`。
5. 重要操作（启动、迁移、插件启用/停用）必须记录执行结果。

## 2. 错误码规范

- 格式：`^[A-Z][A-Z0-9_]{2,63}$`（大写蛇形），由 `AppError` 构造时强制校验。
- 对外暴露的错误码必须登记在
  [packages/contracts/errors/error-codes.json](../../packages/contracts/errors/error-codes.json)，
  并与其 `http_status` / `retryable` 保持一致。
- 仅用于本地启动/迁移流程、不经过 HTTP 的错误码：
  `CONFIG_ERROR`、`STARTUP_ERROR`、`SERVER_PORT_IN_USE`、`LIFECYCLE_STATE_ERROR`、`SHUTDOWN_TIMEOUT`。
- 启动时由 `validate_error_registry()` 校验所有 `AppError` 子类的 `code`
  是否符合格式；非法错误码直接导致启动失败（`StartupError`）。
- 新增对外错误码时，必须同时更新契约文件与两端校验样例。

## 3. 异常层级

| 类 | 错误码 | HTTP | retryable | 场景 |
| --- | --- | --- | --- | --- |
| `AppError` | `INTERNAL_ERROR` | 500 | false | 基类默认值 |
| `ConfigError` | `CONFIG_ERROR` | 500 | false | 配置缺失/非法，启动失败 |
| `StartupError` | `STARTUP_ERROR` | 500 | false | 启动装配失败 |
| `LifecycleStateError` | `LIFECYCLE_STATE_ERROR` | 500 | false | 生命周期状态非法/重复启动 |
| `ValidationFailed` | `INVALID_REQUEST` | 400 | false | 输入校验失败 |
| `AuthenticationError` | `UNAUTHORIZED` | 401 | false | 缺少或无效凭证 |
| `AuthRequired` | `AUTH_REQUIRED` | 401 | false | 缺少 Bearer / Bootstrap Token |
| `AuthInvalid` | `AUTH_INVALID` | 401 | false | 客户端未知/已注销/凭证不可用 |
| `AuthChallengeInvalid` | `AUTH_CHALLENGE_INVALID` | 401 | false | 挑战过期、重复使用或 proof 错误 |
| `TokenInvalid` | `TOKEN_INVALID` | 401 | false | Access Token 无法识别 |
| `TokenExpired` | `TOKEN_EXPIRED` | 401 | false | Access Token 已过期 |
| `TokenRevoked` | `TOKEN_REVOKED` | 401 | false | Access Token 被撤销/轮换 |
| `SessionInvalid` | `SESSION_INVALID` | 401 | false | Session Token 无法识别或状态非法 |
| `SessionExpired` | `SESSION_EXPIRED` | 401 | false | Session 已过期 |
| `SessionRevoked` | `SESSION_REVOKED` | 401 | false | Session 已被撤销 |
| `ProjectAccessDenied` | `PROJECT_ACCESS_DENIED` | 403 | false | 当前 Session 没有该项目的有效访问 |
| `ClientExists` | `CLIENT_EXISTS` | 409 | false | client_id 已注册 |
| `RateLimited` | `RATE_LIMITED` | 429 | true | 触发限流，响应含 `Retry-After` |
| `PermissionDenied` | `PERMISSION_DENIED` | 403 | false | 已认证但无权限（`details.action` / `details.reason`） |
| `RequestTooLarge` | `REQUEST_TOO_LARGE` | 413 | false | 请求体超过 `request_max_body_bytes` |
| `RequestTimeout` | `REQUEST_TIMEOUT` | 504 | true | 请求处理超过 `request_timeout_seconds` |
| `AuditFailed` | `AUDIT_FAILED` | 503 | true | 审计写入失败，敏感操作 fail-closed |
| `NotFoundError` | `NOT_FOUND` | 404 | false | 目标资源不存在 |
| `OperationTimeout` | `TIMEOUT` | 504 | true | 操作超时 |
| `ShutdownTimeout` | `SHUTDOWN_TIMEOUT` | 504 | true | 关闭超时（仅本地流程） |
| `DatabaseError` | `DATABASE_UNAVAILABLE` / `DATABASE_INTEGRITY_ERROR` | 503 / 500 | true / false | 数据库不可用或完整性错误 |
| `InfrastructureError` | `INFRASTRUCTURE_ERROR` | 500 | false | 文件、事件、凭证库等基础设施失败 |
| `MigrationError` | `MIGRATION_FAILED` | 500 | false | 数据库迁移失败 |
| `BackupError` | `BACKUP_FAILED` / `RESTORE_FAILED` | 500 | false | 备份或恢复失败 |

数据库驱动异常（`SQLAlchemyError` / `OperationalError` / `IntegrityError` 等）
必须在基础设施层转换为上表异常，领域层不得直接依赖驱动类型。

实现：`apps/backend/src/core/errors.py`。

## 4. 对外错误格式

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "请求不合法",
    "details": {"field": "action"},
    "retryable": false,
    "correlation_id": "req-9f2c"
  }
}
```

该结构对应 `packages/contracts/errors/error.schema.json`，
集成测试会直接用契约校验返回体。

框架层错误也转换为同一结构（E2-T01/T02）：

| HTTP | 错误码 | 说明 |
| --- | --- | --- |
| 404 | `NOT_FOUND` | 未知路由 |
| 405 | `METHOD_NOT_ALLOWED` | 请求方法不被支持，保留 `Allow` 响应头 |
| 422 | `VALIDATION_FAILED` | 参数或请求体校验失败，`details.errors` 列出 `loc` / `type` / `msg` |

## 5. 处理要求

1. 捕获异常后不得忽略：要么转换（`raise X(...) from exc`），要么记录后继续。
2. 记录异常使用 `logger.exception(...)` 保留堆栈；普通业务错误用 `log_event`。
3. 4xx 业务错误记 `WARNING`，5xx 与迁移失败记 `ERROR`。
4. 转换异常时保留上游信息：`details` 只放可公开字段，堆栈留在日志。
5. 禁止在入口层堆积 try/except；由中间件与统一异常处理器兜底。

## 6. 请求关联 ID

- `create_app()` 中间件为每个请求生成/复用：
  - `X-Request-ID`（缺省 `req-<uuid>`）
  - `X-Correlation-ID`（缺省等于 request_id）
- 两个 ID 写入日志上下文与 `request.state`，响应头原样回传。
- 错误响应中的 `correlation_id` 与响应头一致，便于用户报错时定位日志。

## 7. Godot 侧错误记录

- 使用 `PluginLog.error(event, {"error_code": "...", ...})`，
  `event` 为 snake_case，`error_code` 与 Backend 保持同名同义。
- 错误必须同时反映到状态面板（`ui/status_panel.gd`），不能只写日志。

## 8. 验收

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_errors.py tests/unit/test_error_taxonomy.py tests/integration/test_health.py -q
```

覆盖：错误体符合契约、错误码大小写校验、异常层级默认值、
契约 `http_status` / `retryable` 一致性、关联 ID 传递。
