# E11 验收报告：Platformer Demo

**阶段：** E11
**文档版本：** V1.0
**验收日期：** 2026-11-26
**迁移版本：** `000032`
**用户验收结论：** `ACCEPTED_WITH_NOTES`（自动化与真实运行验证通过；视觉与音频需人工确认）
**阶段结论：** 通过（20 项任务全部落地；已知限制见 §9）

---

## 1. 交付范围

| 批次 | 任务 | 状态 | 主要交付 |
|---|---|---|---|
| M1 | T01 需求分析、T02 游戏设计、T03 技术架构 | 完成 | `modules/demo_game/{specification,models,repository,service}.py`、迁移 `000032`（8 张 `demo_game_*` 表）、`specification/` 与 `design/` 12 份文档、`app/api/demo.py` 与 `app/schemas/demo_game.py` |
| M2 | T04 项目初始化与工程基础 | 完成 | `demo/platformer/godot_project`（`project.godot`、主场景、输入映射、自动加载、物理层、导出预设） |
| M3 | T05 玩家、T06 战斗、T07 敌人、T08 关卡、T09 收集与分数 | 完成 | `scripts/{player,combat,enemies,systems}`；`TileMapLayer` 地面与平台层、陷阱、终点、巡逻敌人、收集物与 ScoreManager |
| M4 | T10 UI 与流程、T11 表现层、T12 存档 | 完成 | 主菜单 / HUD / 暂停 / 结算场景与控制器、`game_flow_manager.gd`、`AudioManager`、`SaveManager`（最佳分数） |
| M5 | T13 多 Agent、T14 ChangeSet / Approval、T15 Context | 完成 | 复用 E7 多 Agent 编排与 E4 ChangeSet；E11 交付链路测试验证变更审批与 Context 装配 |
| M6 | T16 验证与 QA、T17 构建与发布 | 完成 | `test_e11_delivery_chain.py`：三层静态验证 + 真实运行证据 + 真实导出 → 制品 → 包 → 候选 → 冒烟 → 审批 → 本地交付 → 发布后验证 |
| M7 | T18 可观测性 / UX、T19 稳定性、T20 最终验收 | 完成 | `system_report` 聚合、Demo API、验收评审与追踪矩阵、本报告与 `demo/platformer/reports/acceptance-report.md` |

## 2. 游戏系统验收（E11.md §2.4）

| 系统 | 优先级 | 结论 | 证据 |
|---|---|---|---|
| Player（移动 / 跳跃 / 攻击 / 受伤 / 死亡） | P0 | 通过 | `runtime-verify.log`：`MOVE_RIGHT`、`JUMP`、`PLAYER_DEAD` 等用例 PASS |
| Physics（重力 / 碰撞 / 平台检测） | P0 | 通过 | `PLAYER_ON_GROUND`；玩家与 TileMapLayer 碰撞配置 |
| Level（TileMapLayer / 平台 / 陷阱） | P0 | 通过 | `Ground` / `Platforms` 两个 TileMapLayer、`HAZARD_DAMAGE` |
| Enemy（巡逻 / 攻击 / 受伤 / 死亡） | P0 | 通过 | `ENEMY_PATROL`、`ENEMY_ATTACKS_PLAYER`、`ENEMY_DEFEATED` |
| Combat（攻击判定 / 伤害 / 无敌帧） | P0 | 通过 | `ATTACK_DAMAGES_ENEMY`、`ATTACK_NO_DOUBLE_HIT`、`IFRAME_BLOCKS_REPEAT` |
| Health（玩家与敌人生命） | P0 | 通过 | `INVULNERABLE_AFTER_HIT`、`ENEMY_COUNT` |
| Collectible（收集与分数） | P0 | 通过 | `COLLECT_ADDS_SCORE`（score=10）、`COLLECT_ONCE` |
| UI / Menu / Pause / Game Flow | P0 | 通过 | `PAUSE`、`RESUME`、`FLOW_GAME_OVER`、`FLOW_VICTORY`；主菜单与结算场景 |
| Animation / VFX | P1 | 部分 | 静态占位 SVG + GDScript Tween（受击闪烁、跳跃尘土、收集缩放），无逐帧动画 |
| Audio | P1 | 部分 | 背景音乐与跳跃 / 受伤 / 收集音效；攻击 / 死亡 / UI 音效未独立制作 |
| Save | P1 | 通过 | `SaveManager` 最佳分数持久化，损坏存档回退默认值 |

## 3. 端到端链路证据

| 链路步骤 | 证据 | 结果 |
|---|---|---|
| 需求 → 规格冻结 | `test_e11_delivery_chain.py`：21 需求 / 36 验收条件 / 18 场景，`freeze_spec` 转 `FROZEN` | 通过 |
| ChangeSet → 审批 → 应用 | 以真实文件 SHA-256 登记 8 个交付物，`VALID → APPROVED → APPLYING → APPLIED` | 通过 |
| 三层验证 | STATIC / STRUCTURE / RESOURCE 执行器在真实工程文件上运行，`FAILED == 0` | 通过 |
| 真实运行时证据 | `reports/evidence/runtime-verify.log`：24 / 24 PASS，绑定为 `GODOT_RUNTIME` 证据 | 通过 |
| 质量门禁 | `evaluate_quality_gate`（风险 HIGH）返回 `PASSED / PASSED_WITH_WARNINGS` | 通过 |
| Context 装配 | `ContextAssemblyService` 返回项目层，`token_estimate > 0` | 通过 |
| 构建与交付 | 真实 Godot headless 导出 → 不可变制品 → 包 → 候选 → 冒烟 → 审批 → 本地交付 → 发布后验证，交付文件哈希一致 | 通过（本机 Godot 4.5.1；CI 跳过） |
| 验收评审与系统报告 | 用户验收 `ACCEPTED_WITH_NOTES`；`system-report` 聚合规格、验证、构建与覆盖度 | 通过 |

## 4. 数据一致性与恢复

| 场景 | 结论 | 证据 |
|---|---|---|
| Demo 规格重复初始化幂等 | 通过 | `test_seed_is_idempotent_and_complete` |
| 验收条件 / 场景非法状态拒绝 | 通过 | `test_criterion_and_scenario_statuses`（`UNKNOWN` 拒绝、未知场景 404） |
| 拒绝验收必须带后续修复任务 | 通过 | `test_acceptance_review_rules` 与 `DemoAcceptanceReviewRequest` 校验 |
| 构建 `UNKNOWN` 恢复 | 通过（复用 E10） | `test_unknown_build_requires_recovery_before_release` |
| 交付中断与哈希复核 | 通过（复用 E10） | `test_local_release_lifecycle` / `test_local_release_withdraw_removes_delivery` |
| 状态归属 | 通过 | E11 仅通过公开服务读写；`demo_game` 不直接修改 Task / Workflow / Verification / Build 状态 |

## 5. 安全与权限

| 场景 | 结论 | 证据 |
|---|---|---|
| 未认证访问 Demo API | 通过 | 路由级 `require_authenticated` + `enforce_rate_limit` |
| 跨项目读取 Demo 规格 | 通过 | `authorize_project_action` 在每个端点先解析项目再授权 |
| 非 Owner 提交验收 | 通过 | `demo.accept` 仅 Owner；`test_acceptance_requires_owner_role` |
| Agent 自行通过验收 | 通过 | 验收接口需 `demo.accept`；Agent 默认不具备该动作 |
| 敏感信息泄漏 | 通过 | Demo 报告只输出规格、覆盖度与公开摘要，不含密钥或隐藏推理 |
| 伪装视觉/音频通过 | 通过 | 验收结论保留 `ACCEPTED_WITH_NOTES`，明确视觉/音频需人工确认 |

## 6. 可观测性与用户体验（T18）

`GET /api/v1/demo/projects/{project_id}/system-report` 聚合以下信息，用户可回答
「AI 做了什么、做到哪里、是否通过、交付物在哪」：

- 规格与需求：21 需求、36 验收条件、18 场景与追踪矩阵。
- 覆盖度：已满足验收条件比例、阻塞场景数量。
- 验证摘要：Campaign / 结果统计（来自 Verification 模块公开接口）。
- 构建摘要：构建数、制品数、发布数（来自 Build & Release 模块公开接口）。
- 验收结论与历史：`ACCEPTED / ACCEPTED_WITH_NOTES / REJECTED`。

## 7. 交付物

| 编号 | 交付物 | 状态 |
|---|---|---|
| 1–3 | 需求规格、游戏设计、技术架构 | 完成（`specification/`、`design/`） |
| 4 | Godot 项目工程 | 完成（可被 Godot 4.5.1 打开，主场景与输入映射校验通过） |
| 5–9 | 玩家、战斗、敌人、关卡、收集与分数 | 完成 |
| 10–12 | UI 与流程、表现层、存档 | 完成（表现层有已知限制） |
| 13 | 多 Agent 协作 | 完成（复用 E7 编排与 Demo 计划） |
| 14–15 | ChangeSet / Approval、Context | 完成（交付链路测试） |
| 16 | Verification & QA | 完成（三层验证 + 24 项运行时用例 + 真实证据） |
| 17 | Build & Release | 完成（真实导出与本地交付闭环） |
| 18 | 可观测性 / UX | 完成（`system-report` 聚合） |
| 19 | 稳定性与恢复 | 完成（复用 E1–E10 恢复证据） |
| 20 | 最终验收与用户验收 | 完成（本报告 + Demo 交付说明 + `system-report`） |
| 21 | Database Migration | 完成（`000032`，8 张表） |
| 22 | Test Suite | 完成（3 个 E11 测试文件 / 17 个测试函数） |
| 23 | Demo 交付说明 | 完成（`demo/platformer/reports/acceptance-report.md`） |

## 8. 质量门禁

| 项目 | 结果 |
|---|---|
| 后端 pytest | 916 passed，1 warning（956.89s） |
| 后端 ruff | `ruff check src tests` 通过；`ruff format --check` 通过 |
| 结构与敏感扫描 | 13 个必需路径齐全；897 个文件未发现敏感文件或凭证 |
| 契约 | 57 passed |
| Alembic head | `000032`（`test_migrations` 断言） |
| E11 测试 | 17 passed（规格 6 / 工程 9 / 交付链路 2） |
| Godot 运行时验证 | 24 / 24 PASS（真实引擎 headless） |
| 导出程序冒烟 | `[SMOKE] RESULT=PASS`（13 项检查） |
| Godot 插件回归 | 68 / 68 passed（未改动插件测试入口） |

### 8.1 全量测试

| 项 | 数值 |
|---|---|
| pytest | 916 passed |
| 警告 | 1（Starlette `httpx` 弃用警告，第三方） |
| 迁移验证 | `000032` |

## 9. 已知限制

1. 视觉资产为静态占位 SVG，无逐帧动画；表现层仅用 Tween 与状态切换（T11 P1）。
2. 音频为程序生成占位音效，攻击 / 死亡 / UI 音效未独立制作（T11 P1）。
3. 无头环境无法验证实际画面与声音，视觉/音频需人工确认。
4. 真实 Godot 导出仅在本机 Windows + Godot 4.5.1 验证；CI 缺少 Godot 可执行文件时该用例跳过。
5. `godot_project/build/` 中的导出产物（约 92 MB）不入库，需要时在目标环境重新导出。
6. E11 未新增 12 个 Phase 的 Demo 专用 Workflow 模板；Phase 状态由 E4 Workflow 与 E7
   `game_workflow_service` 提供，Demo 通过 Task/Phase 状态读取，未做独立编排。
7. T13 多 Agent 证据来自 E7 的 Platformer Demo 计划与 E2E；E11 未新增独立的多 Agent 编排场景。
8. 管理界面未新增 Demo 专用页面，用户通过 Demo API 与现有 Dashboard 查看状态。

## 10. 结论与 E12 准入

E11 的 20 项任务全部落地：需求可追踪、Godot 工程可打开、核心玩法在真实引擎中 24 项用例全部通过、
导出程序冒烟通过、构建与发布链路具备真实制品、审批绑定哈希、本地交付哈希复核，
平台侧新增的 Demo 规格/验收数据与 API 不复制其他模块的状态管理。

已知限制集中在表现层（P1）与「Demo 专用 Workflow / 多 Agent 独立编排」两处，均不阻断系统级
验收。阶段结论为通过，用户验收结论为 `ACCEPTED_WITH_NOTES`，可进入 E12 Productization。
