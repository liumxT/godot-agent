# E0 测试报告（E0-D12）

| 项 | 内容 |
| --- | --- |
| 阶段 | E0 Project Foundation |
| 报告日期 | 2026-11-17 |
| 测试环境 | Windows / Python 3.14.2 / Godot 4.5.1.stable / pytest 8.x |
| 执行方式 | 本地 `check_all.py` + `pytest`，Godot headless 编辑器模式 |
| 结论 | 单元测试 10/10 通过；集成测试 8/8 有证据；故障注入 6/8 自动化或演练 |

## 1. 执行汇总

```powershell
cd apps/backend
.\.venv\Scripts\python.exe ..\..\scripts\testing\check_all.py
```

| 阶段 | 结果 | 耗时 |
| --- | --- | --- |
| 仓库结构 | PASS | 0ms |
| 敏感文件 | PASS | 505ms |
| 代码格式 | PASS | 92ms |
| 静态检查 | PASS | 88ms |
| Contracts Schema | PASS | 733ms |
| Backend 测试 | PASS | 2182ms |
| Godot Plugin | PASS | 8637ms |

补充统计：`pytest` 共 **52 passed**（contract 15 / integration 10 / unit 27）。

| 测试文件 | 用例数 |
| --- | --- |
| `tests/contract/test_protocol_samples.py` | 15 |
| `tests/integration/test_migrations.py` | 7 |
| `tests/integration/test_health.py` | 2 |
| `tests/integration/test_lifecycle.py` | 1 |
| `tests/unit/test_settings.py` | 8 |
| `tests/unit/test_logging.py` | 5 |
| `tests/unit/test_errors.py` | 5 |
| `tests/unit/test_secrets.py` | 5 |
| `tests/unit/test_env_example.py` | 4 |

## 2. 单元测试（E0-UT）

| 编号 | 内容 | 覆盖位置 | 结果 |
| --- | --- | --- | --- |
| E0-UT-001 | Backend 工程启动 | `test_lifecycle.py` + `test_health.py` | PASS |
| E0-UT-002 | 配置加载 | `test_settings.py::test_load_settings_success` | PASS |
| E0-UT-003 | 配置缺失 | `test_settings.py::test_missing_required_field_raises_config_error` | PASS |
| E0-UT-004 | 日志输出格式 | `test_logging.py`（字段、上下文、事件、堆栈） | PASS |
| E0-UT-005 | 错误格式 | `test_errors.py` + `test_error_response_shape` | PASS |
| E0-UT-006 | Contracts Schema 合法数据 | `test_protocol_samples.py`（manifest 11 样例） | PASS |
| E0-UT-007 | 非法协议数据 | `test_protocol_samples.py` 反例用例 | PASS |
| E0-UT-008 | Migration 执行 | `test_upgrade_creates_schema` | PASS |
| E0-UT-009 | Migration 重复执行 | `test_upgrade_is_idempotent` | PASS |
| E0-UT-010 | Secrets 检查 | `test_env_example.py` / `test_secrets.py` | PASS |

## 3. 集成测试（E0-IT）

| 编号 | 内容 | 覆盖方式 | 结果 |
| --- | --- | --- | --- |
| E0-IT-001 | Backend 整体启动 | `TestClient` 触发 lifespan，健康检查 200 | PASS |
| E0-IT-002 | Godot Plugin 安装 | `addons/godot_ai_agent` 被编辑器识别并加载 | PASS |
| E0-IT-003 | Godot Plugin 启用 | 日志 `plugin_enabled`（headless 编辑器） | PASS |
| E0-IT-004 | Godot Plugin 关闭 | 日志 `plugin_disabled`，退出码 0 | PASS |
| E0-IT-005 | 两端协议样例一致 | Backend `tests/contract` + Godot `--contract-test` 探针 | PASS |
| E0-IT-006 | CI 流程 | `check_all.py` 7 阶段全 PASS，退出码 0 | PASS（本地；远程 workflow 待接 remote 验证） |
| E0-IT-007 | Migration 失败模拟 | `test_failure_is_wrapped`（包装为 `MIGRATION_FAILED`） | PASS |
| E0-IT-008 | 日志敏感信息 | `redact()` 测试 + 仓库敏感文件扫描 | PASS（机制层面） |

Godot 运行证据：

```text
[GodotAI] {"component":"godot_plugin","event":"plugin_enabled","level":"INFO",...,"version":"0.1.0"}
[GodotAI] {"component":"godot_plugin","event":"plugin_disabled","level":"INFO","message":"plugin_disabled",...}
exit 0
```

## 4. 故障注入（E0 §5.3）

| # | 场景 | 验证方式 | 结果 |
| --- | --- | --- | --- |
| 1 | 配置文件不存在 | 缺 `database_url` → `ConfigError` | PASS |
| 2 | 配置格式错误 | 端口越界 / 非回环 host / 非法日志级别 / 非 SQLite URL | PASS |
| 3 | 数据库文件无法创建 | 父路径被普通文件占用 → `OSError` 抛出 | PASS |
| 4 | 数据库文件不可写 | 未自动化（Windows ACL 场景），与 #3 共用同类异常路径 | 未覆盖 |
| 5 | Migration 执行失败 | monkeypatch 注入异常 → `MIGRATION_FAILED`，日志含堆栈 | PASS |
| 6 | CI 某项检查失败 | 开发中触发敏感文件误报，脚本退出码 1 并阻断 | PASS（人工演练） |
| 7 | 插件重复启用 | `plugin.gd` 的 `_enabled` 保护；编辑器实际只启用一次 | 代码审查通过，未自动化 |
| 8 | 插件初始化异常 | 版本不支持分支创建降级面板 | 未覆盖（本机版本满足要求） |

结论：错误均能被发现、记录并安全终止；4/7/8 不属于"必须自动恢复"的场景，
已列入遗留项。

## 5. 遗留问题

| 编号 | 问题 | 影响 | 计划 |
| --- | --- | --- | --- |
| G1 | 故障注入 #4 未自动化 | 低 | E1 引入可写性检查时补充 |
| G2 | 故障注入 #7/#8 未自动化 | 低 | E3 Editor Bridge 测试体系内补充 |
| G3 | CI workflow 未在远程执行 | 中 | 接入 remote 后首次运行确认 |
| G4 | `TestClient` 触发 Starlette 弃用告警 | 极低 | 等待上游 httpx2 支持后处理 |
