# 日志规范（E0-T08）

## 1. 目标

任何故障都能仅凭日志定位：谁（component）、发生了什么（event）、
关联哪个请求/任务（request_id / correlation_id），以及错误码。

Backend 与 Godot Plugin 使用同一套字段和单行 JSON 输出。

## 2. 字段定义

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `timestamp` | 是 | ISO 8601，UTC |
| `level` | 是 | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `component` | 是 | `bootstrap` / `database` / `errors` / `godot_plugin` 等 |
| `event` | 是 | snake_case 事件名，如 `migration_applied` |
| `message` | 是 | 人类可读描述，不含 Secrets |
| `request_id` | 可用时 | 单次请求标识，HTTP 头 `X-Request-ID` |
| `correlation_id` | 可用时 | 跨进程关联标识，HTTP 头 `X-Correlation-ID` |
| `session_id` | 可用时 | 编辑器会话（E3 起） |
| `project_id` | 可用时 | 当前 Godot 项目（E2 起） |
| `error_code` | 错误时 | 见 [errors.md](errors.md) |
| `exception` | 异常时 | 调用栈（仅 Backend） |

实现：`apps/backend/src/core/logging.py` 的 `JsonFormatter`。

## 3. 级别使用

| 级别 | 使用场景 |
| --- | --- |
| `DEBUG` | 开发期细节，生产默认关闭 |
| `INFO` | 正常业务事件（启动、迁移成功、插件启用） |
| `WARNING` | 可恢复异常、4xx 业务错误、降级行为 |
| `ERROR` | 操作失败（5xx、迁移失败、凭证库不可用） |
| `CRITICAL` | 系统关键故障，进程无法继续 |

## 4. 事件命名

- snake_case，表达"发生了什么"：`application_start`、`migration_applied`、
  `plugin_enabled`、`secret_missing`。
- 同一事件在所有模块中使用相同名称，不要用自然语言句子。
- `message` 可以补充上下文，但不得成为唯一信息来源。

## 5. Backend 用法

```python
import logging
from core.logging import get_logger, log_event

logger = get_logger("backend.database")
log_event(
    logger,
    logging.INFO,
    "migration_applied",
    component="database",
    error_code=None,
)
```

- 请求级 ID 由 `create_app()` 的中间件写入上下文，格式化时自动附加，
  业务代码不需要手工传递。
- 请求头 `X-Request-ID` / `X-Correlation-ID` 会被复用，响应头原样回传。
- 未在 `_EXTRA_FIELDS` 中声明的 `extra` 字段会被丢弃，避免污染日志。

## 6. Godot Plugin 用法

```gdscript
const PluginLog := preload("res://addons/godot_ai_agent/core/logger.gd")

PluginLog.info("plugin_enabled", {"version": "0.1.0"})
PluginLog.error("unsupported_godot_version", {
    "error_code": "UNSUPPORTED_GODOT_VERSION",
    "version": version_text,
})
```

- 插件内禁止直接 `print` / `printerr`，统一走 `core/logger.gd`。
- 输出 `[GodotAI] {json}`；`WARNING` 走 `push_warning`，`ERROR` 走 `push_error`。
- 测试探针（`tests/contract_probe`）属于测试夹具，允许直接输出 `[PASS]/[FAIL]`。

## 7. 脱敏规范

禁止写入日志的内容：

1. API Key、Token、密码、私钥（使用 `infrastructure.secrets.redact()` 占位）。
2. 用户代码与项目文件的完整内容（只记录路径、行号、哈希）。
3. 模型隐藏推理、完整 Prompt/Completion（只记录模型名、token 数、请求 ID）。
4. 系统凭证库返回的原始错误内容。

允许记录：标识符、路径、错误码、耗时、计数、状态。

## 8. 输出示例

```json
{"timestamp":"2026-11-17T09:31:50+00:00","level":"INFO","logger":"backend.database","component":"database","event":"migration_applied","message":"migration_applied 000001 -> 000001","request_id":"req-9f2c","correlation_id":"req-9f2c"}
```

## 9. 验收

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_logging.py tests/integration/test_health.py -q
```

Godot 侧：

```powershell
& $env:GODOT '--headless' '--path' 'apps/godot-plugin' '--editor' '--quit'
```

应输出 `[GodotAI] {...}` 单行 JSON，且退出码为 0。
