# 健康检查与诊断（E1-T12 / E1-T13）

## 1. 健康接口

| 端点 | 作用 | 状态码 |
| --- | --- | --- |
| `GET /health/live` | 进程存活探测，不访问依赖 | 恒 200 |
| `GET /health/ready` | 能否接受工作（RUNNING + 数据库 + 迁移） | 200 / 503 |
| `GET /health` | 完整健康视图，保留 E0 字段并增加 `checks` | 恒 200 |

E2 起同一组接口同时挂载在 `/api/v1/health`、`/api/v1/health/live`、`/api/v1/health/ready`，
根路径 `/health*` 保留为兼容别名，语义完全一致（见 [API 服务规范](api.md)）。

`status` 取值：

| 值 | 含义 |
| --- | --- |
| `HEALTHY` | 应用 RUNNING，全部依赖正常 |
| `DEGRADED` | 部分依赖未就绪（未注册、未启动），但应用可运行 |
| `UNHEALTHY` | 数据库不可用或迁移版本不一致 |
| `STARTING` | 尚未进入 RUNNING（启动中或未启动） |
| `STOPPING` | 正在关闭 |

检查项实现：`apps/backend/src/app/health.py`（只读，不触发写入）。

| 检查 | 判定 |
| --- | --- |
| `application` | 生命周期状态映射到上述状态 |
| `database` | `database_health.check()`：连接可用 + `PRAGMA integrity_check`；完整性非 `ok` 判为 `UNHEALTHY` |
| `migration` | `MigrationService.verify_at_head()`，失败记录 `MIGRATION_FAILED` |
| `config` | 服务已注册 |
| `logging` | root logger 至少有一个 handler |
| `events` | dispatcher 运行中；内存库允许 `embedded` 模式 |
| `backup` | `BackupService` 已注册 |

聚合规则：应用处于 `STARTING` / `STOPPING` 时直接返回该状态；否则 `UNHEALTHY` > `DEGRADED` > `HEALTHY`。

### Readiness

`/health/ready` 要求 `application`、`database`、`migration` 全部 `HEALTHY`，
否则返回 503 并在 `reason` 指明首个不满足的检查项名。

## 2. 诊断接口

`GET /diagnostics/summary` 输出（不包含 Secrets、完整数据库路径与事件 payload）：

| 字段 | 内容 |
| --- | --- |
| `application` | 名称、版本、环境、生命周期状态、启动时间、运行秒数 |
| `database` | `ready` / `unavailable`、当前 revision |
| `migration` | current、head、`at_head` |
| `logging` | 日志文件路径与级别 |
| `events` | dispatcher 是否运行、outbox/inbox 计数、`backlog`（pending + failed） |
| `backup` | 是否可用、备份数量、最近备份时间 |
| `recent_errors` | 最近错误摘要（最多 10 条，已脱敏） |

### 鉴权

- 开发 / 测试环境：免鉴权（服务仅绑定 loopback）。
- 生产环境：必须携带 `X-Diagnostics-Token`，与密钥库中的
  `backend.diagnostics_token` 使用常量时间比较；缺失或不匹配返回 403
  `PERMISSION_DENIED`。

## 3. 最近错误摘要

实现：`apps/backend/src/core/diagnostics.py`。

- `RecentErrorHandler` 挂在 root logger 上，收集 `ERROR` 及以上记录；
- 使用固定容量环形缓冲（默认 20 条），快照按时间倒序返回；
- 写入时统一调用 `redact_text`（覆盖 token / api_key / password / Authorization 等），
  并折叠空白、截断到 500 字符；
- 诊断收集自身失败不得影响日志主流程。

日志字段仅使用允许集合（`component` / `event` / `error_code` 等），
不打印事件 payload 或完整凭证。

## 4. 故障排查顺序

1. `/health/ready` 的 `reason` 定位不可用依赖；
2. `/diagnostics/summary` 看 `database.status`、`migration.at_head` 与 `events.backlog`；
3. `event_outbox.status = 'failed'` 的 `last_error` 与 `correlation_id`；
4. `recent_errors` 中的脱敏错误码与组件。

## 5. 验收方式

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_health_service.py tests/unit/test_recent_errors.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_health.py tests/integration/test_diagnostics.py -q
```

覆盖：健康状态生成、数据库不可用、迁移未到 head、启动中/已停止状态、依赖缺失降级、
liveness/readiness 状态码、诊断数据生成、Outbox 积压、服务异常降级、敏感字段脱敏与生产鉴权。
