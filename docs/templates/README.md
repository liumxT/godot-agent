# 文档模板

## 1. 模板清单

| 模板 | 用途 | 归档位置 |
| --- | --- | --- |
| [module-design.md](module-design.md) | 模块设计文档 | `docs/02-architecture/` |
| [phase-implementation.md](phase-implementation.md) | 阶段实施文档 | `完整开发计划细分/`（E0 现状）或 `docs/00-project/` |
| [api-design.md](api-design.md) | API / 事件设计 | `docs/05-api/` |
| [data-model.md](data-model.md) | 数据模型与迁移 | `docs/02-architecture/` |
| [adr.md](adr.md) | 技术决策记录 | `docs/06-decisions/` |
| [test-case.md](test-case.md) | 测试用例 | `docs/04-testing/` |
| [bug-report.md](bug-report.md) | Bug 报告 | Issue（`bug` 标签） |
| [code-review.md](code-review.md) | Code Review 记录 | PR 描述 / 评论 |
| [phase-acceptance.md](phase-acceptance.md) | 阶段验收报告 | `docs/00-project/` |
| [release-notes.md](release-notes.md) | 发布说明 | `CHANGELOG.md` 对应版本段 |

## 2. 使用规则

1. 复制模板到归档位置，删除模板中的说明性占位文字。
2. 文件名前缀使用编号或日期，如 `adr-004-database.md`、`2026-11-17-e0-acceptance.md`。
3. 模板中的必填项不得留空；确实不适用时写"不适用"并说明原因。
4. 模板变更属于流程变更，需在 PR 中说明理由。

## 3. 相关流程

- [开发流程规范](../00-project/development-workflow.md)
- [Code Review 规范](../00-project/code-review.md)
- [Bug 管理规范](../00-project/bug-management.md)
