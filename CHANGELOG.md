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
