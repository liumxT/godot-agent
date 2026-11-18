# 项目进度表

> 更新于 2026-11-18，对应提交 `a0035b2`。
> 阶段划分依据 [完整开发计划细分/](../../完整开发计划细分/)（E0–E12）。
> 单阶段细节见 [E0 验收报告](e0-acceptance-report.md) 与 [E0 测试报告](e0-test-report.md)。

## 1. 总体进度

| 项 | 状态 |
| --- | --- |
| 当前阶段 | **E1 Backend Core（待启动）** |
| 阶段进度 | 1 / 13 完成（E0） |
| 仓库 | `github.com/liumxT/godot-agent`，分支 `main` |
| CI | GitHub Actions 双 job 通过（[run 44065613603](https://github.com/liumxT/godot-agent/actions/runs/44065613603)） |
| 后端测试 | 52 passed（contract / integration / unit），ruff 全通过 |

## 2. 阶段总览

| 阶段 | 名称 | 状态 | 说明 |
| --- | --- | --- | --- |
| E0 | Project Foundation | ✅ 已通过 | 2026-11-17 验收，条件 C1–C4 全部关闭 |
| E1 | Backend Core | ⏳ 下一阶段 | 14 个任务，见 §5 |
| E2 | Backend Services | ⬜ 未开始 | 依赖 E1 |
| E3 | Godot Integration | ⬜ 未开始 | 依赖 E1/E2 |
| E4 | Project & Workflow Systems | ⬜ 未开始 | |
| E5 | AI & Tool Foundation | ⬜ 未开始 | |
| E6 | Agent Runtime | ⬜ 未开始 | |
| E7 | Multi-Agent & Game Development | ⬜ 未开始 | |
| E8 | Asset Pipeline | ⬜ 未开始 | |
| E9 | Verification & QA | ⬜ 未开始 | 需补 Godot runtime 冒烟检查 |
| E10 | Build & Release | ⬜ 未开始 | 导出模板已就绪，见 §6 |
| E11 | Platformer Demo | ⬜ 未开始 | 系统级集成验收 |
| E12 | Productization | ⬜ 未开始 | 含存量文档归档 |

## 3. E0 任务明细（已完成）

| 任务 | 内容 | 关键交付物 |
| --- | --- | --- |
| E0-T01 | 仓库与工程规范 | Monorepo 目录、`.gitignore` / `.gitattributes` / `.editorconfig`、README / CONTRIBUTING / CHANGELOG |
| E0-T02 | 技术栈与运行环境 | [ADR-001…007](../06-decisions/README.md)、环境版本清单、打包 spike |
| E0-T03 | Backend 骨架 | FastAPI 入口、lifespan、配置加载、健康检查、统一异常与日志入口 |
| E0-T04 | Godot Plugin 骨架 | `plugin.cfg` / `plugin.gd`、状态面板、重复启用保护、契约探针插件 |
| E0-T05 | Shared Contracts | 协议 1.0 schema（request / response / event / error）、12 个错误码、11 个契约样例 |
| E0-T06 | 数据库规范 | Alembic 基线 `000001`、WAL 等 PRAGMA、升级前备份、[数据库规范](../03-development/database.md) |
| E0-T07 | 配置与 Secrets | 分区配置与校验、`.env.example`、系统凭据库、[配置规范](../03-development/configuration.md) / [Secrets 规范](../03-development/secrets.md) |
| E0-T08 | 日志与异常 | 双端结构化 JSON 日志、`request_id` / `correlation_id`、契约一致的错误体 |
| E0-T09 | CI | [check_all.py](../../scripts/testing/check_all.py) 7 阶段、[GitHub Actions](../../.github/workflows/ci.yml)、[CI 规范](../03-development/ci.md) |
| E0-T10 | 工程文档 | [10 类模板](../templates/README.md)、[开发流程](../00-project/development-workflow.md)、[Code Review](../00-project/code-review.md)、[Bug 管理](../00-project/bug-management.md) |

## 4. 质量与技术基线

| 项 | 状态 / 数值 |
| --- | --- |
| Backend 测试 | 52 passed（pytest，asyncio auto） |
| 契约校验 | 11 个 manifest 用例，Backend 与 Godot 双向验证 |
| Godot 运行 | headless 编辑器模式加载插件、契约探针，`exit 0` |
| 打包（onedir） | 39.1 MB，冷启动到 `/health` 1248 ms，迁移与健康检查通过 |
| 打包（onefile） | 23.4 MB，冷启动 1757 ms，整棵进程树可正常结束 |
| 技术基线 | Godot 4.5.1 / Python 3.14.2 / FastAPI / SQLite（WAL）/ Alembic / PyInstaller 6.22.3 |
| 远程 CI | `Backend checks` + `Godot plugin checks` 通过（ubuntu-24.04） |

## 5. E1 计划（未开始）

| 任务 | 内容 |
| --- | --- |
| E1-T01 | Backend 生命周期管理 |
| E1-T02 | 配置服务实现 |
| E1-T03 | SQLite 数据库服务 |
| E1-T04 | 数据库 Migration 服务 |
| E1-T05 | Repository 基础设施 |
| E1-T06 | 事务管理服务 |
| E1-T07 | 日志服务 |
| E1-T08 | 统一异常处理服务 |
| E1-T09 | 事件基础设施 |
| E1-T10 | Outbox / Inbox 基础机制 |
| E1-T11 | 数据库备份与恢复 |
| E1-T12 | Health Check 健康检查 |
| E1-T13 | 可观测性和诊断 |
| E1-T14 | Core 集成测试和性能验证 |

启动前动作：以 [E1.md](../../完整开发计划细分/E1.md) 为准，先做任务拆解与设计，再进入编码。

## 6. 已知问题与待办

| 事项 | 影响阶段 | 状态 |
| --- | --- | --- |
| Godot runtime 首次启动 `signal 11`，根因未确证，已不再复现 | E9 | 待 E9 增加 runtime 冒烟检查，复现则升级/重装 |
| Godot 4.5.1 导出模板 | E10 | ✅ 已安装（`%APPDATA%\Godot\export_templates\4.5.1.stable`） |
| 无 Python 干净机器上的打包验证 | E10 | 待安装包制作时执行 |
| CI 未覆盖打包冒烟与 Markdown 链接检查 | E10 / E12 | 待补 |
| onefile 便携产物的杀软误报 | E10 | 分发前在目标环境实测 |
| 存量规划文档归档 `docs/` | E12 | 规则已定，E12 执行 |
| Godot 安装路径含中文（建议迁 ASCII） | — | 非阻塞，未执行 |

## 7. 维护规则

1. 每完成一个任务勾选或更新状态，每阶段结束同步本文件与阶段验收报告。
2. 状态符号：`✅ 已完成 / ⏳ 进行中 / ⬜ 未开始 / ⛔ 阻塞`。
3. 新增已知问题或风险时，必须写明影响阶段与处理状态。
4. 阶段验收结论以对应 `docs/00-project/e*-acceptance-report.md` 为准。
