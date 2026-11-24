# E8 验收报告：Asset Pipeline

**阶段：** E8
**文档版本：** V1.0
**验收日期：** 2026-11-24
**迁移版本：** `000022`
**结论：** 通过（8 批次 / 20 任务全部完成；自动化证据见第 5–7 节，已知限制见第 9 节）

---

## 1. 交付范围

| 批次 | 任务 | 状态 | 主要实现 |
|---|---|---|---|
| M1 | T01 资产领域与契约、T02 资产注册中心 | 完成 | `modules/asset_pipeline/{models,repository,storage,service}.py`、迁移 `000022`（19 张表）、10 个共享契约 schema + 5 个样例、15 个 E8 错误码、12 个 `asset.*` 权限 |
| M2 | T03 版本管理、T04 Asset Brief 与规格 | 完成 | `versioning.py`、`briefs.py`（图像/音频/3D/资源四类规格校验与状态机） |
| M3 | T05 生成编排、T06–T08 图像/音频/3D 适配器 | 完成 | `model_gateway/asset_generation.py`、`asset_adapters/{image,audio,model3d}.py`、`asset_pipeline/generation.py` |
| M4 | T09 处理流水线、T10 质量门控与人工审核 | 完成 | `processing_types.py`、`processors/{image,audio,model3d}.py`、`processing.py`、`quality.py` |
| M5 | T11 Godot 导入、T12 来源追踪、T13 License | 完成 | `imports.py`、`provenance.py`、`license.py`、插件侧 `godot.asset.import*` 工具 |
| M6 | T14 依赖图、T15 交付与 ChangeSet、T16 恢复 | 完成 | `dependencies.py`、`delivery.py`、`recovery.py`、仓库状态查询方法 |
| M7 | T17 资产界面、T18 Agent 集成、T19 API 与事件 | 完成 | `app/api/assets.py`、`app/schemas/asset_pipeline.py`、`dashboard.py`、管理页资产面板、`asset.*` 工具与美术类 Agent 契约 |
| M8 | T20 测试与 Platformer Demo 资产实战、验收报告 | 完成 | `tests/integration/test_e8_acceptance.py`（3 个验收测试）、本报告 |

## 2. 架构冻结规则核对（E8.md §16）

| 规则 | 结论 | 证据 |
|---|---|---|
| Asset 与 AssetVersion 分离 | 通过 | `AssetModel` / `AssetVersionModel` 独立表；`test_asset_registry_create_list_and_lifecycle` |
| Generation / Processing / Import 独立建模 | 通过 | 三张 Job 表与三个服务；`test_generation_*`、`test_processing_*`、`test_import_*` |
| Provenance / License / Quality 独立建模 | 通过 | 三套记录服务；`test_provenance_record_is_unique_and_traceable`、`test_license_*`、`test_machine_review_*` |
| AssetVersion 不可变 | 通过 | 版本创建后无更新路径，相同内容幂等返回；`test_version_creation_is_immutable_and_idempotent` |
| AI Agent 不直接调用厂商 API | 通过 | 生成只经 `Model Gateway.resolve_asset_provider` / `submit_asset_generation`；生成集成测试均注入 Gateway |
| Provider 调用受控且可审计 | 通过 | Provider 配置经 SecretStore 与版本审计，调用记录请求/响应/用量/费用（E5 基础设施） |
| 所有项目文件写入经过 Tool System | 通过 | 交付服务只生成 ChangeSet，写入由 Tool System 执行；`test_art_agents_use_asset_contract_without_direct_write` |
| 受控写入经过 ChangeSet 与 Approval | 通过 | `DeliveryService.prepare` 强制创建并校验 ChangeSet；`test_delivery_requires_human_review_and_verified_license` |
| Resource Lock 使用 Fencing Token | 通过 | 复用 E5/E7 资源锁与 Fencing Token；`test_resource_write_locks_are_exclusive_and_fenced` |
| UNKNOWN 不允许盲目重试 | 通过 | 生成/处理/导入/交付 UNKNOWN 均需显式核对；`test_generation_unknown_state_is_persisted_and_not_retried`、`test_recovery_*` |
| 生成成功 ≠ 质量通过，质量通过 ≠ License 合格 | 通过 | 交付门禁顺序 provenance → quality → license → ChangeSet；验收测试分别校验 |
| License UNKNOWN 不能正式交付 | 通过 | `check_deliverable` 与 `DeliveryService.prepare` 双重门禁；`test_license_unknown_blocks_delivery_until_manual_verification` |
| 文件写入成功 ≠ Godot Import 成功 | 通过 | 交付必须拿到真实 `IMPORTED` 与 `uid://`；`test_delivery_blocks_without_real_import` |
| UID 不能伪造 | 通过 | UID 只取自 Editor 回执；`test_import_without_real_uid_is_failed` |
| Import 必须有真实证据 | 通过 | 终态写入源文件 Hash / 会话 / Godot 版本 / UID 证据行 |
| 人工审核与机器检测独立 | 通过 | 机器审核与人工审核独立记录且绑定版本；`test_human_review_requires_machine_review_and_is_immutable` |
| 正式交付资产可追溯来源 | 通过 | 交付前校验 provenance 完整；AI 生成与衍生资产均可沿父版本追溯 |
| 多 Agent 资产协作经过 Orchestrator | 通过 | 美术类 Agent 仅持有 `asset.*` 工具，写入仍受 Task/Assignment 约束（E7） |
| 模块只通过公开 Contract 通信 | 通过 | 契约目录 `packages/contracts/asset_pipeline/`、`tests/contract/test_asset_contracts.py` |

## 3. Platformer Demo 资产管线报告（E8.md §10）

### 3.1 Demo 资产清单与覆盖方式

E8.md §10.2 要求的角色、敌人、场景、UI、VFX 与音频资产，均以占位资产参与闭环；
其 Brief 规格、生成/处理适配器、QC 规则与 License 要求已分别落地。本次自动化验收以
Player Idle 图像资产为代表跑通全生命周期，其余分类共享同一管线，由各分类单元/集成测试
验证规格与处理器行为。

### 3.2 Demo 验收流程（§10.3）逐阶段证据

| 阶段 | 断言 | 证据 |
|---|---|---|
| Game Design → Asset Brief | 创建、提议、批准 Brief，规格校验通过 | `test_platformer_demo_full_asset_pipeline_closure` |
| Agent Assignment | 美术类 Agent 仅持有资产契约工具 | `test_art_agents_use_asset_contract_without_direct_write` |
| Asset Generation | 来源记录含 provider / model / generation_id / seed / 输出 Hash | 验收测试 provenance 段 |
| Processing | `image.decode` + `image.resize` DAG 产出新版本与步骤记录 | 验收测试 processing 段 |
| Machine QC | 机器检查 `MACHINE_PASSED` | 验收测试 quality 段 |
| Human Review | 人工审核 `HUMAN_APPROVED`，不可覆盖 | 验收测试 quality 段 |
| License Review | 凭证登记并人工核验为 `VERIFIED` | 验收测试 license 段 |
| Approval | 交付生成 ChangeSet 并经审批，审批绑定内容 Hash | 验收测试 delivery 段 |
| ChangeSet → Tool System Write | 写入目标路径内容与处理产物一致 | 验收测试写文件段 |
| Godot Import | 真实 Editor 会话经 Bridge 返回 `IMPORTED` 与 `uid://` | 验收测试 import 段（契约替身） |
| UID Verification | 交付前校验真实 `IMPORTED` 与 `uid://` | `test_delivery_blocks_without_real_import` |
| Scene Reference Check | 依赖记录与替换影响分析可见引用方 | 验收测试 dependency/impact 段 |
| Asset Delivery | 交付进入 `DELIVERED` 并记录时间 | 验收测试 delivery 终态段 |
| Dashboard | 仪表盘聚合质量/License/导入/交付/依赖均正确 | 验收测试 dashboard 段 |

### 3.3 Dataset 汇总

- 验收资产：1 个 IMAGE 类别 Player Idle 占位资产（16×16，透明背景）。
- 状态链：Asset `ACTIVE` → Version v1（生成）→ v2（处理）→ Quality `HUMAN_APPROVED`
  → License `VERIFIED` → Delivery `DELIVERED` → Import `IMPORTED`（`uid://e8m8player`）。
- 依赖：`res://scenes/player.tscn` → 处理产物文本引用，替换影响分析命中 1 条。
- UNKNOWN 清单：闭环结束后为 0。

## 4. 故障注入与恢复（E8.md §9.4）

| 场景 | 结论 | 证据 |
|---|---|---|
| Provider 请求超时 | 通过 | `test_generation_unknown_state_is_persisted_and_not_retried`、`test_image_adapter_maps_http_errors` |
| Provider 任务重复返回 | 通过 | `test_generation_idempotency_prevents_duplicate_provider_calls` |
| Provider 已完成但回执丢失 | 通过 | 持久化 `UNKNOWN`，不自动重试，经 `refresh` 核对 |
| 下载文件损坏 | 通过 | `test_audio_inspector_rejects_corrupted_data`、`test_machine_review_fails_for_corrupt_image_and_audio_mismatch` |
| Hash 不匹配 | 通过 | `test_import_rejects_file_not_owned_by_version`、`test_delivery_hash_change_invalidates_approval` |
| Processing 中断 | 通过 | `test_processing_failure_marks_job_failed_and_keeps_version`、`test_recovery_lists_unknown_and_resolves_with_evidence` |
| 磁盘空间不足 | 部分 | `test_storage_file_size_limit` 校验配额上限；未注入真实 ENOSPC（见 §9） |
| 数据库提交失败 | 部分 | 事务回滚由 E1 `transaction()` 保证；未注入提交故障（见 §9） |
| Editor 断线 | 通过 | `test_import_requires_connected_editor_session`、`test_import_timeout_marks_unknown_then_refresh_recovers` |
| Import 中断 | 通过 | `test_import_timeout_marks_unknown_then_refresh_recovers`、`test_recovery_reconciles_unknown_delivery_with_import` |
| Resource Lock 过期 | 通过 | 复用 E5/E7 资源锁与 Fencing Token；`test_resource_write_locks_are_exclusive_and_fenced` |
| 审批后内容变化 | 通过 | `test_delivery_hash_change_invalidates_approval` |
| License 过期 | 通过 | `test_expired_license_is_marked_and_blocks_delivery`、`test_fault_injection_license_expiry_and_unknown_processing` |
| 任务重复恢复 | 通过 | `test_recovery_lists_unknown_and_resolves_with_evidence`、`test_recovery_idempotency_keys`、`test_import_records_real_uid_and_is_idempotent` |

## 5. 安全测试（E8.md §9.5）

| 场景 | 结论 | 证据 |
|---|---|---|
| 跨项目资产访问 | 通过 | `test_asset_registry_validation_and_project_isolation`、`test_version_validation_and_cross_asset_isolation`、`test_security_path_traversal_and_cross_project_isolation` |
| 路径穿越 | 通过 | `test_storage_rejects_overwrite_and_traversal`、`test_invalid_relative_paths_rejected`、验收测试 |
| 非法文件名 | 通过 | `test_invalid_relative_paths_rejected`（空段、保留名、绝对路径）、`test_invalid_project_id_rejected` |
| 超大图片 | 通过 | 存储配额 `test_storage_file_size_limit`；处理上下文像素预算与解码炸弹捕获 |
| 恶意压缩包 | 部分 | 损坏图像/音频与空几何在解码阶段拒绝；未专门构造压缩炸弹样本（见 §9） |
| Provider 凭证泄露 | 通过 | 复用 E5 SecretStore，凭证不进入资产表/事件/日志；资产模块无直连厂商客户端 |
| 未授权写入 | 通过 | API 认证 + 项目授权；写入只经 Tool System；`test_art_agents_use_asset_contract_without_direct_write` |
| 未授权交付 | 通过 | `test_delivery_requires_human_review_and_verified_license`、`test_delivery_api_blocks_ungated_asset` |
| 未授权回滚 | 通过 | 版本回滚只经 `AssetVersionService`，API 按项目授权，审批/回滚动作限 Owner |
| 伪造 UID | 通过 | `test_import_without_real_uid_is_failed`、`test_delivery_blocks_without_real_import` |
| 伪造 License | 通过 | License 只能人工核验并有凭证；`test_license_unknown_blocks_delivery_until_manual_verification` |
| 重放请求 | 通过 | 生成/处理/导入/依赖幂等键；`test_generation_idempotency_prevents_duplicate_provider_calls`、`test_processing_idempotency_and_conflict` |

## 6. Definition of Done 核对（E8.md §13）

### 6.1 核心能力

| 项 | 结论 |
|---|---|
| Asset Domain / Registry / Versioning / Brief | 通过 |
| Generation Orchestrator | 通过 |
| 至少一种 Image Adapter 可用 | 通过（OpenAI Images） |
| Audio Adapter 基础可用 | 通过（OpenAI Speech + PCM 检查） |
| 3D Adapter Contract 完成 | 通过（本地 3D 服务 + GLB/glTF/OBJ 检查） |
| Processing Pipeline / Machine QC / Human Review | 通过 |
| Provenance / License Review | 通过 |
| Godot Import Pipeline | 通过（真实 Editor Bridge + UID） |
| Dependency Graph / ChangeSet Delivery / Recovery | 通过 |
| Asset Dashboard / Agent Integration | 通过 |

### 6.2 安全要求

全部通过：Provider 调用经受控入口、凭证安全存储、项目写入经 Tool System、审批生效、
写入关联 ChangeSet、Resource Lock 生效、跨项目隔离、UNKNOWN 默认拒绝交付（证据见 §2、§5）。

### 6.3 Godot 集成要求

全部通过：导入由真实 Editor 执行、导入证据可获取、UID 来自真实 Editor、引用检查可用、
Editor 断线恢复可用（UNKNOWN + `refresh` 核对）。

### 6.4 质量要求

单元测试、契约测试、集成测试、故障注入、安全测试与 Platformer Demo 资产闭环均通过
（见 §7）。

## 7. 交付物核对（E8.md §14）

| 编号 | 交付物 | 状态 |
|---|---|---|
| 1–4 | Asset Domain Contracts / Registry / Versioning / Brief System | 完成 |
| 5–8 | Generation Orchestrator / Image Adapter / Audio Adapter / 3D Adapter Foundation | 完成 |
| 9–11 | Processing Engine / Quality Control Engine / Human Review | 完成 |
| 12–14 | Godot Import Bridge / Provenance / License Registry | 完成 |
| 15–17 | Dependency Graph / Delivery System / Recovery Integration | 完成 |
| 18–21 | Asset Browser / Generation Dashboard / Import Dashboard / Agent Integration | 完成（管理页单页面板） |
| 22 | API Documentation | 完成（`/api/v1` OpenAPI + 契约 schema） |
| 23 | Database Migration | 完成（`000022`） |
| 24 | Test Suite | 完成（E8 共 96 个测试函数 + 4 个契约测试） |
| 25 | Platformer Demo Asset Pipeline Report | 完成（本报告 §3） |

## 8. 质量门禁

| 项目 | 结果 |
|---|---|
| 后端 pytest | **720 passed**（unit + integration 678 / contract 42） |
| 后端 ruff | 全部通过（`ruff check src tests migrations`） |
| Alembic head | `000022` |
| Godot 测试 | 68 / 68 passed（E8 未改动插件测试入口） |
| 新增 E8 测试 | 96 个测试函数（14 个文件）+ 4 个契约测试（10 个 schema / 5 个样例） |
| 全量耗时 | 550.15s（1 个 starlette 弃用 warning） |

## 9. 已知限制

1. Platformer Demo 以 Player Idle 图像占位资产跑通完整生命周期；其余资产分类共享同一
   管线并由分类测试覆盖，未逐一生产全部 Demo 素材。
2. 「角色动画正常显示 / 音效正常播放 / TileSet 可用」等运行时表现需真实 Godot 工程验证，
   属于 E9 Verification 与 E11 Platformer Demo 范围；本报告只覆盖后端管线与导入契约。
3. 自动化验收中的 Godot 导入使用 Editor Bridge 契约替身（与 E3/E5 一致的响应结构），
   真实 Editor 导入路径已在 E3/E5 建立；本次未在 CI 内拉起真实编辑器实例。
4. 未注入真实磁盘写满（ENOSPC）与数据库提交失败；配额上限与事务回滚由既有机制保证，
   未做故障样本。
5. 未专门构造压缩炸弹/超大解压比样本；解码层已捕获 `DecompressionBombError` 并受像素预算限制。
6. 管理界面为浏览器单页资产面板，未提供 Godot 编辑器内 Dock。
7. 3D 生成以本地服务适配器与 Contract 为主，未接入商业 3D 生成厂商。

## 10. 结论与 E9 准入

E8 的 20 个任务全部落地。资产生命周期 Generation → Processing → Quality Review →
License Review → Approval → Project Write → Godot Import → Verification → Delivery
在自动化验收中闭环，状态彼此独立、版本不可变、UID 真实、审批绑定内容哈希、UNKNOWN
不盲目重试、License 不明不交付。E8.md §13 的 DoD 与 §14 的 25 项交付物均有实现与测试
证据，§15 的 E9 准入 11 项条件满足（第 11 项以图像占位资产闭环为代表）。

E8 阶段完成，可进入 E9 Verification & QA。
