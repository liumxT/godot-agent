# 数据库与数据管理规范（E0-T06 / E1-T03–T06）

## 1. 存储选型

- **SQLite 是唯一 Primary Database**，不引入第二种关系型存储。
- 驱动：`aiosqlite`（运行时异步）+ `SQLAlchemy 2.0`（ORM/连接管理）。
- 迁移：`Alembic`。
- 不使用 ORM 自动建表（禁止 `Base.metadata.create_all` 用于生产），结构变更一律走 Migration。

## 2. 数据库文件位置

| 场景 | 位置 |
| --- | --- |
| 开发 | `apps/backend/data/backend.db` |
| 测试 | 每个测试独立的临时目录（`tmp_path`），禁止复用开发库 |
| 打包后 | 用户数据目录下 `data/backend.db`，由 E11/E12 决定具体路径 |

规则：

1. 路径由 `GODOT_AI_DATABASE_URL` 决定，代码中不得硬编码。
2. `data/` 目录整体不入库（见 `.gitignore`）。
3. 数据库文件与备份目录必须同盘，避免跨盘复制不一致。
4. 库文件父目录不存在时由 `ensure_database_parent()` 自动创建（SQLite 不会自动建目录）。

## 3. 连接规范

每个连接建立后统一执行：

```sql
PRAGMA journal_mode = WAL;      -- 读写并发
PRAGMA synchronous = NORMAL;    -- WAL 下的安全/性能平衡
PRAGMA foreign_keys = ON;       -- 外键约束默认关闭，必须显式开启
PRAGMA busy_timeout = 5000;     -- 避免瞬时锁冲突直接失败
```

实现位置：`apps/backend/src/infrastructure/database/engine.py`。

### 3.1 DatabaseService（E1-T03）

`apps/backend/src/infrastructure/database/service.py` 统一持有 `AsyncEngine` 与会话工厂：

| 方法 | 行为 |
| --- | --- |
| `initialize()` | 建目录 → 创建引擎 → `SELECT 1` → `PRAGMA quick_check` → 回滚事务内的写探测（识别只读文件），失败即阻断启动 |
| `session()` | 打开/关闭会话，**不提交**；提交由事务边界负责 |
| `ping()` | 轻量可用性探测，异常不外抛 |
| `dispose()` | 释放连接池，幂等 |

异常翻译集中在 `database/errors.py`：

| SQLAlchemy 异常 | 领域异常 | 说明 |
| --- | --- | --- |
| `OperationalError` | `DatabaseError(DATABASE_UNAVAILABLE, retryable=True)` | 运行期暂不可用 |
| `IntegrityError` | `DatabaseError(DATABASE_INTEGRITY_ERROR, retryable=False)` | 约束/完整性失败 |
| 文件不可写/只读 | `StartupError` | 仅在启动阶段，直接阻断 |

健康探测在 `database/health.py`：`integrity_check()`（`PRAGMA integrity_check`）、
`schema_revision()`（读取 `alembic_version`）、`check()`（聚合为 `DatabaseHealth`）。

## 4. 事务规范

1. **短事务**：事务内不发起网络调用、不等待用户输入、不写大文件。
2. 一次状态变更 = 一个事务，禁止跨请求持有事务。
3. 重要写入必须显式事务，成功后提交，异常必须回滚。
4. UNKNOWN 状态不得被当作成功或失败写入，需保留原状态并记录原因。
5. 跨模块消息使用 Outbox / Inbox（E1-T10），投递语义为 At-least-once，消费方必须幂等；
   表结构与派发规则见 [事件与 Outbox/Inbox](events.md)。

### 4.1 事务上下文（E1-T06）

`apps/backend/src/infrastructure/database/transaction.py` 提供唯一事务边界：

```python
async with database.session() as session, transaction(session, timeout=5):
    await repository.add(entity)
```

- 最外层开启事务，正常退出提交、异常回滚；
- 嵌套调用加入外层，不启用 savepoint（E1-Q3），内层不单独提交；
- `timeout` 超时回滚并抛 `OperationTimeout(code=TRANSACTION_TIMEOUT)`，
  同时将会话标记为失效，禁止继续复用；
- 事务内禁止外部 AI 调用与人工审批等待。

## 5. Migration 规范

### 5.1 目录结构

```
apps/backend/
├── alembic.ini
└── migrations/
    ├── env.py
    ├── script.py.mako
    └── versions/
        ├── 000001_initial_schema.py
        ├── 000002_migration_history.py
        └── 000003_event_infrastructure.py
```

### 5.2 命名规则

```
<6 位版本号>_<snake_case 描述>.py
000001_initial_schema
000002_add_task_table
000003_add_task_index
```

- 版本号连续递增，不复用、不跳号。
- 文件名与 `revision` 字段一致（`revision = "000001"`）。
- 一个 Migration 只做一件事：建表、加列、加索引分别提交。

### 5.3 执行状态

- 状态由 `alembic_version` 表记录，禁止手工修改。
- 重复执行 `upgrade head` 必须是无操作（幂等）。
- 不允许绕过 Migration 直接改库结构而不留记录。
- `migration_history`（`000002` 引入）只做审计：revision / name / checksum /
  status / applied_at / duration_ms / error；以 `alembic_version` 为事实源。
- `000003_event_infrastructure` 创建 `event_outbox` / `event_inbox`，见
  [事件与 Outbox/Inbox](events.md)。

### 5.4 迁移服务（E1-T04）

入口：`apps/backend/src/infrastructure/database/manager.py` 的 `MigrationService`。

1. 升级前自动备份（库文件存在时）。
2. 通过运行时引擎连接执行 `alembic upgrade head`（`env.py` 支持外部连接，
   内存库与文件库行为一致）。
3. 成功后为每个 revision 补写 `migration_history` 的 `applied` 记录；
   总耗时记在本次升级到的 head 上，历史补齐记为 0。
4. 失败时写 `failed` 记录（摘要脱敏）并抛 `MigrationError`（`MIGRATION_FAILED`），
   由启动流程阻断进入 `RUNNING`。
5. 启动时校验 `current_revision == head`；不一致拒绝启动（E1-FI-004）。
6. 启动时校验已执行迁移文件 checksum；文件被修改或缺失即 `MigrationError`。
7. 失败后禁止自动重试；需人工确认备份与日志后再处理。
8. 恢复方式：停止服务 → 用备份文件覆盖当前库 → 回退代码 → 重新升级。

## 6. 备份与恢复

实现：`apps/backend/src/infrastructure/database/backup.py`（E1-T11）与迁移前备份
`backup_database()`。

- 备份使用 SQLite 在线备份 API（`sqlite3.Connection.backup`），WAL 下仍保证一致性；
  读取连接一律显式关闭，避免 Windows 下占用库文件导致清理/恢复失败。
- 默认目录：数据库同级 `backups/`；可用 `backup_dir` 覆盖。
- 文件名：`<库名>-<UTC 时间戳>.db`，同名 `.json` 保存 `created_at / reason /
  size_bytes / sha256 / revision / source`。
- 触发时机：每次执行 Migration 前；`BackupService.create()` 供维护或后续定时任务调用。
- 保留策略：`backup_retention`（默认 10），超出部分按时间从旧到新删除并记审计日志。
- 校验：`BackupService.verify()` 执行 `PRAGMA integrity_check` 并读取 revision；
  无效或损坏的备份**拒绝恢复**（E1-FI-008）。

恢复流程（`BackupService.restore()`）：

1. 校验备份文件并核对 `expected_revision`（可选）。
2. 停止事件派发、释放数据库连接。
3. 在 `backups/restore/` 创建当前库保护副本。
4. 清理目标库的 `-wal` / `-shm` / `-journal` 后覆盖。
5. 恢复后重新做完整性检查与 revision 比对，通过后重新初始化数据库、恢复派发。
6. 任一步失败回滚到保护副本并重新打开数据库，抛出 `BackupError`（E1-FI-009），
   当前数据不会被删除。

内存库（`:memory:`）不支持备份与恢复，调用时直接拒绝。

## 7. 开发与测试隔离

| 环境 | 数据库 |
| --- | --- |
| 开发 | `apps/backend/data/backend.db` |
| 测试 | 每个用例独立的 `tmp_path/*.db` |
| CI | 临时目录，任务结束即删除 |

测试禁止：

- 连接开发库。
- 依赖上一个用例遗留的数据。
- 使用共享的内存库（`file::memory:?cache=shared`）。

## 8. Repository 规范

1. 每个模块只暴露自己的 Repository，**禁止跨模块直接访问他方 Repository**。
2. Repository 只负责数据存取，不包含业务规则与跨模块编排。
3. 方法命名：`get_*` / `list_*` / `create_*` / `update_*` / `delete_*`，语义固定。
4. 查询必须显式限定条件；禁止无条件全表更新或删除。
5. 列表查询必须支持分页参数，禁止无界返回。
6. Repository 接收/返回领域对象或明确的 DTO，不向上暴露 ORM 会话与连接。
7. 事务边界由应用服务控制，Repository 不自行提交。
8. 所有涉及时间的字段统一存 UTC。

### 8.1 基类（E1-T05）

`apps/backend/src/infrastructure/database/repository.py` 提供：

```python
class TaskRepository(BaseRepository[Task]):
    model = Task

page = await repository.paginate(limit=50, offset=0, filters=(Task.status == "pending",))
```

- `get / add / delete / paginate`；`add`/`delete` 只 `flush`，不提交；
- `limit` 限制 1–200，`offset ≥ 0`，越界抛 `ValueError`；
- 返回 `Page(items, total, limit, offset)`，默认按主键排序保证分页稳定；
- 查询/写入异常统一翻译为 `DatabaseError`，不向上暴露 SQLAlchemy 异常。

## 9. E0 不做

- 不建立 Task / Workflow / Agent / Asset 等业务表。
- 不做数据迁移工具与历史数据清洗。

Outbox / Inbox 表由 E1-T10 提供（迁移 `000003`），不属于业务表。

## 10. 验收方式

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/integration/test_migrations.py tests/integration/test_migration_service.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_database_service.py tests/unit/test_transaction.py tests/unit/test_repository.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_event_outbox.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_backup.py tests/integration/test_backup_restore.py -q
```

覆盖：服务初始化与关闭、WAL/外键、迁移首次/幂等/顺序/checksum/失败、事务提交/回滚/超时/嵌套、
仓储查询/写入/事务注入/异常映射、启动期迁移阻断、Outbox 派发与 Inbox 幂等、备份创建/校验/
保留策略、恢复成功与失败保护。
