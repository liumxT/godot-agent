# ADR-007：Backend 打包与分发方式

- **状态：** Accepted
- **决策日期：** 2026-11-17
- **决策人：** 项目负责人
- **相关文档：** [ADR-002](ADR-002-backend-framework.md)、[ADR-004](ADR-004-database.md)、[E0-T02](../../完整开发计划细分/E0.md)、[打包配置](../../scripts/release/godot_ai_backend.spec)

## 1. 背景与问题

最终用户不应安装 Python。Backend 必须以可执行产物随插件/安装器分发，
并满足：单目录或单文件可拷贝、启动快、能执行数据库迁移、能读取契约文件。

## 2. 比较标准

| 标准 | 说明 |
| --- | --- |
| Python 3.14 支持 | 当前解释器版本必须先被工具支持 |
| 启动耗时 | 用户点击到 `/health` 可用的时间 |
| 体积 | 安装包大小与解压成本 |
| 资源文件 | 迁移脚本、契约 JSON 需随包分发且可定位 |
| 动态导入 | Alembic 方言、uvicorn 协议按运行时配置导入 |
| 调试成本 | 打包后日志与错误是否可读 |
| 杀软误报 | 单文件自解压更容易被拦截 |

## 3. 备选方案

| 方案 | 评价 |
| --- | --- |
| **PyInstaller onedir** | 启动快、资源明文可查、排错容易；文件数量多 |
| **PyInstaller onefile** | 单文件便于拷贝；每次启动解压到临时目录，更慢、更易触发杀软 |
| Nuitka | 编译为原生代码，启动与体积有优势，但构建链重、Python 3.14 支持滞后 |
| 嵌入式 Python + zipapp | 需要用户态解压与启动脚本，跨平台差异大 |
| 不打包，要求用户装 Python | 违背产品前提 |

## 4. 决策

1. 使用 **PyInstaller 6.22.3**（实测支持 Python 3.14.2）。
2. **onedir 作为默认分发形态**；onefile 作为可选便携形态保留。
3. 资源随包分发：`migrations/` → `migrations`，`packages/contracts` → `packages/contracts`。
4. 运行时通过 `sys._MEIPASS` 定位资源（`shared/contracts.py`、`infrastructure/database/manager.py`）；
   `GODOT_AI_CONTRACTS_DIR` 仍可覆盖契约目录。
5. 打包后 Alembic 用编程方式构造 `Config`，不依赖 `alembic.ini` 的 `prepend_sys_path`。
6. 必须声明 hidden imports：`alembic.ddl.sqlite`、`sqlalchemy.dialects.sqlite[.aiosqlite]`、
   `aiosqlite`、`uvicorn.logging`、`uvicorn.loops.auto`、`uvicorn.protocols.*.auto`、
   `uvicorn.lifespan.on`。
7. 入口支持 `--migrate`：安装器/升级流程先迁移再启动服务。

## 5. 实测结果（Windows，2026-11-17）

| 指标 | onedir | onefile |
| --- | --- | --- |
| 产物体积 | 39.1 MB | 23.4 MB |
| 冷启动到 `/health` 200 | 1248 ms | 1757 ms |
| `--migrate` 建表 | 通过（`000001`） | 通过（`000001`） |
| 冒烟退出 | exit 0 | exit 0 |

构建命令见 [spec 文件头注释](../../scripts/release/godot_ai_backend.spec)，
冒烟脚本为 [smoke_packaged_backend.py](../../scripts/release/smoke_packaged_backend.py)。

## 6. 选择理由

1. onedir 启动更快，资源是明文文件，E10 排错与增量更新更容易。
2. onefile 体积更小、便于"拷一个文件就跑"，但解压开销和杀软误报风险更高，
   因此仅作为便携备选。
3. 保留 `GODOT_AI_CONTRACTS_DIR` 覆盖能力，插件端可与 Backend 共用同一份契约。

## 7. 影响范围

| 影响项 | 说明 |
| --- | --- |
| E10 | 以 onedir 产物制作安装包；onefile 可选 |
| E2/E3 | 启动顺序固定为「迁移 → 启动服务」 |
| 代码约束 | 任何新增运行时资源都必须加入 spec 的 `datas` |
| CI | 打包检查可复用 smoke 脚本，当前不进 E0 门禁 |

## 8. 已知问题与后续

- onefile 启动时会派生子进程，结束进程须按进程树处理（冒烟脚本已验证）。
- 单文件更容易触发杀软误报，正式分发前需在目标环境实测。
- 代码签名、版本信息、图标属于 E10 范围。
- PyInstaller 不在 `pyproject` 依赖中（仅构建期使用），E10 需锁定版本。

## 9. 变更条件

- onefile 的杀软误报在目标用户中不可接受 → 固定 onedir。
- 启动耗时或体积成为明确瓶颈 → 评估 Nuitka 或裁剪依赖。
- Python 3.14 生态出现打包不兼容 → 先回退 3.13（见 Q3）。
