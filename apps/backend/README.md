# Backend（E0 骨架）

Local Backend 的最小可运行骨架。E0 阶段只建立结构与基础设施入口，
不包含任何业务模块。

## 目录职责

| 目录 | 职责 |
| --- | --- |
| `src/app` | 应用入口与 HTTP 接口 |
| `src/bootstrap` | 启动装配、生命周期 |
| `src/config` | 配置加载（唯一入口） |
| `src/core` | 核心抽象：错误、日志 |
| `src/modules` | 业务模块（E1 起填充） |
| `src/infrastructure` | 数据库、文件、外部依赖 |
| `src/shared` | 通用类型 |
| `migrations` | Alembic 迁移 |
| `tests` | unit / contract / integration |

## 本地启动

```powershell
cd apps/backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.main
```

健康检查：`GET http://127.0.0.1:8765/health`

## 配置与密钥

- 配置：`Copy-Item .env.example .env` 后修改，规则见 [配置管理规范](../../docs/03-development/configuration.md)。
- 密钥：只存操作系统凭证库（`GODOT_AI_` 环境变量里不放 Key），见 [Secrets 管理规范](../../docs/03-development/secrets.md)。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 约束

- 配置只能通过 `config.settings.load_settings()` 读取，禁止散落 `os.environ`。
- 业务模块不得访问其他模块的 Repository。
- 本阶段禁止在入口堆积业务逻辑。
