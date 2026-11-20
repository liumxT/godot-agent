# 配置管理规范（E0-T07 / E1-T02）

## 1. 配置分类

| 类型 | 字段 | 示例 |
| --- | --- | --- |
| 应用配置 | `app_name` / `app_version` / `environment` | `godot-ai-backend` |
| 网络配置 | `host` / `port` | `127.0.0.1:8765` |
| 数据配置 | `data_dir` / `database_url` | `sqlite+aiosqlite:///./data/backend.db` |
| 日志配置 | `log_level` / `log_dir` | `INFO` / `logs` |
| 模型配置 | `model_provider` | `none`（具体 Provider 由 E4 定义） |
| 安全配置 | 不在 Settings 中 | 见 [secrets.md](secrets.md) |

**安全配置（API Key、Token、密码）一律不进 Settings**，只通过
`infrastructure.secrets` 读取操作系统凭证库。

## 2. 加载与优先级

配置入口：

- `config/settings.py` 的 `load_settings()`：单层加载（环境变量 + `.env` + 默认值），供测试与简单场景使用；
- `config/layers.py` 的 `load_layered_settings()`：E1 起的应用启动入口，额外支持 TOML 与运行时覆盖；
- `config/service.py` 的 `ConfigService`：持有当前配置，提供只读快照与受策略约束的热更新。

优先级（高 → 低）：

1. `load_layered_settings(overrides=...)` 显式传参（装配与测试用）。
2. 环境变量（前缀 `GODOT_AI_`，如 `GODOT_AI_PORT`）。
3. TOML 配置文件：`GODOT_AI_CONFIG_FILE` 指定，默认 `apps/backend/config/backend.toml`（不存在时跳过）。
4. `apps/backend/.env`（本地开发，不入库；测试传 `env_file=None` 关闭）。
5. 代码默认值。

示例 `config/backend.toml`：

```toml
database_url = "sqlite+aiosqlite:///./data/backend.db"
port = 8765
log_level = "INFO"
```

TOML 中出现未知字段、格式错误或取值非法时统一抛出 `ConfigError`，阻断启动（E1-FI-010）。

禁止在业务代码中直接读取 `os.environ` 或 `os.getenv`。

### 2.1 运行时变更策略

| 策略 | 字段 | 行为 |
| --- | --- | --- |
| `IMMUTABLE` | `app_name` / `environment` / `database_url` | 拒绝修改（`ConfigError`） |
| `RESTART_REQUIRED` | `host` / `port` / `data_dir` / `log_dir` 及未登记字段 | 拒绝修改并提示需重启 |
| `HOT_RELOAD` | `log_level` | 立即生效，并重建日志 handler |

- 被拒绝的变更记录 `config_rejected`（`error_code=CONFIG_ERROR`）；
- 成功加载/热更新记录 `config_loaded`，敏感字段脱敏后输出；
- `ConfigService.snapshot()` 返回只读副本（`MappingProxyType`）。

## 3. 变量命名

- 统一前缀 `GODOT_AI_`，字段名大写下划线（`database_url` → `GODOT_AI_DATABASE_URL`）。
- 示例配置：[apps/backend/.env.example](../../apps/backend/.env.example)，复制为 `.env` 后使用。
- `.env` 已在 `.gitignore` 中排除；仅 `.env.example` 允许入库。

## 4. 校验规则

| 字段 | 规则 | 失败行为 |
| --- | --- | --- |
| `database_url` | 必填，且必须是 SQLite URL | 启动失败，报"缺少必填配置"或"配置格式非法" |
| `host` | 仅回环地址（`127.0.0.1` / `::1` / `localhost`） | 校验失败 |
| `port` | `1–65535` | 校验失败 |
| `log_level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` | 校验失败 |
| `data_dir` / `log_dir` | 非空字符串 | 校验失败 |
| `model_provider` | 非空字符串 | 校验失败 |

所有校验失败统一转换为 `ConfigError`（`code = config_error`），
`details.errors` 保留 pydantic 原始错误项，消息中给出缺失字段名。

## 5. 禁止事项

1. 禁止在代码中硬编码凭证、连接串中的账号密码、默认 Token。
2. 禁止把真实 `.env`、`secrets/`、`*.pem`、`*.key` 提交到仓库。
3. 禁止新增未经校验的配置项（直接 `os.environ[...]` 读取）。
4. 禁止把密钥写入数据库、日志、错误详情或契约样例。
5. 禁止在配置文件中使用非回环监听地址（本地服务只对本机开放）。

## 6. 环境隔离

| 环境 | 配置文件 | 数据库 |
| --- | --- | --- |
| development | `.env` + `config/backend.toml`（本地） | `apps/backend/data/backend.db` |
| test | 代码内 `load_layered_settings(overrides=..., env_file=None)` | 每个用例独立 `tmp_path` |
| production | 由安装器写入用户数据目录内的 `backend.toml` | 用户数据目录下 `data/backend.db` |

测试必须传 `env_file=None`，避免本机 `.env` 影响结果。

## 7. 验收

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_settings.py tests/unit/test_config_layers.py tests/unit/test_config_service.py tests/unit/test_env_example.py -q
```

覆盖：必填缺失、越界端口、非回环地址、非法日志级别、非 SQLite 数据库、
环境变量覆盖、示例配置可加载、示例配置不含凭证、`.env` 已被忽略、
TOML 分层优先级、未知字段/非法值阻断、变更策略与脱敏。
