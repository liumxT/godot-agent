# 开发流程规范（E0-T10）

适用范围：E0 及后续所有阶段的开发任务。

## 1. 流程

```text
需求确认 → 技术设计 → 任务拆分 → 开发实现 → 单元测试
        → Code Review → 集成测试 → 验收 → 合并
```

| 阶段 | 产出 | 责任 |
| --- | --- | --- |
| 需求确认 | 目标与验收标准 | 产品 / 技术负责人 |
| 技术设计 | 模块设计或 ADR | 技术负责人 |
| 任务拆分 | 阶段实施文档（任务含 9 项要素） | 任务负责人 |
| 开发实现 | 代码 + 测试 | 开发者 |
| 单元测试 | 可复现的测试 | 开发者 |
| Code Review | [评审记录](../templates/code-review.md) | 评审人 |
| 集成测试 | `check_all.py` 报告 | 开发者 / CI |
| 验收 | [验收报告](../templates/phase-acceptance.md) | 测试 / 技术负责人 |
| 合并 | 符合 DoD 的提交 | 开发者 |

## 2. 任务必备要素

每项任务必须写清以下 9 项，模板见
[phase-implementation.md](../templates/phase-implementation.md)：

1. 任务 ID。
2. 任务目标。
3. 任务输入。
4. 实施步骤。
5. 代码位置。
6. 前置依赖。
7. 测试要求。
8. 交付物。
9. 验收标准。

缺少任一项的任务不进入开发。

## 3. 分支与提交

遵循 [CONTRIBUTING.md](../../CONTRIBUTING.md)：

- `feature/*` → `develop` → `release/*` → `main`。
- Conventional Commits，一个提交只做一件事。

## 4. 本地检查

提交前必须执行：

```powershell
cd apps/backend
.\.venv\Scripts\python.exe ..\..\scripts\testing\check_all.py
```

要求退出码 `0`；Godot 阶段可为 `SKIP`（本机未安装时）。
检查规则见 [ci.md](../03-development/ci.md)。

## 5. 契约与文档同步

| 变更 | 必须同步 |
| --- | --- |
| 协议字段/事件 | `packages/contracts/` + 两端校验样例 |
| 错误码 | `packages/contracts/errors/` |
| 数据库结构 | 迁移文件 + [data-model 模板](../templates/data-model.md) |
| 架构决策 | ADR |
| 配置项 | `.env.example` + [configuration.md](../03-development/configuration.md) |

## 6. 完成定义（DoD）

- 任务 9 项要素齐全，验收标准全部满足。
- 检查脚本通过，测试可复现。
- 无明文凭证，日志脱敏符合规范。
- 文档、ADR、契约已同步。
- 已通过 Code Review 并合并。

## 7. 文档更新规则

1. 规范类文档（`docs/03-development/`）变更需在 PR 中说明原因。
2. 模板变更视为流程变更，需技术负责人确认。
3. 文档中的文件路径必须指向真实存在的文件。
