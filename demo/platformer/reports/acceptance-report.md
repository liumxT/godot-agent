# Platformer Demo 交付与验收说明（E11）

**项目：** Project Platformer Demo
**内部代号：** PF-DEMO-001
**版本：** 1.0.0
**引擎：** Godot 4.5.1.stable（`gl_compatibility`，960 × 540）
**验收结论：** ACCEPTED_WITH_NOTES（自动化与真实运行验证通过；视觉/音频需人工确认）

---

## 1. 游戏体验入口

| 方式 | 操作 | 说明 |
| --- | --- | --- |
| 编辑器 | 用 Godot 4.5.1 打开 `godot_project/project.godot`，按 F5 | 主场景 `res://scenes/main/main.tscn` |
| 导出程序 | 在本机重新执行 E11 交付测试或在编辑器中导出 | 产物 `godot_project/build/PlatformerDemo.exe`（约 92 MB，构建产物不入库） |
| 无头冒烟 | `godot --headless --path godot_project -- --smoke` | 输出 `[SMOKE] RESULT=PASS` |
| 运行时验证 | `godot --headless --path godot_project res://scenes/tests/runtime_verifier.tscn` | 24 项用例，输出 `[VERIFY] RESULT=PASS` |

## 2. 操作方式

| 动作 | 按键 |
| --- | --- |
| 左/右移动 | `A` / `←`、`D` / `→` |
| 跳跃 | `Space` |
| 攻击 | `J` |
| 暂停 / 恢复 | `Esc` |

## 3. 游戏内容

- 1 个横向卷轴关卡（`TileMapLayer` 地形 + 独立平台层）。
- 玩家：移动、跳跃、攻击、受伤、无敌帧、死亡、重生。
- 敌人：2 个巡逻敌人（边界转向、接触伤害、可被击杀）。
- 收集物：15 个（金币 / 宝石，计分且不重复计分）。
- 陷阱：2 处地刺，造成伤害并进入无敌帧。
- 终点：到达后进入胜利结算。
- UI：主菜单、HUD（生命 / 分数 / 最佳分数）、暂停菜单、结算界面。
- 音频：背景音乐 + 跳跃 / 受伤 / 收集音效。
- 存档：`user://platformer_save.json` 保存最佳分数，损坏时回退默认值。
- 表现：受击闪烁、跳跃尘土、收集缩放等由 GDScript Tween 生成，不依赖外部动画资源。

## 4. 需求完成清单

| 项 | 数量 | 状态 |
| --- | --- | --- |
| 需求（Requirement） | 21 | 全部登记并可追踪 |
| 验收条件（Acceptance Criteria） | 36 | 全部绑定需求 |
| 玩法机制（Mechanics） | 8 | 全部实现 |
| 功能（Features） | 8 | 全部实现 |
| 关卡（Levels） | 1 | 已实现 |
| 测试场景（Test Scenarios） | 18 | 全部登记，运行时验证覆盖核心路径 |
| 运行时用例 | 24 | 24 passed / 0 failed |

需求与验收条件的机器可读基线由后端 `demo_game` 模块维护（`seed_platformer`），
文档基线见 `specification/` 与 `design/`。

## 5. 验证与交付证据

| 证据 | 路径 | 结果 |
| --- | --- | --- |
| 运行时验证日志 | `reports/evidence/runtime-verify.log` | 24 / 24 PASS |
| 编辑器加载日志 | `reports/evidence/editor-import.log` | 无阻断错误 |
| 真实导出日志 | `reports/evidence/build-export.log` | 导出成功，102 个打包步骤 |
| 导出程序冒烟 | `reports/evidence/exported-smoke.log` | `[SMOKE] RESULT=PASS`（13 项检查） |
| 交付链路测试 | `apps/backend/tests/integration/test_e11_delivery_chain.py` | ChangeSet → 验证 → 构建 → 制品 → 候选 → 审批 → 本地交付 → 发布后验证 |
| 工程一致性测试 | `apps/backend/tests/integration/test_e11_godot_project.py` | 主场景 / 输入映射 / 资源引用 / 资产齐备 |
| 规格与验收测试 | `apps/backend/tests/integration/test_e11_demo_spec.py` | 规格冻结、追踪矩阵、验收结论 |

## 6. 资产来源与许可

所有资产均为项目内生成的占位素材（SVG 矢量图与程序生成 WAV），许可为“项目内部”，
无第三方来源或授权受限素材。完整清单见 `design/asset-registry.md`。

## 7. 构建来源

- 构建配置：Windows Desktop / x86_64，Export Preset `Windows Desktop`。
- 制品：`PlatformerDemo.exe`（内嵌 PCK），构建后登记不可变制品哈希、交付包与发布候选，
  审批绑定内容哈希，本地交付复制后再次复核哈希。
- 发布记录与审批证据由后端 Build & Release 模块持久化（E10 能力）。

## 8. 已知问题

1. 视觉资产为静态占位 SVG，无逐帧动画；表现层仅用 Tween 与状态切换。
2. 音频为程序生成的占位音效，攻击 / 死亡 / UI 音效尚未独立制作。
3. 无头环境无法验证实际画面与声音，视觉/音频需人工确认（因此验收结论为
   `ACCEPTED_WITH_NOTES`）。
4. 真实导出仅在本机 Windows + Godot 4.5.1 环境验证；CI 不拉取 Godot，导出用例在 CI 中跳过。
5. `build/` 为本地构建产物，不入库；需要可执行文件时在目标环境重新导出。
