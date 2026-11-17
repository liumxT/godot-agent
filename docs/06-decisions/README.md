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
| Godot 导出模板 | 4.5.1.stable（已安装，2026-11-17） | `%APPDATA%\Godot\export_templates\4.5.1.stable` | 可用（含 Windows/Linux/Web 模板） |

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

### 4.2 Godot 导出模板（已安装）

`%APPDATA%\Godot\export_templates\4.5.1.stable` 已含完整模板（`version.txt` = `4.5.1.stable`，
含 `windows_release_x86_64.exe` 等）。E10 Build & Release 可执行 `--export-release`，
只需届时提供 `export_presets.cfg`（E10 交付物）。

### 4.3 Godot runtime 启动崩溃（已恢复，根因未确证）

首次以非编辑器模式运行任何项目时出现 `CrashHandlerException: signal 11`
（退出码 `-1073741819`），发生在打印版本号之前；同一二进制的 `--headless --editor`
模式始终正常。崩溃前唯一可捕获的错误是 `Could not create directory: 'user://logs'`。

排查结论（2026-11-17）：

| 假设 | 验证方式 | 结果 |
| --- | --- | --- |
| 安装路径含中文 | 同二进制复制到纯 ASCII 路径运行 | 复制件可运行，但原路径随后也恢复 |
| 项目路径含中文 | ASCII 二进制 + 中文项目路径 | 正常，非病因 |
| 工作目录含中文 | 中文 cwd + ASCII 项目 | 正常，非病因 |
| 可执行文件损坏 | 两处文件 SHA256 对比 | 完全一致 |
| 目录链接 / ADS / ACL 差异 | 属性、Stream、Get-Acl | 无差异 |
| 目录名以 `.exe` 结尾 | 复制到同名目录 | 正常，非病因 |

多次运行后原路径自行恢复，随后连续 3 次运行均为 `exit 0`，未再复现。
**判定：与本项目代码无关，属于首次运行状态问题（`user://logs` 缺失 / 首次缓存初始化）。**

应对措施：

- 保留 ASCII 安装路径，降低路径类工具的偶发风险。
- E9 前增加 runtime 冒烟检查（`--headless` 跑空场景 + 固定退出码）。
- 若 E9 阶段复现，再升级或重装 Godot 4.5.1 并采集 WER 事件。

排查期间出现过的 Godot 弹窗（均已定位，非本项目缺陷）：

| 弹窗 | 来源 | 处理 |
| --- | --- | --- |
| `CrashHandlerException: signal 11` 崩溃对话框 | 复现崩溃时反复以 GUI 模式启动 Godot | 崩溃已自行消失；改用 `--headless` |
| `Error: Can't run project: no main scene defined` | 排查用的空测试工程以非编辑器模式运行 | 测试工程已删除（`C:\GodotTest`、`D:\应用程序\Test` 等） |

当前状态：`apps/godot-plugin` 以 `--headless --editor --quit` 运行，插件正常
启用/停用，退出码 `0`，无报错。

### 4.4 待确认项

| 编号 | 事项 | 影响 | 建议 |
| --- | --- | --- | --- |
| Q1 | CI 平台（GitHub Actions / Gitee / 仅本地脚本） | E0-T09 | **已定**：GitHub Actions + 本地同源脚本，见 [ci.md](../03-development/ci.md) |
| Q2 | 现有文档是否迁入 `docs/` 子目录 | E0-T01 目录规范 | 会移动当前打开的文档，需你确认 |
| Q3 | Python 是否锁 3.13（生态最稳）或直接用 3.14.2 | 依赖 wheel 可用性 | 先用 3.14.2，lockfile 冲突再降 3.13 |

## 5. 相关文档

- [完整开发计划细分/E0.md](../../完整开发计划细分/E0.md)（T02 要求、目录、DoD）
- [实施蓝图.md](../../实施蓝图.md)（§2 架构、§25 ADR 清单）
