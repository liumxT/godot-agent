# E10 验收报告：Build & Release

**阶段：** E10
**文档版本：** V1.0
**验收日期：** 2026-11-26
**迁移版本：** `000031`
**结论：** 通过（6 批次 / 20 任务全部完成；自动化证据见第 5–8 节，已知限制见第 10 节）

---

## 1. 交付范围

| 批次 | 任务 | 状态 | 主要实现 |
|---|---|---|---|
| M1 | T01 领域与状态机、T02 构建配置与版本、T03 Export Preset、T04 环境管理 | 完成 | `modules/build_release/{models,repository,service}.py`、迁移 `000028`、E10 错误码与 `build.* / artifact.* / release.* / signing.* / distribution.*` 权限动作 |
| M2 | T05 Build Orchestrator、T06 Godot Headless Adapter、T07 平台导出适配器、T17 恢复 | 完成 | `adapter.py`（受控执行器：可执行白名单、路径守卫、环境变量白名单、超时、日志脱敏）、`orchestrator.py`（门禁前置、产物校验、`UNKNOWN` 恢复） |
| M3 | T08 Artifact Registry、T09 Packaging、T13 Provenance / Evidence | 完成 | `artifacts.py`（内容不可变、清单哈希完整性）、`packaging.py`（清单 + 包哈希绑定）、`provenance.py`（构建来源与发布证据只追加）、迁移 `000029` |
| M4 | T11 Release Candidate、T14 Artifact Verification / Smoke Test | 完成 | `smoke_test.py`（`SKIPPED ≠ PASSED`、冒烟证据）、`release_candidates.py`（候选清单哈希与就绪校验）、迁移 `000030` |
| M5 | T10 Signing & Secrets、T12 Release Approval、T15 Release Manager、T16 Local Distribution | 完成 | `signing.py`（仅保存引用、明文密钥拒绝、UNKNOWN 需核对）、`release_approvals.py`（审批绑定哈希、失效规则）、`release_manager.py`、`distribution.py`（本地交付幂等、复制后哈希校验、撤回/回滚）、迁移 `000031` |
| M6 | T18 Dashboard / UI、T19 Agent 集成、T20 Platformer Demo 验收、验收报告 | 完成 | `dashboard.py`（构建/制品/候选/审批/发布聚合）、`agent_policy.py`（允许/禁止操作矩阵）、`app/api/{builds,artifacts,releases}.py`、`tests/integration/test_e10_acceptance.py`、本报告 |

## 2. 架构冻结规则核对（E10.md §13）

| 规则 | 结论 | 证据 |
|---|---|---|
| 构建 / 导出 / 打包 / 签名 / 发布 / 分发分阶段 | 通过 | 独立状态机 `BUILD / ARTIFACT / RC / APPROVAL / RELEASE / PACKAGE`；`test_e10_domain.py` 7 项 |
| 受控执行器（白名单 / 路径守卫 / 环境变量白名单 / 超时 / 脱敏） | 通过 | `adapter.py` 与 `test_build_orchestrator` 的门禁用例 |
| Artifact 不可变 | 通过 | 同内容幂等、不同内容新版本；`test_artifact_registration_versioning_and_idempotency` |
| 审批绑定哈希 | 通过 | 审批保存候选清单/制品/包哈希，内容变化拒绝或失效；`test_release_requires_approval_binding` |
| UNKNOWN ≠ FAILED / SUCCESS | 通过 | 构建与签名均保持 `UNKNOWN`，只允许核对后收敛；`test_timeout_enters_unknown_and_requires_recovery`、`test_signing_unknown_requires_reconciliation` |
| SKIPPED ≠ PASSED | 通过 | `evaluate_checks` 空检查与 SKIPPED 均不通过；`test_candidate_rejected_without_passing_smoke` |
| 首期桌面平台 Windows / macOS / Linux | 通过 | `DEFAULT_PLATFORM_CAPABILITIES`；`test_platform_capabilities_seeded` |
| 本地交付与线上发布区分 | 通过 | 渠道枚举与本地适配器注册表；`test_local_release_lifecycle`、`test_local_release_withdraw_removes_delivery` |
| 分发幂等 | 通过 | `idempotency_key` 唯一约束，重复提交返回既有操作；`test_local_release_lifecycle` 重复分发断言 |
| Agent 不得自行批准 / 发布 | 通过 | `release.approve / publish` 限定项目 Owner；`agent_policy` 禁止 `SELF_APPROVE`；`test_agent_policy_matrix` |

## 3. Platformer Demo 构建交付闭环（E10.md §12）

验收测试以真实 `project.godot` 工程与真实导出文件跑通完整链路，构建执行器使用可注入替身
（CI 不依赖 Godot 可执行文件），其余环节均为真实数据库与文件操作：

| 阶段 | 断言 | 证据 |
|---|---|---|
| 环境登记 | Windows 环境 `READY`，写入指纹 | `test_build_to_local_delivery_closed_loop` 第 1 步 |
| 构建配置与 Export Preset | 配置版本快照、模板可用 | 同上第 2 步 |
| 受控构建 | 退出码 0 且存在非空产物才 `SUCCEEDED` | 同上第 3 步 |
| 不可变制品 | 清单哈希与体积写入，验证后 `VERIFIED` | 同上第 4 步 |
| 交付包 | 包哈希与绑定校验通过 `VERIFIED` | 同上第 5 步 |
| 发布候选 | 制品/包绑定一致，冒烟通过后 `READY_FOR_APPROVAL` | 同上第 6 步 |
| 用户审批 | 审批 `APPROVED`，候选转 `APPROVED` | 同上第 7 步 |
| 发布创建与授权 | 无审批不能授权，`PENDING → AUTHORIZED` | 同上第 8 步 |
| 本地交付 | 文件复制成功且哈希一致，`PUBLISHED` | 同上第 9 步 |
| 发布后验证 | 目标文件哈希复核通过 `COMPLETED` | 同上第 10 步 |
| UNKNOWN 恢复 | 超时进入 `UNKNOWN`，禁止直接重试，核对产物后收敛 | `test_unknown_build_requires_recovery_before_release` |

## 4. 故障注入与恢复（E10.md §10）

| 场景 | 结论 | 证据 |
|---|---|---|
| 环境未就绪 | 通过 | `test_environment_status_and_dedup` |
| Export Preset 模板缺失 | 通过 | `test_missing_template_blocks_start_before_running` |
| 平台能力不匹配 | 通过 | `test_build_orchestrator.py` 门禁用例 |
| 构建退出码非 0 | 通过 | `test_retry_creates_new_attempt` |
| 退出码 0 但无产物 | 通过 | `test_zero_exit_without_output_is_failure` |
| 构建超时 / 无退出码 | 通过 | `test_timeout_enters_unknown_and_requires_recovery` |
| 恢复时产物缺失 | 通过 | `test_recovery_without_output_resolves_failed` |
| 制品内容变化 | 通过 | 新版本登记，旧版本哈希不变；`test_artifact_registration_versioning_and_idempotency` |
| 包被篡改 | 通过 | `verify_package` 失败转 `REJECTED`；`test_package_create_and_verify` |
| 冒烟 SKIPPED | 通过 | 候选校验失败 `REJECTED`；`test_candidate_rejected_without_passing_smoke` |
| 签名失败 / 不确定 | 通过 | `test_signing_unknown_requires_reconciliation` |
| 审批后内容变化 | 通过 | `assert_binding` 失效并抛 `ReleaseApprovalMismatch`；`test_release_requires_approval_binding` |
| 重复分发 | 通过 | 幂等键返回既有操作，不重复复制；`test_local_release_lifecycle` |
| 撤回本地交付 | 通过 | 删除交付文件并标记 `WITHDRAWN`；`test_local_release_withdraw_removes_delivery` |

## 5. 安全测试（E10.md §10.4）

| 场景 | 结论 | 证据 |
|---|---|---|
| 跨项目构建/制品访问 | 通过 | API 每个资源先解析项目再授权；`app/api/{builds,artifacts,releases}.py` |
| Agent 任意执行 Shell | 通过 | 执行器只允许白名单可执行文件且不使用 shell；`adapter.py` |
| Agent 读取签名私钥 | 通过 | 仅保存引用，拒绝明文密钥；`test_signing_profile_and_attempt` |
| Agent 修改 Artifact | 通过 | 内容不可变，变更生成新版本；`test_artifact_registration_versioning_and_idempotency` |
| Agent 绕过审批 | 通过 | 发布前强制 `require_approved` 与绑定校验；`test_release_requires_approval_binding` |
| Agent 自行批准 / 发布 | 通过 | Owner-only 权限与策略矩阵；`test_agent_policy_matrix` |
| Agent 把 UNKNOWN 标记成功 | 通过 | 只有核对入口可收敛，且 `unknown_cannot_be_marked_success` |
| Agent 调用未授权发布 API | 通过 | 分发适配器白名单，未实现渠道直接拒绝 |
| 签名日志泄漏密钥 | 通过 | 日志与证据只记录引用、工具版本与指纹 |
| 路径穿越 | 通过 | `ensure_within` 路径守卫；构建输出与交付目标均在受控目录 |

## 6. Definition of Done 核对（E10.md §13）

### 6.1 核心能力

| 项 | 结论 |
|---|---|
| Build Configuration / Export Preset / Environment | 通过 |
| Build Orchestrator 与受控执行 | 通过 |
| Artifact Registry（不可变 + 完整性） | 通过 |
| Packaging 与绑定校验 | 通过 |
| Provenance / Release Evidence | 通过 |
| Release Candidate 与校验 | 通过 |
| Artifact Verification / Smoke Test | 通过 |
| Signing & Secrets 管理 | 通过 |
| Release Approval（绑定哈希） | 通过 |
| Release Manager（授权/发布/验证/撤回/回滚） | 通过 |
| Local Distribution（幂等、哈希复核） | 通过 |
| Dashboard / Agent 策略 | 通过 |

### 6.2 安全要求

全部通过：执行器白名单与路径守卫、签名密钥不落库、审批绑定内容哈希、Owner-only 审批与发布、
UNKNOWN 不可伪造成功、分发幂等与未实现渠道失败关闭（证据见 §2、§4、§5）。

### 6.3 质量要求

单元测试、集成测试、故障注入、安全测试与 Platformer Demo 构建交付闭环均通过（见 §8）。

## 7. 交付物核对（E10.md §15）

| 编号 | 交付物 | 状态 |
|---|---|---|
| 1–4 | Build Domain / Build Configuration / Export Preset / Environment | 完成 |
| 5–7 | Build Orchestrator / Godot Headless Adapter / Platform Export Adapter | 完成 |
| 8–9 | Artifact Registry / Packaging | 完成 |
| 10–11 | Signing & Secrets / Release Candidate | 完成 |
| 12–13 | Release Approval / Provenance & Evidence | 完成 |
| 14–16 | Artifact Verification & Smoke Test / Release Manager / Local Distribution | 完成 |
| 17–18 | Build Recovery / Dashboard | 完成 |
| 19 | Agent Integration | 完成 |
| 20 | API Documentation | 完成（`/api/v1` OpenAPI，`builds` / `artifacts` / `releases` 标签） |
| 21 | Database Migration | 完成（`000028`–`000031`） |
| 22 | Test Suite | 完成（8 个 E10 测试文件 / 38 个测试函数） |
| 23 | Platformer Demo Build Report | 完成（本报告 §3） |

## 8. 质量门禁

| 项目 | 结果 |
|---|---|
| 后端 pytest | **898 passed，1 warning（834.97s）** |
| 后端 ruff | 全部通过（`ruff check src tests migrations`、`ruff format --check`，480 文件已格式化） |
| Alembic head | `000031` |
| Godot 测试 | 未改动插件测试入口（E10 为后端构建与发布层） |
| 新增 E10 测试 | 8 个文件 / 38 个测试函数 |

## 9. 事件与审计

- 构建创建、尝试、日志、制品登记、包创建、候选校验、冒烟结果、签名尝试、审批、发布与分发
  操作均持久化；制品、证据与分发操作只追加，不原地改写。
- 审批记录 `requested_by` / `approved_by`，绑定清单哈希；内容变化后原审批失效。
- 分发操作保存 `idempotency_key`、目标引用、文件摘要与结果，支持发布后验证与撤回。

## 10. 已知限制

1. CI 不拉起真实 Godot 可执行文件：构建编排以可注入执行器替身验证，真实 headless 导出链路由
   E11 Demo 在安装导出模板的环境执行。
2. 签名提供配置注册、执行流程与结果核对，未内置具体平台签名工具（如 `signtool` / `codesign`）；
   需在目标环境注入签名适配器。
3. 分发首期只实现本地交付（复制 + 哈希复核）；线上渠道接口未实现，未实现渠道直接失败关闭。
4. 回滚目前只支持本地渠道的标记回滚 (`ROLLED_BACK`)，线上回滚需接入真实渠道 API。
5. 发布候选的清单哈希基于制品内容哈希、包哈希、版本与平台，未包含渠道元数据（渠道在审批中绑定）。
6. 打包产物（onefile 便携版）的杀软误报与干净机器验证需在安装包制作阶段执行。

## 11. 结论与 E11 准入

E10 的 20 个任务全部落地。构建、导出、打包、签名、审批、发布与分发按阶段隔离，执行器受控，
Artifact 不可变，审批绑定内容哈希，UNKNOWN / SKIPPED 与成功严格分离，本地交付具备幂等与
哈希复核能力；Platformer Demo 工程上跑通了「构建 → 制品 → 交付包 → 候选 → 冒烟 → 用户审批
→ 本地交付 → 发布后验证」的完整闭环。E10.md §13 的 DoD 与 §15 的 23 项交付物均有实现与测试证据。

E10 阶段完成，可进入 E11 Platformer Demo。
