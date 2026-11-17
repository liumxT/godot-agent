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
- [配置管理规范](03-development/configuration.md)
- [Secrets 管理规范](03-development/secrets.md)
- [日志规范](03-development/logging.md)
- [错误码与异常规范](03-development/errors.md)
- [CI 与自动化检查](03-development/ci.md)

### 流程与管理

- [开发流程规范](00-project/development-workflow.md)
- [Code Review 规范](00-project/code-review.md)
- [Bug 管理规范](00-project/bug-management.md)
- [E0 测试报告](00-project/e0-test-report.md)
- [E0 验收报告](00-project/e0-acceptance-report.md)

### 技术决策

- [ADR 索引与环境记录](06-decisions/README.md)

## 3. 根目录文档

以下文档暂时保留在仓库根目录（迁移需确认，见
[待确认项 Q2](06-decisions/README.md#44-待确认项)）：

- [实施蓝图.md](../实施蓝图.md)
- [完整开发计划细分/](../完整开发计划细分/)
- [README.md](../README.md)、[CONTRIBUTING.md](../CONTRIBUTING.md)、[CHANGELOG.md](../CHANGELOG.md)

## 4. 写作约定

1. 正文使用中文；文件名使用小写 kebab-case（ADR 除外，保持 `ADR-00x-xxx.md`）。
2. 每份文档开头写清：文档目的、适用范围、最后更新时间。
3. 与代码相关的位置使用相对链接指向真实文件。
4. 模板使用见 [templates/README.md](templates/README.md)。
5. 契约以 [packages/contracts](../packages/contracts/) 为事实源，文档只做解释，不复制 Schema 细节。
