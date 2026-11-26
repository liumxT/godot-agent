# Technical Architecture（PF-DEMO-001）

**文档类型：** Technical Architecture Document（对应 E11-T03）
**Godot 版本：** 4.5.1（冻结，不得中途升级）
**渲染方式：** GL Compatibility（`gl_compatibility`）
**依据：** Game Requirement Document、Gameplay Specification、Level Design Document

---

## 1. 架构目标

1. 场景结构与脚本逻辑分离：`.tscn` 只描述节点与资源引用，逻辑全部在 `.gd`。
2. 单一权威状态：生命、分数、游戏流程各只有一个权威持有者。
3. 数据可配置：玩家数值来自 `resources/game_config/player_config.tres`，关卡布局来自脚本数据表。
4. 引用可静态校验：所有 `res://` 引用必须能被后端结构测试解析并通过。
5. 可无人值守验证：`--smoke` 与 `runtime_verifier.tscn` 在 headless 下输出 PASS/FAIL 证据。

---

## 2. 项目结构

```text
godot_project/
├── project.godot                # 主场景、自动加载、输入映射、渲染与物理配置
├── icon.svg
├── scenes/
│   ├── main/main.tscn           # 主场景装配（World + UI）
│   ├── player/player.tscn
│   ├── enemies/patrol_enemy.tscn
│   ├── levels/level_01.tscn, spike.tscn, goal.tscn
│   ├── collectibles/collectible.tscn
│   ├── ui/main_menu.tscn, hud.tscn, pause_menu.tscn, result_screen.tscn
│   └── tests/runtime_verifier.tscn
├── scripts/
│   ├── core/                    # event_bus / game_flow_manager / audio_manager / main
│   ├── player/                  # controller / health / combat
│   ├── enemies/                 # enemy_base / enemy_patrol
│   ├── combat/                  # hitbox / hurtbox
│   ├── systems/                 # level_01 / collectible / hazard / goal / score_manager / save_manager
│   ├── ui/                      # menu / hud / pause / result
│   └── tests/                   # runtime_verifier
├── assets/                      # characters / environments / tilesets / ui / audio
└── resources/                   # game_config / tilesets
```

目录与 E11 §26 建议布局一致；`tests/` 以 `scenes/tests` + `scripts/tests` 落地，避免与 Godot 资源目录约定冲突。

---

## 3. 场景架构

| 场景 | 根节点 | 职责 | 关键子节点 |
|---|---|---|---|
| `main.tscn` | Node | 装配层：注册关卡容器、启动流程、headless 冒烟 | World(Node2D)、UI(CanvasLayer, `PROCESS_MODE_ALWAYS`) |
| `player.tscn` | CharacterBody2D | 玩家移动/跳跃/攻击/受伤 | Sprite2D、CollisionShape2D、Camera2D、Hurtbox、Hitbox、Health、Combat |
| `patrol_enemy.tscn` | CharacterBody2D | 巡逻与近身攻击 | Sprite2D、FloorCheck(RayCast2D)、Hurtbox、Hitbox |
| `level_01.tscn` | Node2D | 关卡装配：TileMapLayer、实体容器、出生点 | Sky、Ground、Platforms、Entities、PlayerSpawn |
| `collectible.tscn` | Area2D | 金币/宝石拾取 | Sprite2D、CollisionShape2D |
| `spike.tscn` / `goal.tscn` | Area2D | 陷阱伤害 / 胜利触发 | CollisionShape2D |
| UI 四场景 | Control | 菜单 / HUD / 暂停 / 结算 | 由各 controller 绑定 |

**分层规则**

- `main.tscn` 只做装配，不承载玩法逻辑。
- 关卡内实体全部在 `Entities` 下由 `level_01.gd` 生成，关卡场景本身保持最小可读。
- UI 通过 `flow_ui` 组注册，由 `GameFlowManager` 统一调用 `set_active`，UI 不反向控制流程。

---

## 4. 脚本架构

| 模块 | 脚本 | 权威职责 | 对外接口 |
|---|---|---|---|
| 事件 | `core/event_bus.gd`（Autoload） | 事件总线，不持有状态 | 信号：`player_jumped`、`player_damaged`、`player_died`、`health_changed`、`score_changed`、`collectible_collected`、`enemy_defeated`、`game_started`、`game_paused`、`game_resumed`、`game_over`、`level_completed`、`best_score_changed`、`game_state_changed` |
| 流程 | `core/game_flow_manager.gd`（Autoload） | 唯一流程状态机 BOOT/MAIN_MENU/PLAYING/PAUSED/VICTORY/GAME_OVER/LEVEL_RESTART | `register_level_root`、`boot`、`start_game`、`restart_level`、`pause_game`、`resume_game`、`toggle_pause`、`on_player_died`、`on_goal_reached`、`to_menu`、`state_name` |
| 分数 | `systems/score_manager.gd`（Autoload） | 唯一分数权威 | `reset_run`、`add_score`、`commit_best` |
| 存档 | `systems/save_manager.gd`（Autoload） | `user://` JSON 持久化最佳分数，损坏回退默认值 | `get_best_score`、`submit_best_score` |
| 音频 | `core/audio_manager.gd`（Autoload） | 音效池与 BGM 播放 | `play_sfx`、`play_bgm` |
| 玩家 | `player/player_controller.gd` | 移动/跳跃/朝向/受击表现 | `take_damage`、`is_dead` |
| 生命 | `player/player_health.gd` | 生命值与无敌帧 | `setup`、`take_damage`、`heal`、`is_invulnerable` |
| 战斗 | `player/player_combat.gd` | 攻击冷却、有效窗口、Hitbox 开关 | `setup`、`try_attack`、`is_attacking` |
| 命中 | `combat/hitbox.gd` | 命中过滤、单次攻击去重 | `activate`、`deactivate`、`damage`、`source_id` |
| 受击 | `combat/hurtbox.gd` | 伤害转发给拥有者 | `receive_damage` |
| 敌人 | `enemies/enemy_base.gd` | 敌人生命/受击/死亡 | `take_damage`、`die`、`health`、`dead` |
| 敌人 AI | `enemies/enemy_patrol.gd` | 巡逻、边界转向、攻击 | 复用基类 + `patrol_range`、`attack_range` |
| 关卡 | `systems/level_01.gd` | 用数据表构建地形与实体 | `_build_terrain`、`_spawn_*` |

**规则**

1. 数值不写在行为脚本内：玩家数值来自 `PlayerConfig` 资源。
2. UI 只消费信号（`health_changed`、`score_changed`），不持有权威数据。
3. 伤害只能经 `Hitbox → Hurtbox → take_damage` 链路传递，禁止直接跨层改写生命。
4. 攻击判定不依赖动画：`Hitbox.activate()` 是唯一攻击生效开关。

---

## 5. 资源架构

| 资源 | 路径 | 说明 |
|---|---|---|
| 玩家配置 | `resources/game_config/player_config.tres` | 速度、加速度、重力、跳跃、生命、无敌、攻击数值 |
| 地形 TileSet | `resources/tilesets/terrain.tres` | 单图集（tiles.svg），`physics_layer_0` 定义碰撞多边形 |
| 角色贴图 | `assets/characters/player.svg`、`enemy.svg` | 占位矢量资产 |
| 收集物/陷阱/UI | `assets/ui/coin.svg`、`gem.svg`、`assets/environments/spikes.svg` | 占位矢量资产 |
| 音频 | `assets/audio/{jump,hurt,collect,bgm}.wav` | 程序生成的占位音频，导入证据见 `.import` |

**TileMap 决策：** 不使用手写二进制 `tile_map_data`；`level_01.gd` 在 `_ready` 中按 `PLATFORM_ROWS` / `COIN_TILES` 等数据表调用 `set_cell` 构建，保证布局可在代码审查与结构测试中读取，同时 TileSet 仍提供真实物理层。

---

## 6. 物理与碰撞层

| Layer | 名称 | 使用者 |
|---|---|---|
| 1 | world | TileMapLayer 地形 |
| 2 | player | 玩家与敌人 CharacterBody2D |
| 3 | hurtbox | 玩家/敌人 Hurtbox（`monitorable`） |
| 4 | hitbox | 玩家/敌人 Hitbox（`monitoring`，攻击时开启） |
| 5 | collectible | 收集物 Area2D |
| 6 | hazard | 陷阱 Area2D |
| 7 | goal | 终点 Area2D |

过滤规则：Hitbox `mask=hurtbox`；Hurtbox `layer=hurtbox`；收集物/陷阱/终点 `mask=player`。Hitbox 通过 `area.get_parent() == get_parent()` 排除自伤。

---

## 7. 自动加载顺序

`EventBus → AudioManager → ScoreManager → SaveManager → GameFlowManager`

`ScoreManager._ready` 读取 `SaveManager`，因此 `SaveManager` 必须早于 `ScoreManager`；`GameFlowManager` 依赖前四者，排序在最后且其 `process_mode = ALWAYS` 保证暂停时仍可响应输入。

---

## 8. 技术决策记录（ADR）

| ID | 决策 | 理由 | 影响 |
|---|---|---|---|
| ADR-01 | 冻结 Godot 4.5.1 + GDScript + GL Compatibility | 与 E10 验证过的环境一致，跨机器导出稳定 | 不使用 4.6 新 API |
| ADR-02 | 关卡地形用脚本数据表 + `set_cell` | 避免不可审查的二进制 tile 数据，便于结构测试 | 地形改动需改 `level_01.gd` 数据表 |
| ADR-03 | 流程状态集中在 `GameFlowManager` | UI 与流程解耦，避免多状态源 | UI 必须经 `flow_ui` 组注册 |
| ADR-04 | 分数唯一权威在 `ScoreManager` | 防止 HUD 成为数据源 | HUD 只订阅信号 |
| ADR-05 | 伤害走 Hitbox/Hurtbox 组件 | 统一玩家/敌人战斗链路，可追踪来源 | 新增攻击者只需组合组件 |
| ADR-06 | 玩家数值外置为 `PlayerConfig` 资源 | 满足“数值可配置、脚本不硬编码” | 平衡调整改 `.tres` |
| ADR-07 | headless 冒烟 + 运行时验证场景 | 提供不依赖人工点击的真实运行证据 | CI 可执行 `--smoke` / `runtime_verifier` |
| ADR-08 | 占位资产使用自绘 SVG 与程序生成 WAV | 来源与许可清晰，可追踪 | 正式美术替换时更新 Asset Registry |

---

## 9. Editor 与验证

1. 导入验证：`Godot --headless --path godot_project --editor --quit` 退出码必须为 0。
2. 结构验证：`apps/backend/tests/integration/test_e11_godot_project.py` 校验主场景、自动加载、输入映射、资源引用与文档齐备。
3. 运行时验证：
   - 冒烟：`Godot --headless --path godot_project -- --smoke` 输出 `[SMOKE] RESULT=PASS`；
   - 功能：`Godot --headless --path godot_project res://scenes/tests/runtime_verifier.tscn` 输出 `[VERIFY] SUMMARY`。
4. Editor 深度状态（Node Tree / Inspector / Signal / UID）由 E3 Godot Integration 在 M6 记录。

---

## 10. 已知约束

- headless 下无渲染与音频输出，视觉与音频只做导入与引用级验证。
- 占位视觉资产为静态 SVG，不支持逐帧动画，动画表现以 Tween 与状态切换实现。
- 首次导入会生成 `.godot/` 缓存，已被 `.gitignore` 忽略；`.import` 与 `.uid` 属于版本化资产。
