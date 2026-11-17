# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

## [Unreleased]

### Added

- 技术决策记录 ADR-001（Backend 语言）、ADR-002（框架与基础库）、ADR-003（Godot 版本基线）。
- Monorepo 基础目录结构。
- 仓库规范：`.gitignore`、`.editorconfig`、`README.md`、`CONTRIBUTING.md`。
- Backend E0 骨架：配置加载、结构化日志、统一错误、生命周期、健康检查。
- Godot Plugin E0 骨架：插件声明、版本校验、状态 Dock 面板。
- Shared Contracts 1.0：请求/响应/错误/事件 Schema、错误码规范、两端共用的样例清单与校验器。
- 数据库基础（E0-T06）：Alembic 迁移、SQLite 连接 PRAGMA（WAL/外键/超时）、升级前自动备份、失败包装为 `MIGRATION_FAILED`、迁移与 PRAGMA 集成测试、数据库开发规范文档。
- 配置与 Secrets（E0-T07）：配置分组与范围校验（仅回环地址、端口、日志级别、SQLite URL）、`keyring` 系统凭证库访问层与 `redact`、示例配置防泄漏检查、配置与 Secrets 规范文档。
- 日志与异常（E0-T08）：Backend 结构化日志字段对齐（event/component/request_id/correlation_id/error_code）、请求关联 ID 中间件、错误码大写蛇形校验与契约化错误体（含 `retryable` / `correlation_id`）、Godot 插件 JSON 单行日志、日志与错误规范文档。
- CI（E0-T09）：本地一键检查脚本（结构/敏感文件/格式/静态/契约/测试/Godot）、GitHub Actions 双 job 工作流、Markdown + JSON 检查报告、CI 使用说明。
- 工程文档（E0-T10）：10 类文档模板、开发流程 / Code Review / Bug 管理规范、PR 与 Issue 模板、文档索引。
- E0 验收（E0-D12/D13）：E0 测试报告与阶段验收报告；补充生命周期集成测试与数据库目录故障注入测试。
- 技术决策补全（E0-T02）：新增 ADR-004（Primary Database）、ADR-005（本地通信）、ADR-006（测试框架），ADR-001…006 全部 Accepted。
- 打包 spike（E0-T02）：PyInstaller onedir / onefile 构建配置与冒烟脚本、`--migrate` 入口、打包后资源定位（`sys._MEIPASS`）、ADR-007 记录实测体积与启动耗时。
