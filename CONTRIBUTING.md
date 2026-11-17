# 贡献指南

## 1. 分支模型

| 分支 | 用途 |
| --- | --- |
| `main` | 稳定版本，禁止直接提交 |
| `develop` | 日常集成分支 |
| `feature/*` | 新功能 |
| `bugfix/*` | 问题修复 |
| `hotfix/*` | 紧急修复 |
| `release/*` | 发布准备 |

流程：`feature/*` → `develop` → `release/*` → `main`。

## 2. 提交信息

使用 Conventional Commits：

```
<type>(<scope>): <subject>
```

- type：`feat` / `fix` / `refactor` / `test` / `docs` / `chore` / `build` / `ci`
- scope：模块名，如 `backend`、`plugin`、`contracts`、`docs`
- subject：祈使句，不超过 72 字符

示例：`feat(backend): add application factory and health endpoint`

## 3. 提交前检查

1. 不提交密钥、`.env`、本地数据库与构建产物（见 `.gitignore`）。
2. 单元测试通过。
3. 不产生跨模块 Repository 直接访问。
4. 涉及契约变更时，必须同步更新 `packages/contracts/` 并通知两端。

## 4. 评审要求

- 任何进入 `main` 的代码必须经过评审。
- 评审关注：模块边界、状态所有权、错误处理、测试证据。
- 架构级变更必须新增或修订 ADR，不允许在代码中绕过既有约束。

## 5. 完成定义（DoD）

一个任务完成需同时满足：

- 代码与文档已提交。
- 对应测试通过并能复现。
- 无明文凭证。
- 相关 ADR / 契约已同步。
