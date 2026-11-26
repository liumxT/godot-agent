# Game Flow Diagram（E11-T02）

## 1. 状态机

```text
MAIN_MENU ──start──▶ PLAYING ──goal──▶ VICTORY ──confirm──▶ MAIN_MENU
     ▲                   │                 │
     │                   │ pause           │ retry
     │                   ▼                 ▼
     └────menu───── PAUSED            LEVEL_RESTART
                         │
                         ▼ resume
                      PLAYING
PLAYING ──health=0──▶ GAME_OVER ──retry──▶ LEVEL_RESTART
                         │
                         └──menu──▶ MAIN_MENU
```

## 2. 状态定义

| 状态 | 说明 | 场景树暂停 | 输入 |
| --- | --- | --- | --- |
| BOOT | 初始化配置与存档 | 否 | 无 |
| MAIN_MENU | 主菜单 | 否 | UI |
| PLAYING | 关卡进行中 | 否 | 玩家 + UI |
| PAUSED | 暂停菜单 | 是 | UI |
| VICTORY | 胜利结算 | 是 | UI |
| GAME_OVER | 失败结算 | 是 | UI |
| LEVEL_RESTART | 重载关卡 | 否 | 无 |

## 3. 事件与信号

| 信号 | 发送方 | 接收方 |
| --- | --- | --- |
| game_started | GameFlowManager | Level、HUD、Audio |
| player_health_changed | Health | HUD |
| score_changed | ScoreManager | HUD |
| goal_reached | Goal Area2D | GameFlowManager |
| player_died | Health | GameFlowManager、VFX |
| game_paused / game_resumed | GameFlowManager | Audio、UI |
| game_over | GameFlowManager | ResultScreen |
| level_completed | GameFlowManager | ResultScreen、SaveManager |

## 4. 失败循环

1. 玩家受击 → 生命 -1 → 无敌 1 秒。
2. 生命 = 0 → 死亡动画 0.6 秒 → GAME_OVER。
3. 结算界面 Retry → `LEVEL_RESTART` → 重新加载 LEVEL-01。
4. 分数在本轮内清零；最佳分数在 VICTORY 时写入。

## 5. 胜利循环

1. 进入 Goal → `goal_reached`。
2. GameFlowManager 暂停场景树并进入 VICTORY。
3. 结算界面显示分数与最佳分数。
4. 确认 → MAIN_MENU。
