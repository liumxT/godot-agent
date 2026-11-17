# 配置管理规范（E0-T07）

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

唯一入口：`apps/backend/src/config/settings.py` 的 `load_settings()`。

优先级（高 → 低）：

1. `load_settings(**overrides)` 显式传参（测试与装配用）。
2. 环境变量（前缀 `GODOT_AI_`）。
3. `apps/backend/.env`（本地开发，不入库）。
4. 代码默认值。

禁止在业务代码中直接读取 `os.environ` 或 `os.getenv`。

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
| development | `.env`（本地） | `apps/backend/data/backend.db` |
| test | 代码内 `load_settings(_env_file=None, ...)` | 每个用例独立 `tmp_path` |
| production | 由安装器写入用户数据目录 | 用户数据目录下 `data/backend.db` |

测试必须传 `_env_file=None`，避免本机 `.env` 影响结果。

`config/development|test|production/` 目录为后续分环境配置预留，
E0 不引入第二套加载逻辑；新增环境文件时须更新本节。

## 7. 验收

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_settings.py tests/unit/test_env_example.py -q
```

覆盖：必填缺失、越界端口、非回环地址、非法日志级别、非 SQLite 数据库、
环境变量覆盖、示例配置可加载、示例配置不含凭证、`.env` 已被忽略。
