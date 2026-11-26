# Acceptance Criteria Registry（E11-T01）

每条验收条件都标注验证方式，必须能够转化为 E9 测试用例；
`required_evidence` 至少包含 `runtime_trace` 或 `test_report`。

| 需求 | 条件 | 描述 | 验证方式 |
| --- | --- | --- | --- |
| REQ-PLAYER-001 | AC-1 | 按下右方向键后水平速度为正且不超过最大速度 | FUNCTIONAL_TEST |
| REQ-PLAYER-001 | AC-2 | 松开方向键后在地面逐渐减速到静止 | FUNCTIONAL_TEST |
| REQ-PLAYER-002 | AC-1 | 在地面按跳跃键后垂直速度立即为负 | FUNCTIONAL_TEST |
| REQ-PLAYER-002 | AC-2 | 空中重复按跳跃键不产生第二次起跳 | FUNCTIONAL_TEST |
| REQ-PLAYER-002 | AC-3 | 落地后可再次跳跃 | FUNCTIONAL_TEST |
| REQ-PLAYER-003 | AC-1 | 攻击时 Hitbox 处于启用状态 | FUNCTIONAL_TEST |
| REQ-PLAYER-003 | AC-2 | 攻击命中敌人后敌人生命减少 | FUNCTIONAL_TEST |
| REQ-PLAYER-003 | AC-3 | 冷却期间重复按攻击键不造成额外伤害 | FUNCTIONAL_TEST |
| REQ-PLAYER-004 | AC-1 | 受到伤害后生命值减少 | FUNCTIONAL_TEST |
| REQ-PLAYER-004 | AC-2 | 无敌期间再次受到伤害不扣血 | FUNCTIONAL_TEST |
| REQ-PLAYER-005 | AC-1 | 生命归零后状态切换为 DEATH | RUNTIME_TEST |
| REQ-PLAYER-005 | AC-2 | 死亡后不再接受普通攻击伤害 | FUNCTIONAL_TEST |
| REQ-ENEMY-001 | AC-1 | 敌人在巡逻范围内往返移动 | FUNCTIONAL_TEST |
| REQ-ENEMY-001 | AC-2 | 到达巡逻边界后朝向反转 | FUNCTIONAL_TEST |
| REQ-ENEMY-002 | AC-1 | 玩家进入攻击范围后敌人切换到 ATTACK 状态 | FUNCTIONAL_TEST |
| REQ-ENEMY-002 | AC-2 | 敌人攻击命中后玩家生命减少 | FUNCTIONAL_TEST |
| REQ-COMBAT-001 | AC-1 | 命中事件携带 damage 与 source_id | FUNCTIONAL_TEST |
| REQ-COMBAT-001 | AC-2 | 未处于受击层的对象不会产生伤害 | FUNCTIONAL_TEST |
| REQ-COMBAT-002 | AC-1 | 同一次攻击的重复命中被忽略 | FUNCTIONAL_TEST |
| REQ-COMBAT-003 | AC-1 | 死亡状态的 Hurtbox 拒绝伤害 | FUNCTIONAL_TEST |
| REQ-LEVEL-001 | AC-1 | 玩家站在平台上不下落 | FUNCTIONAL_TEST |
| REQ-LEVEL-001 | AC-2 | 玩家高速下落时不会穿过地面 | RUNTIME_TEST |
| REQ-LEVEL-002 | AC-1 | 玩家接触地刺后生命减少 | FUNCTIONAL_TEST |
| REQ-LEVEL-003 | AC-1 | 玩家进入 Goal 区域后触发 VICTORY | FUNCTIONAL_TEST |
| REQ-COLLECT-001 | AC-1 | 接触收集物后分数增加配置值 | FUNCTIONAL_TEST |
| REQ-COLLECT-001 | AC-2 | HUD 分数与 ScoreManager 一致 | FUNCTIONAL_TEST |
| REQ-COLLECT-002 | AC-1 | 第二次接触已收集对象不增加分数 | FUNCTIONAL_TEST |
| REQ-UI-001 | AC-1 | 受伤后 HUD 生命显示同步更新 | FUNCTIONAL_TEST |
| REQ-UI-001 | AC-2 | 收集后 HUD 分数显示同步更新 | FUNCTIONAL_TEST |
| REQ-UI-002 | AC-1 | 选择开始后进入 PLAYING 状态并加载 Level 01 | FUNCTIONAL_TEST |
| REQ-UI-003 | AC-1 | 暂停后游戏状态为 PAUSED 且场景树暂停 | FUNCTIONAL_TEST |
| REQ-UI-003 | AC-2 | 恢复后状态回到 PLAYING 且逻辑继续 | FUNCTIONAL_TEST |
| REQ-FLOW-001 | AC-1 | 胜利界面显示最终分数 | FUNCTIONAL_TEST |
| REQ-FLOW-002 | AC-1 | 生命归零后进入 GAME_OVER | FUNCTIONAL_TEST |
| REQ-SAVE-001 | AC-1 | 刷新最佳分数后重启仍可读取 | FUNCTIONAL_TEST |
| REQ-SAVE-001 | AC-2 | 损坏存档被识别并恢复默认值 | FUNCTIONAL_TEST |

## 判定规则

- `MET`：有对应测试报告或运行证据。
- `WAIVED`：用户书面接受的不适用条件，必须在验收记录中说明。
- `NOT_MET`：存在缺陷，需求状态降级为 IMPLEMENTED，并阻断 ACCEPTED。
- `PENDING`：尚未执行。
