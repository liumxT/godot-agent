# Requirement Registry（E11-T01）

需求 ID 在规格内唯一且不可复用；所有需求均由 `demo_game_requirements` 表持有，
可通过 `GET /api/v1/demo/projects/{project_id}/requirements` 读取。

| 需求 ID | 系统 | 优先级 | 需求 | 验收条件 | 测试场景 |
| --- | --- | --- | --- | --- | --- |
| REQ-PLAYER-001 | PLAYER | P0 | 玩家可以左右移动 | AC-1, AC-2 | TC-003 |
| REQ-PLAYER-002 | PLAYER | P0 | 玩家可以跳跃 | AC-1, AC-2, AC-3 | TC-004 |
| REQ-PLAYER-003 | PLAYER | P0 | 玩家可以攻击敌人 | AC-1, AC-2, AC-3 | TC-005 |
| REQ-PLAYER-004 | PLAYER | P0 | 玩家受伤与无敌帧 | AC-1, AC-2 | TC-006 |
| REQ-PLAYER-005 | PLAYER | P0 | 玩家死亡流程 | AC-1, AC-2 | TC-007 |
| REQ-ENEMY-001 | ENEMY | P0 | 敌人巡逻 | AC-1, AC-2 | TC-008 |
| REQ-ENEMY-002 | ENEMY | P0 | 敌人攻击玩家 | AC-1, AC-2 | TC-009 |
| REQ-COMBAT-001 | COMBAT | P0 | 攻击命中与伤害传递 | AC-1, AC-2 | TC-005 |
| REQ-COMBAT-002 | COMBAT | P0 | 单次攻击不重复伤害 | AC-1 | TC-005 |
| REQ-COMBAT-003 | COMBAT | P0 | 死亡目标不再受击 | AC-1 | TC-009 |
| REQ-LEVEL-001 | LEVEL | P0 | 平台碰撞有效 | AC-1, AC-2 | TC-002 |
| REQ-LEVEL-002 | LEVEL | P0 | 陷阱造成伤害 | AC-1 | TC-011 |
| REQ-LEVEL-003 | LEVEL | P0 | 终点检测 | AC-1 | TC-014 |
| REQ-COLLECT-001 | COLLECTIBLE | P0 | 收集物与分数 | AC-1, AC-2 | TC-010 |
| REQ-COLLECT-002 | COLLECTIBLE | P0 | 收集物不重复计分 | AC-1 | TC-010 |
| REQ-UI-001 | UI | P0 | HUD 显示生命与分数 | AC-1, AC-2 | TC-010 |
| REQ-UI-002 | UI | P0 | 主菜单可开始游戏 | AC-1 | TC-001, TC-002 |
| REQ-UI-003 | UI | P0 | 暂停与恢复 | AC-1, AC-2 | TC-012, TC-013 |
| REQ-FLOW-001 | FLOW | P0 | 胜利结算 | AC-1 | TC-014 |
| REQ-FLOW-002 | FLOW | P0 | 失败结算 | AC-1 | TC-015 |
| REQ-SAVE-001 | SAVE | P1 | 最佳分数保存 | AC-1, AC-2 | TC-018 |

## 需求状态

| 状态 | 含义 |
| --- | --- |
| PLANNED | 已登记，未开始实现 |
| IN_PROGRESS | 至少一条验收条件已进入非 PENDING 状态 |
| IMPLEMENTED | 已实现但存在 NOT_MET 的验收条件 |
| VERIFIED | 全部验收条件为 MET 或 WAIVED |

状态由 `POST /api/v1/demo/projects/{project_id}/acceptance/criteria` 驱动，
不允许人工直接改库。
