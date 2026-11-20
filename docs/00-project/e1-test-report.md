# E1 测试报告（E1-T14）

| 项 | 内容 |
| --- | --- |
| 阶段 | E1 Backend Core |
| 报告日期 | 2026-11-18 |
| 测试环境 | Windows 10（10.0.19045）/ Python 3.14.2 / SQLite 3.50.4 / pytest 8.x |
| 执行方式 | 本地 `check_all.py` + `pytest` + `perf_e1.py` |
| 结论 | P0 用例全部通过；P1 有测试或演练证据；性能基线已记录 |

## 1. 执行汇总

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe ..\..\scripts\testing\perf_e1.py
$env:GODOT_BIN='D:\应用程序\godot\Godot_v4.5.1-stable_win64.exe\Godot_v4.5.1-stable_win64_console.exe'
.\.venv\Scripts\python.exe ..\..\scripts\testing\check_all.py
```

| 项 | 结果 |
| --- | --- |
| Backend 测试 | **176 passed**（contract 15 / integration 38 / unit 123） |
| ruff format / check | PASS |
| check_all 7 阶段（含 Godot） | PASS |
| 性能基线 | `artifacts/perf-e1.json`（20 次采样，P95） |

### 测试文件分布

| 分类 | 文件（用例数） |
| --- | --- |
| 契约 | `test_protocol_samples.py`（15） |
| 集成 | `test_e1_core.py`（1）、`test_lifecycle.py`（1）、`test_lifecycle_core.py`（1）、`test_health.py`（3）、`test_diagnostics.py`（5）、`test_migrations.py`（7）、`test_migration_service.py`（8）、`test_event_outbox.py`（8）、`test_event_startup.py`（1）、`test_backup_restore.py`（3） |
| 单元 | 生命周期 9、配置 16、数据库 9、事务 7、仓储 6、日志 12、错误 20、事件 13、备份 4、健康 7、诊断 3、Secrets/Env 9 |

## 2. 集成测试（E1-T14 的 14 项）

| 编号 | 内容 | 覆盖位置 | 结果 |
| --- | --- | --- | --- |
| 1 | 完整启动 | `test_e1_core.py`、`test_event_startup.py` | PASS |
| 2 | 完整关闭（含重复关闭） | `test_e1_core.py`、`test_lifecycle.py`、`test_lifecycle_manager.py` | PASS |
| 3 | 配置加载 | `test_config_layers.py`、`test_config_service.py`、`test_settings.py` | PASS |
| 4 | 数据库初始化 | `test_database_service.py`、`test_e1_core.py` | PASS |
| 5 | Migration 执行 | `test_migrations.py`、`test_migration_service.py`、`test_e1_core.py` | PASS |
| 6 | Repository 查询 | `test_repository.py`、`test_e1_core.py`（分页与读取） | PASS |
| 7 | 事务提交 | `test_transaction.py`、`test_e1_core.py` | PASS |
| 8 | 事务回滚 | `test_transaction.py`、`test_e1_core.py`（业务异常后行数不变） | PASS |
| 9 | 事件发布 | `test_event_bus.py`、`test_e1_core.py` | PASS |
| 10 | Outbox 恢复 | `test_event_outbox.py`（`publishing` 复位）、`test_e1_core.py` | PASS |
| 11 | 数据库备份 | `test_backup.py`、`test_backup_restore.py` | PASS |
| 12 | 数据库恢复 | `test_backup_restore.py`（成功 / 版本不符 / 损坏拒绝） | PASS |
| 13 | 健康检查 | `test_health_service.py`、`test_health.py` | PASS |
| 14 | 异常统一处理 | `test_errors.py`、`test_error_taxonomy.py`、`test_health.py::test_error_response_shape` | PASS |

## 3. 任务覆盖（E1-T01…T14）

| 任务 | 对应测试 |
| --- | --- |
| T01 生命周期 | `test_lifecycle_manager.py`、`test_lifecycle.py`、`test_lifecycle_core.py` |
| T02 配置 | `test_settings.py`、`test_config_layers.py`、`test_config_service.py` |
| T03 数据库 | `test_database_service.py` |
| T04 Migration | `test_migrations.py`、`test_migration_service.py` |
| T05 Repository | `test_repository.py` |
| T06 事务 | `test_transaction.py` |
| T07 日志 | `test_logging.py`、`test_logging_file.py` |
| T08 异常 | `test_errors.py`、`test_error_taxonomy.py` |
| T09 事件 | `test_event_model.py`、`test_event_bus.py` |
| T10 Outbox/Inbox | `test_event_outbox.py`、`test_event_startup.py` |
| T11 备份/恢复 | `test_backup.py`、`test_backup_restore.py` |
| T12 健康检查 | `test_health_service.py`、`test_health.py` |
| T13 诊断 | `test_recent_errors.py`、`test_diagnostics.py` |
| T14 集成与性能 | `test_e1_core.py` + 本报告 |

## 4. 性能基线

脚本：`scripts/testing/perf_e1.py`；产物：`artifacts/perf-e1.json`（本地生成，目录不入库）。

环境：Windows-10-10.0.19045-SP0 / Python 3.14.2 / SQLite 3.50.4 / 20 次采样（日志 5 次 × 1000 条）。

数据量：200 行业务数据；数据库文件约 100 KB 量级；事件单条派发。

| 指标 | 单位 | 中位数 | P95 | 样本 |
| --- | --- | --- | --- | --- |
| 冷启动（完整 Lifecycle） | ms | 426.58 | 555.47 | 20 |
| 数据库初始化 | ms | 117.92 | 201.78 | 20 |
| Migration（3 个版本） | ms | 438.38 | 500.22 | 20 |
| 简单写入（含提交） | ms | 1.27 | 2.57 | 20 |
| 简单读取 | ms | 1.33 | 2.71 | 20 |
| 事务（20 次写入） | ms | 13.32 | 21.50 | 20 |
| 事件派发延迟（写入 Outbox → 消费完成） | ms | 2.94 | 5.50 | 20 |
| 日志写入开销（单条） | us | 38.66 | 43.64 | 5 |
| 备份 | ms | 133.05 | 208.89 | 5 |
| 恢复 | ms | 20.96 | 70.80 | 5 |

说明：本阶段只建立基线，不设硬性阈值；冷启动包含配置、日志、数据库、
迁移、事件与备份服务装配，测试数据为本地文件 SQLite。

## 5. 故障注入清单

| 编号 | 场景 | 证据 | 结果 |
| --- | --- | --- | --- |
| E1-FI-001 | 数据库不存在 | 首次初始化自动创建（`test_database_service.py`） | PASS |
| E1-FI-002 | 数据库只读 | `test_readonly_database_is_rejected`（真实只读文件 + 回滚写探测） | PASS |
| E1-FI-003 | 数据库损坏 | `test_corrupted_database_is_rejected`、`test_database_integrity_failure_is_unhealthy` | PASS |
| E1-FI-004 | Migration 失败 | `test_migration_failure_blocks_startup` 保留 `MIGRATION_FAILED` | PASS |
| E1-FI-005 | 日志目录不可写 | `test_unwritable_log_dir_raises_startup_error` | PASS |
| E1-FI-006 | Outbox 发布中断 | 事务回滚不丢事件；失败重试与上限（`test_event_outbox.py`） | PASS |
| E1-FI-007 | 进程突然终止 | 启动复位 `publishing → pending`（`test_startup_resets_publishing_rows`） | PASS |
| E1-FI-008 | 备份文件损坏 | `test_verify_rejects_invalid_backup` / `test_restore_failure_keeps_current_database` | PASS |
| E1-FI-009 | 恢复过程失败 | 保护副本回滚，当前数据不被删除 | PASS |
| E1-FI-010 | 配置文件非法 | 配置校验失败阻断启动（`test_settings.py`） | PASS |

## 6. 已知限制

1. 性能数据来自单机 Windows 文件系统，不能替代后续真实项目规模压测。
2. 恢复操作要求无并发写入；当前由 `BackupService` 停止事件派发并释放连接来保证。
3. `/health` 每次调用执行 `PRAGMA integrity_check`，可发现运行期文件损坏；数据库规模显著增大后需评估探测频率。

## 7. DoD 核对

- [x] Backend 完整启动/关闭，重复关闭幂等
- [x] 生命周期状态转换正确
- [x] 配置加载、验证与覆盖机制正常
- [x] SQLite 服务正常（WAL、外键、完整性检查）
- [x] Migration 可执行、可审计、可阻断失败启动
- [x] Repository 可供业务模块使用
- [x] 事务提交/回滚/超时/嵌套策略通过测试
- [x] 日志结构化、轮转、脱敏
- [x] 异常统一为 `AppError` 与契约错误结构
- [x] 事件发布与 Outbox/Inbox 通过测试
- [x] 备份与恢复有真实测试证据
- [x] Health Check 区分 live/ready 与依赖状态
- [x] Diagnostics 不泄露敏感信息（脱敏 + 生产令牌）
