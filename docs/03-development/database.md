# 数据库与数据管理规范（E0-T06）

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

## 4. 事务规范

1. **短事务**：事务内不发起网络调用、不等待用户输入、不写大文件。
2. 一次状态变更 = 一个事务，禁止跨请求持有事务。
3. 重要写入必须显式事务，成功后提交，异常必须回滚。
4. UNKNOWN 状态不得被当作成功或失败写入，需保留原状态并记录原因。
5. 跨模块消息使用 Outbox / Inbox（E2 起实现），投递语义为 At-least-once，消费方必须幂等。

## 5. Migration 规范

### 5.1 目录结构

```
apps/backend/
├── alembic.ini
└── migrations/
    ├── env.py
    ├── script.py.mako
    └── versions/
        └── 000001_initial_schema.py
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

### 5.4 失败处理

1. 升级前自动备份（库文件存在时）。
2. 每个 Migration 在事务中执行；SQLite 的 DDL 可回滚。
3. 失败统一抛出 `MigrationError`（`code = MIGRATION_FAILED`），
   错误信息只包含起始版本与备份路径，不泄露 SQL 与绝对路径以外的内部细节。
4. 失败后禁止自动重试；需人工确认备份与日志后再处理。
5. 恢复方式：停止服务 → 用备份文件覆盖当前库 → 回退代码 → 重新升级。

入口：`apps/backend/src/infrastructure/database/manager.py` 的 `upgrade_to_head()`。

## 6. 备份与恢复

- 备份使用 SQLite 在线备份 API（`sqlite3.Connection.backup`），WAL 下仍保证一致性。
- 默认目录：数据库同级 `backups/`，文件名 `<库名>-<UTC 时间戳>.db`。
- 触发时机：每次执行 Migration 前；后续可增加定时备份（E12）。
- 保留策略：E0 阶段不自动清理；上线前由 E12 定义保留窗口。
- 恢复步骤：
  1. 停止 Backend。
  2. 校验备份文件可打开：`PRAGMA integrity_check`。
  3. 覆盖当前库文件（连同 `-wal` / `-shm` 一并清理）。
  4. 启动并验证 `alembic_version` 与预期一致。

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

## 9. E0 不做

- 不建立 Task / Workflow / Agent / Asset 等业务表。
- 不实现 Outbox / Inbox 表结构（E2）。
- 不做数据迁移工具与历史数据清洗。

## 10. 验收方式

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/integration/test_migrations.py -q
```

覆盖：升级成功、幂等、PRAGMA 生效、备份生成、失败转换。
