# Gameplay Specification（E11-T02）

所有参数保存在 `resources/game_config/player_config.tres` 与
`resources/game_config/game_config.tres`，脚本不得硬编码数值。

## 1. 移动

| 参数 | 值 | 说明 |
| --- | --- | --- |
| max_speed | 220 px/s | 地面最大水平速度 |
| acceleration | 1600 px/s² | 地面加速度 |
| friction | 1800 px/s² | 地面减速度 |
| air_control | 0.6 | 空中输入系数 |
| gravity | 1200 px/s² | 重力加速度 |
| max_fall_speed | 900 px/s | 最大下落速度 |

## 2. 跳跃

| 参数 | 值 | 说明 |
| --- | --- | --- |
| jump_velocity | -420 px/s | 起跳初速度 |
| jump_buffer | 0.1 s | 落地前输入缓存 |
| coyote_time | 0.08 s | 离开平台后的宽限 |
| max_jump_count | 1 | 禁止非法二次跳跃 |

验收：AC-1 起跳瞬间速度必须为负；AC-2 空中重复按键不得再次起跳；
AC-3 落地后必须恢复起跳能力。

## 3. 攻击

| 参数 | 值 | 说明 |
| --- | --- | --- |
| damage | 1 | 单次伤害 |
| cooldown | 0.35 s | 攻击间隔 |
| active_window | 0.12 s | Hitbox 有效窗口 |
| hitbox_range | 34 px | 攻击距离 |

攻击流程：输入 → 冷却检查 → 播放攻击动画 → 在有效帧启用 Hitbox →
命中后记录已命中目标 → 有效帧结束关闭 Hitbox。

验收：命中必须有 damage 与 source_id；同一次攻击不得重复伤害同一目标。

## 4. 伤害与无敌

| 参数 | 值 |
| --- | --- |
| player_max_health | 3 |
| enemy_max_health | 2 |
| invulnerability | 1.0 s |
| knockback | 160 px/s |
| hurt_knockback_decay | 0.2 s |

受伤流程：Hurtbox 收到 DamageData → 检查无敌与死亡 → 扣血 → 击退 →
无敌计时 → 动画闪烁。无敌期间直接丢弃伤害。

## 5. 生命与死亡

- 生命归零 → `Health.died` 信号 → Player 切换 DEATH → 禁用输入与碰撞层 →
  播放死亡动画 0.6 秒 → GameFlowManager 进入 GAME_OVER。
- 敌人生命归零 → 停用 Hurtbox → 播放死亡动画 → 0.4 秒后 `queue_free`。

## 6. 收集与计分

| 类型 | 分值 | 表现 |
| --- | --- | --- |
| coin | 10 | 旋转 + 收集粒子 + 音效 |
| gem | 50 | 闪烁 + 收集粒子 + 音效 |

ScoreManager 持有权威分数并通过 `score_changed(score)` 通知 HUD。
已收集对象必须先置 `collected = true` 再发信号，防止重复计分。

## 7. 敌人巡逻

| 参数 | 值 |
| --- | --- |
| patrol_speed | 60 px/s |
| detect_range | 140 px |
| attack_range | 48 px |
| turn_delay | 0.2 s |

状态：PATROL → ALERT（发现玩家）→ ATTACK → DEAD。
边界检测使用 `RayCast2D` 与墙检测，防止走下平台。

## 8. 失败与胜利

- 胜利：玩家进入 Goal 的 Area2D → GameFlowManager.state = VICTORY → 暂停游戏
  → 结算界面显示分数。
- 失败：生命归零且无重生 → GAME_OVER → 结算界面显示 Retry / Main Menu。

## 9. 暂停

Escape 切换暂停；暂停时 `get_tree().paused = true`，
玩家、敌人、计时器全部依赖 `process_mode` 控制；UI 使用 ALWAYS 模式。
