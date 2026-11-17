# 错误码与异常处理规范（E0-T08）

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
  `CONFIG_ERROR`、`STARTUP_ERROR`、`MIGRATION_FAILED`。
- 新增对外错误码时，必须同时更新契约文件与两端校验样例。

## 3. 异常层级

| 类 | 错误码 | HTTP | retryable | 场景 |
| --- | --- | --- | --- | --- |
| `AppError` | `INTERNAL_ERROR` | 500 | false | 基类默认值 |
| `ConfigError` | `CONFIG_ERROR` | 500 | false | 配置缺失/非法，启动失败 |
| `StartupError` | `STARTUP_ERROR` | 500 | false | 启动装配失败 |
| `MigrationError` | `MIGRATION_FAILED` | 500 | false | 数据库迁移失败 |

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
.\.venv\Scripts\python.exe -m pytest tests/unit/test_errors.py tests/integration/test_health.py -q
```

覆盖：错误体符合契约、错误码大小写校验、关联 ID 传递、retryable 透传。
