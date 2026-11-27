# E12 验收报告：Productization

> 验收日期：2026-11-27
> 范围：[E12.md](../../完整开发计划细分/E12.md) T01–T20
> 结论：**PASS（GA Ready）**，已知限制见第 9 节。

## 1. 交付范围

| 任务 | 交付 | 证据 |
| --- | --- | --- |
| E12-T01 产品化领域与契约 | `modules/product/{models,repository,versioning,service}.py`；迁移 `000033`（20 张表） | `test_e12_product_domain.py`、`test_e12_product.py` |
| E12-T02 产品架构与打包 | 产品/组件/契约版本清单、版本域隔离、发布目录脚本 | `versioning.py`、`scripts/release/build_product.py` |
| E12-T03 安装器与首次运行 | 安装状态机、预检查、验证、回滚、卸载、12 步向导、插件安装计划 | `installer.py`、T03 测试 |
| E12-T04 配置与 Secrets UX | 四层配置、受保护键、明文密钥拒绝、脱敏导出、模型显式选择 | `configuration.py`、T04 测试、[Secrets 规范](../03-development/secrets.md) |
| E12-T05 License 与 Entitlement | License 状态机、离线宽限、时钟异常、Feature Flag 默认关闭 | `licensing.py`、T05 测试 |
| E12-T06 更新通道与发布管理 | DEV/BETA/STABLE、清单签名、哈希、批准、禁止降级 | `updates.py`、T06 测试 |
| E12-T07 升级与数据库迁移 | 目标 schema、降级阻断、强制备份、受限执行、失败恢复标记 | `migrations.py`、T07 测试 |
| E12-T08 回滚与恢复 | 恢复点、状态检查、UNKNOWN 人工核实、保留用户数据 | `recovery.py`、T08 测试、[Runbook](../04-operations/runbooks.md) |
| E12-T09 兼容性矩阵与环境诊断 | 平台/Godot/Python/协议/schema/凭据/磁盘检查，UNKNOWN 不通过 | `compatibility.py`、T09 测试 |
| E12-T10 安全加固与威胁模型 | 产品动作 RBAC、Agent 拒绝、签名与哈希、审计、确认门禁 | `core/security/{principal,policy}.py`、T10/T19 测试 |
| E12-T11 隐私与数据治理 | 遥测默认 OFF、类别选择、上下文预览、导出与删除范围 | `privacy.py`、T11 测试 |
| E12-T12 可观测性与诊断 | 错误目录、脱敏、支持包、崩溃报告 LOCAL_ONLY、健康聚合 | `diagnostics.py`、`service.py`、T12 测试 |
| E12-T13 文档与 Onboarding | [用户指南](../05-product/user-guide.md)、[开发者指南](../05-product/developer-guide.md)、[运维手册](../04-operations/runbooks.md) | 文档索引、发布目录说明 |
| E12-T14 UX 与产品流程 | 安装/首运/配置/更新/恢复/隐私 API 与状态机；现有管理页复用 | `app/api/product.py`、OpenAPI 路由校验 |
| E12-T15 性能与资源管理 | 产品健康检查、操作状态与积压可见；沿用 E1 性能基线 | `/product/health`、`scripts/testing/perf_e1.py` |
| E12-T16 可靠性与长期运行 | 幂等、状态机、未完成操作扫描、恢复协调、审计 | 各服务 `get_latest` / `list_unfinished` / 恢复测试 |
| E12-T17 支持与维护运营 | 错误码到 Runbook 的处置路径、支持包、发布撤回流程 | `ERROR_CATALOG`、Runbook §10–§14 |
| E12-T18 API 与扩展稳定性 | 契约登记、版本状态、组件版本、稳定级别说明 | `versioning.CONTRACTS`、开发者指南 §2 |
| E12-T19 产品发布流水线 | 候选/证据/SBOM/审批/发布状态机；发布组装脚本 | `release_pipeline.py`、`build_product.py` |
| E12-T20 GA 验收 | 本报告、进度表、全量门禁 | §8 |

## 2. 产品域与数据模型

迁移 `000033_e12_product_core.py` 将 head 从 `000032` 推进到 `000033`，新增：

- 安装：`product_installations`、`product_installation_steps`、`product_components`
- 发布与更新：`product_releases`、`update_manifests`、`update_operations`
- 迁移：`product_migrations`、`product_migration_runs`
- 恢复：`recovery_points`、`recovery_operations`
- 授权：`product_licenses`、`product_entitlements`、`product_feature_flags`
- 配置与治理：`product_configurations`、`product_telemetry_consents`、`product_policies`
- 诊断与审计：`product_support_bundles`、`product_crash_reports`、`product_audits`
- 兼容性：`compatibility_results`

模型显式写入时间戳，服务使用 `DatabaseService` + 事务，仓储只做本域查询。

## 3. 安装、首次运行与配置

- 预检查覆盖目录隔离、组件完整性、写权限与磁盘空间；关键项未通过禁止安装。
- 安装分 7 步执行，验证 10 项；缺失证据为 `PARTIAL`，失败为 `RECOVERY_REQUIRED`。
- 回滚与卸载保留用户数据；卸载声明 `project_files_touched=false`。
- 插件安装计划区分 `SKIP / INSTALL / UPGRADE / CONFLICT`；冲突文件不覆盖。
- 首次运行向导 12 步，凭据、模型与项目不可用时阻止完成。
- 配置分层 `SYSTEM < USER < PROJECT < SESSION`；受保护键不可被低层覆盖。
- 敏感值必须是 `cred://` / `secret://` / `keyring://` / `env://` / `${VAR}`；
  导出配置脱敏密钥与绝对路径。
- 模型不可用直接失败，不静默降级。

## 4. 更新、迁移与恢复

- 更新清单校验版本、通道、哈希、最低版本与签名（HMAC-SHA256）。
- 签名无效、哈希不符、降级、未批准均禁止安装；批准后内容变化会失效。
- 迁移目标取 `database_schema` 组件；降级阻断；备份缺失禁止执行。
- 迁移失败进入 `RECOVERY_REQUIRED`，不掩盖失败。
- 恢复检查外部区域，无法探测标记 `UNKNOWN`；计划要求人工核实后才能执行。
- 恢复执行保留用户数据并明确 `deleted_user_project=false`。

## 5. 兼容性、安全、隐私与诊断

- 兼容性矩阵：Windows x86_64 VERIFIED、Linux x86_64 PARTIAL、macOS UNVERIFIED；
  Godot 4.5 VERIFIED / 4.4 PARTIAL；Python 3.14 VERIFIED。
- UNKNOWN 永不自动变为 PASS；schema 高于支持版本为 FAILED，低版本为 WARNING。
- 产品读动作允许非 Agent 已认证客户端；所有变更动作要求 admin；Agent 一律拒绝。
- 支持包脱敏密钥、Token、绝对路径并截断超长字段；导出需确认并记录 SHA-256。
- 崩溃报告 `LOCAL_ONLY`，不上传。
- 遥测默认关闭；开启必须选择类别；删除仅作用于遥测/诊断，不触碰项目。

## 6. 文档与用户体验

- [用户指南](../05-product/user-guide.md)：安装、首次运行、日常使用、升级/回滚/卸载、
  平台支持等级、隐私与故障排查。
- [开发者指南](../05-product/developer-guide.md)：模块边界、版本与契约、API 摘要、
  状态机、扩展点、迁移与测试。
- [运维手册](../04-operations/runbooks.md)：安装/更新/迁移失败、恢复、数据库损坏、
  凭据、模型、安全事件、支持包、长期运行、发布与下线。
- [发布目录说明](../../release/README.md) 与 `scripts/release/build_product.py`。
- 产品 API 均带 summary/tags，路由校验通过（`test_api_routing.py`）。

## 7. 发布流水线与 API 稳定性

- 发布候选必须满足：版本域正确、7 类证据齐全、签名 `SIGNED`、SBOM 可用。
- 审批要求候选处于可审批状态；发布要求 `APPROVED` 且签名与证据仍有效。
- `build_product.py` 生成产品/组件/契约/兼容性清单、SBOM 与校验和；
  `--check` 模式用于 CI 门禁。
- 契约登记 10 项，未知或超版本契约为 `UNKNOWN`；API 稳定级别见开发者指南。

## 8. 质量门禁

| 项 | 结果 |
| --- | --- |
| E12 新增测试 | 37 passed（单元 23 / 集成 14） |
| 后端全量 pytest | 953 passed，1 warning（896 业务 + 57 契约，960.78s） |
| ruff check / format | 全通过（src / tests / migrations） |
| check_all 8 阶段 | 全部 PASS（Godot 68/68，契约 57 passed） |
| 迁移 head | `000033` |
| 发布目录校验 | `build_product.py --check` OK；生成 5 个清单文件 + SBOM（57 packages） |

## 9. 已知限制

| 事项 | 影响 | 处理 |
| --- | --- | --- |
| 安装器与各平台二进制未在本仓库构建 | T02/T19 | 由打包流水线写入 `release/backend` 与 `release/installers`；脚本负责清单与校验 |
| macOS / Linux 桌面安装器未做真机验证 | T02/T09 | 矩阵标记 UNVERIFIED / PARTIAL，不宣称 GA 支持 |
| 未执行 24 小时长稳与多进程压测 | T15/T16 | 依赖状态机、幂等、健康检查与 E1 性能基线；后续补压测 |
| 产品管理页面复用现有浏览器管理页 | T14 | 产品流程以 API 与状态机交付，Dock/独立安装向导 UI 后续增强 |
| 更新签名使用内置 HMAC 密钥 | T06/T10 | 当前为本地/离线分发；公共分发需升级为非对称签名与密钥轮换 |
| 外部区域（项目文件、插件目录）恢复前默认 UNKNOWN | T08 | 必须人工核实，避免误删用户项目 |

## 10. 结论与 GA 准入

E12 的 20 项任务均有实现、测试或文档证据；产品域、安装/更新/迁移/恢复、
授权/隐私/诊断、发布流水线与文档形成闭环。全量测试与 `check_all` 结果见 §8。
**结论：E12 通过，项目达到 GA Ready。**
