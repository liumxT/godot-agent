# Game Requirement Document（E11-T01）

- 项目：Project Platformer Demo
- 内部代号：PF-DEMO-001
- 引擎版本：Godot 4.5.1（GDScript，2D Renderer，Forward+ 关闭，Mobile 渲染器）
- 文档状态：FROZEN（规格基线）
- 来源需求：创建一款 2D 平台跳跃游戏，玩家可以移动、跳跃和攻击敌人，能够收集物品、避开陷阱，最终完成关卡。

## 1. Game Concept

一款单关卡、横向卷轴的 2D 平台跳跃游戏。玩家在关卡中移动、跳跃、近战攻击巡逻敌人，
避开地刺陷阱，收集金币累积分数，并通过终点完成关卡。玩家拥有 3 点生命，
受伤后进入 1 秒无敌状态；生命归零进入 Game Over。最佳分数保存在本地。

## 2. Core Gameplay Loop

```text
Start Level -> Explore -> Avoid Obstacles -> Fight Enemies
            -> Collect Items -> Reach Goal -> Victory -> Results
```

失败循环：

```text
Take Damage -> Lose Health -> Health Reaches Zero -> Death -> Game Over
```

## 3. Game Mechanics

| 机制 | 说明 | 关键参数 |
| --- | --- | --- |
| 水平移动 | 加速度驱动，支持空中控制与摩擦 | max_speed 220 / acceleration 1600 / friction 1800 |
| 跳跃 | 地面起跳，带跳跃缓冲 | jump_velocity -420 / gravity 1200 / buffer 0.1s |
| 近战攻击 | Hitbox 仅在有效帧启用，带冷却 | damage 1 / cooldown 0.35s / active 0.12s |
| 伤害与无敌 | 伤害带来源，受击后无敌 | invulnerability 1.0s / knockback 160 |
| 生命值 | 玩家 3 点，敌人 2 点 | player 3 / enemy 2 |
| 收集与计分 | ScoreManager 统一累计 | coin 10 / gem 50 |
| 敌人巡逻 | 边界与平台边缘转向 | speed 60 / attack_range 48 / detect_range 140 |
| 暂停 | 暂停菜单与场景树暂停 | pause action = Escape |

## 4. Player Requirements

- 左右移动，带加速度、减速度、最大速度限制；空中控制系数为地面的 0.6。
- 地面跳跃；空中不允许未经设计的二次跳跃；落地后恢复跳跃能力。
- 攻击时启用攻击 Hitbox，命中敌人造成 1 点伤害，冷却 0.35 秒。
- 受伤扣 1 点生命并进入 1 秒无敌；无敌期间忽略伤害。
- 生命归零进入死亡状态，播放死亡表现，随后进入 Game Over。
- 不能穿透 TileMapLayer 地面、平台与墙体。

## 5. Enemy Requirements

- 在配置的巡逻范围内往返移动，到达边界或平台边缘时转向。
- 检测到玩家进入攻击范围（48px）后切换到 ATTACK 状态并造成 1 点伤害。
- 敌人拥有 2 点生命；生命归零后播放死亡表现并退出战斗。
- 死亡后的敌人不再接受普通攻击伤害。

## 6. Level Requirements

- 关卡使用 TileMapLayer，包含地面、浮空平台与墙体。
- 天赋碰撞有效：玩家可站立、不能穿透。
- 包含地刺陷阱，接触造成 1 点伤害（受无敌帧限制）。
- 包含金币收集物、巡逻敌人与终点 Goal 区域。
- 关卡长度约 160 格宽、24 格高，分 6 个区段：TUTORIAL / JUMPS / TRAPS / ENEMY / COLLECT / GOAL。

## 7. UI Requirements

- HUD 显示玩家生命值与当前分数。
- 主菜单提供开始游戏与退出。
- 暂停菜单支持继续与返回主菜单。
- 胜负结算界面显示最终分数，并提供重试或返回主菜单。

## 8. Asset Requirements

| 类别 | 内容 | 来源 |
| --- | --- | --- |
| 角色 | 玩家、巡逻敌人（占位 SVG） | 项目内生成，记录来源 |
| 环境 | TileSet 图集（地面/平台/地刺） | 项目内生成，记录来源 |
| UI | 菜单与 HUD 使用主题与矢量图形 | 项目内生成 |
| 音频 | 跳跃/受伤/收集音效与背景音乐占位 | 项目内生成，记录来源 |
| VFX | 跳跃尘土、受伤闪烁、收集粒子 | 项目内效果 |

## 9. Technical Constraints

- Godot 版本冻结为 4.5.1，不在项目中途升级。
- 使用 GDScript；场景结构与脚本逻辑分离。
- 可配置数据使用 Resource；避免不必要的全局单例。
- 输入映射必须在 `project.godot` 的 Input Map 中定义。
- 场景与资源引用必须可验证（路径稳定、无悬空引用）。

## 10. Acceptance Criteria（摘要）

- 每条需求至少拥有 1 条可验证的验收条件，且可转化为 E9 测试用例。
- P0 需求必须全部具备功能性验证；导出产物必须通过 Smoke Test。
- 验收结论仅允许 ACCEPTED / ACCEPTED_WITH_NOTES / REJECTED；REJECTED 必须创建后续修复任务。
- 详见 [acceptance-criteria.md](acceptance-criteria.md) 与 [traceability-matrix.md](traceability-matrix.md)。

## 11. Out of Scope

- 在线多人、云存档、复杂 RPG 装备与技能树、大型开放世界、复杂经济系统、
  多平台账号系统、复杂剧情分支、大规模 3D 内容。
