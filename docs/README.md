# 项目文档索引

## 1. 目录职责

| 目录 | 内容 |
| --- | --- |
| `00-project/` | 开发流程、Code Review、Bug 管理、发布流程 |
| `01-product/` | 产品需求、用户故事、验收场景（E1 起） |
| `02-architecture/` | 模块设计、架构图、跨模块约束 |
| `03-development/` | 具体工程规范（数据库、配置、日志、CI 等） |
| `04-testing/` | 测试计划、测试用例集（E1 起） |
| `05-api/` | API / 事件协议说明（契约事实源在 `packages/contracts/`） |
| `06-decisions/` | ADR 与待确认事项 |
| `templates/` | 各类文档模板，复制后填写 |

## 2. 现有文档

### 工程规范

- [数据库规范](03-development/database.md)
- [API 服务规范](03-development/api.md)
- [事件与 Outbox/Inbox](03-development/events.md)
- [健康检查与诊断](03-development/observability.md)
- [配置管理规范](03-development/configuration.md)
- [Secrets 管理规范](03-development/secrets.md)
- [日志规范](03-development/logging.md)
- [错误码与异常规范](03-development/errors.md)
- [CI 与自动化检查](03-development/ci.md)

### 流程与管理

- [项目进度表](00-project/progress.md)
- [开发流程规范](00-project/development-workflow.md)
- [Code Review 规范](00-project/code-review.md)
- [Bug 管理规范](00-project/bug-management.md)
- [E0 测试报告](00-project/e0-test-report.md)
- [E0 验收报告](00-project/e0-acceptance-report.md)
- [E1 测试报告](00-project/e1-test-report.md)
- [E1 验收报告](00-project/e1-acceptance-report.md)
- [E2 安全测试报告](00-project/e2-security-test-report.md)
- [E2 验收报告](00-project/e2-acceptance-report.md)
- [E3 验收报告](00-project/e3-acceptance-report.md)
- [E4 验收报告](00-project/e4-acceptance-report.md)
- [E5 验收报告](00-project/e5-acceptance-report.md)
- [E6 验收报告](00-project/e6-acceptance-report.md)
- [E7 验收报告](00-project/e7-acceptance-report.md)
- [E8 验收报告](00-project/e8-acceptance-report.md)
- [E9 验收报告](00-project/e9-acceptance-report.md)
- [E10 验收报告](00-project/e10-acceptance-report.md)
- [E11 验收报告](00-project/e11-acceptance-report.md)
- [Platformer Demo 交付说明](../demo/platformer/reports/acceptance-report.md)

### 架构设计

- [E1 Backend Core 设计与任务拆解](02-architecture/e1-backend-core-design.md)
- [E2 Backend Services 设计与任务拆解](02-architecture/e2-backend-services-design.md)

### 技术决策

- [ADR 索引与环境记录](06-decisions/README.md)

## 3. 根目录文档

**文档归档规则（2026-11-17 确认）：**

1. 新文档一律创建在 `docs/` 对应子目录，不再新增到仓库根目录。
2. 存量的规划与设计文档暂时保留在根目录，避免批量修改跨文档链接。
3. E12 结束后统一归档到 `docs/`（蓝图与设计说明书 → `02-architecture/`，
   实施计划 → `00-project/`，测试计划 → `04-testing/`，E0–E12 → `00-project/plans/`）。
4. 归档时必须同步更新引用链接，并在 CI 中检查 Markdown 相对链接有效性。

待迁移清单：

- [实施蓝图.md](../实施蓝图.md)
- [Godot AI Agent 完整项目设计说明书.md](../Godot%20AI%20Agent%20完整项目设计说明书.md)
- [Godot AI Agent 完整开发实施计划.md](../Godot%20AI%20Agent%20完整开发实施计划.md)
- [Godot AI Agent 全项目测试与质量保证计划.md](../Godot%20AI%20Agent%20全项目测试与质量保证计划.md)
- [完整开发计划细分/](../完整开发计划细分/)（E0–E12 共 13 份）

根目录长期保留：[README.md](../README.md)、[CONTRIBUTING.md](../CONTRIBUTING.md)、
[CHANGELOG.md](../CHANGELOG.md)。

## 4. 写作约定

1. 正文使用中文；文件名使用小写 kebab-case（ADR 除外，保持 `ADR-00x-xxx.md`）。
2. 每份文档开头写清：文档目的、适用范围、最后更新时间。
3. 与代码相关的位置使用相对链接指向真实文件。
4. 模板使用见 [templates/README.md](templates/README.md)。
5. 契约以 [packages/contracts](../packages/contracts/) 为事实源，文档只做解释，不复制 Schema 细节。
