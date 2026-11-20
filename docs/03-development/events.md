# 事件与 Outbox/Inbox 规范（E1-T09 / E1-T10）

## 1. 定位

事件用于模块间解耦：业务事务只负责写入 `event_outbox`，提交后由 `EventDispatcher`
轮询投递给本进程订阅者。投递语义为 **At-least-once**，消费方通过 `event_inbox` 保证幂等。

分层约束：

| 位置 | 职责 | 可依赖 |
| --- | --- | --- |
| `src/core/events/` | 事件模型、注册表、进程内发布 | 只依赖 `core/*`（含错误与日志） |
| `src/infrastructure/events/` | Outbox / Inbox 仓储、派发器 | `core/*`、`infrastructure/database/*` |
| `src/bootstrap/` | 装配与生命周期接入 | 全部 |

`core` 不依赖 `infrastructure`；仓储与派发器不得被业务模块直接跨模块复用。

## 2. 事件模型

实现：`apps/backend/src/core/events/model.py`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | `str` | `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`，默认 UUID4 hex |
| `event_type` | `str` | 小写点分命名，如 `task.created`、`agent.run.failed` |
| `payload` | `dict` | 必须为 JSON 对象，序列化时按键排序 |
| `event_version` | `int` | ≥ 1，仅内部使用，**不进入契约** |
| `occurred_at` | `datetime` | 必须带时区，统一 UTC |
| `producer` | `str` | `backend` / `plugin`，映射为契约 `source` |
| `correlation_id` | `str \| None` | 贯穿日志与事件的追踪 ID |
| `session_id` / `project_id` | `str \| None` | 可选上下文，空值不写入契约 |
| `protocol_version` | `str` | 固定 `1.0` |

校验失败一律抛 `ValidationFailed`，不得静默降级。

### 2.1 契约映射

`Event.to_contract()` 对齐 `packages/contracts/events/event.schema.json`：

| 内部字段 | 契约字段 |
| --- | --- |
| `occurred_at` | `timestamp`（ISO8601，`Z` 结尾） |
| `producer` | `source` |
| `event_version` | 不输出（schema 禁止额外字段） |

`payload_json` 用于 Outbox 持久化；`Event.from_storage()` 负责反向解析，
payload 非 JSON 或非对象时抛 `ValidationFailed`。

## 3. 注册表与进程内发布

- `EventRegistry`：以 `consumer_id` 绑定 `(event_type, handler)`，同一 `consumer_id`
  重复注册抛 `StartupError`（装配错误应尽早失败）。
- `handlers_for(event_type)` 返回订阅快照，注册顺序即调用顺序。
- `EventBus.publish(event)` 逐个调用处理器，`invoke_handler` 兼容同步函数与协程：

  ```python
  async with database.session() as session, transaction(session):
      registry.register("task.created", on_task_created, consumer_id="task-audit")
      results = await bus.publish(event)
  ```

- 单个处理器失败**隔离**：返回 `DeliveryResult(status="failed", error=...)` 并记录
  `event_handler_failed`（`component="events"`、`error_code="EVENT_HANDLER_FAILED"`）。
- `EventBus` 不做持久化与去重；重复发布同一事件会再次调用处理器，幂等由 Inbox 负责。

## 4. Outbox

实现：`apps/backend/src/infrastructure/events/outbox.py`；表结构见迁移
`migrations/versions/000003_event_infrastructure.py`。

### 4.1 写入

```python
async with database.session() as session, transaction(session):
    await business_repository.add(item)          # 业务写入
    await outbox.add(session, Event.create("task.created", {"task_id": item.id}))
```

业务写入与 Outbox 写入**必须同一事务**：任一步失败整体回滚，避免「事件残留但业务未生效」。

### 4.2 状态机

```text
pending ──claim──> publishing ──成功──> published
   ↑                    │
   └──复位(启动)──   ──失败──> failed ──重试──> publishing
```

| 方法 | 行为 |
| --- | --- |
| `add` | 插入 `pending`，不提交 |
| `fetch_dispatchable` | `status IN ('pending','failed') AND retry_count < max_retries ORDER BY id LIMIT n` |
| `mark_publishing` | 抢占，防止同进程重复派发 |
| `mark_published` | 写 `published_at` |
| `mark_failed` | `retry_count += 1`，记录 `last_error` |
| `reset_publishing` | 启动时把残留 `publishing` 复位为 `pending`（E1-FI-007） |
| `counts` | 按状态聚合，供诊断接口使用 |

`retry_count` 达到上限后不再被选取，保留 `failed` 行供人工排查，不自动删除。

## 5. Inbox

实现：`apps/backend/src/infrastructure/events/inbox.py`，主键 `(event_id, consumer_id)`。

- 投递前 `is_processed()`：仅 `status = 'processed'` 视为已消费；`failed` 行仍会重试。
- 成功写 `processed` 并记 `processed_at`；失败写 `failed` 与 `last_error`。
- 写入使用 `ON CONFLICT(event_id, consumer_id) DO UPDATE`，重复投递不会产生多行。

## 6. EventDispatcher

实现：`apps/backend/src/infrastructure/events/dispatcher.py`。

| 行为 | 说明 |
| --- | --- |
| 启动 | 先在同一事务内 `reset_publishing`，再启动后台任务 `event-dispatcher` |
| 轮询 | 默认 100 ms（E1-Q5），每轮取 `event_batch_size` 条 |
| 派发 | 逐条还原事件 → 查 Inbox → 调处理器 → 记录 Inbox → 标记 `published` / `failed` |
| 退避 | 本轮存在失败时按 `poll_interval × 2^failed`（上限 5 s）延迟下一轮 |
| 关闭 | 置停止标志并等待任务，超时取消并抛 `ShutdownTimeout` |
| 内存库 | `DatabaseService.is_ephemeral` 为真时**不启动后台任务**，只记录 `event_dispatcher_embedded`；测试直接调 `dispatch_once()` |

`dispatch_once()` 返回 `DispatchReport(claimed, published, failed, skipped)`，
供测试与诊断复用；单条坏 JSON 只标记该条失败，不中断整批。

## 7. 配置

`config/settings.py` 中的事件参数：

| 配置 | 默认 | 范围 | 说明 |
| --- | --- | --- | --- |
| `event_poll_interval_ms` | 100 | 10–60000 | 轮询间隔 |
| `event_batch_size` | 50 | 1–500 | 单轮最大派发条数 |
| `event_max_retries` | 5 | 0–100 | 单个事件最大重试次数 |

启动顺序为 `config → logging → errors → database → migration → events`；
关闭顺序为 `events → database → flush_logging`，保证停派发早于关连接。

## 8. 故障恢复

| 场景 | 处理 |
| --- | --- |
| 派发前进程崩溃（`publishing` 残留） | 下次启动复位为 `pending`，重新投递（重复由 Inbox 兜底） |
| 处理器抛异常 | `failed` + `retry_count`，退避后重试；达到上限保留失败记录 |
| payload 损坏 | 该条记 `failed` 并记录 `last_error`，不影响同批其他事件 |
| 数据库暂时不可用 | 本轮循环记录 `event_dispatch_cycle_failed`，下一轮重试；不退出后台循环 |
| 关闭超时 | `ShutdownTimeout`，由生命周期在关闭步骤中记录错误并继续清理 |

排查建议：先看 `event_outbox.status = 'failed'` 的 `last_error` 与 `correlation_id`，
再看 `event_inbox` 对应 `(event_id, consumer_id)` 是否已 `processed`（已处理则不会重复执行）。

## 9. 开发约束

1. 事务内禁止等待外部 AI 响应或人工审批，Outbox 写入必须短小。
2. 不允许绕过 Outbox 直接调用跨模块 Service 来传递「状态变更通知」。
3. 事件不承载业务状态的唯一真相；消费方需要时回查自己的数据。
4. 处理器必须幂等：同一 `(event_id, consumer_id)` 可能被多次投递。
5. 日志只用 `log_event` 与允许字段，禁止打印完整 payload 中的敏感信息。

## 10. 验收方式

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_event_model.py tests/unit/test_event_bus.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_event_outbox.py tests/integration/test_event_startup.py -q
```

覆盖：事件创建与契约校验、非法事件拒绝、发布订阅与失败隔离、Outbox 写入与状态推进、
失败重试至成功与重试上限、Inbox 幂等、业务与 Outbox 事务原子性、启动复位与后台派发。
