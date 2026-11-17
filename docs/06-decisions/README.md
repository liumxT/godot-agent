# 技术决策记录（ADR）索引 — E0-T02 交付物

> 本目录为 E0-T02「技术栈和运行环境确定」的交付物。
> 命名与位置遵循 [E0.md](../../完整开发计划细分/E0.md) 的约定 `docs/06-decisions/`
> （[实施蓝图.md](../../实施蓝图.md) 第二十五部分使用 `docs/adr/`，以本目录为准，后续如需统一再迁移）。
>
> 最后更新：2026-11-17

## 1. ADR 状态

| ADR | 主题 | 决策 | 状态 |
| --- | --- | --- | --- |
| [ADR-001](ADR-001-backend-language.md) | Backend 编程语言 | Python 3.14 | Accepted |
| [ADR-002](ADR-002-backend-framework.md) | Backend 框架与基础库 | FastAPI + Pydantic v2 + SQLAlchemy 2.0 + Alembic | Accepted |
| [ADR-003](ADR-003-godot-version.md) | Godot 版本基线 | Godot 4.5.1（GDScript-only） | Accepted |
| ADR-004 | Primary Database | SQLite（蓝图 §7.1 已定，待补文档） | Pending |
| ADR-005 | 本地通信 | 本地 WebSocket + HTTP（蓝图 §8.2 已定，待补文档） | Pending |
| ADR-006 | 测试框架 | pytest 系（待补文档） | Pending |

## 2. 技术栈清单

| 层次 | 选型 | 版本策略 |
| --- | --- | --- |
| Godot Plugin | GDScript，`EditorPlugin` | 随 Godot 4.5.1 基线 |
| Backend 语言 | Python | 3.14.2（锁定到 patch） |
| Backend 框架 | FastAPI + uvicorn | 锁定 lockfile |
| 数据校验/契约 | Pydantic v2 + JSON Schema | 契约版本化管理 |
| ORM / 迁移 | SQLAlchemy 2.0 + Alembic + aiosqlite | 迁移文件入仓 |
| 数据库 | SQLite（WAL、短事务、单写者） | 单文件本地库 |
| 通信 | 本地 WebSocket（主）+ HTTP（健康检查/诊断） | 仅绑定 127.0.0.1 |
| 测试 | pytest + pytest-asyncio + httpx | — |
| 打包分发 | PyInstaller（Nuitka 为备选） | E0 spike 验证 |
| 日志 | 标准库 logging + 结构化 JSON formatter | E0-T08 落规范 |
| 版本控制 | Git 2.54.0 | — |
| CI | 待定（见 §4 待确认项） | E0-T09 |

## 3. 开发环境版本清单（2026-11-17 本机实测）

| 组件 | 实测版本 | 实际路径 | 状态 |
| --- | --- | --- | --- |
| Python | 3.14.2 | `D:\python\python.exe` | 可用 |
| Node.js | v24.21.0 | `C:\Program Files\nodejs\node.exe` | 可用（非必需） |
| .NET SDK | 8.0.422 | `C:\Program Files\dotnet\dotnet.exe` | 可用（本阶段不用） |
| Git | 2.54.0.windows.1 | `D:\应用程序\git\Git\cmd\git.exe` | 已装，**PATH 损坏** |
| Godot | 4.5.1.stable.official.f62fdbde1 | `D:\应用程序\godot\Godot_v4.5.1-stable_win64.exe\Godot_v4.5.1-stable_win64_console.exe` | 已装 |
| Godot 导出模板 | 未安装 | `%APPDATA%\Godot\export_templates`（空） | **缺失，阻塞 E10** |

`godot --version` 实测输出：`4.5.1.stable.official.f62fdbde1`

## 4. 环境问题与待确认项

### 4.1 必须修复：git 不在 PATH

用户 PATH 中该条目的中文目录被写坏（`D:\应锟矫筹拷锟斤拷\git\Git\cmd`），
导致 `git` 无法解析。真实路径为 `D:\应用程序\git\Git\cmd`。

修复（用户级 PATH，追加而非覆盖）：

```powershell
$userPath = [Environment]::GetEnvironmentVariable('Path','User')
if ($userPath -notlike '*\Git\cmd*') {
  [Environment]::SetEnvironmentVariable('Path', "$userPath;D:\应用程序\git\Git\cmd", 'User')
}
```

验证：新开终端执行 `git --version`，应输出 `git version 2.54.0.windows.1`。

### 4.2 必须修复：Godot 导出模板缺失

`%APPDATA%\Godot\export_templates` 为空目录。E10 Build & Release 无法执行
`--export-release`。需在 Godot 4.5.1 编辑器中安装匹配版本的 Export Templates
（编辑器菜单「编辑器 → 管理导出模板」）。E0/E1/E2 不受影响，但必须在 E10 前完成。

### 4.3 环境阻塞：Godot runtime 模式崩溃

在本机以非编辑器模式运行任何 Godot 项目（含已有的 `first_2d`）都会段错误
（`CrashHandlerException: signal 11`，退出码 `-1073741819`），发生在启动早期，
与项目内容无关；`--headless --editor` 模式正常。

- 影响：E9 运行时验证、E10 导出后的冒烟测试目前无法在本机执行。
- 已排除：项目配置、脚本内容、渲染驱动 `dummy`、音频驱动 `Dummy`。
- 待办：升级/重装 Godot 4.5.1 或检查显卡驱动，需在 E9 前解决。

### 4.4 待确认项

| 编号 | 事项 | 影响 | 建议 |
| --- | --- | --- | --- |
| Q1 | CI 平台（GitHub Actions / Gitee / 仅本地脚本） | E0-T09 | 仓库尚无 remote，建议先本地脚本 + 预留 CI 配置 |
| Q2 | 现有文档是否迁入 `docs/` 子目录 | E0-T01 目录规范 | 会移动当前打开的文档，需你确认 |
| Q3 | Python 是否锁 3.13（生态最稳）或直接用 3.14.2 | 依赖 wheel 可用性 | 先用 3.14.2，lockfile 冲突再降 3.13 |

## 5. 相关文档

- [完整开发计划细分/E0.md](../../完整开发计划细分/E0.md)（T02 要求、目录、DoD）
- [实施蓝图.md](../../实施蓝图.md)（§2 架构、§25 ADR 清单）
