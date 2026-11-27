# 开发者与集成指南

> 文档目的：说明产品化域（`modules/product`）的边界、版本与契约稳定性、
> 扩展点、数据库迁移和测试方式。
> 适用范围：后端、Godot 插件、安装器与发布流水线开发者。
> 最后更新：2026-11-27（E12-T13 / T18）。

## 1. 分层与模块边界

产品化域位于 `apps/backend/src/modules/product`，只依赖 Core、Infrastructure 与
`DatabaseService`，不直接访问其他业务模块的 Repository。

| 文件 | 职责 |
| --- | --- |
| `models.py` | 20 张产品表与状态常量 |
| `repository.py` | 产品域仓储 |
| `versioning.py` | 产品/游戏版本域、组件版本、契约登记 |
| `compatibility.py` | 兼容性矩阵与环境检查 |
| `installer.py` | 安装状态机、插件安装、首次运行向导 |
| `configuration.py` | 四层配置、受保护键、Secrets 引用校验 |
| `licensing.py` | License / Entitlement / Feature Flag |
| `updates.py` | 更新通道、清单签名、批准与安装 |
| `migrations.py` | 升级计划、备份、受限迁移执行 |
| `recovery.py` | 恢复点、状态检查、恢复计划与执行 |
| `diagnostics.py` | 错误目录、脱敏、支持包与崩溃报告 |
| `privacy.py` | 遥测同意、上下文预览、数据导出与删除 |
| `release_pipeline.py` | 发布候选、证据、SBOM、审批与发布 |
| `service.py` | 信息、能力、健康检查、审计入口 |

API 位于 `app/api/product.py`，请求模型位于 `app/schemas/product.py`。
服务在 `bootstrap/startup.py` 的 `_init_product()` 注册，启动顺序位于 `backup` 之后。

## 2. 版本与契约

- 产品版本：`versioning.PRODUCT_VERSION`，当前 `1.0.0`，版本域 `product`。
- 游戏制品版本：版本域 `game_artifact`。任何跨域比较都会抛 `ValidationFailed`。
- 组件版本：后端、启动器、Godot 插件、API 协议、数据库 schema、Agent 定义、
  工具 Schema、Provider 契约、安装器、产品包与文档。
- 契约登记：`CONTRACTS` 记录契约 ID、版本、摘要与文件路径；
  未知契约或高于支持版本一律返回 `UNKNOWN`，不自动通过。
- API 稳定级别：
  - `STABLE`：`/api/v1/product/*` 的产品信息、健康、兼容性、能力、配置读写。
  - `EXPERIMENTAL`：恢复流程中的外部区域探测与支持包内部结构。
  - 变更必须登记契约并提升版本；破坏性变更需要新增主版本并保留旧版本读取。

数据库 head 为 `000033`（`000033_e12_product_core.py`）。
组件清单中的 `database_schema` 必须与 Alembic head 一致。

## 3. 产品 API 摘要

| 方法与路径 | 说明 | 权限 |
| --- | --- | --- |
| `GET /api/v1/product/info` | 产品、版本域、组件、契约 | 非 Agent 已认证客户端 |
| `GET /api/v1/product/version` | 只读版本信息 | 同上 |
| `GET /api/v1/product/components` | 组件版本 | 同上 |
| `GET /api/v1/product/compatibility` | 兼容性矩阵 | 同上 |
| `GET /api/v1/product/health` | 产品健康聚合 | 同上 |
| `GET /api/v1/product/capabilities` | License 与能力 | 同上 |
| `POST /api/v1/product/installations/preflight` | 安装预检查 | admin |
| `POST /api/v1/product/installations` | 开始安装 | admin |
| `POST /api/v1/product/installations/{id}/verify` | 安装验证 | admin |
| `POST /api/v1/product/installations/{id}/rollback` | 回滚安装 | admin |
| `POST /api/v1/product/plugin/install-plan` | 插件安装计划 | admin |
| `POST /api/v1/product/first-run` | 首次运行向导 | admin |
| `GET/PUT /api/v1/product/configurations` | 分层配置 | 读：非 Agent；写：admin |
| `POST /api/v1/product/licenses` | 登记 License | admin |
| `POST /api/v1/product/licenses/{id}/revoke` | 撤销能力 | admin |
| `POST /api/v1/product/updates/manifests` | 登记更新清单 | admin |
| `POST /api/v1/product/updates/check` | 检查更新 | 非 Agent |
| `POST /api/v1/product/updates/{id}/approve` | 批准更新 | admin |
| `POST /api/v1/product/updates/{id}/install` | 安装更新 | admin |
| `POST /api/v1/product/migrations/plan` | 升级计划 | admin |
| `POST /api/v1/product/migrations/{id}/execute` | 执行迁移 | admin |
| `POST /api/v1/product/recovery-points` | 创建恢复点 | admin |
| `POST /api/v1/product/recovery/{id}/plan` | 恢复计划 | admin |
| `POST /api/v1/product/recovery/{id}/execute` | 执行恢复 | admin |
| `GET /api/v1/product/errors` | 错误码目录 | 非 Agent |
| `POST /api/v1/product/support-bundles` | 生成支持包（需确认） | admin |
| `GET /api/v1/product/support-bundles` | 支持包列表 | admin |
| `POST /api/v1/product/crash-reports` | 本地崩溃报告 | admin |
| `GET/PUT /api/v1/product/privacy/telemetry` | 遥测状态 | 读：非 Agent；写：admin |
| `GET /api/v1/product/privacy/context-preview` | 上下文预览 | 非 Agent |
| `POST /api/v1/product/privacy/delete` | 删除遥测/诊断数据 | admin |
| `GET /api/v1/product/sbom` | SBOM | 非 Agent |
| `POST /api/v1/product/releases` | 创建发布候选 | admin |
| `POST /api/v1/product/releases/{id}/approve` | 审批候选 | admin |
| `POST /api/v1/product/releases/{id}/publish` | 发布 | admin |

变更类产品动作在策略层统一要求 admin；`client_type=agent` 对产品动作一律拒绝。
所有变更写入 `product_audits`，并关联 `client_id` / `session_id`。

## 4. 状态机要点

- 安装：`CREATED → PRECHECK → INSTALLING → VERIFYING → COMPLETED`；
  失败进入 `FAILED` / `PARTIAL` / `RECOVERY_REQUIRED`；回滚进入 `ROLLED_BACK`。
- 更新：`CHECKED → VERIFIED → APPROVED → DOWNLOADED → STAGED → INSTALLING → VERIFYING → COMPLETED`；
  非法签名、哈希不符、降级与未批准禁止推进。
- 迁移：`PLANNED → BACKED_UP → EXECUTING → COMPLETED`；
  失败进入 `FAILED` / `RECOVERY_REQUIRED`，备份是前置条件。
- 恢复：`RECOVERY_DETECTED → STATE_INSPECTION → RECOVERY_PLAN → USER_CONFIRMATION → EXECUTION → VERIFICATION → RECOVERED`；
  外部区域 `UNKNOWN` 必须人工核实，不允许自动收敛为成功。
- 发布：`DRAFT → RELEASE_CANDIDATE → APPROVED → PUBLISHED`；
  `UNSIGNED` 或证据不全禁止审批/发布。

## 5. 扩展点

1. **Provider 适配器**：实现统一请求/响应、流式事件与能力声明；
   不可用能力返回 `UNKNOWN`，禁止静默切换模型。
2. **工具**：在 Tool Registry 登记名称、版本、JSON Schema 与风险等级；
   写工具必须经 ChangeSet，R3+ 必须审批。
3. **Agent / 多 Agent**：Definition 发布后不可变；能力与工具白名单必须已登记。
4. **资产 Provider**：按图像/音频/3D 契约实现，提交结果需可追溯来源。
5. **验证执行器**：输出证据并绑定来源；没有证据的 PASS 会被降级。
6. **构建适配器**：只允许白名单可执行文件与受限环境变量；产物必须可校验哈希。

扩展实现不得绕过产品域直接改写其他模块状态。

## 6. 数据库迁移

1. 新迁移使用顺序号，`down_revision` 指向当前 head。
2. 迁移必须可在空库与已有库上执行；不得依赖隐式 server default。
3. 升级前备份由 `ProductMigrationService` 强制执行。
4. 模型需显式写入 `created_at` / `updated_at`。
5. 同步更新 `versioning.COMPONENTS` 中的 `database_schema` 与
   [数据库规范](../03-development/database.md)。

## 7. 测试

```powershell
cd apps/backend
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m pytest tests/unit/test_e12_product_domain.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_e12_product.py -q
```

全量检查：

```powershell
$env:GODOT_BIN="d:\godot 插件agent\.tools\godot.exe"
.\apps\backend\.venv\Scripts\python.exe scripts\testing\check_all.py
```

E12 测试覆盖：版本域隔离、契约状态、兼容性矩阵（UNKNOWN 不通过）、
安装生命周期与插件冲突、配置分层与明文 Secrets 拒绝、License 宽限/过期/时钟异常、
更新签名与批准、迁移备份与确认、恢复 UNKNOWN 人工核实、支持包脱敏、
遥测默认关闭、发布证据与审批、产品 API 权限。

## 8. 发布

```powershell
python scripts/release/build_product.py --check
python scripts/release/build_product.py --output release
```

脚本生成 `release/manifests`（产品/组件/契约/兼容性）、`release/security/sbom/sbom.json`
与校验和清单；二进制与安装器由各自打包步骤写入对应目录。
发布候选必须带签名、SBOM 与 7 类证据，审批后才能发布。
